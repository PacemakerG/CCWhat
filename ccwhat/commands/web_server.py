"""web (web-server) subcommand — start the agent session viewer HTTP server."""

from __future__ import annotations

import socket
import webbrowser
from pathlib import Path

import click

from ccwhat.adapters.registry import create_adapter
from ccwhat.config import DEFAULT_CONFIG_PATH, DEFAULT_RAW_LOG_DIR
from ccwhat.runtime.infra.ports import format_port_bind_error, port_bind_error


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


@click.command("web")
@click.option("--port", default=7789, show_default=True, type=int, help="Port for the viewer API server.")
@click.option(
    "--agent",
    default="claude",
    show_default=True,
    type=str,
    help="Coding agent name (claude, codex, opencode).",
)
@click.option(
    "--projects-dir",
    default=None,
    type=click.Path(file_okay=False, path_type=Path),
    help="Path to the agent's projects directory. Overrides the agent default.",
)
@click.option(
    "--req-resp-dir",
    default=str(DEFAULT_RAW_LOG_DIR),
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory containing raw HTTP request/response JSONL files.",
)
@click.option(
    "--config",
    "config_path",
    default=str(DEFAULT_CONFIG_PATH),
    show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to config.toml used for recording status display.",
)
def web_server(
    port: int,
    agent: str,
    projects_dir: Path | None,
    req_resp_dir: Path,
    config_path: Path,
) -> None:
    """Start the session viewer API server."""
    import sys
    from pathlib import Path as _Path

    project_root = _Path(__file__).parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from viewer.server import run_server, viewer_url

    if _port_in_use(port):
        url = viewer_url(port)
        click.echo(f"Viewer may already be running: {url}")
        webbrowser.open(url)
        return

    bind_error = port_bind_error(port)
    if bind_error is not None:
        click.echo(
            format_port_bind_error(
                port,
                bind_error,
                "Use a different port: ccwhat web --port <other-port>",
            ),
            err=True,
        )
        raise click.ClickException("viewer port is not bindable")

    adapter = create_adapter(agent, projects_dir)
    resolved_projects_dir = projects_dir if projects_dir is not None else adapter.default_projects_dir()

    run_server(port, resolved_projects_dir, req_resp_dir, config_path=config_path, adapter=adapter)


# Keep old alias for backwards compatibility
web_server.name = "web"
