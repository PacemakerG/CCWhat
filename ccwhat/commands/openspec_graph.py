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
@click.option("--event", "event_type", default=None, help="Optional workflow event type to append before syncing.")
@click.option("--artifact", default=None, help="Artifact name for artifact events.")
@click.option("--task", default=None, help="Task label for task events.")
@click.option("--success/--failure", default=None, help="Success flag for validation/archive events.")
@click.option("--note", default=None, help="Optional event note.")
def sync(
    change: str,
    event_type: str | None,
    artifact: str | None,
    task: str | None,
    success: bool | None,
    note: str | None,
) -> None:
    """Sync graph/*.json for an OpenSpec change."""
    try:
        outputs = sync_openspec_graph(
            change=change,
            event_type=event_type,
            artifact=artifact,
            task=task,
            success=success,
            note=note,
            cwd=Path.cwd(),
        )
    except OpenSpecGraphError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"OpenSpec graph synced: {outputs['diagnosis'].parent}")
