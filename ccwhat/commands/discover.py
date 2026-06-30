"""discover subcommand — metadata-only traffic discovery for model API endpoints."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import click

from ccwhat.config import (
    DEFAULT_CONFIG_PATH,
    RecordingConfig,
    normalize_path,
    save_config,
)
from ccwhat.runtime.infra.ports import format_port_bind_error, port_bind_error
from ccwhat.runtime.platform import mitmdump_missing_message


# ---------------------------------------------------------------------------
# Candidate scoring
# ---------------------------------------------------------------------------

def _score_candidate(host: str, method: str, path: str, status: int, content_type: str, is_sse: bool) -> tuple[int, str]:
    """Return (score, reason). Higher score = more likely a model API endpoint."""
    score = 0
    reasons: list[str] = []

    # Anthropic messages shape
    if path in ("/v1/messages", "/v1/messages/count_tokens"):
        score += 10
        reasons.append("Anthropic Messages API path")
    elif "/v1/messages" in path:
        score += 5
        reasons.append("Anthropic Messages-like path")

    # OpenAI Responses shape used by Codex CLI
    if path == "/v1/responses":
        score += 10
        reasons.append("OpenAI Responses API path")
    elif "/v1/responses" in path:
        score += 5
        reasons.append("OpenAI Responses-like path")

    # Streaming model response
    if is_sse or "text/event-stream" in content_type:
        score += 8
        reasons.append("streaming model response (SSE)")

    # POST to a likely inference path
    if method == "POST" and score > 0:
        score += 2
        reasons.append("POST method")

    return score, "; ".join(reasons) if reasons else ""


# ---------------------------------------------------------------------------
# Discovery mitmproxy addon (runs inside mitmdump)
# ---------------------------------------------------------------------------

_DISCOVERY_ADDON_CODE = '''\
"""mitmproxy addon for metadata-only discovery — no payload storage."""
import json, os, sys, uuid
from datetime import datetime, timezone
from pathlib import Path
from mitmproxy import http

_SENSITIVE_NAMES = frozenset({"authorization", "cookie", "set-cookie", "x-api-key",
                               "proxy-authorization"})
_SENSITIVE_PATTERNS = ("token", "secret", "key")
_OUT = Path(os.environ.get("CCWHAT_DISCOVERY_OUT", "/tmp/ccwhat-discovery.jsonl"))


def _has_sensitive(headers) -> bool:
    for k in headers:
        kl = k.lower()
        if kl in _SENSITIVE_NAMES:
            return True
        if any(p in kl for p in _SENSITIVE_PATTERNS):
            return True
    return False


class DiscoveryAddon:
    def __init__(self):
        self._sse: set = set()

    def responseheaders(self, flow: http.HTTPFlow):
        if flow.response is None:
            return
        ct = flow.response.headers.get("content-type", "")
        if "text/event-stream" in ct:
            self._sse.add(flow.id)
            flow.response.stream = True

    def response(self, flow: http.HTTPFlow):
        if flow.response is None:
            return
        is_sse = flow.id in self._sse
        self._sse.discard(flow.id)
        resp_ct = flow.response.headers.get("content-type", "")
        req_ct = flow.request.headers.get("content-type", "")
        record = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "host": flow.request.pretty_host,
            "method": flow.request.method,
            "path": flow.request.path.split("?")[0],
            "status": flow.response.status_code,
            "req_content_type": req_ct,
            "resp_content_type": resp_ct,
            "is_sse": is_sse,
            "has_sensitive_headers": _has_sensitive(flow.request.headers),
        }
        try:
            with _OUT.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\\n")
        except OSError:
            pass


addons = [DiscoveryAddon()]
'''


# ---------------------------------------------------------------------------
# Discovery runner
# ---------------------------------------------------------------------------

def _proxy_is_running(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _start_discovery_proxy(port: int, out_path: Path) -> subprocess.Popen | None:
    bind_error = port_bind_error(port)
    if bind_error is not None:
        click.echo(
            format_port_bind_error(
                port,
                bind_error,
                "Use a different port: ccwhat discover --port <other-port>",
            ),
            err=True,
        )
        return None

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(_DISCOVERY_ADDON_CODE)
        addon_path = f.name

    env = os.environ.copy()
    env["CCWHAT_DISCOVERY_OUT"] = str(out_path)

    cmd = [
        "mitmdump",
        "--listen-host", "127.0.0.1",
        "--listen-port", str(port),
        "-s", addon_path,
        "--set", f"hardump={os.devnull}",
        "--flow-detail", "0",
        "-q",
    ]
    try:
        proc = subprocess.Popen(cmd, env=env)
    except FileNotFoundError:
        click.echo(mitmdump_missing_message(), err=True)
        return None

    for _ in range(30):
        if _proxy_is_running(port):
            break
        time.sleep(0.1)
    return proc


def _read_candidates(out_path: Path) -> list[dict]:
    if not out_path.exists():
        return []
    records = []
    for line in out_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            import json
            records.append(json.loads(line))
        except Exception:
            pass
    return records


def _score_and_deduplicate(records: list[dict]) -> tuple[list[dict], list[str]]:
    """Returns (candidates_with_score, all_observed_hosts)."""
    seen_hosts: set[str] = set()
    best: dict[tuple[str, str], tuple[int, str, dict]] = {}  # (host, path) -> (score, reason, record)

    for r in records:
        host = r.get("host", "")
        seen_hosts.add(host)
        method = r.get("method", "")
        path = r.get("path", "")
        status = r.get("status", 0)
        resp_ct = r.get("resp_content_type", "")
        is_sse = r.get("is_sse", False)
        score, reason = _score_candidate(host, method, path, status, resp_ct, is_sse)
        if score > 0:
            key = (host, path)
            if key not in best or score > best[key][0]:
                best[key] = (score, reason, r)

    candidates = sorted(
        [{"host": k[0], "path": k[1], "score": v[0], "reason": v[1], "record": v[2]} for k, v in best.items()],
        key=lambda x: -x["score"],
    )
    return candidates, sorted(seen_hosts)


def _prompt_and_save_candidates(candidates: list[dict], config_path: Path | None) -> None:
    if not candidates:
        return

    click.echo("\n=== Discovered model API candidates ===\n")
    for i, c in enumerate(candidates, 1):
        click.echo(f"  {i}) {c['host']}{c['path']}  [{c['reason']}]")

    raw = click.prompt(
        "\nEnter numbers to save (e.g. 1,2 or press Enter to select all)",
        default="all",
    )
    raw = raw.strip()
    if raw.lower() == "all" or raw == "":
        selected = candidates
    else:
        try:
            indices = [int(x.strip()) - 1 for x in raw.split(",")]
            selected = [candidates[i] for i in indices if 0 <= i < len(candidates)]
        except (ValueError, IndexError):
            click.echo("Invalid selection. No config saved.", err=True)
            return

    if not selected:
        click.echo("No candidates selected.")
        return

    domains = list(dict.fromkeys(c["host"] for c in selected))
    paths = list(dict.fromkeys(normalize_path(c["path"]) for c in selected))
    cfg = RecordingConfig(domains=domains, paths=paths, onboarding_complete=True)
    save_config(cfg, config_path)
    click.echo(f"\nConfiguration saved to {config_path or DEFAULT_CONFIG_PATH}")
    click.echo(f"Domains: {', '.join(domains)}")
    click.echo("You can now run: ccwhat -- <your-cli>")


@click.command(
    "discover",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
@click.option("--port", default=7788, show_default=True, type=int, help="Proxy port for discovery.")
@click.option(
    "--config",
    "config_path",
    default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to config.toml.",
)
@click.argument("target_args", nargs=-1, type=click.UNPROCESSED)
def discover(port: int, config_path: Path | None, target_args: tuple[str, ...]) -> None:
    """Observe traffic metadata to discover model API endpoints.

    Runs without storing request/response bodies. Use to detect the right
    domains and paths for your setup.

    Examples:

      ccwhat discover -- claude
      ccwhat discover
    """
    ca_cert = Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.pem"

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tf:
        out_path = Path(tf.name)

    click.echo("Starting metadata-only discovery proxy (no request/response bodies stored).")

    proxy_proc = _start_discovery_proxy(port, out_path)
    if proxy_proc is None:
        sys.exit(1)

    child_env = os.environ.copy()
    child_env["HTTPS_PROXY"] = f"http://127.0.0.1:{port}"
    child_env["HTTP_PROXY"] = f"http://127.0.0.1:{port}"
    child_env["NODE_EXTRA_CA_CERTS"] = str(ca_cert)

    exit_code = 0
    target_proc: subprocess.Popen | None = None

    try:
        if target_args:
            click.echo(f"Launching: {' '.join(target_args)}\n")
            try:
                target_proc = subprocess.Popen(list(target_args), env=child_env)
                exit_code = target_proc.wait()
            except FileNotFoundError:
                click.echo(f"Error: command not found: {target_args[0]}", err=True)
                exit_code = 127
        else:
            click.echo(
                f"\nProxy listening on http://127.0.0.1:{port}\n"
                f"Configure your AI coding CLI to use this proxy:\n"
                f"  HTTPS_PROXY=http://127.0.0.1:{port} <your-cli>\n"
                f"  NODE_EXTRA_CA_CERTS={ca_cert} <your-cli>\n\n"
                "Press Ctrl+C when done to see discovered endpoints."
            )
            try:
                while True:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
    except KeyboardInterrupt:
        if target_proc:
            target_proc.terminate()
            try:
                target_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                target_proc.kill()
    finally:
        proxy_proc.terminate()
        try:
            proxy_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proxy_proc.kill()

    records = _read_candidates(out_path)
    try:
        out_path.unlink(missing_ok=True)
    except Exception:
        pass

    candidates, all_hosts = _score_and_deduplicate(records)

    click.echo(f"\nObserved {len(records)} request(s) across {len(all_hosts)} host(s).")
    if all_hosts:
        click.echo(f"All hosts: {', '.join(all_hosts)}")

    if candidates:
        _prompt_and_save_candidates(candidates, config_path)
    else:
        click.echo(
            "\nNo likely model API endpoints detected.\n"
            "Troubleshooting:\n"
            "  • Ensure your AI coding CLI was launched through this proxy\n"
            "  • Check CA certificate trust: ccwhat proxy (shows install command)\n"
            "  • Try running ccwhat discover -- claude  to capture traffic automatically"
        )

    sys.exit(exit_code)
