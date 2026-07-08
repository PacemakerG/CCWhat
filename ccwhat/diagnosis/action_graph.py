"""Build the fixed OpenSpec Action Graph template."""

from __future__ import annotations

from .models import ActionGraph, ActionNode, GraphEdge


OPEN_SPEC_ACTIONS = [
    ("A1", "proposal", "Proposal"),
    ("A2", "specs", "Specs"),
    ("A3", "design", "Design"),
    ("A4", "tasks", "Tasks"),
    ("A5", "apply", "Apply"),
    ("A6", "verify", "Verify"),
    ("A7", "archive", "Archive"),
]


def build_openspec_action_graph() -> ActionGraph:
    actions = [
        ActionNode(
            action_id=action_id,
            type=action_type,
            label=label,
            expected_because=["openspec_workflow_template"],
        )
        for action_id, action_type, label in OPEN_SPEC_ACTIONS
    ]
    edges = []
    for index in range(len(actions) - 1):
        edges.append(
            GraphEdge(
                edge_id=f"AE{index + 1:03d}",
                from_id=actions[index].action_id,
                to_id=actions[index + 1].action_id,
                type="workflow_expected",
                confidence=1.0,
                required=True,
                evidence=["openspec_workflow_template"],
            )
        )
    return ActionGraph(workflow="openspec", actions=actions, edges=edges)
