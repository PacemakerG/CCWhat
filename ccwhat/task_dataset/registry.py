"""Registry save/export helpers for Task Dataset v1."""

from __future__ import annotations

import io
import json
import re
import shutil
import tarfile
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ccwhat.runtime.infra.registry import RunRegistry
from ccwhat.task_segments.events import normalize_session_events
from ccwhat.task_segments.models import EvidenceBundle, NormalizedEvent, TaskSegment

from .builder import DatasetBuildError, build_dataset_bundle_from_segments
from .models import TaskDiffEvidence
from .validator import validate_dataset_path

OVERLAY_SCHEMA_VERSION = "task-trace-overlay-v1"
TASK_SEGMENTATION_SCHEMA_VERSION = "task-segmentation-v1"
DATASET_ID_RE = re.compile(r"^dataset-\d{8}-\d{6}-[0-9A-Za-z_-]+(?:-\d+)?$")
RUNTIME_RUN_ID_RE = re.compile(r"^run-\d{8}-\d{6}-[0-9a-fA-F]{8}$")
RUNTIME_TASK_ID_RE = re.compile(r"^task-\d{3,}$")


class DatasetRegistryError(ValueError):
    """Raised when a Dataset save/export request cannot be completed."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class SavedDataset:
    dataset_id: str
    dataset_path: Path
    download_url: str


def default_dataset_registry_root() -> Path:
    """Return the default local Dataset Registry root."""
    return Path.home() / ".ccwhat" / "datasets"


def save_task_dataset_from_request(
    *,
    payload: dict[str, Any],
    session: dict[str, Any],
    registry_root: Path | None = None,
    runtime_registry_root: Path | None = None,
    now: datetime | None = None,
) -> SavedDataset:
    """Validate a viewer request, build a Dataset bundle, and save it."""
    if _raw_inclusion_requested(payload.get("includeRawSession")) or _raw_inclusion_requested(payload.get("includeReqResp")):
        raise DatasetRegistryError("raw source inclusion is not supported in this Dataset version")

    session_id = _require_nonempty_string(payload, "sessionId")
    source = payload.get("source")
    if not isinstance(source, dict):
        raise DatasetRegistryError("task source payload is required")

    task_source = _require_nonempty_string(payload, "taskSource")
    normalized_events = normalize_session_events(session)
    event_ids = [event.event_id for event in normalized_events]
    if not event_ids:
        raise DatasetRegistryError("current session has no normalized events to align source trace")

    metadata = _session_metadata(session)
    tasks, task_diffs = _tasks_from_source(
        source=source,
        task_source=task_source,
        request_session_id=session_id,
        events=normalized_events,
        session_metadata=metadata,
        runtime_registry_root=runtime_registry_root,
    )

    bundle = build_dataset_bundle_from_segments(
        session_metadata=metadata,
        events=normalized_events,
        tasks=tasks,
        session_id=session_id,
        task_source=task_source,
        task_diffs=task_diffs,
    )

    root = (registry_root or default_dataset_registry_root()).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    dataset_id = _unique_dataset_id(root, session_id, now or datetime.now(timezone.utc))
    target_dir = root / dataset_id
    tmp_dir = root / f".{dataset_id}.tmp-{uuid.uuid4().hex[:8]}"
    try:
        bundle.write_to_directory(tmp_dir)
        result = validate_dataset_path(tmp_dir)
        if not result.ok:
            details = "; ".join(_format_issue(issue) for issue in result.errors[:5])
            raise DatasetRegistryError(f"Dataset validator failed: {details}", status=500)
        tmp_dir.rename(target_dir)
    except DatasetRegistryError:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except (OSError, DatasetBuildError) as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise DatasetRegistryError(f"failed to save Dataset: {exc}", status=500) from exc

    return SavedDataset(
        dataset_id=dataset_id,
        dataset_path=target_dir,
        download_url=f"/api/task-datasets/{dataset_id}/download",
    )


def build_dataset_tar_gz(
    *,
    dataset_id: str,
    registry_root: Path | None = None,
) -> tuple[bytes, str]:
    """Build a validated Dataset tar.gz for a saved registry entry."""
    dataset_dir = _resolve_dataset_dir(dataset_id, registry_root or default_dataset_registry_root())
    result = validate_dataset_path(dataset_dir)
    if not result.ok:
        details = "; ".join(_format_issue(issue) for issue in result.errors[:5])
        raise DatasetRegistryError(f"Dataset validator failed: {details}", status=500)

    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as tar:
        for child in sorted(dataset_dir.rglob("*")):
            if not child.is_file():
                continue
            rel_path = child.relative_to(dataset_dir).as_posix()
            if not _allowed_dataset_member(rel_path):
                continue
            tar.add(child, arcname=f"ccwhat-dataset/{rel_path}")
    data.seek(0)
    tar_bytes = data.getvalue()

    with tempfile.NamedTemporaryFile(suffix=".tar.gz") as tmp:
        tmp.write(tar_bytes)
        tmp.flush()
        tar_result = validate_dataset_path(tmp.name)
        if not tar_result.ok:
            details = "; ".join(_format_issue(issue) for issue in tar_result.errors[:5])
            raise DatasetRegistryError(f"Dataset tar validator failed: {details}", status=500)

    return tar_bytes, f"{dataset_id}.tar.gz"


def _tasks_from_source(
    *,
    source: dict[str, Any],
    task_source: str,
    request_session_id: str,
    events: list[NormalizedEvent],
    session_metadata: dict[str, Any],
    runtime_registry_root: Path | None,
) -> tuple[list[TaskSegment], dict[str, TaskDiffEvidence]]:
    event_ids = [event.event_id for event in events]
    kind = str(source.get("kind") or "").strip()
    if task_source == "activeOverlay":
        if kind != "overlay":
            raise DatasetRegistryError("taskSource activeOverlay must use source.kind overlay")
        return _overlay_tasks(source, request_session_id, event_ids), {}
    if task_source == "taskSegments":
        if kind != "taskSegments":
            raise DatasetRegistryError("taskSource taskSegments must use source.kind taskSegments")
        return _segmentation_tasks(source, request_session_id, event_ids), {}
    if task_source == "runtimeTasks":
        if kind != "runtimeTasks":
            raise DatasetRegistryError("taskSource runtimeTasks must use source.kind runtimeTasks")
        return _runtime_tasks(
            source=source,
            events=events,
            session_metadata=session_metadata,
            runtime_registry_root=runtime_registry_root,
        )
    raise DatasetRegistryError("taskSource must be activeOverlay, taskSegments, or runtimeTasks")


def _raw_inclusion_requested(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"", "false", "0", "no", "n", "off", "disabled", "disable"}:
            return False
        return normalized in {"true", "1", "yes", "y", "on", "enabled", "enable", "include", "included"}
    if value is None:
        return False
    return bool(value)


def _overlay_tasks(
    source: dict[str, Any],
    request_session_id: str,
    event_ids: list[str],
) -> list[TaskSegment]:
    overlay = _source_payload(source, "overlay")
    overlay_version = source.get("overlayVersion") or overlay.get("schemaVersion") or overlay.get("version")
    if overlay_version != OVERLAY_SCHEMA_VERSION:
        raise DatasetRegistryError("overlay version is missing or unsupported")
    provenance = _require_provenance(source, overlay, request_session_id)
    if overlay.get("dirty") is True or provenance.get("dirty") is True:
        raise DatasetRegistryError("dirty overlay cannot be saved as Dataset source")
    if overlay.get("saved") is not True and provenance.get("saved") is not True and not provenance.get("savedAt"):
        raise DatasetRegistryError("overlay provenance must show the overlay has been saved")
    _validate_source_trace(source, overlay, request_session_id, event_ids)
    return _segments_from_payload(overlay, event_ids)


def _segmentation_tasks(
    source: dict[str, Any],
    request_session_id: str,
    event_ids: list[str],
) -> list[TaskSegment]:
    payload = _source_payload(source, "taskSegments")
    source_schema_version = (
        source.get("sourceSchemaVersion")
        or payload.get("schemaVersion")
        or payload.get("version")
    )
    if source_schema_version != TASK_SEGMENTATION_SCHEMA_VERSION:
        raise DatasetRegistryError("task segmentation source schema version is missing or unsupported")
    _require_provenance(source, payload, request_session_id)
    _validate_source_trace(source, payload, request_session_id, event_ids)
    return _segments_from_payload(payload, event_ids)


def _runtime_tasks(
    *,
    source: dict[str, Any],
    events: list[NormalizedEvent],
    session_metadata: dict[str, Any],
    runtime_registry_root: Path | None,
) -> tuple[list[TaskSegment], dict[str, TaskDiffEvidence]]:
    payload = source.get("payload") if isinstance(source.get("payload"), dict) else source
    run_id = str(payload.get("runId") or payload.get("run_id") or "").strip()
    if not RUNTIME_RUN_ID_RE.fullmatch(run_id):
        raise DatasetRegistryError("runtime task source requires a valid runId")

    registry = RunRegistry(runtime_registry_root)
    try:
        run = registry.load(run_id)
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise DatasetRegistryError("runtime run was not found or is invalid", status=404) from exc

    _validate_runtime_session(run.agent, run.workspace, session_metadata)
    requested_ids = _runtime_task_ids(payload.get("taskIds") or payload.get("task_ids"))
    task_root = registry.run_dir(run_id) / "tasks"
    task_dirs = sorted(path for path in task_root.glob("task-*") if path.is_dir())
    if requested_ids is not None:
        available = {path.name: path for path in task_dirs}
        missing = [task_id for task_id in requested_ids if task_id not in available]
        if missing:
            raise DatasetRegistryError(f"runtime task was not found: {missing[0]}", status=404)
        task_dirs = [available[task_id] for task_id in requested_ids]

    tasks: list[TaskSegment] = []
    task_diffs: dict[str, TaskDiffEvidence] = {}
    for index, task_dir in enumerate(task_dirs, 1):
        task_path = task_dir / "task.json"
        diff_path = task_dir / "task.diff"
        try:
            task_record = json.loads(task_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            if requested_ids is None:
                continue
            raise DatasetRegistryError(f"runtime task metadata is invalid: {task_dir.name}") from exc
        if not isinstance(task_record, dict):
            raise DatasetRegistryError(f"runtime task metadata is invalid: {task_dir.name}")

        if not task_record.get("finished_at") or not diff_path.is_file():
            if requested_ids is None:
                continue
            raise DatasetRegistryError(f"runtime task is not finalized: {task_dir.name}")
        task_id = str(task_record.get("task_id") or task_dir.name)
        if task_id != task_dir.name or not RUNTIME_TASK_ID_RE.fullmatch(task_id):
            raise DatasetRegistryError(f"runtime task id is invalid: {task_dir.name}")
        if str(task_record.get("run_id") or run_id) != run_id:
            raise DatasetRegistryError(f"runtime task run_id does not match: {task_id}")

        task_events = _events_in_runtime_window(
            events,
            started_at=task_record.get("started_at"),
            finished_at=task_record.get("finished_at"),
            task_id=task_id,
        )
        tasks.append(
            TaskSegment(
                task_id=task_id,
                title=str(task_record.get("title") or f"任务 {index}"),
                task_type="unknown",
                status="unevaluated",
                start_event_id=task_events[0].event_id,
                end_event_id=task_events[-1].event_id,
                boundary_reasons=["runtime /ccwhat:start and /ccwhat:finish"],
                is_open=False,
            )
        )
        try:
            diff_content = diff_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise DatasetRegistryError(f"runtime task diff is invalid: {task_id}") from exc
        task_diffs[task_id] = TaskDiffEvidence(content=diff_content)

    if not tasks:
        raise DatasetRegistryError("runtime run has no finalized tasks that align with this session")
    return tasks, task_diffs


def _runtime_task_ids(raw_task_ids: Any) -> list[str] | None:
    if raw_task_ids is None:
        return None
    if not isinstance(raw_task_ids, list) or not raw_task_ids:
        raise DatasetRegistryError("runtime taskIds must be a non-empty array")
    task_ids = [str(task_id).strip() for task_id in raw_task_ids]
    if any(not RUNTIME_TASK_ID_RE.fullmatch(task_id) for task_id in task_ids):
        raise DatasetRegistryError("runtime taskIds contains an invalid task id")
    return list(dict.fromkeys(task_ids))


def _validate_runtime_session(
    run_agent: str,
    run_workspace: str,
    session_metadata: dict[str, Any],
) -> None:
    session_agent = str(session_metadata.get("agent") or "").strip().lower()
    if session_agent and session_agent != str(run_agent).strip().lower():
        raise DatasetRegistryError("runtime run agent does not match the selected session")
    session_workspace = session_metadata.get("project_dir")
    if session_workspace:
        selected = Path(str(session_workspace)).expanduser().resolve()
        recorded = Path(run_workspace).expanduser().resolve()
        if selected != recorded:
            raise DatasetRegistryError("runtime run workspace does not match the selected session")


def _events_in_runtime_window(
    events: list[NormalizedEvent],
    *,
    started_at: Any,
    finished_at: Any,
    task_id: str,
) -> list[NormalizedEvent]:
    start = _parse_timestamp(started_at, f"runtime task {task_id} started_at")
    finish = _parse_timestamp(finished_at, f"runtime task {task_id} finished_at")
    if finish < start:
        raise DatasetRegistryError(f"runtime task {task_id} has an invalid time window")

    selected = []
    for event in events:
        if not event.timestamp:
            continue
        try:
            event_time = _parse_timestamp(event.timestamp, "event timestamp")
        except DatasetRegistryError:
            continue
        if start <= event_time <= finish:
            selected.append(event)
    if not selected:
        raise DatasetRegistryError(
            f"runtime task {task_id} cannot be aligned to normalized session events by timestamp"
        )
    return selected


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise DatasetRegistryError(f"{field} is required")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise DatasetRegistryError(f"{field} is invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _source_payload(source: dict[str, Any], preferred_key: str) -> dict[str, Any]:
    payload = source.get("payload") or source.get(preferred_key)
    if not isinstance(payload, dict):
        raise DatasetRegistryError("task source payload is required")
    if not isinstance(payload.get("tasks"), list) or not payload["tasks"]:
        raise DatasetRegistryError("task source payload must include tasks")
    return payload


def _require_provenance(
    source: dict[str, Any],
    payload: dict[str, Any],
    request_session_id: str,
) -> dict[str, Any]:
    provenance = source.get("provenance") or payload.get("provenance")
    if not isinstance(provenance, dict):
        raise DatasetRegistryError("Dataset source provenance is required")
    for candidate in (payload.get("sessionId"), source.get("sessionId"), provenance.get("sessionId")):
        if candidate is not None and str(candidate) != request_session_id:
            raise DatasetRegistryError("session provenance does not match request sessionId")
    if not provenance.get("sessionId"):
        raise DatasetRegistryError("Dataset source provenance is missing sessionId")
    return provenance


def _validate_source_trace(
    source: dict[str, Any],
    payload: dict[str, Any],
    request_session_id: str,
    event_ids: list[str],
) -> None:
    source_trace = source.get("sourceTrace") or payload.get("sourceTrace")
    if not isinstance(source_trace, dict):
        raise DatasetRegistryError("source trace information is required")
    if source_trace.get("sessionId") is not None and str(source_trace.get("sessionId")) != request_session_id:
        raise DatasetRegistryError("source trace session does not match request sessionId")
    trace_event_ids = source_trace.get("eventIds")
    if isinstance(trace_event_ids, list):
        missing = [str(event_id) for event_id in trace_event_ids if str(event_id) not in event_ids]
        if missing:
            raise DatasetRegistryError(f"source trace cannot be aligned: missing event {missing[0]}")
    elif not source_trace.get("sourceTraceId"):
        raise DatasetRegistryError("source trace information must include eventIds or sourceTraceId")


def _segments_from_payload(payload: dict[str, Any], event_ids: list[str]) -> list[TaskSegment]:
    event_index = {event_id: index for index, event_id in enumerate(event_ids)}
    tasks = []
    for idx, raw_task in enumerate(payload.get("tasks") or [], 1):
        if not isinstance(raw_task, dict):
            raise DatasetRegistryError(f"task {idx} must be an object")
        task_id = str(raw_task.get("taskId") or raw_task.get("task_id") or f"task-{idx:03d}")
        start_event_id = raw_task.get("startEventId") or raw_task.get("start_event_id")
        end_event_id = raw_task.get("endEventId") if "endEventId" in raw_task else raw_task.get("end_event_id")
        if not isinstance(start_event_id, str) or not start_event_id:
            raise DatasetRegistryError(f"task {task_id} is missing startEventId")
        if start_event_id not in event_index:
            raise DatasetRegistryError(f"source trace cannot be aligned: task {task_id} startEventId was not found")
        if end_event_id is not None:
            if not isinstance(end_event_id, str) or not end_event_id:
                raise DatasetRegistryError(f"task {task_id} has invalid endEventId")
            if end_event_id not in event_index:
                raise DatasetRegistryError(f"source trace cannot be aligned: task {task_id} endEventId was not found")
            if event_index[end_event_id] < event_index[start_event_id]:
                raise DatasetRegistryError(f"task {task_id} endEventId is before startEventId")
        tasks.append(
            TaskSegment(
                task_id=task_id,
                title=str(raw_task.get("title") or f"任务 {idx}"),
                task_type=str(raw_task.get("taskType") or raw_task.get("task_type") or "unknown"),
                status=str(raw_task.get("status") or "unevaluated"),
                start_event_id=start_event_id,
                end_event_id=end_event_id,
                boundary_reasons=list(raw_task.get("boundaryReasons") or raw_task.get("boundary_reasons") or []),
                evidence=_evidence_from_task(raw_task.get("evidence")),
                file_weights=dict(raw_task.get("fileWeights") or raw_task.get("file_weights") or {}),
                is_ambiguous=bool(raw_task.get("isAmbiguous") or raw_task.get("is_ambiguous") or False),
                final_claim=raw_task.get("finalClaim") or raw_task.get("final_claim"),
                is_open=bool(raw_task.get("isOpen") if "isOpen" in raw_task else raw_task.get("is_open", True)),
            )
        )
    if not tasks:
        raise DatasetRegistryError("task source payload must include tasks")
    return tasks


def _evidence_from_task(raw_evidence: Any) -> EvidenceBundle:
    evidence = raw_evidence if isinstance(raw_evidence, dict) else {}
    return EvidenceBundle(
        files_read=list(evidence.get("filesRead") or evidence.get("files_read") or []),
        files_changed=list(evidence.get("filesChanged") or evidence.get("files_changed") or []),
        commands=list(evidence.get("commands") or []),
        test_commands=list(evidence.get("testCommands") or evidence.get("test_commands") or []),
        errors=list(evidence.get("errors") or []),
        skills=list(evidence.get("skills") or []),
        subagent_ids=list(evidence.get("subagentIds") or evidence.get("subagent_ids") or []),
        final_claims=list(evidence.get("finalClaims") or evidence.get("final_claims") or []),
        todos_user=list(evidence.get("todosUser") or evidence.get("todos_user") or []),
        todos_assistant=list(evidence.get("todosAssistant") or evidence.get("todos_assistant") or []),
        todos_tool=list(evidence.get("todosTool") or evidence.get("todos_tool") or []),
        file_weights=dict(evidence.get("fileWeights") or evidence.get("file_weights") or {}),
    )


def _session_metadata(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent": session.get("agent") or session.get("agent_type") or session.get("source_agent"),
        "project_dir": session.get("projectDir") or session.get("project_dir") or session.get("cwd"),
        "repo": session.get("repo") or session.get("project"),
        "base_commit": session.get("baseCommit") or session.get("base_commit"),
        "head_commit": session.get("headCommit") or session.get("head_commit"),
        "git_dirty_at_export": session.get("gitDirtyAtExport") or session.get("git_dirty_at_export"),
    }


def _unique_dataset_id(root: Path, session_id: str, now: datetime) -> str:
    timestamp = now.astimezone(timezone.utc).strftime("%Y%m%d-%H%M%S")
    session_short_id = re.sub(r"[^0-9A-Za-z_-]", "", session_id)[:8] or "session"
    base = f"dataset-{timestamp}-{session_short_id}"
    candidate = base
    suffix = 1
    while (root / candidate).exists():
        suffix += 1
        candidate = f"{base}-{suffix}"
    return candidate


def _resolve_dataset_dir(dataset_id: str, registry_root: Path) -> Path:
    if not DATASET_ID_RE.fullmatch(dataset_id):
        raise DatasetRegistryError("invalid dataset id", status=400)
    root = registry_root.expanduser().resolve()
    dataset_dir = (root / dataset_id).resolve()
    if dataset_dir.parent != root:
        raise DatasetRegistryError("invalid dataset path", status=400)
    if not dataset_dir.is_dir():
        raise DatasetRegistryError("Dataset not found", status=404)
    return dataset_dir


def _allowed_dataset_member(rel_path: str) -> bool:
    if rel_path in {"manifest.json", "dataset.jsonl", "scores.jsonl"}:
        return True
    if rel_path.startswith("traces/") and rel_path.endswith(".json"):
        return True
    return rel_path.startswith("diffs/") and rel_path.endswith(".diff")


def _require_nonempty_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise DatasetRegistryError(f"{field} is required")
    return value.strip()


def _format_issue(issue: Any) -> str:
    field = f" {issue.field}" if getattr(issue, "field", None) else ""
    return f"{issue.path}{field}: {issue.message}"
