"""mitmproxy addon that records HTTP/HTTPS traffic to JSONL files.

This module is loaded by mitmdump at runtime and must NOT import the ccwhat
package (it runs in a different process). All config is passed via env vars.
"""

from __future__ import annotations

import codecs
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from mitmproxy import http

# ---------------------------------------------------------------------------
# Config from environment variables (set by proxy / run commands)
# ---------------------------------------------------------------------------

_DEFAULT_OUTPUT_DIR = Path.home() / ".ccwhat" / "raw-req-resp"
_OUTPUT_DIR = Path(os.environ.get("CCWHAT_OUTPUT_DIR", str(_DEFAULT_OUTPUT_DIR)))

_DEFAULT_RECORD_DOMAINS: list[str] = []
_DEFAULT_MAX_BODY_BYTES = 512 * 1024
_DEFAULT_REDACT_HEADERS = frozenset({
    "authorization", "cookie", "set-cookie", "x-api-key", "proxy-authorization",
})
_DEFAULT_REDACT_PATTERNS = ("token", "secret", "key")


def _list_from_env(key: str) -> list[str]:
    raw = os.environ.get(key, "")
    return [x.strip() for x in raw.split(",") if x.strip()]


def _record_domains_from_env() -> list[str]:
    domains = _list_from_env("CCWHAT_RECORD_DOMAINS")
    return domains if domains else list(_DEFAULT_RECORD_DOMAINS)


def _record_paths_from_env() -> list[str]:
    return _list_from_env("CCWHAT_RECORD_PATHS")


def _max_body_bytes_from_env() -> int:
    try:
        return int(os.environ.get("CCWHAT_MAX_BODY_BYTES", str(_DEFAULT_MAX_BODY_BYTES)))
    except ValueError:
        return _DEFAULT_MAX_BODY_BYTES


def _redact_headers_from_env() -> frozenset[str]:
    headers = _list_from_env("CCWHAT_REDACT_HEADERS")
    if not headers:
        return _DEFAULT_REDACT_HEADERS
    return frozenset(h.lower() for h in headers)


def _redact_patterns_from_env() -> tuple[str, ...]:
    patterns = _list_from_env("CCWHAT_REDACT_PATTERNS")
    return tuple(patterns) if patterns else _DEFAULT_REDACT_PATTERNS


def _local_session_id_from_env() -> str:
    return os.environ.get("CCWHAT_LOCAL_SESSION_ID", f"local-{id(object())}")


# ---------------------------------------------------------------------------
# Recorder addon
# ---------------------------------------------------------------------------


class RecorderAddon:
    """Records matching HTTP flows to a daily JSONL file.

    Each request is written as a single JSON line to
    ``<output_dir>/<sessionId>/YYYY-MM-DD.jsonl``.
    SSE responses are buffered and written as one record when the flow completes.
    """

    def __init__(self, output_dir: Path | None = None) -> None:
        self._output_dir = output_dir if output_dir is not None else _OUTPUT_DIR
        self._domains: list[str] = _record_domains_from_env()
        self._paths: list[str] = _record_paths_from_env()
        self._max_body_bytes: int = _max_body_bytes_from_env()
        self._redact_headers: frozenset[str] = _redact_headers_from_env()
        self._redact_patterns: tuple[str, ...] = _redact_patterns_from_env()
        self._local_session_id: str = _local_session_id_from_env()
        # Per-flow SSE state: flow_id -> {"events": [...], "buffer": ""}
        self._sse_buffers: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Domain / path filtering
    # ------------------------------------------------------------------

    def _should_record(self, flow: http.HTTPFlow) -> bool:
        if not self._domains:
            return False
        host = flow.request.pretty_host
        if host not in self._domains:
            return False
        if self._paths:
            request_path = flow.request.path.split("?")[0]
            if not any(request_path.startswith(p) for p in self._paths):
                return False
        # Content-type guard: only record likely AI API responses
        if flow.response is not None:
            resp_ct = flow.response.headers.get("content-type", "")
            req_ct = flow.request.headers.get("content-type", "")
            is_json_or_sse = (
                "application/json" in resp_ct
                or "text/event-stream" in resp_ct
                or "application/json" in req_ct
            )
            if not is_json_or_sse:
                return False
        return True

    # ------------------------------------------------------------------
    # Session ID
    # ------------------------------------------------------------------

    def _get_session_id(self, flow: http.HTTPFlow) -> str:
        sid = flow.request.headers.get("X-Claude-Code-Session-Id", "").strip()
        return sid if sid else self._local_session_id

    # ------------------------------------------------------------------
    # Header redaction
    # ------------------------------------------------------------------

    def _is_sensitive_header(self, name: str) -> bool:
        nl = name.lower()
        if nl in self._redact_headers:
            return True
        return any(p in nl for p in self._redact_patterns)

    def _redact_headers_dict(self, headers: Any) -> dict[str, str]:
        return {
            k: ("[REDACTED]" if self._is_sensitive_header(k) else v)
            for k, v in headers.items()
        }

    # ------------------------------------------------------------------
    # Body size limiting
    # ------------------------------------------------------------------

    def _limit_body(self, body: str) -> tuple[str, bool, int]:
        """Return (body_text, was_truncated, original_byte_len)."""
        encoded = body.encode("utf-8", errors="replace")
        original_len = len(encoded)
        if original_len <= self._max_body_bytes:
            return body, False, original_len
        truncated = encoded[: self._max_body_bytes].decode("utf-8", errors="ignore")
        return truncated, True, original_len

    # ------------------------------------------------------------------
    # File paths
    # ------------------------------------------------------------------

    def _jsonl_path(self, session_id: str) -> Path:
        today = date.today().isoformat()
        path = self._output_dir / session_id / f"{today}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _append_record(self, record: dict[str, Any], session_id: str) -> None:
        path = self._jsonl_path(session_id)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # mitmproxy hooks
    # ------------------------------------------------------------------

    def responseheaders(self, flow: http.HTTPFlow) -> None:
        if flow.response is None:
            return
        content_type = flow.response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            if self._should_record_with_response(flow):
                flow.response.stream = self._make_sse_stream_handler(flow)
                self._sse_buffers[flow.id] = {
                    "events": [], "buffer": "",
                    "decoder": codecs.getincrementaldecoder("utf-8")("replace"),
                }

    def _should_record_with_response(self, flow: http.HTTPFlow) -> bool:
        """Check domain/path match (response already present for CT check)."""
        if not self._domains:
            return False
        host = flow.request.pretty_host
        if host not in self._domains:
            return False
        if self._paths:
            request_path = flow.request.path.split("?")[0]
            if not any(request_path.startswith(p) for p in self._paths):
                return False
        return True

    def _make_sse_stream_handler(self, flow: http.HTTPFlow):
        def handler(chunk: bytes) -> bytes:
            state = self._sse_buffers.get(flow.id)
            if state is None:
                return chunk
            text = state["buffer"] + state["decoder"].decode(chunk, final=not chunk)
            parts = re.split(r"\r\n\r\n|\n\n|\r\r", text)
            for event in parts[:-1]:
                event = event.strip()
                if event:
                    state["events"].append(event)
            state["buffer"] = parts[-1]
            return chunk

        return handler

    def response(self, flow: http.HTTPFlow) -> None:
        if not self._should_record(flow):
            # Still pop SSE state if it was set
            self._sse_buffers.pop(flow.id, None)
            return
        if flow.response is None:
            return

        timestamp = datetime.now(tz=timezone.utc).isoformat()
        session_id = self._get_session_id(flow)

        # Request body
        try:
            req_body_raw = flow.request.get_text(strict=False) or ""
        except Exception:
            req_body_raw = flow.request.content.decode("utf-8", errors="replace")
        req_body, req_truncated, req_original_len = self._limit_body(req_body_raw)

        request_data: dict[str, Any] = {
            "headers": self._redact_headers_dict(flow.request.headers),
            "body": req_body,
        }
        if req_truncated:
            request_data["body_truncated"] = True
            request_data["body_original_bytes"] = req_original_len

        # SSE vs normal response
        sse_state = self._sse_buffers.pop(flow.id, None)
        is_sse = sse_state is not None

        if is_sse:
            remaining = sse_state["buffer"].strip()
            if remaining:
                sse_state["events"].append(remaining)
            # Enforce body size limit on SSE events: stop accumulating once the
            # joined body would exceed max_body_bytes.
            sse_events_all: list[str] = sse_state["events"]
            sse_events: list[str] = []
            running_bytes = 0
            sse_events_truncated = False
            for ev in sse_events_all:
                ev_bytes = len((ev + "\n\n").encode("utf-8", errors="replace"))
                if running_bytes + ev_bytes > self._max_body_bytes:
                    sse_events_truncated = True
                    break
                sse_events.append(ev)
                running_bytes += ev_bytes
            resp_body_raw = "\n\n".join(sse_events)
        else:
            try:
                resp_body_raw = flow.response.get_text(strict=False) or ""
            except Exception:
                resp_body_raw = flow.response.content.decode("utf-8", errors="replace")
            sse_events = []

        resp_body, resp_truncated, resp_original_len = self._limit_body(resp_body_raw)

        response_data: dict[str, Any] = {
            "status": flow.response.status_code,
            "headers": self._redact_headers_dict(flow.response.headers),
            "body": resp_body,
        }
        if resp_truncated:
            response_data["body_truncated"] = True
            response_data["body_original_bytes"] = resp_original_len

        record: dict[str, Any] = {
            "timestamp": timestamp,
            "session_id": session_id,
            "domain": flow.request.pretty_host,
            "method": flow.request.method,
            "url": flow.request.pretty_url,
            "request": request_data,
            "response": response_data,
            "is_sse": is_sse,
        }
        if is_sse:
            record["sse_events"] = sse_events
            if sse_events_truncated:
                record["sse_events_truncated"] = True
                record["sse_events_total"] = len(sse_events_all)

        try:
            self._append_record(record, session_id)
        except OSError as exc:
            print(f"[ccwhat] Failed to write log: {exc}", file=sys.stderr)


# Module-level addon instance required by `mitmdump -s <this_file>`
addons = [RecorderAddon()]
