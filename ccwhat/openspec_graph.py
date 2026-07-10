"""Build OpenSpec graphs from Claude Code Session logs and Marker boundaries."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ccwhat.adapters.claude import ClaudeAdapter
from ccwhat.diagnosis.action_graph import OPEN_SPEC_ACTIONS
from ccwhat.diagnosis.event_graph import build_event_graph
from ccwhat.diagnosis.models import ActionGraph, ActionNode, EventGraph, GraphEdge
from ccwhat.task_segments.events import normalize_session_events
from ccwhat.task_segments.models import NormalizedEvent


class OpenSpecGraphError(ValueError):
    """Raised when an OpenSpec graph cannot be synchronized."""


_CHANGE_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
_MARKER_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_MARKER_PHASES = {"start", "end"}
_ACTION_TYPES = {action_type for _, action_type, _ in OPEN_SPEC_ACTIONS}
_ACTION_LABELS = {action_type: label for _, action_type, label in OPEN_SPEC_ACTIONS}


@dataclass(frozen=True)
class MarkerSegment:
    action: str
    ordinal: int
    start_index: int
    end_index: int
    start_marker: dict[str, Any]
    end_marker: dict[str, Any]
    start_event_id: str
    end_event_id: str
    started_at: str | None
    ended_at: str | None


def write_openspec_marker(
    *,
    change: str,
    action: str,
    phase: str,
    marker_id: str,
    cwd: str | Path | None = None,
) -> Path:
    """Append one explicit action boundary; actions may occur repeatedly."""
    if not _CHANGE_NAME_RE.fullmatch(change):
        raise OpenSpecGraphError("change must be a lowercase kebab-case name.")
    if action not in _ACTION_TYPES:
        raise OpenSpecGraphError(f"action must be one of: {', '.join(sorted(_ACTION_TYPES))}.")
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
    session_id: str | None = None,
    projects_dir: str | Path | None = None,
    cwd: str | Path | None = None,
) -> dict[str, Path]:
    """Write one coarse and one fine graph from a Marker-scoped raw Session."""
    if not session_id:
        raise OpenSpecGraphError("--session-id is required; OpenSpec graphs use Marker-scoped Claude Code Session logs.")

    root = Path(cwd or ".").resolve()
    change_root = _resolve_change_root(change, root)
    graph_dir = change_root / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)
    event_graph, action_graph, diagnosis = _session_graph_payloads(
        change=change,
        change_root=change_root,
        session_id=session_id,
        projects_dir=Path(projects_dir).expanduser() if projects_dir else None,
    )
    outputs = {
        "event_graph": graph_dir / "event_graph.json",
        "action_graph": graph_dir / "action_graph.json",
        "diagnosis": graph_dir / "diagnosis.json",
    }
    _write_json(outputs["event_graph"], event_graph)
    _write_json(outputs["action_graph"], action_graph)
    _write_json(outputs["diagnosis"], diagnosis)
    return outputs


def _session_graph_payloads(
    *,
    change: str,
    change_root: Path,
    session_id: str,
    projects_dir: Path | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    session = ClaudeAdapter(projects_dir).load_session(session_id)
    if session is None:
        raise OpenSpecGraphError(f"Session {session_id!r} was not found.")
    normalized_events = normalize_session_events(session)
    if not normalized_events:
        raise OpenSpecGraphError(f"Session {session_id!r} has no normalized events.")

    events, segments = _scope_marker_events(
        normalized_events,
        change=change,
        markers_path=change_root / "graph" / "markers.jsonl",
    )
    event_graph = build_event_graph(_trace_from_events(events, session_id=session_id))
    # The fine graph is only the observed event sequence. No inferred or
    # cross-Action relations are added.
    event_graph.edges = [edge for edge in event_graph.edges if edge.type == "timeline"]
    action_graph = _build_marker_action_graph(events, event_graph, segments)
    metadata = {
        "change": change,
        "source_kind": "marker_scoped_session",
        "source_confidence": "high",
        "session_id": session_id,
        "marker_ranges": _marker_range_metadata(segments),
    }
    diagnosis = {
        "session_id": session_id,
        "workflow": "openspec",
        "status": "awaiting_feedback",
        "summary": "Session graph is ready for user feedback diagnosis.",
        "symptoms": [],
        "causal_chains": [],
        "missing_evidence": [],
        "metadata": metadata,
    }
    return (
        _with_metadata(event_graph.to_dict(), metadata),
        _with_metadata(action_graph.to_dict(), metadata),
        diagnosis,
    )


def _scope_marker_events(
    events: list[NormalizedEvent],
    *,
    change: str,
    markers_path: Path,
) -> tuple[list[NormalizedEvent], list[MarkerSegment]]:
    markers = _load_markers(markers_path)
    if not markers:
        raise OpenSpecGraphError(f"No markers found for change {change!r}. Run ccwhat openspec-mark first.")

    marker_positions: dict[str, int] = {}
    for marker in markers:
        action = marker.get("action")
        phase = marker.get("phase")
        marker_id = marker.get("marker_id")
        if marker.get("change") != change or action not in _ACTION_TYPES or phase not in _MARKER_PHASES or not isinstance(marker_id, str):
            raise OpenSpecGraphError(f"Invalid marker record in {markers_path}.")
        if marker_id in marker_positions:
            raise OpenSpecGraphError(f"Duplicate marker id {marker_id!r} in {markers_path}.")
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

    boundaries = sorted(
        ((marker_positions[str(marker["marker_id"])], marker) for marker in markers),
        key=lambda item: item[0],
    )
    segments: list[MarkerSegment] = []
    active: tuple[int, dict[str, Any]] | None = None
    counts: dict[str, int] = {}
    for index, marker in boundaries:
        if marker["phase"] == "start":
            if active is not None:
                raise OpenSpecGraphError(
                    f"Marker {marker['marker_id']!r} starts {marker['action']!r} before "
                    f"{active[1]['action']!r} ends. Action ranges must be sequential."
                )
            active = (index, marker)
            continue
        if active is None:
            raise OpenSpecGraphError(f"End Marker {marker['marker_id']!r} has no matching start Marker.")
        start_index, start_marker = active
        if start_marker["action"] != marker["action"]:
            raise OpenSpecGraphError(
                f"End Marker {marker['marker_id']!r} for {marker['action']!r} does not match "
                f"open Action {start_marker['action']!r}."
            )
        action = str(marker["action"])
        ordinal = counts.get(action, 0) + 1
        counts[action] = ordinal
        segments.append(MarkerSegment(
            action=action,
            ordinal=ordinal,
            start_index=start_index,
            end_index=index,
            start_marker=start_marker,
            end_marker=marker,
            start_event_id=events[start_index].event_id,
            end_event_id=events[index].event_id,
            started_at=events[start_index].timestamp,
            ended_at=events[index].timestamp,
        ))
        active = None
    if active is not None:
        raise OpenSpecGraphError(f"Action {active[1]['action']!r} has incomplete Marker boundaries: missing end.")

    context_by_index: dict[int, tuple[MarkerSegment, str | None, str | None]] = {}
    for segment in segments:
        for index in range(segment.start_index, segment.end_index + 1):
            phase = "start" if index == segment.start_index else "end" if index == segment.end_index else None
            marker_id = segment.start_marker["marker_id"] if index == segment.start_index else segment.end_marker["marker_id"] if index == segment.end_index else None
            context_by_index[index] = (segment, phase, marker_id)

    scoped_events: list[NormalizedEvent] = []
    for index, event in enumerate(events):
        context = context_by_index.get(index)
        if context is None:
            continue
        segment, phase, marker_id = context
        metadata = {**event.metadata, "marker_action": segment.action, "marker_ordinal": segment.ordinal}
        if marker_id:
            metadata.update({"marker_id": marker_id, "marker_phase": phase})
        scoped_events.append(replace(
            event,
            event_type="marker" if marker_id else event.event_type,
            metadata=metadata,
        ))
    return scoped_events, segments


def _build_marker_action_graph(
    events: list[NormalizedEvent],
    event_graph: EventGraph,
    segments: list[MarkerSegment],
) -> ActionGraph:
    event_ids_by_segment: dict[tuple[str, int], list[str]] = {}
    errors_by_segment: dict[tuple[str, int], bool] = {}
    for event, node in zip(events, event_graph.nodes):
        key = (str(event.metadata["marker_action"]), int(event.metadata["marker_ordinal"]))
        event_ids_by_segment.setdefault(key, []).append(node.node_id)
        errors_by_segment[key] = errors_by_segment.get(key, False) or _marker_event_is_error(event)

    actions: list[ActionNode] = []
    for segment in segments:
        key = (segment.action, segment.ordinal)
        action_id = f"{segment.action}-{segment.ordinal}"
        actions.append(ActionNode(
            action_id=action_id,
            type=segment.action,
            label=f"{_ACTION_LABELS[segment.action]} #{segment.ordinal}",
            status="failed" if errors_by_segment.get(key) else "observed",
            event_ids=event_ids_by_segment.get(key, []),
            required=False,
            evidence=[{
                "source": "marker_range",
                "confidence": "high",
                "start_marker_id": segment.start_marker["marker_id"],
                "end_marker_id": segment.end_marker["marker_id"],
            }],
            ordinal=segment.ordinal,
            started_at=segment.started_at,
            ended_at=segment.ended_at,
            marker_range={
                "start_marker_id": str(segment.start_marker["marker_id"]),
                "end_marker_id": str(segment.end_marker["marker_id"]),
                "start_event_id": segment.start_event_id,
                "end_event_id": segment.end_event_id,
            },
        ))
    edges = [
        GraphEdge(
            edge_id=f"AE{index:03d}",
            from_id=actions[index - 1].action_id,
            to_id=actions[index].action_id,
            type="next",
        )
        for index in range(1, len(actions))
    ]
    return ActionGraph(workflow="openspec", actions=actions, edges=edges)


def _marker_range_metadata(segments: list[MarkerSegment]) -> list[dict[str, str]]:
    return [
        {
            "action": segment.action,
            "action_id": f"{segment.action}-{segment.ordinal}",
            "start_marker_id": str(segment.start_marker["marker_id"]),
            "end_marker_id": str(segment.end_marker["marker_id"]),
            "start_event_id": segment.start_event_id,
            "end_event_id": segment.end_event_id,
        }
        for segment in segments
    ]


def _marker_event_is_error(event: NormalizedEvent) -> bool:
    if event.event_type == "error" or bool(event.metadata.get("is_error") or event.metadata.get("result_is_error")):
        return True
    return _has_error_text(event.text)


def _trace_from_events(events: list[NormalizedEvent], *, session_id: str) -> dict[str, Any]:
    return {
        "trace_id": f"trace-{session_id}",
        "task_id": session_id,
        "session_id": session_id,
        "events": [event.__dict__ for event in events],
    }


def _has_error_text(text: str | None) -> bool:
    lowered = str(text or "").lower()
    return any(token in lowered for token in ("error", "failed", "failure", "traceback", "assertionerror", "失败", "报错"))


def _with_metadata(payload: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["metadata"] = metadata
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
            return Path(change_root).resolve()
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        pass
    for base in (cwd / "openspec" / "changes", cwd / "openspec" / "changes" / "archive"):
        candidate = base / change
        if candidate.is_dir():
            return candidate.resolve()
    raise OpenSpecGraphError(f"OpenSpec change {change!r} was not found.")


def _load_markers(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    markers: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise OpenSpecGraphError(f"Invalid marker JSON in {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise OpenSpecGraphError(f"Invalid marker record in {path}.")
        markers.append(value)
    return markers


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
