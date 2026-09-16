"""Normalize Anthropic Messages, Chat Completions and Responses API records."""

from __future__ import annotations

import copy
import json
import re
from typing import Any


def _json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        return value


def _usage(usage: dict | None) -> dict:
    result = dict(usage or {})
    if "prompt_tokens" in result:
        result["input_tokens"] = result["prompt_tokens"]
    if "completion_tokens" in result:
        result["output_tokens"] = result["completion_tokens"]
    return result


def parse_response(response: dict) -> dict:
    """Add a common content view while retaining the original response fields."""
    if not isinstance(response, dict):
        return {"content": [], "raw": response}
    result = copy.deepcopy(response)
    contents = []
    if isinstance(response.get("content"), list):
        contents = result["content"]
    elif isinstance(response.get("content"), str):
        contents = [{"type": "text", "text": response["content"]}]
    elif isinstance(response.get("choices"), list):
        for choice in response["choices"]:
            msg = choice.get("message", {})
            if msg.get("reasoning_content"):
                contents.append({"type": "thinking", "thinking": msg["reasoning_content"]})
            if isinstance(msg.get("content"), str) and msg["content"]:
                contents.append({"type": "text", "text": msg["content"]})
            elif isinstance(msg.get("content"), list):
                contents.extend(msg["content"])
            if msg.get("refusal"):
                contents.append({"type": "text", "text": msg["refusal"]})
            for tool in msg.get("tool_calls", []):
                fn = tool.get("function", {})
                contents.append({"type": "tool_use", "id": tool.get("id"), "name": fn.get("name"),
                                 "input": _json_value(fn.get("arguments", ""))})
            result["stop_reason"] = choice.get("finish_reason")
    elif isinstance(response.get("output"), list):
        for item in response["output"]:
            kind = item.get("type")
            if kind == "message":
                for block in item.get("content", []):
                    if block.get("type") in {"output_text", "text"}:
                        contents.append({**block, "type": "text"})
                    elif block.get("type") == "refusal":
                        contents.append({"type": "text", "text": block.get("refusal", "")})
            elif kind == "function_call":
                contents.append({"type": "tool_use", "id": item.get("call_id", item.get("id")),
                                 "name": item.get("name"), "input": _json_value(item.get("arguments", ""))})
            elif kind == "reasoning":
                contents.append({"type": "thinking", "thinking": "\n".join(
                    part.get("text", "") for part in item.get("summary", []))})
            else:
                contents.append(copy.deepcopy(item))
        result["stop_reason"] = response.get("status")
    if "content" in response and not isinstance(response["content"], (str, list)):
        result["raw_content"] = result["content"]
    result["content"] = contents
    if response.get("usage"):
        result["usage"] = _usage(response["usage"])
    return result


def sse_data(events: list[str]):
    """Read SSE data fields, including CRLF framing and multiline JSON data."""
    for event in events:
        for frame in re.split(r"\r\n\r\n|\n\n|\r\r", event):
            raw = "\n".join(line[5:].lstrip(" ") for line in frame.splitlines() if line.startswith("data:"))
            if not raw or raw.strip() == "[DONE]":
                continue
            try:
                value = json.loads(raw)
            except ValueError:
                continue
            if isinstance(value, dict):
                yield value


def parse_sse_events(events: list[str]) -> dict:
    message: dict[str, Any] = {}
    blocks: dict[int, dict] = {}
    arguments: dict[int, str] = {}
    choices: dict[int, dict] = {}
    outputs: dict[int, dict] = {}
    protocol = "anthropic"
    for d in sse_data(events):
        kind = d.get("type", "")
        if kind in {"error", "response.failed"} or d.get("error"):
            message["error"] = d.get("error") or d.get("response", {}).get("error") or d
        if kind == "message_start":
            message.update(copy.deepcopy(d.get("message", {})))
        elif kind == "content_block_start":
            blocks[d.get("index", 0)] = copy.deepcopy(d.get("content_block", {}))
        elif kind == "content_block_delta":
            idx = d.get("index", 0)
            delta = d.get("delta", {})
            block = blocks.setdefault(idx, {})
            if delta.get("type") == "text_delta":
                block["type"] = "text"
                block["text"] = block.get("text", "") + delta.get("text", "")
            elif delta.get("type") == "thinking_delta":
                block["type"] = "thinking"
                block["thinking"] = block.get("thinking", "") + delta.get("thinking", "")
            elif delta.get("type") == "signature_delta":
                block["signature"] = block.get("signature", "") + delta.get("signature", "")
            elif delta.get("type") == "input_json_delta":
                arguments[idx] = arguments.get(idx, "") + delta.get("partial_json", "")
        elif kind == "message_delta":
            message.update(d.get("delta", {}))
            message["usage"] = {**message.get("usage", {}), **d.get("usage", {})}
        elif kind.startswith("response."):
            protocol = "responses"
            if isinstance(d.get("response"), dict):
                message.update(copy.deepcopy(d["response"]))
            idx = d.get("output_index", 0)
            if kind in {"response.output_item.added", "response.output_item.done"}:
                outputs[idx] = copy.deepcopy(d.get("item", {}))
            elif kind in {"response.content_part.added", "response.content_part.done"}:
                item = outputs.setdefault(idx, {"type": "message", "content": []})
                content = item.setdefault("content", [])
                ci = d.get("content_index", 0)
                while len(content) <= ci:
                    content.append({})
                content[ci] = copy.deepcopy(d.get("part", {}))
            elif kind in {"response.output_text.delta", "response.output_text.done", "response.refusal.delta", "response.refusal.done"}:
                item = outputs.setdefault(idx, {"type": "message", "content": []})
                content = item.setdefault("content", [])
                ci = d.get("content_index", 0)
                while len(content) <= ci:
                    content.append({})
                field = "refusal" if ".refusal." in kind else "text"
                content[ci]["type"] = "refusal" if field == "refusal" else "output_text"
                content[ci][field] = (content[ci].get(field, "") + d.get("delta", "")) if kind.endswith(".delta") else d.get(field, "")
            elif kind in {"response.function_call_arguments.delta", "response.function_call_arguments.done"}:
                item = outputs.setdefault(idx, {"type": "function_call", "id": d.get("item_id")})
                item["arguments"] = (item.get("arguments", "") + d.get("delta", "")) if kind.endswith(".delta") else d.get("arguments", "")
        elif isinstance(d.get("choices"), list):
            protocol = "chat"
            for key in ("id", "model", "object"):
                if key in d:
                    message[key] = d[key]
            if d.get("usage"):
                message["usage"] = d["usage"]
            for choice in d["choices"]:
                idx = choice.get("index", 0)
                out = choices.setdefault(idx, {"index": idx, "message": {}, "finish_reason": None})
                delta = choice.get("delta", {})
                msg = out["message"]
                for key in ("content", "reasoning_content", "refusal"):
                    if isinstance(delta.get(key), str):
                        msg[key] = msg.get(key, "") + delta[key]
                if choice.get("finish_reason"):
                    out["finish_reason"] = choice["finish_reason"]
                tools = msg.setdefault("tool_calls", [])
                for tool in delta.get("tool_calls", []):
                    ti = tool.get("index", 0)
                    while len(tools) <= ti:
                        tools.append({"function": {"name": "", "arguments": ""}})
                    if tool.get("id"):
                        tools[ti]["id"] = tool["id"]
                    for key in ("name", "arguments"):
                        tools[ti]["function"][key] += tool.get("function", {}).get(key, "")
    if protocol == "chat":
        message["choices"] = [v for _, v in sorted(choices.items())]
    elif protocol == "responses":
        if not message.get("output"):
            message["output"] = [v for _, v in sorted(outputs.items())]
    elif blocks:
        for idx, raw in arguments.items():
            blocks[idx]["input"] = _json_value(raw)
        message["content"] = [v for _, v in sorted(blocks.items())]
    return parse_response(message)


def parse_sse_record(raw: dict[str, Any]) -> dict[str, Any]:
    request_json = json.loads(raw["request"]["body"])
    headers = {k.lower(): v for k, v in raw["request"].get("headers", {}).items()}
    session_id = raw.get("session_id") or headers.get("x-claude-code-session-id")
    response = parse_sse_events(raw.get("sse_events", []))
    return {
        "timestamp": raw["timestamp"], "domain": raw["domain"], "method": raw["method"], "url": raw["url"],
        "session_id": session_id, "message_id": response.get("id"),
        # Retain aliases for existing consumers and exported archives.
        "claude_session_id": session_id, "claude_message_id": response.get("id"),
        "request_json": request_json, "response_json": {"message": response},
    }
