"""OpenSpec workflow graph synchronization."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ccwhat.adapters.claude import ClaudeAdapter
from ccwhat.diagnosis.action_graph import OPEN_SPEC_ACTIONS
from ccwhat.diagnosis.action_graph import build_openspec_action_graph
from ccwhat.diagnosis.attribution import attribute_symptoms
from ccwhat.diagnosis.engine import DiagnosisEngine, DiagnosisInputError
from ccwhat.diagnosis.event_graph import build_event_graph
from ccwhat.diagnosis.mapping import map_events_to_actions
from ccwhat.diagnosis.models import ActionGraph, ActionNode, EventGraph, GraphEdge, GraphNode, Symptom
from ccwhat.diagnosis.symptoms import detect_symptoms
from ccwhat.task_dataset import default_dataset_registry_root
from ccwhat.task_segments.events import normalize_session_events
from ccwhat.task_segments.models import NormalizedEvent


class OpenSpecGraphError(ValueError):
    """Raised when an OpenSpec graph cannot be synchronized."""


_CHANGE_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
_MARKER_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_MARKER_PHASES = {"start", "end"}
_ACTION_IDS_BY_TYPE = {action_type: action_id for action_id, action_type, _ in OPEN_SPEC_ACTIONS}


@dataclass
class OpenSpecGraphEvent:
    type: str
    timestamp: str
    artifact: str | None = None
    task: str | None = None
    success: bool | None = None
    note: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value not in (None, {}, [])}


def write_openspec_marker(
    *,
    change: str,
    action: str,
    phase: str,
    marker_id: str,
    cwd: str | Path | None = None,
) -> Path:
    """Append one explicit OpenSpec action boundary marker."""
    if not _CHANGE_NAME_RE.fullmatch(change):
        raise OpenSpecGraphError("change must be a lowercase kebab-case name.")
    if action not in _ACTION_IDS_BY_TYPE:
        raise OpenSpecGraphError(f"action must be one of: {', '.join(_ACTION_IDS_BY_TYPE)}.")
    if phase not in _MARKER_PHASES:
        raise OpenSpecGraphError("phase must be start or end.")
    if not _MARKER_ID_RE.fullmatch(marker_id):
        raise OpenSpecGraphError("marker-id must contain only letters, digits, '.', '_', ':' or '-'.")

    root = Path(cwd or ".").resolve()
    graph_dir = _resolve_change_root(change, root) / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)
    path = graph_dir / "markers.jsonl"
    markers = _load_markers(path)
    if any(item.get("marker_id") == marker_id for item in markers):
        raise OpenSpecGraphError(f"marker-id {marker_id!r} already exists for change {change!r}.")
    if any(item.get("action") == action and item.get("phase") == phase for item in markers):
        raise OpenSpecGraphError(f"{action} already has a {phase} marker for change {change!r}.")

    marker = {
        "marker_id": marker_id,
        "change": change,
        "action": action,
        "phase": phase,
        "timestamp": _now(),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(marker, ensure_ascii=False) + "\n")
    return path


def sync_openspec_graph(
    *,
    change: str,
    event_type: str | None = None,
    artifact: str | None = None,
    task: str | None = None,
    task_id: str | None = None,
    dataset_id: str | None = None,
    session_id: str | None = None,
    projects_dir: str | Path | None = None,
    allow_full_session: bool = False,
    success: bool | None = None,
    note: str | None = None,
    cwd: str | Path | None = None,
) -> dict[str, Path]:
    root = Path(cwd or ".").resolve()
    change_root = _resolve_change_root(change, root)
    graph_dir = change_root / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)

    if event_type:
        _append_event(
            graph_dir / "events.jsonl",
            OpenSpecGraphEvent(
                type=event_type,
                timestamp=_now(),
                artifact=artifact,
                task=task,
                success=success,
                note=note,
            ),
        )

    events = _load_events(graph_dir / "events.jsonl")
    event_graph, action_graph, diagnosis = _build_graph_payloads(
        change=change,
        change_root=change_root,
        milestone_events=events,
        dataset_id=dataset_id,
        session_id=session_id,
        task_id=task_id,
        projects_dir=Path(projects_dir).expanduser() if projects_dir else None,
        allow_full_session=allow_full_session,
    )

    outputs = {
        "events": graph_dir / "events.jsonl",
        "event_graph": graph_dir / "event_graph.json",
        "action_graph": graph_dir / "action_graph.json",
        "diagnosis": graph_dir / "diagnosis.json",
    }
    _write_json(outputs["event_graph"], event_graph)
    _write_json(outputs["action_graph"], action_graph)
    _write_json(outputs["diagnosis"], diagnosis)
    return outputs


def _build_graph_payloads(
    *,
    change: str,
    change_root: Path,
    milestone_events: list[dict[str, Any]],
    dataset_id: str | None,
    session_id: str | None,
    task_id: str | None,
    projects_dir: Path | None,
    allow_full_session: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    missing_evidence: list[str] = []
    if dataset_id:
        try:
            return _dataset_graph_payloads(
                change=change,
                dataset_id=dataset_id,
                task_id=task_id,
                milestone_events=milestone_events,
            )
        except OpenSpecGraphError:
            raise
        except (DiagnosisInputError, OSError, ValueError) as exc:
            missing_evidence.append(f"dataset step evidence unavailable: {exc}")

    if session_id:
        try:
            return _session_graph_payloads(
                change=change,
                change_root=change_root,
                session_id=session_id,
                task_id=task_id,
                projects_dir=projects_dir,
                milestone_events=milestone_events,
                allow_full_session=allow_full_session,
            )
        except OpenSpecGraphError:
            raise
        except (OSError, ValueError) as exc:
            missing_evidence.append(f"session step evidence unavailable: {exc}")

    if not dataset_id and not session_id:
        missing_evidence.append("session or Dataset step evidence was not provided")
    return _milestone_graph_payloads(change, change_root, milestone_events, missing_evidence)


def _dataset_graph_payloads(
    *,
    change: str,
    dataset_id: str,
    task_id: str | None,
    milestone_events: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not task_id:
        raise OpenSpecGraphError("--task-id is required when --dataset-id is used.")
    dataset_path = _resolve_dataset_path(dataset_id)
    event_graph, action_graph, diagnosis = DiagnosisEngine().diagnose_dataset_task(dataset_path, task_id)
    metadata = _source_metadata(
        change=change,
        source_kind="dataset_task",
        source_confidence="high",
        dataset_id=dataset_id,
        session_id=None,
        task_id=task_id,
        milestone_events=milestone_events,
    )
    return (
        _with_metadata(event_graph, metadata),
        _with_metadata(action_graph, metadata),
        _diagnosis_with_metadata(diagnosis, metadata, []),
    )


def _session_graph_payloads(
    *,
    change: str,
    change_root: Path,
    session_id: str,
    task_id: str | None,
    projects_dir: Path | None,
    milestone_events: list[dict[str, Any]],
    allow_full_session: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    session = ClaudeAdapter(projects_dir).load_session(session_id)
    if session is None:
        raise OpenSpecGraphError(f"Session {session_id!r} was not found.")
    normalized_events = normalize_session_events(session)
    if not normalized_events:
        raise OpenSpecGraphError(f"Session {session_id!r} has no normalized events.")

    marker_ranges: list[dict[str, str]] = []
    if allow_full_session:
        task_events, source_kind, missing_evidence = _scope_session_events(normalized_events, session, task_id)
    else:
        task_events, marker_ranges = _scope_marker_events(
            normalized_events,
            change=change,
            markers_path=change_root / "graph" / "markers.jsonl",
        )
        source_kind = "marker_scoped_session"
        missing_evidence = []
    trace = _trace_from_events(task_events, task_id=task_id or session_id, session_id=session_id)
    event_graph = build_event_graph(trace)
    action_graph = build_openspec_action_graph()
    if source_kind == "marker_scoped_session":
        _bind_marker_events_to_actions(action_graph, task_events)
    else:
        map_events_to_actions(action_graph, trace)
    metadata = _source_metadata(
        change=change,
        source_kind=source_kind,
        source_confidence="high" if source_kind == "marker_scoped_session" else "medium" if source_kind == "session_task" else "low",
        dataset_id=None,
        session_id=session_id,
        task_id=task_id,
        milestone_events=milestone_events,
        marker_ranges=marker_ranges,
    )
    diagnosis = {
        "task_id": task_id or session_id,
        "workflow": "openspec",
        "status": "awaiting_feedback",
        "summary": "Session graph is ready for user feedback diagnosis.",
        "symptoms": [],
        "causal_chains": [],
        "missing_evidence": missing_evidence,
    }
    return (
        _with_metadata(event_graph.to_dict(), metadata),
        _with_metadata(action_graph.to_dict(), metadata),
        _diagnosis_with_metadata(diagnosis, metadata, missing_evidence),
    )


def _milestone_graph_payloads(
    change: str,
    change_root: Path,
    milestone_events: list[dict[str, Any]],
    missing_evidence: list[str],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    event_graph = _build_milestone_event_graph(change_root, milestone_events)
    action_graph = _build_milestone_action_graph(change_root, milestone_events, event_graph)
    symptoms = _detect_openspec_symptoms(action_graph)
    causal_chains = attribute_symptoms(action_graph, symptoms)
    metadata = _source_metadata(
        change=change,
        source_kind="milestone_fallback",
        source_confidence="low",
        dataset_id=None,
        session_id=None,
        task_id=None,
        milestone_events=milestone_events,
    )
    diagnosis = {
        "task_id": change,
        "workflow": "openspec",
        "summary": _summary(symptoms, causal_chains),
        "symptoms": [symptom.to_dict() for symptom in symptoms],
        "causal_chains": [chain.to_dict() for chain in causal_chains],
        "missing_evidence": [*missing_evidence, *_missing_evidence(action_graph)],
    }
    return (
        _with_metadata(event_graph.to_dict(), metadata),
        _with_metadata(action_graph.to_dict(), metadata),
        _diagnosis_with_metadata(diagnosis, metadata, diagnosis["missing_evidence"]),
    )


def _resolve_dataset_path(dataset_id: str) -> Path:
    candidate = Path(dataset_id).expanduser()
    if candidate.exists():
        return candidate
    return default_dataset_registry_root() / dataset_id


def _scope_session_events(
    events: list[NormalizedEvent],
    session: dict[str, Any],
    task_id: str | None,
) -> tuple[list[NormalizedEvent], str, list[str]]:
    if not task_id:
        return events, "session_full", []
    task = _find_session_task(session, task_id)
    if not task:
        return events, "session_full", [f"task {task_id!r} was not found in session task boundaries; using full session"]
    start_event_id = task.get("startEventId") or task.get("start_event_id")
    end_event_id = task.get("endEventId") if "endEventId" in task else task.get("end_event_id")
    event_index = {event.event_id: index for index, event in enumerate(events)}
    if start_event_id not in event_index:
        return events, "session_full", [f"task {task_id!r} start event was not found; using full session"]
    start = event_index[str(start_event_id)]
    end = event_index[str(end_event_id)] if end_event_id in event_index else len(events) - 1
    if end < start:
        return events, "session_full", [f"task {task_id!r} end event is before start event; using full session"]
    return events[start : end + 1], "session_task", []


def _scope_marker_events(
    events: list[NormalizedEvent],
    *,
    change: str,
    markers_path: Path,
) -> tuple[list[NormalizedEvent], list[dict[str, str]]]:
    markers = _load_markers(markers_path)
    if not markers:
        raise OpenSpecGraphError(
            f"No markers found for change {change!r}. Run ccwhat openspec-mark or use --allow-full-session."
        )

    pairs: dict[str, dict[str, dict[str, Any]]] = {}
    seen_marker_ids: set[str] = set()
    for marker in markers:
        marker_change = marker.get("change")
        action = marker.get("action")
        phase = marker.get("phase")
        marker_id = marker.get("marker_id")
        if marker_change != change or action not in _ACTION_IDS_BY_TYPE or phase not in _MARKER_PHASES or not isinstance(marker_id, str):
            raise OpenSpecGraphError(f"Invalid marker record in {markers_path}.")
        if marker_id in seen_marker_ids:
            raise OpenSpecGraphError(f"Duplicate marker id {marker_id!r} in {markers_path}.")
        seen_marker_ids.add(marker_id)
        action_pair = pairs.setdefault(action, {})
        if phase in action_pair:
            raise OpenSpecGraphError(f"Duplicate {phase} marker for action {action!r}.")
        action_pair[phase] = marker

    marker_positions: dict[str, int] = {}
    for marker_id in seen_marker_ids:
        matches = [
            index
            for index, event in enumerate(events)
            if event.event_type == "tool_call"
            and str(event.tool_name or "").lower() == "bash"
            and marker_id in str(event.command or "")
        ]
        if len(matches) != 1:
            detail = "was not found" if not matches else "appears more than once"
            raise OpenSpecGraphError(f"Marker {marker_id!r} {detail} in the selected Session.")
        marker_positions[marker_id] = matches[0]

    ranges: list[tuple[int, int, str, dict[str, Any], dict[str, Any]]] = []
    for action, pair in pairs.items():
        if set(pair) != _MARKER_PHASES:
            missing = ", ".join(sorted(_MARKER_PHASES - set(pair)))
            raise OpenSpecGraphError(f"Action {action!r} has incomplete Marker boundaries: missing {missing}.")
        start_marker = pair["start"]
        end_marker = pair["end"]
        start = marker_positions[start_marker["marker_id"]]
        end = marker_positions[end_marker["marker_id"]]
        if end <= start:
            raise OpenSpecGraphError(f"Action {action!r} end Marker must occur after its start Marker.")
        ranges.append((start, end, action, start_marker, end_marker))

    ranges.sort(key=lambda item: item[0])
    previous_end = -1
    for start, end, action, _, _ in ranges:
        if start <= previous_end:
            raise OpenSpecGraphError(f"Marker range for action {action!r} overlaps another Action range.")
        previous_end = end

    actions_by_index: dict[int, tuple[str, str | None, str | None]] = {}
    range_metadata: list[dict[str, str]] = []
    for start, end, action, start_marker, end_marker in ranges:
        range_metadata.append({
            "action": action,
            "start_marker_id": start_marker["marker_id"],
            "end_marker_id": end_marker["marker_id"],
            "start_event_id": events[start].event_id,
            "end_event_id": events[end].event_id,
        })
        for index in range(start, end + 1):
            phase = "start" if index == start else "end" if index == end else None
            marker_id = start_marker["marker_id"] if index == start else end_marker["marker_id"] if index == end else None
            actions_by_index[index] = (action, phase, marker_id)

    scoped_events = []
    for index, event in enumerate(events):
        context = actions_by_index.get(index)
        if context is None:
            continue
        action, phase, marker_id = context
        metadata = {**event.metadata, "marker_action": action}
        if marker_id:
            metadata.update({"marker_id": marker_id, "marker_phase": phase})
        scoped_events.append(replace(
            event,
            event_type="marker" if marker_id else event.event_type,
            metadata=metadata,
        ))
    return scoped_events, range_metadata


def _bind_marker_events_to_actions(action_graph: ActionGraph, events: list[NormalizedEvent]) -> None:
    events_by_action: dict[str, list[NormalizedEvent]] = {}
    for event in events:
        action = event.metadata.get("marker_action")
        if action in _ACTION_IDS_BY_TYPE:
            events_by_action.setdefault(str(action), []).append(event)

    for action_node in action_graph.actions:
        scoped_events = events_by_action.get(action_node.type, [])
        if not scoped_events:
            continue
        action_node.event_ids = [event.event_id for event in scoped_events]
        action_node.status = "failed" if any(_marker_event_is_error(event) for event in scoped_events) else "observed"
        action_node.evidence.append({
            "source": "marker_range",
            "confidence": "high",
            "reason": f"marker_range:{action_node.type}",
            "event_ids": list(action_node.event_ids),
        })


def _marker_event_is_error(event: NormalizedEvent) -> bool:
    if event.event_type == "error" or bool(event.metadata.get("is_error") or event.metadata.get("result_is_error")):
        return True
    return _has_error_text(event.text)


def _find_session_task(session: dict[str, Any], task_id: str) -> dict[str, Any] | None:
    containers = [
        session.get("tasks"),
        session.get("taskSegments"),
        session.get("task_segments"),
        (session.get("taskSegmentation") or {}).get("tasks") if isinstance(session.get("taskSegmentation"), dict) else None,
    ]
    for container in containers:
        if not isinstance(container, list):
            continue
        for item in container:
            if not isinstance(item, dict):
                continue
            candidate = item.get("taskId") or item.get("task_id") or item.get("id")
            if str(candidate) == task_id:
                return item
    return None


def _trace_from_events(events: list[NormalizedEvent], *, task_id: str, session_id: str) -> dict[str, Any]:
    errors = [event.text for event in events if event.event_type == "error" or _has_error_text(event.text)]
    final_claim = next((event.text for event in reversed(events) if _looks_like_claim(event.text)), None)
    commands = [event.command for event in events if event.command]
    return {
        "trace_id": f"trace-{task_id}",
        "task_id": task_id,
        "session_id": session_id,
        "events": [asdict(event) for event in events],
        "commands": commands,
        "test_commands": [command for command in commands if _looks_like_test_command(command)],
        "changes": [],
        "errors": errors,
        "final_claim": final_claim,
    }


def _has_error_text(text: str | None) -> bool:
    lowered = str(text or "").lower()
    return any(token in lowered for token in ("error", "failed", "failure", "traceback", "assertionerror", "失败", "报错"))


def _looks_like_claim(text: str | None) -> bool:
    lowered = str(text or "").lower()
    return any(token in lowered for token in ("complete", "completed", "done", "fixed", "implemented", "完成", "已完成", "修复"))


def _looks_like_test_command(command: str) -> bool:
    lowered = command.lower()
    return "pytest" in lowered or "python -m unittest" in lowered or "openspec validate" in lowered


def _source_metadata(
    *,
    change: str,
    source_kind: str,
    source_confidence: str,
    dataset_id: str | None,
    session_id: str | None,
    task_id: str | None,
    milestone_events: list[dict[str, Any]],
    marker_ranges: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "change": change,
        "source_kind": source_kind,
        "source_confidence": source_confidence,
        "dataset_id": dataset_id,
        "session_id": session_id,
        "task_id": task_id,
        "milestone_event_count": len(milestone_events),
        "milestones": list(milestone_events),
        "marker_ranges": list(marker_ranges or []),
    }


def _with_metadata(payload: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["metadata"] = metadata
    return result


def _diagnosis_with_metadata(
    diagnosis: dict[str, Any],
    metadata: dict[str, Any],
    missing_evidence: list[str],
) -> dict[str, Any]:
    result = dict(diagnosis)
    result["metadata"] = metadata
    result["missing_evidence"] = _dedupe([*missing_evidence, *list(result.get("missing_evidence") or [])])
    return result


def _resolve_change_root(change: str, cwd: Path) -> Path:
    try:
        result = subprocess.run(
            ["openspec", "status", "--change", change, "--json"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        change_root = payload.get("changeRoot")
        if change_root:
            path = Path(str(change_root))
            if path.exists():
                return path
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError):
        pass

    path = cwd / "openspec" / "changes" / change
    if path.exists():
        return path
    raise OpenSpecGraphError(f"OpenSpec change {change!r} was not found.")


def _append_event(path: Path, event: OpenSpecGraphEvent) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")


def _load_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


def _load_markers(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise OpenSpecGraphError(f"Invalid marker JSON in {path}: {exc.msg}.") from exc
        if not isinstance(value, dict):
            raise OpenSpecGraphError(f"Invalid marker record in {path}.")
        result.append(value)
    return result


def _build_milestone_event_graph(change_root: Path, events: list[dict[str, Any]]) -> EventGraph:
    nodes: list[GraphNode] = []
    for artifact_type, path in _artifact_paths(change_root).items():
        if path.exists():
            nodes.append(
                GraphNode(
                    node_id=f"artifact:{artifact_type}",
                    type="artifact_present",
                    label=path.relative_to(change_root).as_posix(),
                    data={"artifact": artifact_type, "path": path.as_posix(), "size": path.stat().st_size},
                )
            )
    specs = sorted((change_root / "specs").glob("**/spec.md")) if (change_root / "specs").exists() else []
    for index, path in enumerate(specs, 1):
        nodes.append(
            GraphNode(
                node_id=f"artifact:specs:{index}",
                type="artifact_present",
                label=path.relative_to(change_root).as_posix(),
                data={"artifact": "specs", "path": path.as_posix(), "size": path.stat().st_size},
            )
        )
    for index, event in enumerate(events, 1):
        nodes.append(
            GraphNode(
                node_id=f"event:{index}",
                type=str(event.get("type") or "workflow_event"),
                label=_event_label(event),
                timestamp=event.get("timestamp"),
                data=dict(event),
            )
        )
    edges = [
        GraphEdge(edge_id=f"OE{index:03d}", from_id=nodes[index - 1].node_id, to_id=nodes[index].node_id, type="timeline")
        for index in range(1, len(nodes))
    ]
    return EventGraph(nodes=nodes, edges=edges)


def _build_milestone_action_graph(change_root: Path, events: list[dict[str, Any]], event_graph: EventGraph) -> ActionGraph:
    nodes_by_artifact: dict[str, list[str]] = {}
    for node in event_graph.nodes:
        artifact = node.data.get("artifact")
        if artifact:
            nodes_by_artifact.setdefault(str(artifact), []).append(node.node_id)

    actions: list[ActionNode] = []
    for action_id, action_type, label in OPEN_SPEC_ACTIONS:
        evidence = []
        event_ids = list(nodes_by_artifact.get(action_type, []))
        status = "observed" if event_ids else "missing"

        if action_type == "apply":
            completed = _completed_tasks(change_root)
            if completed:
                status = "observed"
                event_ids.extend(_workflow_event_ids(events, "task_completed"))
                evidence.append({"source": "tasks.md", "confidence": "high", "completed_tasks": completed})
        elif action_type == "verify":
            validate_events = _workflow_event_ids(events, "validate_ran")
            if validate_events:
                status = "observed" if _latest_success(events, "validate_ran") else "failed"
                event_ids.extend(validate_events)
        elif action_type == "archive":
            archive_events = _workflow_event_ids(events, "archive_ran")
            if archive_events:
                status = "observed"
                event_ids.extend(archive_events)

        if action_type in {"proposal", "specs", "design", "tasks"} and event_ids:
            evidence.append({"source": "artifact_file", "confidence": "high", "event_ids": list(event_ids)})

        action = ActionNode(
            action_id=action_id,
            type=action_type,
            label=label,
            status=status,
            event_ids=_dedupe(event_ids),
            required=True,
            expected_because=["openspec_workflow_template"],
            evidence=evidence,
        )
        if action.status in {"missing", "failed"}:
            action.expected_because.append("required_openspec_action_without_success_evidence")
        actions.append(action)

    edges = [
        GraphEdge(
            edge_id=f"AE{index + 1:03d}",
            from_id=actions[index].action_id,
            to_id=actions[index + 1].action_id,
            type="workflow_expected",
            confidence=1.0,
            required=True,
            evidence=["openspec_workflow_template"],
        )
        for index in range(len(actions) - 1)
    ]
    return ActionGraph(workflow="openspec", actions=actions, edges=edges)


def _detect_openspec_symptoms(action_graph: ActionGraph) -> list[Symptom]:
    symptoms: list[Symptom] = []
    for action in action_graph.actions:
        if action.status in {"missing", "skipped"}:
            symptoms.append(
                Symptom(
                    symptom_id=f"S{len(symptoms) + 1}",
                    type="missing_required_action",
                    action_id=action.action_id,
                    severity="high",
                    evidence=[f"{action.type} action has no success evidence"],
                )
            )
        elif action.status == "failed":
            symptoms.append(
                Symptom(
                    symptom_id=f"S{len(symptoms) + 1}",
                    type="validation_failed",
                    action_id=action.action_id,
                    severity="high",
                    evidence=[f"{action.type} action failed"],
                )
            )
    return symptoms


def _artifact_paths(change_root: Path) -> dict[str, Path]:
    return {
        "proposal": change_root / "proposal.md",
        "design": change_root / "design.md",
        "tasks": change_root / "tasks.md",
    }


def _completed_tasks(change_root: Path) -> list[str]:
    tasks = change_root / "tasks.md"
    if not tasks.exists():
        return []
    return [line.strip()[6:].strip() for line in tasks.read_text(encoding="utf-8").splitlines() if line.strip().startswith("- [x]")]


def _workflow_event_ids(events: list[dict[str, Any]], event_type: str) -> list[str]:
    return [f"event:{index}" for index, event in enumerate(events, 1) if event.get("type") == event_type]


def _latest_success(events: list[dict[str, Any]], event_type: str) -> bool:
    matching = [event for event in events if event.get("type") == event_type]
    if not matching:
        return False
    return bool(matching[-1].get("success"))


def _summary(symptoms, causal_chains) -> str:
    if not symptoms:
        return "OpenSpec graph is complete; no required workflow symptoms detected."
    if causal_chains:
        top = causal_chains[0]
        return f"Detected {len(symptoms)} OpenSpec workflow symptom(s); top suspected action is {top.root_action_id} with score {top.score}."
    return f"Detected {len(symptoms)} OpenSpec workflow symptom(s)."


def _missing_evidence(action_graph: ActionGraph) -> list[str]:
    return [f"{action.type} action evidence missing" for action in action_graph.actions if action.status == "missing"]


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _event_label(event: dict[str, Any]) -> str:
    parts = [str(event.get("type") or "event")]
    for key in ("artifact", "task", "note"):
        if event.get(key):
            parts.append(str(event[key]))
    if "success" in event:
        parts.append(f"success={event['success']}")
    return " ".join(parts)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
