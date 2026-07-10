"""Build fine-grained Event Graphs from session traces."""

from __future__ import annotations

from typing import Any

from .models import EventGraph, GraphEdge, GraphNode

READ_TOOLS = {"read", "grep", "glob", "find"}
EDIT_TOOLS = {"edit", "multiedit", "write", "patch", "str_replace_editor"}
CLAIM_TOKENS = ("complete", "completed", "done", "fixed", "implemented", "完成", "已完成", "修复", "已解决")


def build_event_graph(trace: dict[str, Any]) -> EventGraph:
    events = [event for event in trace.get("events", []) if isinstance(event, dict)]
    seen_ids: dict[str, int] = {}
    nodes: list[GraphNode] = []
    for index, event in enumerate(events):
        source_id = str(event.get("event_id") or event.get("id") or f"event-{index + 1}")
        occurrence = seen_ids.get(source_id, 0) + 1
        seen_ids[source_id] = occurrence
        node_id = source_id if occurrence == 1 else f"{source_id}#{occurrence}"
        nodes.append(_node_from_event(event, index, node_id=node_id, source_event_id=source_id))
    edges: list[GraphEdge] = []

    for index in range(len(nodes) - 1):
        edges.append(_edge("timeline", nodes[index].node_id, nodes[index + 1].node_id, len(edges) + 1))

    _add_tool_result_edges(events, nodes, edges)
    return EventGraph(nodes=nodes, edges=edges)


def _node_from_event(
    event: dict[str, Any],
    index: int,
    *,
    node_id: str | None = None,
    source_event_id: str | None = None,
) -> GraphNode:
    event_id = node_id or str(event.get("event_id") or event.get("id") or f"event-{index + 1}")
    source_id = source_event_id or event_id
    event_type = _event_type(event)
    label = _label(event, event_type)
    raw_ref = event.get("raw_ref") if isinstance(event.get("raw_ref"), dict) else {}
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    tool_input = raw_ref.get("tool_input") if isinstance(raw_ref.get("tool_input"), dict) else None
    result_summary = metadata.get("result_text")
    if result_summary is None and event_type == "tool_result":
        result_summary = event.get("text")
    return GraphNode(
        node_id=event_id,
        type=event_type,
        label=label,
        event_id=event_id,
        timestamp=event.get("timestamp"),
        agent_id=event.get("agent_id"),
        data={
            "source_event_id": source_id,
            "source": event.get("source"),
            "tool_name": event.get("tool_name"),
            "tool_use_id": event.get("tool_use_id"),
            "tool_call_id": event.get("tool_use_id"),
            "tool_input": tool_input,
            "files": list(event.get("files") or []),
            "command": event.get("command"),
            "text": event.get("text"),
            "turn_index": event.get("turn_index"),
            "result_summary": _clip(result_summary, 2000),
            "is_error": _is_error_event(event),
            "raw_ref": raw_ref,
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

def _looks_like_claim(event: dict[str, Any]) -> bool:
    text = str(event.get("text") or "").lower()
    return any(token in text for token in CLAIM_TOKENS)


def _is_error_event(event: dict[str, Any]) -> bool:
    if str(event.get("event_type") or "") == "error":
        return True
    if bool(event.get("is_error")):
        return True
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    raw_ref = event.get("raw_ref") if isinstance(event.get("raw_ref"), dict) else {}
    return bool(metadata.get("is_error") or raw_ref.get("is_error"))


def _clip(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"
