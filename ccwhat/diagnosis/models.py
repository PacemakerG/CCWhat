"""Data models for graph-backed task diagnosis."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class GraphNode:
    node_id: str
    type: str
    label: str
    event_id: str | None = None
    timestamp: str | None = None
    agent_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GraphEdge:
    edge_id: str
    from_id: str
    to_id: str
    type: str
    confidence: float = 1.0
    evidence: list[str] = field(default_factory=list)
    required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "from": self.from_id,
            "to": self.to_id,
            "type": self.type,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "required": self.required,
        }


@dataclass
class EventGraph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
        }


@dataclass
class ActionNode:
    action_id: str
    type: str
    label: str
    status: str = "missing"
    event_ids: list[str] = field(default_factory=list)
    required: bool = True
    expected_because: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    suspicion_score: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ActionGraph:
    workflow: str
    actions: list[ActionNode]
    edges: list[GraphEdge]

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow": self.workflow,
            "actions": [action.to_dict() for action in self.actions],
            "edges": [edge.to_dict() for edge in self.edges],
        }


@dataclass
class ActionEventMapping:
    action_id: str
    event_ids: list[str]
    reason: str
    confidence: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Symptom:
    symptom_id: str
    type: str
    action_id: str
    severity: str
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CausalChain:
    root_action_id: str
    root_cause: str
    score: int
    confidence: str
    chain: list[str]
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DiagnosisResult:
    task_id: str
    workflow: str
    summary: str
    symptoms: list[Symptom] = field(default_factory=list)
    causal_chains: list[CausalChain] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "workflow": self.workflow,
            "summary": self.summary,
            "symptoms": [symptom.to_dict() for symptom in self.symptoms],
            "causal_chains": [chain.to_dict() for chain in self.causal_chains],
            "missing_evidence": list(self.missing_evidence),
        }
