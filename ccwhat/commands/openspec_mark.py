"""Write explicit OpenSpec action boundary markers."""

from __future__ import annotations

from pathlib import Path

import click

from ccwhat.openspec_graph import OpenSpecGraphError, write_openspec_marker


@click.command("openspec-mark")
@click.option("--change", required=True, help="OpenSpec change name.")
@click.option("--action", required=True, help="OpenSpec action: proposal, specs, design, tasks, apply, verify or archive.")
@click.option("--phase", type=click.Choice(["start", "end"]), required=True, help="Action boundary phase.")
@click.option("--marker-id", required=True, help="Unique marker id included in this command's Session event.")
def openspec_mark(change: str, action: str, phase: str, marker_id: str) -> None:
    """Write one OpenSpec action boundary marker."""
    try:
        path = write_openspec_marker(
            change=change,
            action=action,
            phase=phase,
            marker_id=marker_id,
            cwd=Path.cwd(),
        )
    except OpenSpecGraphError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"OpenSpec marker written: {path}")
