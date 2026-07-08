"""diagnose subcommand — generate OpenSpec action graph attribution outputs."""

from __future__ import annotations

from pathlib import Path

import click

from ccwhat.diagnosis import DiagnosisEngine, DiagnosisInputError
from ccwhat.diagnosis.engine import write_diagnosis_outputs


@click.command("diagnose")
@click.option(
    "--dataset",
    "dataset_path",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Dataset v1 directory or tar archive.",
)
@click.option("--task-id", required=True, help="Dataset task id to diagnose.")
@click.option(
    "--output",
    "output_dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory where event_graph.json, action_graph.json, and diagnosis.json are written.",
)
@click.option("--llm/--no-llm", default=False, show_default=True, help="LLM diagnosis is not supported in this MVP.")
def diagnose(dataset_path: Path, task_id: str, output_dir: Path, llm: bool) -> None:
    """Generate OpenSpec graph-backed diagnosis JSON for one Dataset task."""
    if llm:
        raise click.ClickException("LLM diagnosis is not supported in the OpenSpec Action Graph MVP. Use --no-llm.")
    try:
        event_graph, action_graph, diagnosis_result = DiagnosisEngine().diagnose_dataset_task(dataset_path, task_id)
        write_diagnosis_outputs(
            output_dir=output_dir,
            event_graph=event_graph,
            action_graph=action_graph,
            diagnosis=diagnosis_result,
        )
    except DiagnosisInputError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Wrote diagnosis outputs to {output_dir}")
