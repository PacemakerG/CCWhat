"""openspec-graph subcommands."""

from __future__ import annotations

from pathlib import Path

import click

from ccwhat.openspec_graph import OpenSpecGraphError, sync_openspec_graph


@click.group("openspec-graph")
def openspec_graph() -> None:
    """Generate OpenSpec workflow graph artifacts."""


@openspec_graph.command("sync")
@click.option("--change", required=True, help="OpenSpec change name.")
@click.option("--session-id", required=True, help="Claude Code session id containing the Marker commands.")
@click.option("--projects-dir", type=click.Path(path_type=Path), default=None, help="Claude projects directory for --session-id lookup.")
def sync(
    change: str,
    session_id: str,
    projects_dir: Path | None,
) -> None:
    """Sync graph/*.json from one Marker-scoped Claude Code Session."""
    try:
        outputs = sync_openspec_graph(
            change=change,
            session_id=session_id,
            projects_dir=projects_dir,
            cwd=Path.cwd(),
        )
    except OpenSpecGraphError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"OpenSpec graph synced: {outputs['diagnosis'].parent}")
