"""Detect diagnosis symptoms on an OpenSpec Action Graph."""

from __future__ import annotations

from typing import Any

from .models import ActionGraph, Symptom

ERROR_TOKENS = ("error", "failed", "failure", "traceback", "assertionerror", "失败", "报错")


def detect_symptoms(action_graph: ActionGraph, trace: dict[str, Any]) -> list[Symptom]:
    symptoms: list[Symptom] = []
    actions = {action.action_id: action for action in action_graph.actions}

    for action in action_graph.actions:
        if action.required and action.status in {"missing", "skipped"}:
            symptoms.append(
                Symptom(
                    symptom_id=f"S{len(symptoms) + 1}",
                    type="missing_required_action",
                    action_id=action.action_id,
                    severity="high",
                    evidence=[f"{action.type} action has no mapped events"],
                )
            )

    verify = actions.get("A6")
    if verify and verify.event_ids and _verify_failed(verify.event_ids, trace):
        verify.status = "failed"
        symptoms.append(
            Symptom(
                symptom_id=f"S{len(symptoms) + 1}",
                type="validation_failed",
                action_id=verify.action_id,
                severity="high",
                evidence=["verify action contains error evidence"],
            )
        )

    final_claim = trace.get("final_claim")
    tasks = actions.get("A4")
    if final_claim and ((tasks and _tasks_incomplete(tasks.event_ids, trace)) or _bad_verify(verify)):
        symptoms.append(
            Symptom(
                symptom_id=f"S{len(symptoms) + 1}",
                type="unsupported_final_claim",
                action_id="A7" if actions.get("A7") else (verify.action_id if verify else "A6"),
                severity="high",
                evidence=[f"final_claim: {str(final_claim)[:200]}"],
            )
        )

    _add_workflow_skip_symptoms(action_graph, symptoms)
    _add_artifact_missing_symptoms(action_graph, symptoms)
    return symptoms


def _bad_verify(verify: Any) -> bool:
    return verify is None or verify.status in {"missing", "skipped", "failed"}


def _events_by_id(trace: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(event.get("event_id") or event.get("id")): event
        for event in trace.get("events", [])
        if isinstance(event, dict)
    }


def _verify_failed(event_ids: list[str], trace: dict[str, Any]) -> bool:
    events = _events_by_id(trace)
    errors = " ".join(str(error) for error in trace.get("errors", []))
    if _has_error(errors):
        return True
    for event_id in event_ids:
        event = events.get(event_id)
        if not event:
            continue
        text = f"{event.get('text') or ''} {event.get('command') or ''}"
        if _has_error(text):
            return True
    return False


def _tasks_incomplete(event_ids: list[str], trace: dict[str, Any]) -> bool:
    if not event_ids:
        return True
    events = _events_by_id(trace)
    task_text = []
    for event_id in event_ids:
        event = events.get(event_id)
        if event:
            task_text.append(str(event.get("text") or ""))
    for change in trace.get("changes", []):
        if not isinstance(change, dict) or change.get("event_id") not in event_ids:
            continue
        task_text.append(str(change.get("content") or ""))
        task_text.append(str(change.get("new_string") or ""))
    return any("- [ ]" in text for text in task_text)


def _has_error(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in ERROR_TOKENS)


def _add_workflow_skip_symptoms(action_graph: ActionGraph, symptoms: list[Symptom]) -> None:
    previous_missing: str | None = None
    for action in action_graph.actions:
        if not action.required:
            continue
        if previous_missing and action.event_ids:
            symptoms.append(
                Symptom(
                    symptom_id=f"S{len(symptoms) + 1}",
                    type="workflow_skip",
                    action_id=action.action_id,
                    severity="medium",
                    evidence=[f"{previous_missing} was missing before observed {action.action_id}"],
                )
            )
        if action.status in {"missing", "skipped"}:
            previous_missing = action.action_id


def _add_artifact_missing_symptoms(action_graph: ActionGraph, symptoms: list[Symptom]) -> None:
    for action in action_graph.actions[:4]:
        if action.status in {"missing", "skipped"}:
            symptoms.append(
                Symptom(
                    symptom_id=f"S{len(symptoms) + 1}",
                    type="artifact_missing_or_empty",
                    action_id=action.action_id,
                    severity="high",
                    evidence=[f"{action.type} artifact has no mapped evidence"],
                )
            )
