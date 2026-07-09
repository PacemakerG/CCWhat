"""Map fine-grained Dataset events to OpenSpec action nodes."""

from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any

from .models import ActionEventMapping, ActionGraph, ActionNode


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
    unmapped: dict[int, list[str]] = defaultdict(list)

    for event in events:
        event_id = str(event.get("event_id") or event.get("id") or "")
        if not event_id:
            continue
        action_type, reason, confidence = _classify_event(event, event_files.get(event_id, []))
        if action_type:
            _add_mapping(mappings, ACTION_BY_TYPE[action_type], event_id, reason, confidence)
        else:
            turn = int(event.get("turn_index") or 0)
            unmapped[turn].append(event_id)

    for turn, event_ids in sorted(unmapped.items()):
        action_id = f"ADHOC-{turn or len(mappings) + 1}"
        action_graph.actions.append(
            ActionNode(
                action_id=action_id,
                type="ad_hoc_turn",
                label=f"Ad hoc turn {turn or '?'}",
                status="observed",
                event_ids=list(event_ids),
                required=False,
                evidence=[{"source": "event_mapping", "confidence": "low", "reason": "unmapped_turn"}],
            )
        )
        mappings[action_id] = ActionEventMapping(
            action_id=action_id,
            event_ids=list(event_ids),
            reason="unmapped_turn",
            confidence="low",
        )

    _apply_mappings(action_graph, mappings)
    _mark_missing_actions(action_graph)
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
        mappings[action_id] = ActionEventMapping(action_id=action_id, event_ids=[event_id], reason=reason, confidence=confidence)
        return
    if event_id not in mapping.event_ids:
        mapping.event_ids.append(event_id)
    if _confidence_rank(confidence) > _confidence_rank(mapping.confidence):
        mapping.confidence = confidence
        mapping.reason = reason


def _apply_mappings(action_graph: ActionGraph, mappings: dict[str, ActionEventMapping]) -> None:
    for action in action_graph.actions:
        mapping = mappings.get(action.action_id)
        if not mapping:
            continue
        action.event_ids = list(mapping.event_ids)
        action.status = "observed"
        action.evidence.append({
            "source": "event_mapping",
            "confidence": mapping.confidence,
            "reason": mapping.reason,
            "event_ids": list(mapping.event_ids),
        })


def _mark_missing_actions(action_graph: ActionGraph) -> None:
    previous_missing = False
    for action in action_graph.actions:
        if action.event_ids or not action.required:
            previous_missing = False
            continue
        action.status = "skipped" if previous_missing else "missing"
        action.expected_because.append("required_openspec_action_without_events")
        previous_missing = True


def _classify_event(event: dict[str, Any], change_files: list[str]) -> tuple[str | None, str, str]:
    files = [*(_event_files(event)), *change_files]
    for file_path in files:
        action = _classify_path(file_path)
        if action:
            return action, f"path:{file_path}", "high"

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


def _confidence_rank(value: str) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(value, 0)
