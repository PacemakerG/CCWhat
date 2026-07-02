"""Start command for CCWhat tracking session."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import click

from ccwhat.commands.run import run
from ccwhat.config import DEFAULT_RAW_LOG_DIR


@click.command()
@click.option("--port", default=None, show_default="auto", type=int, help="Proxy port.")
@click.option("--web/--no-web", default=True, show_default=True, help="Start and open the viewer.")
@click.option("--web-port", default=None, show_default="auto", type=int, help="Viewer port.")
@click.option(
    "--output",
    default=str(DEFAULT_RAW_LOG_DIR),
    show_default=True,
    type=click.Path(file_okay=False),
    help="Directory where JSONL log files are written.",
)
@click.option(
    "--config",
    "config_path",
    default=None,
    type=click.Path(dir_okay=False),
    help="Path to config.toml.",
)
def start(
    port: int | None,
    web: bool,
    web_port: int | None,
    output: str,
    config_path: str | None,
) -> None:
    """Start a CCWhat tracking session with task boundary diff recording.

    This command launches Claude Code with CCWhat tracking enabled.
    File modifications between /ccwhat:start and /ccwhat:finish are recorded to task.diff.

    Examples:

        ccwhat start                    # Start with default settings

        ccwhat start --no-web           # Start without viewer

        ccwhat start --port 8080        # Use custom proxy port
    """
    # Set environment variable to enable diff tracking
    os.environ["CCWHAT_ENABLED"] = "1"

    ctx = click.get_current_context()

    # Invoke the run command with claude as target
    ctx.invoke(
        run,
        port=port,
        web=web,
        web_port=web_port,
        output=Path(output),
        config_path=Path(config_path) if config_path else None,
        no_setup=False,
        runtime_recording=True,
        target_args=("claude",),
    )
