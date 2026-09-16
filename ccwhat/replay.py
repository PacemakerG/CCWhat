"""Replay recorded JSON requests without assuming a particular agent or gateway."""

from __future__ import annotations

import copy
import json
import os
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ccwhat.parsers.sse_parser import parse_response, parse_sse_events
from ccwhat.config import DEFAULT_REDACT_HEADERS, DEFAULT_REDACT_PATTERNS, load_config


def _origin(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Replay requires an HTTP(S) URL without embedded credentials")
    port = parts.port
    host = parts.hostname
    if ":" in host:
        host = f"[{host}]"
    suffix = f":{port}" if port and port != (443 if parts.scheme == "https" else 80) else ""
    return f"{parts.scheme}://{host}{suffix}"


def _current_headers(origin: str) -> dict[str, str]:
    """An explicit per-origin header set takes precedence over provider defaults."""
    try:
        overrides = json.loads(os.environ.get("CCWHAT_REPLAY_HEADERS", "{}"))
        if not isinstance(overrides, dict):
            raise ValueError
        for target, values in overrides.items():
            if _origin(target) != origin:
                continue
            if not isinstance(values, dict) or not all(
                isinstance(k, str) and isinstance(v, str) and "[REDACTED]" not in v
                for k, v in values.items()
            ):
                raise ValueError
            return {k.lower(): v for k, v in values.items()}
    except (ValueError, TypeError):
        raise ValueError("CCWHAT_REPLAY_HEADERS must map HTTP(S) origins to current header objects") from None

    fresh: dict[str, str] = {}
    if origin == _origin(os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"):
        if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            fresh["authorization"] = "Bearer " + os.environ["ANTHROPIC_AUTH_TOKEN"]
        elif os.environ.get("ANTHROPIC_API_KEY"):
            fresh["x-api-key"] = os.environ["ANTHROPIC_API_KEY"]
        for line in os.environ.get("ANTHROPIC_CUSTOM_HEADERS", "").splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                fresh[key.strip().lower()] = value.strip()
    if origin == _origin(os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com"):
        if os.environ.get("OPENAI_API_KEY") and not fresh:
            fresh["authorization"] = "Bearer " + os.environ["OPENAI_API_KEY"]
    return fresh


def replay_headers(
    url: str, recorded: dict[str, str], *, config_path: Path | None = None,
) -> dict[str, str]:
    """Keep ordinary metadata, discard historical credentials, and load current ones."""
    origin = _origin(url)
    recorded = {k.lower(): v for k, v in recorded.items()}
    transport = {"host", "content-length", "accept-encoding", "content-encoding", "connection",
                 "transfer-encoding", "keep-alive", "te", "trailer", "upgrade", "proxy-authorization"}
    transport.update(x.strip().lower() for x in recorded.get("connection", "").split(","))
    cfg = load_config(config_path)
    sensitive = set(DEFAULT_REDACT_HEADERS)
    patterns = set(DEFAULT_REDACT_PATTERNS) | {"auth", "credential", "signature"}
    if cfg is not None:
        sensitive.update(name.lower() for name in cfg.redact_headers)
        patterns.update(pattern.lower() for pattern in cfg.redact_header_patterns)

    headers = {
        k: v for k, v in recorded.items()
        if k not in transport and k not in sensitive
        and not any(pattern in k for pattern in patterns)
        and "[REDACTED]" not in v
    }
    fresh = _current_headers(origin)
    headers.update({k: v for k, v in fresh.items() if k not in transport and "[REDACTED]" not in v})
    # Historical header names do not define the current gateway's auth contract.
    # It may now use another auth method or require no authentication at all.
    headers.setdefault("content-type", "application/json")
    return headers


def edit_targets(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Enumerate editable text leaves, preserving images, tools and reasoning."""
    targets = []

    def add(path: list, text: Any, role: str) -> None:
        if isinstance(text, str):
            targets.append({"path": path, "text": text, "role": role})

    field = "messages" if isinstance(body.get("messages"), list) else "input"
    messages = body.get(field, [])
    if isinstance(messages, str):
        add([field], messages, "user")
        return targets
    if not isinstance(messages, list):
        return targets
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", msg.get("type", "unknown"))
        base = [field, i]
        if msg.get("type") == "function_call_output":
            add(base + ["output"], msg.get("output"), role)
        content = msg.get("content")
        if isinstance(content, str):
            add(base + ["content"], content, role)
        elif isinstance(content, list):
            for j, block in enumerate(content):
                if not isinstance(block, dict):
                    continue
                path = base + ["content", j]
                if block.get("type") in {"text", "input_text", "output_text"}:
                    add(path + ["text"], block.get("text"), role)
                elif block.get("type") == "tool_result":
                    if isinstance(block.get("content"), str):
                        add(path + ["content"], block["content"], role)
                    elif isinstance(block.get("content"), list):
                        for k, part in enumerate(block["content"]):
                            if isinstance(part, dict) and part.get("type") == "text":
                                add(path + ["content", k, "text"], part.get("text"), role)
    return targets


def apply_edits(body: dict[str, Any], edits: list) -> tuple[dict, list]:
    if not isinstance(edits, list):
        raise ValueError("edits must be a list")
    result = copy.deepcopy(body)
    targets = edit_targets(body)
    applied = []
    for edit in edits:
        if not isinstance(edit, dict) or not isinstance(edit.get("editedText"), str):
            raise ValueError("Each edit needs a text value and an editable path")
        path = edit.get("path")
        if path is None:  # Older Viewers address a whole message; only unambiguous edits are safe.
            idx = edit.get("msgIndex")
            candidates = [t for t in targets if len(t["path"]) > 1 and t["path"][1] == idx]
            if type(idx) is not int or len(candidates) != 1:
                raise ValueError("Use an explicit text path for this message")
            path = candidates[0]["path"]
        target = next((t for t in targets if t["path"] == path), None)
        if target is None:
            raise ValueError("Edit path does not point to editable request text")
        parent = result
        for key in path[:-1]:
            parent = parent[key]
        parent[path[-1]] = edit["editedText"]
        applied.append({"path": path, "role": target["role"], "originalText": target["text"],
                        "editedText": edit["editedText"]})
    return result, applied


def recorded_body(record: dict) -> dict:
    if not isinstance(record, dict) or not isinstance(record.get("request"), dict):
        raise ValueError("Missing recorded request")
    _origin(record.get("url", ""))
    if record.get("method", "").upper() != "POST":
        raise ValueError("Replay supports recorded POST requests")
    if record["request"].get("body_truncated"):
        raise ValueError("Cannot replay a truncated request; record it again with a larger body limit")
    try:
        body = json.loads(record["request"].get("body", ""))
    except (ValueError, TypeError):
        raise ValueError("Recorded request body must be complete JSON") from None
    if not isinstance(body, dict):
        raise ValueError("Recorded request body must be a JSON object")
    return body


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Recorded credentials belong to the original endpoint only.
        return None


def send_replay(record: dict, edits: list, *, config_path: Path | None = None) -> tuple[dict, list]:
    body, applied = apply_edits(recorded_body(record), edits)
    headers = replay_headers(record["url"], record["request"].get("headers", {}), config_path=config_path)
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(record["url"], data=data, headers=headers, method="POST")
    with urllib.request.build_opener(_NoRedirect()).open(request, timeout=600) as response:
        raw = response.read().decode("utf-8")
        if "text/event-stream" in response.headers.get("Content-Type", "").lower():
            result = parse_sse_events([raw])
        else:
            result = parse_response(json.loads(raw))
    if result.get("error"):
        raise ValueError("Upstream returned an error: " + json.dumps(result["error"], ensure_ascii=False))
    return result, applied
