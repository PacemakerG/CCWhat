"""OpenSpec workflow graph synchronization."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
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
                session_id=session_id,
                task_id=task_id,
                projects_dir=projects_dir,
                milestone_events=milestone_events,
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
    session_id: str,
    task_id: str | None,
    projects_dir: Path | None,
    milestone_events: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    session = ClaudeAdapter(projects_dir).load_session(session_id)
    if session is None:
        raise OpenSpecGraphError(f"Session {session_id!r} was not found.")
    normalized_events = normalize_session_events(session)
    if not normalized_events:
        raise OpenSpecGraphError(f"Session {session_id!r} has no normalized events.")

    task_events, source_kind, missing_evidence = _scope_session_events(normalized_events, session, task_id)
    trace = _trace_from_events(task_events, task_id=task_id or session_id, session_id=session_id)
    event_graph = build_event_graph(trace)
    action_graph = build_openspec_action_graph()
    map_events_to_actions(action_graph, trace)
    metadata = _source_metadata(
        change=change,
        source_kind=source_kind,
        source_confidence="medium" if source_kind == "session_task" else "low",
        dataset_id=None,
        session_id=session_id,
        task_id=task_id,
        milestone_events=milestone_events,
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
