"""Build Task Dataset v1 bundles from segmented sessions."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ccwhat.task_segments.evidence import extract_evidence
from ccwhat.task_segments.models import (
    EvidenceBundle,
    NormalizedEvent,
    TaskSegment,
    TaskSegmentationResult,
)

from .change_evidence import extract_change_evidence
from .models import DATASET_SCHEMA_VERSION, DIFFS_DIR, DatasetBundle, TaskDiffEvidence


class DatasetBuildError(ValueError):
    """Raised when a Dataset bundle cannot be built from the supplied inputs."""


def build_dataset_bundle(
    *,
    session_metadata: dict[str, Any],
    events: list[NormalizedEvent],
    segmentation: TaskSegmentationResult,
    task_source: str = "auto",
    task_diffs: dict[str, TaskDiffEvidence] | None = None,
    created_at: str | None = None,
) -> DatasetBundle:
    """Build a Dataset v1 bundle from a TaskSegmentationResult."""
    return build_dataset_bundle_from_segments(
        session_metadata=session_metadata,
        events=events,
        tasks=segmentation.tasks,
        session_id=segmentation.session_id,
        task_source=task_source,
        task_diffs=task_diffs,
        created_at=created_at,
    )


def build_dataset_bundle_from_segments(
    *,
    session_metadata: dict[str, Any],
    events: list[NormalizedEvent],
    tasks: list[TaskSegment],
    session_id: str,
    task_source: str = "auto",
    task_diffs: dict[str, TaskDiffEvidence] | None = None,
    created_at: str | None = None,
) -> DatasetBundle:
    """Build a Dataset v1 bundle from explicit task segments."""
    if not tasks:
        raise DatasetBuildError("Cannot build Dataset v1: task list is empty.")
    if not events:
        raise DatasetBuildError("Cannot build Dataset v1: normalized events are empty.")

    event_index = {event.event_id: index for index, event in enumerate(events)}
    agent = _first_present(
        session_metadata,
        "agent",
        "agent_type",
        "source_agent",
        default=None,
    )
    project_dir = _first_present(
        session_metadata,
        "project_dir",
        "projectDir",
        "cwd",
        default=None,
    )
    repo = _first_present(session_metadata, "repo", "repo_name", "project", default=None)
    if repo is None and project_dir:
        repo = Path(str(project_dir)).name

    base_commit = _first_present(session_metadata, "base_commit", "baseCommit", default=None)
    head_commit = _first_present(session_metadata, "head_commit", "headCommit", default=None)
    git_dirty = _first_present(
        session_metadata,
        "git_dirty_at_export",
        "gitDirtyAtExport",
        default=None,
    )

    dataset_rows = []
    traces = {}
    diffs: dict[str, str] = {}
    diff_evidence_by_task = task_diffs or {}

    for task in tasks:
        trace_id = f"trace-{task.task_id}"
        trace_path = f"traces/{trace_id}.json"
        task_events = _slice_events(events, event_index, task)
        evidence = _merge_evidence(task.evidence, task_events, repo_root=str(project_dir) if project_dir else None)
        changes, patches = extract_change_evidence(task_events, agent=agent)
        diff_evidence = diff_evidence_by_task.get(task.task_id)
        diff_path = f"{DIFFS_DIR}/{trace_id}.diff" if diff_evidence is not None else None
        if diff_evidence is not None and diff_path is not None:
            diffs[diff_path] = diff_evidence.content

        dataset_rows.append(
            {
                "id": task.task_id,
                "input": {
                    "instruction": _instruction_for_task(task, task_events),
                    "repo": repo,
                    "base_commit": base_commit,
                },
                "expected": {
                    "success_criteria": _success_criteria_for_task(task),
                    "tests": list(evidence.test_commands),
                },
                "metadata": {
                    "agent": agent,
                    "session_id": session_id,
                    "task_source": task_source,
                    "trace_id": trace_id,
                    "trace_path": trace_path,
                    "start_event_id": task.start_event_id,
                    "end_event_id": task.end_event_id,
                    "task_type": task.task_type,
                    "status": task.status,
                },
            }
        )

        traces[trace_id] = {
            "trace_id": trace_id,
            "task_id": task.task_id,
            "session_id": session_id,
            "agent": agent,
            "boundary": {
                "start_event_id": task.start_event_id,
                "end_event_id": task.end_event_id,
                "start_turn": task_events[0].turn_index if task_events else None,
                "end_turn": task_events[-1].turn_index if task_events else None,
            },
            "events": [_event_to_dict(event) for event in task_events],
            "commands": list(evidence.commands),
            "test_commands": list(evidence.test_commands),
            "files": {
                "read": list(evidence.files_read),
                "changed": list(evidence.files_changed),
            },
            "changes": changes,
            "patches": patches,
            "errors": list(evidence.errors),
            "final_claim": task.final_claim or (evidence.final_claims[0] if evidence.final_claims else None),
            "repo_state": {
                "cwd": project_dir,
                "base_commit": base_commit,
                "head_commit": head_commit,
                "git_dirty_at_export": git_dirty,
            },
            "task_diff": {
                "available": diff_evidence is not None,
                "source": diff_evidence.source if diff_evidence is not None else None,
                "confidence": diff_evidence.confidence if diff_evidence is not None else None,
                "path": diff_path,
            },
        }

    manifest = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "created_at": created_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "tool": "ccwhat",
        "session": {
            "session_id": session_id,
            "agent": agent,
            "project_dir": project_dir,
        },
        "counts": {
            "dataset_items": len(dataset_rows),
            "traces": len(traces),
            "scores": 0,
        },
    }

    return DatasetBundle(
        manifest=manifest,
        dataset_rows=dataset_rows,
        traces=traces,
        scores_rows=[],
        diffs=diffs,
    )


def _slice_events(
    events: list[NormalizedEvent],
    event_index: dict[str, int],
    task: TaskSegment,
) -> list[NormalizedEvent]:
    if task.start_event_id not in event_index:
        raise DatasetBuildError(
            f"Cannot build trace for {task.task_id}: start_event_id "
            f"{task.start_event_id!r} was not found."
        )
    start = event_index[task.start_event_id]
    if task.end_event_id is None:
        end = len(events) - 1
    else:
        if task.end_event_id not in event_index:
            raise DatasetBuildError(
                f"Cannot build trace for {task.task_id}: end_event_id "
                f"{task.end_event_id!r} was not found."
            )
        end = event_index[task.end_event_id]
    if end < start:
        raise DatasetBuildError(
            f"Cannot build trace for {task.task_id}: end_event_id "
            f"{task.end_event_id!r} is before start_event_id {task.start_event_id!r}."
        )
    return events[start : end + 1]


def _merge_evidence(
    task_evidence: EvidenceBundle,
    task_events: list[NormalizedEvent],
    repo_root: str | None,
) -> EvidenceBundle:
    extracted = extract_evidence(task_events, repo_root=repo_root)
    merged = EvidenceBundle(
        files_read=_dedupe([*task_evidence.files_read, *extracted.files_read]),
        files_changed=_dedupe([*task_evidence.files_changed, *extracted.files_changed]),
        commands=_dedupe([*task_evidence.commands, *extracted.commands]),
        test_commands=_dedupe([*task_evidence.test_commands, *extracted.test_commands]),
        errors=_dedupe([*task_evidence.errors, *extracted.errors]),
        skills=_dedupe([*task_evidence.skills, *extracted.skills]),
        subagent_ids=_dedupe([*task_evidence.subagent_ids, *extracted.subagent_ids]),
        final_claims=_dedupe([*task_evidence.final_claims, *extracted.final_claims]),
        todos_user=_dedupe([*task_evidence.todos_user, *extracted.todos_user]),
        todos_assistant=_dedupe([*task_evidence.todos_assistant, *extracted.todos_assistant]),
        todos_tool=_dedupe([*task_evidence.todos_tool, *extracted.todos_tool]),
    )
    merged.file_weights = {**extracted.file_weights, **task_evidence.file_weights}
    return merged


def _instruction_for_task(
    task: TaskSegment,
    task_events: list[NormalizedEvent],
) -> str | None:
    if task.evidence.todos_user:
        return task.evidence.todos_user[0]
    for event in task_events:
        if event.event_type == "user_message" and event.text.strip():
            return event.text.strip()
    return task.title or None


def _success_criteria_for_task(task: TaskSegment) -> str | None:
    value = getattr(task.evidence, "success_criteria", None)
    return value if isinstance(value, str) and value else None


def _event_to_dict(event: NormalizedEvent) -> dict[str, Any]:
    return asdict(event)


def _first_present(
    values: dict[str, Any],
    *keys: str,
    default: Any,
) -> Any:
    for key in keys:
        value = values.get(key)
        if value is not None:
            return value
    return default


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
