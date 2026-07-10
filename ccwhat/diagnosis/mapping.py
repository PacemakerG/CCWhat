"""Map fine-grained Dataset events to OpenSpec action nodes."""

from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any

from .models import ActionEventMapping, ActionGraph


PATH_ACTIONS = (
    ("proposal", "proposal.md"),
    ("design", "design.md"),
    ("tasks", "tasks.md"),
)
ACTION_BY_TYPE = {
    "proposal": "A1",
    "specs": "A2",
    "design": "A3",
    "tasks": "A4",
    "apply": "A5",
    "verify": "A6",
    "archive": "A7",
}


def map_events_to_actions(action_graph: ActionGraph, trace: dict[str, Any]) -> list[ActionEventMapping]:
    events = [event for event in trace.get("events", []) if isinstance(event, dict)]
    changes = [change for change in trace.get("changes", []) if isinstance(change, dict)]
    event_files = _event_files_from_changes(changes)
    mappings: dict[str, ActionEventMapping] = {}
    tool_actions: dict[str, tuple[str, str, str]] = {}

    for event in events:
        event_id = str(event.get("event_id") or event.get("id") or "")
        if not event_id:
            continue
        tool_use_id = str(event.get("tool_use_id") or "")
        event_type = str(event.get("event_type") or "")
        if event_type == "tool_result" and tool_use_id in tool_actions:
            action_id, call_reason, call_confidence = tool_actions[tool_use_id]
            _add_mapping(
                mappings,
                action_id,
                event_id,
                f"tool_result_of:{call_reason}",
                call_confidence,
            )
            continue

        action_type, reason, confidence = _classify_event(event, event_files.get(event_id, []))
        if action_type:
            action_id = ACTION_BY_TYPE[action_type]
            _add_mapping(mappings, action_id, event_id, reason, confidence)
            if tool_use_id:
                tool_actions[tool_use_id] = (action_id, reason, confidence)

    _apply_mappings(action_graph, mappings)
    _mark_unobserved_actions(action_graph)
    _mark_failed_actions(action_graph, events)
    return list(mappings.values())


def _add_mapping(
    mappings: dict[str, ActionEventMapping],
    action_id: str,
    event_id: str,
    reason: str,
    confidence: str,
) -> None:
    mapping = mappings.get(action_id)
    if mapping is None:
        mappings[action_id] = ActionEventMapping(
            action_id=action_id,
            event_ids=[event_id],
            reason=reason,
            confidence=confidence,
            event_reasons={event_id: reason},
            event_confidences={event_id: confidence},
        )
        return
    if event_id not in mapping.event_ids:
        mapping.event_ids.append(event_id)
    if _confidence_rank(confidence) > _confidence_rank(mapping.confidence):
        mapping.confidence = confidence
        mapping.reason = reason
    mapping.event_reasons[event_id] = reason
    mapping.event_confidences[event_id] = confidence


def _apply_mappings(action_graph: ActionGraph, mappings: dict[str, ActionEventMapping]) -> None:
    for action in action_graph.actions:
        mapping = mappings.get(action.action_id)
        if not mapping:
            continue
        action.event_ids = list(mapping.event_ids)
        action.status = "observed"
        for event_id in mapping.event_ids:
            action.evidence.append({
                "source": "event_mapping",
                "confidence": mapping.event_confidences.get(event_id, mapping.confidence),
                "reason": mapping.event_reasons.get(event_id, mapping.reason),
                "event_ids": [event_id],
            })


def _mark_unobserved_actions(action_graph: ActionGraph) -> None:
    for action in action_graph.actions:
        if action.event_ids or not action.required:
            continue
        action.status = "not_observed"


def _mark_failed_actions(action_graph: ActionGraph, events: list[dict[str, Any]]) -> None:
    events_by_id = {
        str(event.get("event_id") or event.get("id") or ""): event
        for event in events
    }
    for action in action_graph.actions:
        if any(_event_is_error(events_by_id.get(event_id, {})) for event_id in action.event_ids):
            action.status = "failed"


def _classify_event(event: dict[str, Any], change_files: list[str]) -> tuple[str | None, str, str]:
    files = [*(_event_files(event)), *change_files]
    if _is_code_change_event(event):
        for file_path in files:
            action = _classify_path(file_path)
            if action:
                return action, f"edited_path:{file_path}", "high"

    command = str(event.get("command") or "").lower()
    if "openspec validate" in command or "opsx:verify" in command or "opsx-verify" in command:
        return "verify", "command:openspec_validate", "high"
    if "openspec archive" in command or "opsx:archive" in command or "opsx-archive" in command:
        return "archive", "command:openspec_archive", "high"
    if "opsx:apply" in command or "opsx-apply" in command:
        return "apply", "command:opsx_apply", "high"
    if "pytest" in command or "python -m unittest" in command:
        return "verify", "command:test", "medium"
    if _is_code_change_event(event):
        return "apply", "event:file_change", "medium"
    return None, "unmapped", "low"


def _classify_path(path_value: str) -> str | None:
    normalized = path_value.replace("\\", "/")
    name = PurePosixPath(normalized).name
    if "/specs/" in normalized and name == "spec.md":
        return "specs"
    for action, filename in PATH_ACTIONS:
        if name == filename and "/openspec/changes/" in normalized:
            return action
    if "/openspec/changes/" not in normalized and normalized.startswith("openspec/changes/"):
        if "/specs/" in normalized and name == "spec.md":
            return "specs"
        for action, filename in PATH_ACTIONS:
            if name == filename:
                return action
    return None


def _event_files(event: dict[str, Any]) -> list[str]:
    return [str(file_path) for file_path in event.get("files") or [] if file_path]


def _event_files_from_changes(changes: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for change in changes:
        event_id = str(change.get("event_id") or "")
        file_path = change.get("file")
        if event_id and file_path:
            result[event_id].append(str(file_path))
    return result


def _is_code_change_event(event: dict[str, Any]) -> bool:
    event_type = str(event.get("event_type") or "")
    tool = str(event.get("tool_name") or "").lower()
    return event_type in {"file_edit"} or tool in {"edit", "multiedit", "write", "patch", "str_replace_editor"}


def _event_is_error(event: dict[str, Any]) -> bool:
    if not event:
        return False
    if str(event.get("event_type") or "") == "error" or bool(event.get("is_error")):
        return True
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    raw_ref = event.get("raw_ref") if isinstance(event.get("raw_ref"), dict) else {}
    return bool(
        metadata.get("is_error")
        or metadata.get("result_is_error")
        or raw_ref.get("is_error")
    )


def _confidence_rank(value: str) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(value, 0)
