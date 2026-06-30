"""proxy subcommand — start mitmproxy via mitmdump CLI with config-driven recording."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click

from ccwhat.config import (
    DEFAULT_RAW_LOG_DIR,
    RecordingConfig,
    generate_local_session_id,
    load_config,
    normalize_path,
    validate_domain,
)
from ccwhat.runtime.infra.ports import format_port_bind_error, port_bind_error
from ccwhat.runtime.platform import mitmdump_missing_message


def _build_recording_config_from_opts(
    domain: tuple[str, ...],
    path: tuple[str, ...],
    preset: str | None,
    config_path: Path | None,
) -> RecordingConfig:
    """Resolve recording config from CLI options > saved config."""
    if domain or preset:
        # CLI-provided options override saved config for this run
        cfg = RecordingConfig(
            preset=preset,
            domains=[validate_domain(d) for d in domain],
            paths=[normalize_path(p) for p in path],
        )
        return cfg

    saved = load_config(config_path)
    if saved is not None:
        return saved

    return RecordingConfig()  # empty — will fail validation


def _print_ca_guidance(port: int) -> None:
    ca_cert = Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.pem"
    click.echo(f"CA certificate    : {ca_cert}")
    click.echo(
        "  macOS  : sudo security add-trusted-cert -d -r trustRoot "
        f"-k /Library/Keychains/System.keychain {ca_cert}\n"
        "  Windows: import this certificate into Trusted Root Certification Authorities,\n"
        "    or set NODE_EXTRA_CA_CERTS for the target process only.\n"
        f"  Proxy  : set your client's HTTP proxy to http://127.0.0.1:{port}"
    )


@click.command()
@click.option("--port", default=7788, show_default=True, type=int, help="Port for the proxy.")
@click.option(
    "--output",
    default=str(DEFAULT_RAW_LOG_DIR),
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory where JSONL log files are written.",
)
@click.option("--domain", multiple=True, help="Record this domain (overrides saved config for this run).")
@click.option("--path", "path_filter", multiple=True, help="Only record paths matching this prefix.")
@click.option("--preset", default=None, help="Use a named preset (e.g. claude, codex).")
@click.option(
    "--config",
    "config_path",
    default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to config.toml (defaults to ~/.ccwhat/config.toml).",
)
def proxy(
    port: int,
    output: Path,
    domain: tuple[str, ...],
    path_filter: tuple[str, ...],
    preset: str | None,
    config_path: Path | None,
) -> None:
    """Start an HTTP/HTTPS intercepting proxy and record matching traffic to JSONL."""
    cfg = _build_recording_config_from_opts(domain, path_filter, preset, config_path)

    if not cfg.is_valid_for_recording():
        is_interactive = sys.stdin.isatty()
        if is_interactive:
            click.echo(
                "No recording domains configured.\n"
                "Run `ccwhat setup` to configure which model API endpoints to record.\n"
                "Or pass --domain / --preset directly: ccwhat proxy --preset codex",
                err=True,
            )
            from ccwhat.commands.setup import _run_setup_wizard
            cfg = _run_setup_wizard(config_path)
            if not cfg or not cfg.is_valid_for_recording():
                sys.exit(1)
        else:
            click.echo(
                "Error: no recording domains configured. Set up recording with:\n"
                "  ccwhat setup --preset claude --yes\n"
                "  ccwhat setup --preset codex --yes\n"
                "  ccwhat setup --domain <host> --path /v1/messages --yes\n"
                "  ccwhat discover\n"
                "Or pass --domain / --preset to this command.",
                err=True,
            )
            sys.exit(1)

    addon_path = Path(__file__).parent.parent / "addons" / "recorder.py"
    output.mkdir(parents=True, exist_ok=True)

    effective_domains = cfg.effective_domains()
    effective_paths = cfg.effective_paths()
    local_session_id = generate_local_session_id()

    bind_error = port_bind_error(port)
    if bind_error is not None:
        click.echo(
            format_port_bind_error(
                port,
                bind_error,
                "Use a different port: ccwhat proxy --port <other-port>",
            ),
            err=True,
        )
        sys.exit(1)

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
    env["CCWHAT_MAX_BODY_BYTES"] = str(cfg.max_body_bytes)
    env["CCWHAT_REDACT_HEADERS"] = ",".join(cfg.redact_headers)
    env["CCWHAT_REDACT_PATTERNS"] = ",".join(cfg.redact_header_patterns)
    env["CCWHAT_LOCAL_SESSION_ID"] = local_session_id

    click.echo(f"Proxy listening on http://127.0.0.1:{port}")
    click.echo(f"Recording domains : {', '.join(effective_domains)}")
    if effective_paths:
        click.echo(f"Path filters      : {', '.join(effective_paths)}")
    click.echo(f"Log directory     : {output.resolve()}")
    click.echo(f"Viewer hint       : ccwhat web")
    _print_ca_guidance(port)
    click.echo("Press Ctrl+C to stop.\n")

    try:
        result = subprocess.run(cmd, env=env)
        sys.exit(result.returncode)
    except FileNotFoundError:
        click.echo(mitmdump_missing_message(), err=True)
        sys.exit(1)
    except KeyboardInterrupt:
        click.echo("\nProxy stopped.")
