"""run subcommand — launch an AI coding CLI through the ccwhat proxy."""

from __future__ import annotations

import os
import json
import shutil
import signal
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

import click

from ccwhat.adapters.registry import create_adapter, infer_agent_from_target
from ccwhat.config import (
    DEFAULT_RAW_LOG_DIR,
    generate_local_session_id,
    load_config,
)
from ccwhat.runtime.integrations.claude import (
    ClaudeIntegrationConflict,
    install_claude_integration,
)
from ccwhat.runtime.integrations.codex import (
    CodexIntegrationConflict,
    install_codex_integration,
)
from ccwhat.runtime.http.controller import RuntimeController
from ccwhat.runtime.integrations.opencode import (
    OpenCodeIntegrationConflict,
    install_opencode_integration,
)
from ccwhat.runtime.infra.ports import format_port_bind_error, port_bind_error, resolve_runtime_ports
from ccwhat.runtime.platform import mitmdump_missing_message
from ccwhat.runtime.infra.registry import RunRegistry, utc_now


class _ManagedWebServer(Protocol):
    def serve_forever(self) -> None: ...

    def shutdown(self) -> None: ...

    def server_close(self) -> None: ...



def _marker_path(port: int) -> Path:
    """Return path to the ccwhat proxy marker file for this port."""
    import tempfile
    return Path(tempfile.gettempdir()) / f"ccwhat-proxy-{port}.pid"


def _viewer_agent_marker_path(port: int) -> Path:
    """Return path to the marker file tracking which agent the viewer serves."""
    import tempfile
    return Path(tempfile.gettempdir()) / f"ccwhat-viewer-{port}.agent"


def _write_viewer_agent_marker(port: int, agent_name: str) -> None:
    try:
        _viewer_agent_marker_path(port).write_text(agent_name, encoding="utf-8")
    except OSError:
        pass


def _clear_viewer_agent_marker(port: int) -> None:
    _viewer_agent_marker_path(port).unlink(missing_ok=True)


def _proxy_port_in_use(port: int) -> bool:
    """Return True if something is listening on localhost:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _proxy_is_running(port: int) -> bool:
    """Return True if a ccwhat-managed proxy is listening on this port.

    Raises SystemExit if the port is occupied by a non-ccwhat process.
    """
    if not _proxy_port_in_use(port):
        return False
    marker = _marker_path(port)
    if marker.exists():
        try:
            pid = int(marker.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            pid = None
        # Verify the process is still alive
        if pid is not None:
            try:
                os.kill(pid, 0)  # signal 0 = existence check
                return True
            except (ProcessLookupError, PermissionError):
                pass
        marker.unlink(missing_ok=True)
    # Port is occupied but no ccwhat marker — refuse to proceed
    click.echo(
        f"Error: port {port} is already in use by another process "
        "(not a ccwhat proxy).\n"
        f"Use a different port: ccwhat --port <other-port> -- <cli>",
        err=True,
    )
    sys.exit(1)


def _start_managed_proxy(
    port: int,
    output: Path,
    effective_domains: list[str],
    effective_paths: list[str],
    max_body_bytes: int,
    redact_headers: list[str],
    redact_patterns: list[str],
    local_session_id: str,
) -> subprocess.Popen | None:
    """Start mitmdump as a background process. Returns the Popen handle or None on failure."""
    addon_path = Path(__file__).parent.parent / "addons" / "recorder.py"
    output.mkdir(parents=True, exist_ok=True)

    cmd = [
        "mitmdump",
        "--listen-host", "127.0.0.1",
        "--listen-port", str(port),
        "-s", str(addon_path),
        "--set", f"hardump={os.devnull}",
        "--flow-detail", "0",
        "-q",
    ]

    env = os.environ.copy()
    env["CCWHAT_OUTPUT_DIR"] = str(output.resolve())
    env["CCWHAT_RECORD_DOMAINS"] = ",".join(effective_domains)
    env["CCWHAT_RECORD_PATHS"] = ",".join(effective_paths)
    env["CCWHAT_MAX_BODY_BYTES"] = str(max_body_bytes)
    env["CCWHAT_REDACT_HEADERS"] = ",".join(redact_headers)
    env["CCWHAT_REDACT_PATTERNS"] = ",".join(redact_patterns)
    env["CCWHAT_LOCAL_SESSION_ID"] = local_session_id

    try:
        proc = subprocess.Popen(cmd, env=env)
    except FileNotFoundError:
        click.echo(mitmdump_missing_message(), err=True)
        return None

    # Brief wait for proxy to bind (up to 2 s)
    import time
    bound = False
    for _ in range(20):
        # Check process is still alive
        if proc.poll() is not None:
            break
        if _proxy_port_in_use(port):
            bound = True
            break
        time.sleep(0.1)

    if not bound or proc.poll() is not None:
        # Proxy failed to start — terminate any still-running process, clean up
        returncode = proc.poll()
        if returncode is None:
            # Process is alive but never bound — kill it to avoid orphan
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            returncode = proc.poll()
        click.echo(
            f"Error: managed proxy failed to bind on port {port}"
            + (f" (exit code {returncode})" if returncode is not None else "")
            + ".\nCheck that mitmproxy is installed and the port is free.",
            err=True,
        )
        _marker_path(port).unlink(missing_ok=True)
        return None

    # Write marker only after successful bind
    try:
        _marker_path(port).write_text(str(proc.pid), encoding="utf-8")
    except OSError:
        pass

    return proc


def _start_managed_web(
    port: int,
    req_resp_dir: Path,
    config_path: Path | None,
    analyzer_cmd: tuple[str, ...] | None = None,
    agent_name: str = "claude",
) -> _ManagedWebServer | None:
    from viewer.server import create_server, open_viewer, viewer_url

    url = viewer_url(port)
    if _proxy_port_in_use(port):
        # Use API probe first (most reliable), fall back to file-based marker
        existing_agent = _probe_viewer_agent(port) or (
            _viewer_agent_marker_path(port).read_text(encoding="utf-8").strip()
            if _viewer_agent_marker_path(port).exists() else None
        )
        if existing_agent is not None and existing_agent != agent_name:
            click.echo(
                f"Error: viewer port {port} is already serving agent '{existing_agent}', "
                f"but this run needs '{agent_name}'.\n"
                f"Stop the existing ccwhat process or use --web-port <other-port>.",
                err=True,
            )
            return None
        if existing_agent is None:
            click.echo(
                f"Warning: viewer port {port} is already in use but did not expose ccwhat status. "
                "Opening it anyway; if the page is stale, stop the old process or use --web-port.",
                err=True,
            )
        click.echo(f"Viewer: {url}")
        open_viewer(port)
        return None

    bind_error = port_bind_error(port)
    if bind_error is not None:
        click.echo(
            format_port_bind_error(
                port,
                bind_error,
                "Use a different port: ccwhat --web-port <other-port> -- <cli>",
            ),
            err=True,
        )
        return None

    adapter = create_adapter(agent_name)
    projects_dir = adapter.default_projects_dir()
    try:
        server = create_server(port, projects_dir, req_resp_dir, config_path, analyzer_cmd, adapter=adapter)
    except OSError:
        click.echo(f"Viewer may already be running: {url}")
        open_viewer(port)
        return None

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _write_viewer_agent_marker(port, agent_name)
    click.echo(f"Viewer: {url}")
    open_viewer(port)
    return server


def _probe_viewer_agent(port: int) -> str | None:
    """Return the agent served by an existing viewer, or None if unknown."""
    def _read_json(path: str, timeout: float = 0.5) -> dict | list | None:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}{path}",
                timeout=timeout,
            ) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError):
            return None

    data = _read_json("/api/viewer/status")
    if isinstance(data, dict):
        agent = data.get("agent")
        if agent:
            return str(agent)

    # Backwards-compatible probe for older viewer processes that predate
    # /api/viewer/status but already include agent on /api/projects rows.
    data = _read_json("/api/projects", timeout=1.0)
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict) and first.get("agent"):
            return str(first["agent"])
    return None


def _stop_managed_web(server: _ManagedWebServer | None, web_port: int | None = None) -> None:
    if server is None:
        return
    server.shutdown()
    server.server_close()
    if web_port is not None:
        _clear_viewer_agent_marker(web_port)


_KNOWN_BINARY_PATHS: dict[str, str] = {
    "codex": "/Applications/Codex.app/Contents/Resources/codex",
    "opencode": "/Applications/OpenCode.app/Contents/MacOS/opencode",
}


def _resolve_target_binary(target_args: tuple[str, ...]) -> tuple[str, ...]:
    """Resolve the first argument to an absolute path if it's a known agent binary.

    Falls back to PATH lookup; returns target_args unchanged if nothing is found.
    """
    if not target_args:
        return target_args
    name = target_args[0].lower()
    if shutil.which(name) is not None:
        return target_args  # already in PATH
    if name in _KNOWN_BINARY_PATHS and os.path.isfile(_KNOWN_BINARY_PATHS[name]):
        return (os.path.abspath(_KNOWN_BINARY_PATHS[name]),) + target_args[1:]
    return target_args


@click.command(
    "run",
    hidden=True,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
@click.option("--port", default=7788, show_default=True, type=int, help="Proxy port.")
@click.option("--web/--no-web", default=True, show_default=True, help="Start and open the viewer.")
@click.option("--web-port", default=7789, show_default=True, type=int, help="Viewer port.")
@click.option(
    "--output",
    default=str(DEFAULT_RAW_LOG_DIR),
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory where JSONL log files are written.",
)
@click.option(
    "--config",
    "config_path",
    default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to config.toml.",
)
@click.option("--no-setup", is_flag=True, help="Skip onboarding even if no config exists.")
@click.option("--runtime-recording/--no-runtime-recording", default=False, hidden=True)
@click.argument("target_args", nargs=-1, type=click.UNPROCESSED)
def run(
    port: int | None,
    web: bool,
    web_port: int | None,
    output: Path,
    config_path: Path | None,
    no_setup: bool,
    runtime_recording: bool,
    target_args: tuple[str, ...],
) -> None:
    """Launch a command through the ccwhat proxy with env vars injected.

    Example:

      ccwhat -- claude
      ccwhat -- my-ai-cli --model sonnet
    """
    if not target_args:
        click.echo(
            "Error: no target command provided.\n\n"
            "Usage: ccwhat -- <command> [args...]\n\n"
            "Examples:\n"
            "  ccwhat -- claude\n"
            "  ccwhat -- mc --code\n"
            "  ccwhat -- my-ai-cli --model sonnet --resume",
            err=True,
        )
        sys.exit(1)

    agent_name = infer_agent_from_target(target_args)
    proxy_auto_allocated = port is None
    viewer_auto_allocated = web_port is None
    port, web_port, control_port = resolve_runtime_ports(
        proxy_port=port,
        viewer_port=web_port,
        need_viewer=web,
    )
    cfg = load_config(config_path)

    from ccwhat.config import DEFAULT_MAX_BODY_BYTES, DEFAULT_REDACT_HEADERS, DEFAULT_REDACT_PATTERNS
    if no_setup:
        effective_domains: list[str] = []
        effective_paths: list[str] = []
        max_body_bytes = DEFAULT_MAX_BODY_BYTES
        redact_headers = list(DEFAULT_REDACT_HEADERS)
        redact_patterns = list(DEFAULT_REDACT_PATTERNS)
        click.echo("Note: payload recording disabled (--no-setup). Traffic is proxied for discovery only.")
    else:
        from ccwhat import agent_config as _agent_config

        configured_domains = cfg.effective_domains() if cfg is not None else []
        detected_domains = _agent_config.detect_domains(agent_name)
        effective_domains = list(dict.fromkeys(configured_domains + detected_domains))

        configured_paths = cfg.effective_paths() if cfg is not None else []
        detected_paths = (
            _agent_config.detect_default_paths(agent_name)
            if detected_domains
            else []
        )
        effective_paths = list(dict.fromkeys(configured_paths + detected_paths))

        max_body_bytes = cfg.max_body_bytes if cfg is not None else DEFAULT_MAX_BODY_BYTES
        redact_headers = cfg.redact_headers if cfg is not None else list(DEFAULT_REDACT_HEADERS)
        redact_patterns = (
            cfg.redact_header_patterns
            if cfg is not None
            else list(DEFAULT_REDACT_PATTERNS)
        )
        if detected_domains:
            click.echo(
                f"Auto-detected domains : {', '.join(detected_domains)} "
                f"(from {agent_name} config/defaults)"
            )
        if not effective_domains:
            click.echo(
                f"No recording domains auto-detected for {agent_name}; "
                "starting proxy without payload recording."
            )

    proxy_running = _proxy_is_running(port)
    if not proxy_running:
        bind_error = port_bind_error(port)
        if bind_error is not None:
            click.echo(
                format_port_bind_error(
                    port,
                    bind_error,
                    "Use a different port: ccwhat --port <other-port> -- <cli>",
                ),
                err=True,
            )
            sys.exit(1)

    local_session_id = generate_local_session_id()
    proxy_proc: subprocess.Popen | None = None
    web_server: _ManagedWebServer | None = None
    registry: RunRegistry | None = None
    runtime_run_id: str | None = None
    runtime_controller: RuntimeController | None = None
    runtime_token = ""

    if runtime_recording and agent_name in {"claude", "codex", "opencode"}:
        registry = RunRegistry()
        runtime_run = registry.create_run(
            agent=agent_name,
            workspace=Path.cwd(),
            target_args=target_args,
            proxy_port=port,
            viewer_port=web_port,
            control_port=control_port,
            proxy_auto_allocated=proxy_auto_allocated,
            viewer_auto_allocated=viewer_auto_allocated,
        )
        runtime_run_id = runtime_run.run_id
        runtime_token = str(runtime_run.control.get("token") or "")
        try:
            if agent_name == "claude":
                install_claude_integration(Path.cwd())
            elif agent_name == "codex":
                install_codex_integration(Path.cwd())
            else:
                install_opencode_integration(Path.cwd())
        except (
            ClaudeIntegrationConflict,
            CodexIntegrationConflict,
            OpenCodeIntegrationConflict,
            json.JSONDecodeError,
        ) as exc:
            registry.update(runtime_run_id, status="integration_error", finished_at=utc_now())
            click.echo(f"Error: failed to install {agent_name} CCWhat integration: {exc}", err=True)
            sys.exit(1)
        runtime_controller = RuntimeController(registry, runtime_run_id, control_port)
        runtime_controller.start()
        registry.update(runtime_run_id, status="running")
        click.echo(f"Runtime run       : {runtime_run_id}")

    if proxy_running:
        click.echo(f"Reusing existing ccwhat proxy on port {port}.")
    else:
        if effective_domains:
            click.echo(f"Starting proxy on port {port}...")
            click.echo(f"Recording domains : {', '.join(effective_domains)}")
            if effective_paths:
                click.echo(f"Path filters      : {', '.join(effective_paths)}")
            click.echo(f"Log directory     : {output.resolve()}")
            click.echo("Viewer hint       : ccwhat web\n")

        proxy_proc = _start_managed_proxy(
            port, output, effective_domains, effective_paths,
            max_body_bytes, redact_headers, redact_patterns, local_session_id,
        )
        if proxy_proc is None:
            sys.exit(1)

    if web:
        web_server = _start_managed_web(web_port, output, config_path, None, agent_name=agent_name)

    # Build child environment
    ca_cert = Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.pem"
    child_env = os.environ.copy()
    child_env["HTTPS_PROXY"] = f"http://127.0.0.1:{port}"
    child_env["HTTP_PROXY"] = f"http://127.0.0.1:{port}"
    child_env["NODE_EXTRA_CA_CERTS"] = str(ca_cert)
    if runtime_run_id is not None:
        child_env["CCWHAT_RUNTIME_RUN_ID"] = runtime_run_id
        child_env["CCWHAT_RUNTIME_CONTROL_PORT"] = str(control_port)
        child_env["CCWHAT_RUNTIME_TOKEN"] = runtime_token
        child_env["CCWHAT_RUNTIME_WORKSPACE"] = str(Path.cwd().resolve())
        child_env["CCWHAT_ENABLED"] = "1"
    # NO_PROXY is preserved unless already overridden

    target_proc: subprocess.Popen | None = None
    exit_code = 1

    try:
        resolved = _resolve_target_binary(target_args)
        if resolved != target_args:
            click.echo(f"Resolved {target_args[0]} -> {resolved[0]}")
        target_proc = subprocess.Popen(list(resolved), env=child_env)
        if registry is not None and runtime_run_id is not None:
            registry.update(
                runtime_run_id,
                agent_process={"pid": target_proc.pid, "status": "running"},
                status="running",
            )
        exit_code = target_proc.wait()
    except FileNotFoundError:
        click.echo(f"Error: command not found: {target_args[0]}", err=True)
        exit_code = 127
    except KeyboardInterrupt:
        if target_proc:
            try:
                target_proc.send_signal(signal.SIGINT)
                exit_code = target_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                target_proc.kill()
                exit_code = target_proc.wait()
    finally:
        if registry is not None and runtime_run_id is not None:
            registry.update(
                runtime_run_id,
                status="exited",
                finished_at=utc_now(),
                agent_process={
                    "pid": target_proc.pid if target_proc is not None else None,
                    "status": "exited",
                    "exit_code": exit_code,
                },
            )
        if runtime_controller is not None:
            runtime_controller.stop()
        if proxy_proc is not None:
            proxy_proc.terminate()
            try:
                proxy_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proxy_proc.kill()
            _marker_path(port).unlink(missing_ok=True)
        _stop_managed_web(web_server, web_port)

    sys.exit(exit_code)
