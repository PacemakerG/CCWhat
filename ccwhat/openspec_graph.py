"""OpenSpec workflow graph synchronization."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ccwhat.diagnosis.action_graph import OPEN_SPEC_ACTIONS
from ccwhat.diagnosis.attribution import attribute_symptoms
from ccwhat.diagnosis.models import ActionGraph, ActionNode, EventGraph, GraphEdge, GraphNode, Symptom


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
    event_graph = _build_event_graph(change_root, events)
    action_graph = _build_action_graph(change_root, events, event_graph)
    symptoms = _detect_openspec_symptoms(action_graph)
    causal_chains = attribute_symptoms(action_graph, symptoms)
    diagnosis = {
        "task_id": change,
        "workflow": "openspec",
        "summary": _summary(symptoms, causal_chains),
        "symptoms": [symptom.to_dict() for symptom in symptoms],
        "causal_chains": [chain.to_dict() for chain in causal_chains],
        "missing_evidence": _missing_evidence(action_graph),
    }

    outputs = {
        "events": graph_dir / "events.jsonl",
        "event_graph": graph_dir / "event_graph.json",
        "action_graph": graph_dir / "action_graph.json",
        "diagnosis": graph_dir / "diagnosis.json",
    }
    _write_json(outputs["event_graph"], event_graph.to_dict())
    _write_json(outputs["action_graph"], action_graph.to_dict())
    _write_json(outputs["diagnosis"], diagnosis)
    return outputs


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


def _build_event_graph(change_root: Path, events: list[dict[str, Any]]) -> EventGraph:
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
        GraphEdge(edge_id=f"OE{index:03d}", from_id=nodes[index - 1].node_id, to_id=nodes[index].node_id, type="temporal")
        for index in range(1, len(nodes))
    ]
    return EventGraph(nodes=nodes, edges=edges)


def _build_action_graph(change_root: Path, events: list[dict[str, Any]], event_graph: EventGraph) -> ActionGraph:
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
