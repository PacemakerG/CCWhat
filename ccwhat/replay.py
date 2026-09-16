"""Replay recorded JSON requests without assuming a particular agent or gateway."""

from __future__ import annotations

import copy
import json
import os
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ccwhat.parsers.sse_parser import parse_response, parse_sse_events
from ccwhat.config import DEFAULT_REDACT_HEADERS, DEFAULT_REDACT_PATTERNS, load_config


_ANTHROPIC_REPLAY_ENV = (
    "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_CUSTOM_HEADERS",
)


def _claude_settings_env() -> dict[str, str]:
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()
    try:
        settings = json.loads((config_dir / "settings.json").read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise ValueError("Cannot read Claude settings.json for replay credentials") from None
    env = settings.get("env", {}) if isinstance(settings, dict) else None
    if not isinstance(env, dict) or any(
        key in env and not isinstance(env[key], str) for key in _ANTHROPIC_REPLAY_ENV
    ):
        raise ValueError("Claude settings.json must contain an env object with string replay settings")
    return {key: env[key] for key in _ANTHROPIC_REPLAY_ENV if key in env}


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


def _explicit_headers(origin: str) -> dict[str, str] | None:
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
    return None


def _current_headers(origin: str, anthropic_env: dict[str, str] | None = None) -> dict[str, str]:
    """Use explicit headers, then process credentials, then local Claude settings."""
    explicit = _explicit_headers(origin)
    if explicit is not None:
        return explicit
    openai_key = None
    if origin == _origin(os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com"):
        openai_key = os.environ.get("OPENAI_API_KEY")
    if anthropic_env is None:
        anthropic_env = {key: os.environ[key] for key in _ANTHROPIC_REPLAY_ENV if key in os.environ}
        if not anthropic_env and not openai_key:
            anthropic_env = _claude_settings_env()

    fresh: dict[str, str] = {}
    if origin == _origin(anthropic_env.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"):
        if anthropic_env.get("ANTHROPIC_AUTH_TOKEN"):
            # This is a Bearer header value, which can itself be a provider API key.
            fresh["authorization"] = "Bearer " + anthropic_env["ANTHROPIC_AUTH_TOKEN"]
        elif anthropic_env.get("ANTHROPIC_API_KEY"):
            fresh["x-api-key"] = anthropic_env["ANTHROPIC_API_KEY"]
        for line in anthropic_env.get("ANTHROPIC_CUSTOM_HEADERS", "").splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                fresh[key.strip().lower()] = value.strip()
    if openai_key and not fresh:
        fresh["authorization"] = "Bearer " + openai_key
    return fresh


def _replay_endpoint(url: str) -> tuple[str, dict[str, str] | None]:
    """Rebuild CC Messages URLs using the same local settings as authentication."""
    original = urlsplit(url)
    endpoint = next((path for path in ("/v1/messages", "/v1/messages/count_tokens")
                     if original.path.rstrip("/").endswith(path)), None)
    if endpoint is None or _explicit_headers(_origin(url)) is not None:
        return url, None
    anthropic_env = {key: os.environ[key] for key in _ANTHROPIC_REPLAY_ENV if key in os.environ}
    if not anthropic_env and os.environ.get("OPENAI_API_KEY") and _origin(url) == _origin(
        os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com"
    ):
        return url, None
    if not anthropic_env:
        anthropic_env = _claude_settings_env()
    if not anthropic_env:
        return url, anthropic_env
    base_url = anthropic_env.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"
    _origin(base_url)
    base = urlsplit(base_url)
    if base.query or base.fragment:
        raise ValueError("Replay ANTHROPIC_BASE_URL must not contain a query or fragment")
    target = urlunsplit((base.scheme, base.netloc, base.path.rstrip("/") + endpoint,
                        original.query, ""))
    return target, anthropic_env


def replay_headers(
    url: str, recorded: dict[str, str], *, config_path: Path | None = None,
    anthropic_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Keep ordinary metadata, discard historical credentials, and load current ones."""
    origin = _origin(url)
    recorded = {k.lower(): v for k, v in recorded.items()}
    transport = {"host", "content-length", "accept-encoding", "content-encoding", "connection", "proxy-connection",
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
    fresh = _current_headers(origin, anthropic_env)
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
        # Current credentials belong only to the selected endpoint.
        return None


def send_replay(record: dict, edits: list, *, config_path: Path | None = None) -> tuple[dict, list]:
    body, applied = apply_edits(recorded_body(record), edits)
    url, anthropic_env = _replay_endpoint(record["url"])
    headers = replay_headers(url, record["request"].get("headers", {}), config_path=config_path,
                             anthropic_env=anthropic_env)
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.build_opener(_NoRedirect()).open(request, timeout=600) as response:
        raw = response.read().decode("utf-8")
        if "text/event-stream" in response.headers.get("Content-Type", "").lower():
            result = parse_sse_events([raw])
        else:
            result = parse_response(json.loads(raw))
    if result.get("error"):
        raise ValueError("Upstream returned an error: " + json.dumps(result["error"], ensure_ascii=False))
    return result, applied
