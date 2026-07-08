"""Build fine-grained Event Graphs from Dataset traces."""

from __future__ import annotations

from typing import Any

from .models import EventGraph, GraphEdge, GraphNode

READ_TOOLS = {"read", "grep", "glob", "find"}
EDIT_TOOLS = {"edit", "multiedit", "write", "patch", "str_replace_editor"}
ERROR_TOKENS = ("error", "failed", "failure", "traceback", "timeout", "assertionerror", "失败", "报错")
CLAIM_TOKENS = ("complete", "completed", "done", "fixed", "implemented", "完成", "已完成", "修复", "已解决")


def build_event_graph(trace: dict[str, Any]) -> EventGraph:
    events = [event for event in trace.get("events", []) if isinstance(event, dict)]
    nodes = [_node_from_event(event, index) for index, event in enumerate(events)]
    edges: list[GraphEdge] = []

    for index in range(len(nodes) - 1):
        edges.append(_edge("temporal", nodes[index].node_id, nodes[index + 1].node_id, len(edges) + 1))

    _add_tool_result_edges(events, nodes, edges)
    _add_read_edit_edges(events, nodes, edges)
    _add_edit_command_edges(events, nodes, edges)
    _add_command_error_edges(events, nodes, edges)
    _add_claim_edges(events, nodes, edges)
    return EventGraph(nodes=nodes, edges=edges)


def _node_from_event(event: dict[str, Any], index: int) -> GraphNode:
    event_id = str(event.get("event_id") or event.get("id") or f"event-{index + 1}")
    event_type = _event_type(event)
    label = _label(event, event_type)
    return GraphNode(
        node_id=event_id,
        type=event_type,
        label=label,
        event_id=event_id,
        timestamp=event.get("timestamp"),
        agent_id=event.get("agent_id"),
        data={
            "tool_name": event.get("tool_name"),
            "tool_use_id": event.get("tool_use_id"),
            "files": list(event.get("files") or []),
            "command": event.get("command"),
            "text": event.get("text"),
            "turn_index": event.get("turn_index"),
        },
    )


def _event_type(event: dict[str, Any]) -> str:
    raw_type = str(event.get("event_type") or event.get("kind") or "").strip()
    tool = str(event.get("tool_name") or "").strip().lower()
    if raw_type:
        if raw_type == "tool_call" and tool in READ_TOOLS:
            return "file_read"
        if raw_type == "tool_call" and tool in EDIT_TOOLS:
            return "file_edit"
        if raw_type == "tool_call" and tool == "bash":
            return "command"
        if raw_type == "assistant_text" and _looks_like_claim(event):
            return "final_claim"
        return raw_type
    if event.get("command"):
        return "command"
    return "event"


def _label(event: dict[str, Any], event_type: str) -> str:
    if event.get("command"):
        return str(event["command"])[:120]
    if event.get("files"):
        return ", ".join(str(item) for item in event["files"])[:120]
    text = str(event.get("text") or event.get("summary") or event_type)
    return text.replace("\n", " ")[:120]


def _edge(edge_type: str, from_id: str, to_id: str, index: int, evidence: list[str] | None = None) -> GraphEdge:
    return GraphEdge(
        edge_id=f"E{index:04d}",
        from_id=from_id,
        to_id=to_id,
        type=edge_type,
        evidence=evidence or [],
    )


def _add_tool_result_edges(events: list[dict[str, Any]], nodes: list[GraphNode], edges: list[GraphEdge]) -> None:
    calls: dict[str, str] = {}
    for event, node in zip(events, nodes):
        tool_use_id = event.get("tool_use_id")
        if not tool_use_id:
            continue
        if str(event.get("event_type")) == "tool_call":
            calls[str(tool_use_id)] = node.node_id
        elif str(event.get("event_type")) == "tool_result" and str(tool_use_id) in calls:
            edges.append(_edge("tool_result_of", calls[str(tool_use_id)], node.node_id, len(edges) + 1, [f"tool_use_id={tool_use_id}"]))


def _add_read_edit_edges(events: list[dict[str, Any]], nodes: list[GraphNode], edges: list[GraphEdge]) -> None:
    reads: list[tuple[int, str, str]] = []
    for index, (event, node) in enumerate(zip(events, nodes)):
        files = set(_files(event))
        if not files:
            continue
        if node.type == "file_read":
            reads.extend((index, file_path, node.node_id) for file_path in files)
        if node.type == "file_edit":
            for read_index, read_file, read_node in reads:
                if read_index < index and read_file in files:
                    edges.append(_edge("reads_before_edit", read_node, node.node_id, len(edges) + 1, [read_file]))


def _add_edit_command_edges(events: list[dict[str, Any]], nodes: list[GraphNode], edges: list[GraphEdge]) -> None:
    edits: list[GraphNode] = []
    for node in nodes:
        if node.type == "file_edit":
            edits.append(node)
        elif node.type == "command":
            for edit_node in edits[-5:]:
                edges.append(_edge("edit_before_command", edit_node.node_id, node.node_id, len(edges) + 1))


def _add_command_error_edges(events: list[dict[str, Any]], nodes: list[GraphNode], edges: list[GraphEdge]) -> None:
    last_command: GraphNode | None = None
    for event, node in zip(events, nodes):
        if node.type == "command":
            last_command = node
        if last_command and (node.type == "error" or _has_error_text(event)):
            edges.append(_edge("command_produces_error", last_command.node_id, node.node_id, len(edges) + 1))


def _add_claim_edges(events: list[dict[str, Any]], nodes: list[GraphNode], edges: list[GraphEdge]) -> None:
    last_action: GraphNode | None = None
    for event, node in zip(events, nodes):
        if node.type in {"file_edit", "command", "tool_call", "tool_result", "error"}:
            last_action = node
        if node.type == "final_claim" and last_action:
            edges.append(_edge("claim_after_action", last_action.node_id, node.node_id, len(edges) + 1))


def _files(event: dict[str, Any]) -> list[str]:
    return [str(file_path) for file_path in event.get("files") or [] if file_path]


def _has_error_text(event: dict[str, Any]) -> bool:
    text = f"{event.get('text') or ''} {event.get('summary') or ''}".lower()
    return any(token in text for token in ERROR_TOKENS)


def _looks_like_claim(event: dict[str, Any]) -> bool:
    text = str(event.get("text") or "").lower()
    return any(token in text for token in CLAIM_TOKENS)
