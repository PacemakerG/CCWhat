"""Backward attribution over OpenSpec Action Graphs."""

from __future__ import annotations

from collections import defaultdict, deque

from .models import ActionGraph, CausalChain, Symptom


EVIDENCE_POINTS = {"high": 20, "medium": 12, "low": 5}
ROOT_CAUSE_LABELS = {
    "missing_required_action": "OpenSpec required action is missing",
    "unsupported_final_claim": "Final claim is not supported by workflow evidence",
    "validation_failed": "Validation failed",
    "workflow_skip": "Workflow skipped a required upstream action",
    "artifact_missing_or_empty": "Required OpenSpec artifact evidence is missing",
}


def attribute_symptoms(action_graph: ActionGraph, symptoms: list[Symptom]) -> list[CausalChain]:
    actions = {action.action_id: action for action in action_graph.actions}
    reverse_edges = defaultdict(list)
    forward_edges = defaultdict(list)
    for edge in action_graph.edges:
        reverse_edges[edge.to_id].append(edge.from_id)
        forward_edges[edge.from_id].append(edge.to_id)

    chains: list[CausalChain] = []
    best_scores: dict[str, int] = defaultdict(int)
    for symptom in symptoms:
        candidates = _upstream_distances(symptom.action_id, reverse_edges)
        if symptom.action_id not in candidates:
            candidates[symptom.action_id] = 0
        for action_id, distance in candidates.items():
            action = actions.get(action_id)
            if not action:
                continue
            score = _score_candidate(symptom, action_id, distance, action_graph, forward_edges)
            best_scores[action_id] = max(best_scores[action_id], score)
            chains.append(
                CausalChain(
                    root_action_id=action_id,
                    root_cause=_root_cause(symptom.type, action.type),
                    score=score,
                    confidence=_confidence(score),
                    chain=_chain_to_symptom(action_id, symptom, reverse_edges),
                    evidence=[*symptom.evidence, *_action_evidence_text(action)],
                )
            )

    for action in action_graph.actions:
        action.suspicion_score = int(best_scores.get(action.action_id, 0))

    chains.sort(key=lambda chain: chain.score, reverse=True)
    return chains[:10]


def _upstream_distances(start: str, reverse_edges: dict[str, list[str]]) -> dict[str, int]:
    result: dict[str, int] = {}
    queue = deque([(start, 0)])
    while queue:
        current, distance = queue.popleft()
        for parent in reverse_edges.get(current, []):
            if parent in result:
                continue
            result[parent] = distance + 1
            queue.append((parent, distance + 1))
    return result


def _score_candidate(
    symptom: Symptom,
    action_id: str,
    distance: int,
    action_graph: ActionGraph,
    forward_edges: dict[str, list[str]],
) -> int:
    actions = {action.action_id: action for action in action_graph.actions}
    action = actions[action_id]
    score = 0
    if symptom.type in {"missing_required_action", "artifact_missing_or_empty", "unsupported_final_claim"} or action.status in {"missing", "skipped"}:
        score += 40
    score += max(0, 25 - max(0, distance - 1) * 5)
    score += _evidence_points(action)
    if _template_index(action_id, action_graph) <= _template_index(symptom.action_id, action_graph):
        score += 10
    score += min(5, _downstream_count(action_id, forward_edges))
    return max(0, min(100, score))


def _evidence_points(action) -> int:
    if action.status in {"missing", "skipped"}:
        return 20
    best = 0
    for item in action.evidence:
        if isinstance(item, dict):
            best = max(best, EVIDENCE_POINTS.get(str(item.get("confidence")), 0))
    return best or 5


def _template_index(action_id: str, action_graph: ActionGraph) -> int:
    for index, action in enumerate(action_graph.actions):
        if action.action_id == action_id:
            return index
    return 999


def _downstream_count(action_id: str, forward_edges: dict[str, list[str]]) -> int:
    seen: set[str] = set()
    queue = deque([action_id])
    while queue:
        current = queue.popleft()
        for child in forward_edges.get(current, []):
            if child in seen:
                continue
            seen.add(child)
            queue.append(child)
    return len(seen)


def _confidence(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def _root_cause(symptom_type: str, action_type: str) -> str:
    return f"{ROOT_CAUSE_LABELS.get(symptom_type, symptom_type)}: {action_type}"


def _chain_to_symptom(action_id: str, symptom: Symptom, reverse_edges: dict[str, list[str]]) -> list[str]:
    if action_id == symptom.action_id:
        return [action_id, symptom.symptom_id]
    parents = {child: parent for child, items in reverse_edges.items() for parent in items}
    path = [symptom.action_id]
    current = symptom.action_id
    while current != action_id and current in parents:
        current = parents[current]
        path.append(current)
    path.reverse()
    path.append(symptom.symptom_id)
    return path


def _action_evidence_text(action) -> list[str]:
    result = []
    if action.event_ids:
        result.append(f"{action.action_id} mapped events: {', '.join(action.event_ids)}")
    if action.expected_because:
        result.append(f"{action.action_id} expected because: {', '.join(action.expected_because)}")
    return result
