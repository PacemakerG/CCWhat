"""Task segmentation event normalization."""

from __future__ import annotations

import re
from typing import Any

from .models import NormalizedEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PATH_FIELDS = ("file_path", "path", "notebook_path", "file_path_1", "file_path_2")
_PATH_LIKE = re.compile(r"^(/|~/|\.{1,2}/|[A-Za-z]:\\)")


def _extract_text(content: Any) -> str:
    """Return a human-readable string from a content value.

    content may be:
    - a plain string
    - a list of blocks, each being a dict with a "type" key
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type", "")
        if btype == "text":
            parts.append(block.get("text", ""))
        elif btype == "tool_use":
            name = block.get("name", "")
            parts.append(f"[tool_use: {name}]")
        elif btype == "tool_result":
            inner = block.get("content", "")
            parts.append(_extract_text(inner))
    return "\n".join(p for p in parts if p)


def _extract_files_from_input(inp: Any) -> list[str]:
    """Extract file paths from a tool's input dict."""
    if not isinstance(inp, dict):
        return []
    paths: list[str] = []
    for field in _PATH_FIELDS:
        val = inp.get(field)
        if isinstance(val, str) and val:
            paths.append(val)
    # Also scan all string values that look like paths
    for key, val in inp.items():
        if key in _PATH_FIELDS:
            continue
        if isinstance(val, str) and _PATH_LIKE.match(val):
            paths.append(val)
    return paths


def _find_tool_use_blocks(content: Any) -> list[dict]:
    """Return all tool_use blocks from a content list."""
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]


def _find_tool_result_blocks(content: Any) -> list[dict]:
    """Return all tool_result blocks from a content list."""
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]


def _block_event_id(base_id: str, index: int, total: int) -> str:
    """Keep legacy ids for single blocks and suffix ids only when needed."""
    return base_id if total <= 1 else f"{base_id}:{index + 1}"


# ---------------------------------------------------------------------------
# Task 2.1 – main session normalization
# ---------------------------------------------------------------------------

def normalize_main_entries(
    entries: list[dict],
    session_id: str,
) -> list[NormalizedEvent]:
    """Normalize raw JSONL entries from the main session conversation."""
    events: list[NormalizedEvent] = []
    turn_index = 0
    # Task 2.2 – track pending tool_use events keyed by tool_use_id
    tool_uses: dict[str, NormalizedEvent] = {}

    for idx, entry in enumerate(entries):
        line_no = entry.get("_fileLine", idx + 1)
        event_id = f"main:{line_no}"
        etype = entry.get("type", "")
        # Claude logs nest content under "message.content" for assistant entries
        content = entry.get("content") or entry.get("message", {}).get("content", "")
        if content is None:
            content = ""
        timestamp = entry.get("timestamp")
        raw_ref: dict[str, Any] = {
            "session_id": session_id,
            "_fileLine": entry.get("_fileLine"),
        }

        if etype == "user":
            turn_index += 1

            # Handle tool_result blocks embedded in user messages (task 2.2)
            tool_result_blocks = _find_tool_result_blocks(content)
            for tr_block in tool_result_blocks:
                tuid = tr_block.get("tool_use_id")
                if tuid and tuid in tool_uses:
                    result_text = _extract_text(tr_block.get("content", ""))
                    tool_uses[tuid].metadata["result_text"] = result_text
                    tool_uses[tuid].metadata["result_is_error"] = bool(tr_block.get("is_error"))

            # If the user message is *only* tool_result blocks, emit tool_result events
            non_tr_blocks = [
                b for b in (content if isinstance(content, list) else [])
                if not (isinstance(b, dict) and b.get("type") == "tool_result")
            ]
            if tool_result_blocks and not non_tr_blocks and not isinstance(content, str):
                for block_index, tr_block in enumerate(tool_result_blocks):
                    tuid = tr_block.get("tool_use_id")
                    result_text = _extract_text(tr_block.get("content", ""))
                    result_raw_ref = {
                        **raw_ref,
                        "block_index": block_index,
                        "block_type": "tool_result",
                        "is_error": bool(tr_block.get("is_error")),
                    }
                    ev = NormalizedEvent(
                        event_id=_block_event_id(event_id, block_index, len(tool_result_blocks)),
                        source="main",
                        agent_id="main",
                        turn_index=turn_index,
                        event_type="tool_result",
                        text=result_text,
                        tool_use_id=tuid,
                        timestamp=timestamp,
                        raw_ref=result_raw_ref,
                        metadata={"is_error": bool(tr_block.get("is_error"))},
                    )
                    events.append(ev)
                continue

            # Regular user message
            ev = NormalizedEvent(
                event_id=event_id,
                source="main",
                agent_id="main",
                turn_index=turn_index,
                event_type="user_message",
                text=_extract_text(content),
                timestamp=timestamp,
                raw_ref=raw_ref,
            )
            events.append(ev)

        elif etype == "assistant":
            tool_use_blocks = _find_tool_use_blocks(content)
            if tool_use_blocks:
                # Emit one tool_call event per tool_use block
                for block_index, tu_block in enumerate(tool_use_blocks):
                    tool_name = tu_block.get("name")
                    tool_use_id = tu_block.get("id")
                    inp = tu_block.get("input", {})
                    files = _extract_files_from_input(inp)
                    command = inp.get("command") if isinstance(inp, dict) else None
                    tool_raw_ref = dict(raw_ref)
                    if isinstance(inp, dict):
                        tool_raw_ref["tool_input"] = inp
                    tool_raw_ref["block_index"] = block_index
                    tool_raw_ref["block_type"] = "tool_use"
                    ev = NormalizedEvent(
                        event_id=_block_event_id(event_id, block_index, len(tool_use_blocks)),
                        source="main",
                        agent_id="main",
                        turn_index=turn_index,
                        event_type="tool_call",
                        text=_extract_text(content),
                        tool_name=tool_name,
                        tool_use_id=tool_use_id,
                        files=files,
                        command=command,
                        timestamp=timestamp,
                        raw_ref=tool_raw_ref,
                    )
                    events.append(ev)
                    # Track for task 2.2 association
                    if tool_use_id:
                        tool_uses[tool_use_id] = ev
            else:
                # Pure text assistant message
                ev = NormalizedEvent(
                    event_id=event_id,
                    source="main",
                    agent_id="main",
                    turn_index=turn_index,
                    event_type="assistant_text",
                    text=_extract_text(content),
                    timestamp=timestamp,
                    raw_ref=raw_ref,
                )
                events.append(ev)

        elif etype == "tool":
            # Legacy tool-result format (type=="tool" at top level)
            tool_use_id = entry.get("tool_use_id")
            result_text = _extract_text(content)
            if tool_use_id and tool_use_id in tool_uses:
                tool_uses[tool_use_id].metadata["result_text"] = result_text
            ev = NormalizedEvent(
                event_id=event_id,
                source="main",
                agent_id="main",
                turn_index=turn_index,
                event_type="tool_result",
                text=result_text,
                tool_use_id=tool_use_id,
                timestamp=timestamp,
                raw_ref={**raw_ref, "is_error": bool(entry.get("is_error"))},
                metadata={"is_error": bool(entry.get("is_error"))},
            )
            events.append(ev)

        # Unknown types are silently skipped

    return events


# ---------------------------------------------------------------------------
# Task 2.3 – subagent normalization
# ---------------------------------------------------------------------------

def normalize_subagent_entries(subagents: list[dict]) -> list[NormalizedEvent]:
    """Normalize subagent conversation entries."""
    all_events: list[NormalizedEvent] = []
    for subagent in subagents:
        agent_id = subagent.get("agentId", "unknown")
        meta = subagent.get("meta", {})
        entries = subagent.get("entries", [])
        base_metadata = {
            "agentType": meta.get("agentType"),
            "description": meta.get("description"),
        }

        # Re-use main normalization logic with a patched event_id prefix
        sub_events = normalize_main_entries(entries, session_id=agent_id)
        for ev in sub_events:
            # Rewrite event_id, source, agent_id
            line_part = ev.event_id.split(":", 1)[1] if ":" in ev.event_id else ev.event_id
            ev.event_id = f"agent-{agent_id}:{line_part}"
            ev.source = "subagent"
            ev.agent_id = agent_id
            # Merge base_metadata (don't overwrite existing keys)
            merged = dict(base_metadata)
            merged.update(ev.metadata)
            ev.metadata = merged
        all_events.extend(sub_events)
    return all_events


# ---------------------------------------------------------------------------
# Codex / OpenCode support: convert adapter-normalized events
# ---------------------------------------------------------------------------

_KIND_TO_EVENT_TYPE: dict[str, str] = {
    "message": "",          # resolved per role below
    "tool_call": "tool_call",
    "tool_result": "tool_result",
    "reasoning": "assistant_text",
    "metadata": "assistant_text",
    "step": "assistant_text",
    "unknown": "assistant_text",
}


def _normalize_from_events(
    events: list[dict[str, Any]],
    session_id: str,
) -> list[NormalizedEvent]:
    """Convert adapter normalized events (Codex/OpenCode) to NormalizedEvent list."""
    result: list[NormalizedEvent] = []
    turn_index = 0
    for idx, ev in enumerate(events):
        if not isinstance(ev, dict):
            continue
        role = str(ev.get("role") or "")
        kind = str(ev.get("kind") or "message")
        event_id = str(ev.get("eventId") or ev.get("id") or f"ev:{idx}")
        timestamp = ev.get("timestamp")
        content_raw = ev.get("content") or ev.get("summary") or ""
        tool_name = ev.get("toolName")
        tool_call_id = ev.get("toolCallId")
        agent_id_field = ev.get("agentId") or "main"

        if role == "user" and kind == "message":
            turn_index += 1
            event_type = "user_message"
        elif role == "assistant" and kind == "message":
            event_type = "assistant_text"
        elif kind == "tool_call":
            event_type = "tool_call"
        elif kind == "tool_result":
            event_type = "tool_result"
        else:
            event_type = "assistant_text"

        text = content_raw if isinstance(content_raw, str) else ""
        files: list[str] = []
        command: str | None = None
        if isinstance(content_raw, dict):
            files = _extract_files_from_input(content_raw)
            command = content_raw.get("command")

        result.append(NormalizedEvent(
            event_id=event_id,
            source="main",
            agent_id=str(agent_id_field),
            turn_index=turn_index,
            event_type=event_type,
            text=text,
            tool_name=tool_name,
            tool_use_id=tool_call_id,
            files=files,
            command=command,
            timestamp=timestamp,
            raw_ref={
                "eventId": event_id,
                "agent": ev.get("agent"),
                "kind": kind,
                "content": content_raw,
                "raw_event": ev,
            },
        ))
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize_session_events(session: dict) -> list[NormalizedEvent]:
    """Return all normalized events for a session, with subagent events inserted
    after the Agent tool_use that spawned them.

    Insertion strategy:
    1. Find all Agent tool_use positions in main_events (spawn positions).
    2. For each subagent, find the spawn position:
       - If the subagent has timestamps: find the last Agent spawn whose
         timestamp <= the subagent's first event timestamp.
       - If no timestamps: assign the n-th subagent to the n-th Agent tool_use
         (index-based).
       - If main has no Agent tool_use at all: fall back to appending at end.
    3. Insert each subagent's events immediately after its spawn position.
    """
    session_id = session.get("sessionId", "")
    main_entries = session.get("main") or session.get("entries", [])
    subagents = session.get("subagents", [])

    # Codex/OpenCode: session["events"] is a normalized event list from the adapter.
    # When main_entries is empty but events exist, convert normalized events to
    # NormalizedEvent objects so the segmenter can work cross-agent.
    if not main_entries and session.get("events"):
        main_events = _normalize_from_events(session["events"], session_id)
        return main_events  # normalized events don't have subagents structure

    main_events = normalize_main_entries(main_entries, session_id)

    if not subagents:
        return main_events

    # Collect per-subagent event lists
    subagent_event_lists: list[list[NormalizedEvent]] = []
    for subagent in subagents:
        agent_id = subagent.get("agentId", "unknown")
        meta = subagent.get("meta", {})
        entries = subagent.get("entries", [])
        base_metadata = {
            "agentType": meta.get("agentType"),
            "description": meta.get("description"),
        }
        sub_events = normalize_main_entries(entries, session_id=agent_id)
        for ev in sub_events:
            line_part = ev.event_id.split(":", 1)[1] if ":" in ev.event_id else ev.event_id
            ev.event_id = f"agent-{agent_id}:{line_part}"
            ev.source = "subagent"
            ev.agent_id = agent_id
            merged = dict(base_metadata)
            merged.update(ev.metadata)
            ev.metadata = merged
        subagent_event_lists.append(sub_events)

    # Find spawn positions: indices in main_events where tool_name == "Agent"
    spawn_indices: list[int] = [
        i for i, ev in enumerate(main_events)
        if ev.event_type == "tool_call" and ev.tool_name == "Agent"
    ]

    # Determine insert-after index for each subagent
    # Returns the index in main_events after which to insert, or len(main_events) for append.
    def _spawn_index_for(sub_idx: int, sub_evs: list[NormalizedEvent]) -> int:
        if not spawn_indices:
            return len(main_events)

        # Try timestamp-based matching
        first_ts = next((ev.timestamp for ev in sub_evs if ev.timestamp), None)
        if first_ts is not None:
            # Find the last spawn whose timestamp <= first_ts
            best = None
            for si in spawn_indices:
                spawn_ts = main_events[si].timestamp
                if spawn_ts is not None and spawn_ts <= first_ts:
                    best = si
            if best is not None:
                return best
            # All spawns are after first_ts – fall through to index-based

        # Index-based: n-th subagent → n-th Agent tool_use
        if sub_idx < len(spawn_indices):
            return spawn_indices[sub_idx]

        # More subagents than Agent tool_uses: append after last spawn
        return spawn_indices[-1]

    # Build the final event list by inserting subagent blocks after their spawn
    # We process insertions from back to front so earlier indices stay valid.
    # Map: insert_after_index -> list of subagent event lists to insert there
    insert_map: dict[int, list[list[NormalizedEvent]]] = {}
    for sub_idx, sub_evs in enumerate(subagent_event_lists):
        after = _spawn_index_for(sub_idx, sub_evs)
        insert_map.setdefault(after, []).append(sub_evs)

    result: list[NormalizedEvent] = []
    for i, ev in enumerate(main_events):
        result.append(ev)
        if i in insert_map:
            for sub_evs in insert_map[i]:
                result.extend(sub_evs)

    # Handle any subagents mapped to len(main_events) (append at end)
    append_key = len(main_events)
    if append_key in insert_map:
        for sub_evs in insert_map[append_key]:
            result.extend(sub_evs)

    return result
