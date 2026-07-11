from __future__ import annotations

import json
from typing import Any


_STATUS_EVENT_TYPES = {
    "thread.started",
    "turn.started",
    "turn.completed",
    "turn.failed",
    "error",
}


def _content_to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = _content_to_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts)
    if isinstance(value, dict):
        for key in ("text", "content", "message", "output_text"):
            if key in value:
                text = _content_to_text(value.get(key))
                if text:
                    return text
    return ""


def _append_message_text(message: Any, texts: list[str]) -> None:
    if isinstance(message, str):
        if message.strip():
            texts.append(message)
        return
    if not isinstance(message, dict):
        return
    role = message.get("role")
    if role and role not in ("assistant", "agent"):
        return
    text = _content_to_text(message.get("content") or message.get("message") or message.get("text"))
    if text.strip():
        texts.append(text)


def _append_item_text(item: Any, texts: list[str]) -> None:
    if not isinstance(item, dict):
        return
    item_type = item.get("type")
    role = item.get("role")
    if item_type == "message":
        if role in ("assistant", "agent", None):
            _append_message_text(item, texts)
        return
    if item_type in ("agent_message", "assistant_message"):
        _append_message_text(item.get("message") or item, texts)
        return
    if role in ("assistant", "agent"):
        _append_message_text(item, texts)


def parse_jsonl_text(stdout: str, stderr: str = "", extra_files: dict[str, str] | None = None) -> str:
    """Extract final assistant/agent text from Codex exec JSONL output."""
    texts: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        ev_type = ev.get("type", "")
        if ev_type in _STATUS_EVENT_TYPES:
            continue
        if ev_type == "assistant" and ev.get("content"):
            text = _content_to_text(ev.get("content"))
            if text.strip():
                texts.append(text)
        elif ev_type == "agent" and ev.get("messages"):
            for msg in ev["messages"]:
                _append_message_text(msg, texts)
        elif ev_type == "event_msg":
            payload = ev.get("payload", {})
            if isinstance(payload, dict) and payload.get("type") == "agent_message":
                _append_message_text(payload.get("message"), texts)
        elif ev_type == "response_item":
            _append_item_text(ev.get("payload"), texts)
        else:
            payload = ev.get("payload")
            _append_item_text(payload, texts)
            if isinstance(payload, dict):
                _append_item_text(payload.get("item"), texts)
                _append_message_text(payload.get("message"), texts)
            _append_item_text(ev.get("item"), texts)
            _append_message_text(ev.get("message"), texts)
    return "\n".join(texts)
