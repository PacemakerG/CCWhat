"""Viewer HTTP server — serves agent session log data via REST API."""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable
import urllib.request

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from ccwhat.adapters.base import AdapterNotImplementedError, AgentAdapter, SessionRenameError
from ccwhat.adapters.claude import ClaudeAdapter
from ccwhat.session_report import normalize_session_for_report


# ---------------------------------------------------------------------------
# Data loading helpers (kept as thin wrappers for backwards compatibility)
# ---------------------------------------------------------------------------

def get_projects(projects_dir: Path) -> list[dict[str, Any]]:
    """Return list of {projectDir, sessions} for all projects.
    Thin wrapper around ClaudeAdapter for backwards compatibility.
    """
    adapter = ClaudeAdapter(projects_dir)
    return adapter.list_projects()


def get_session(session_id: str, projects_dir: Path) -> dict[str, Any] | None:
    """Find session by ID across all project dirs.
    Thin wrapper around ClaudeAdapter for backwards compatibility.
    """
    adapter = ClaudeAdapter(projects_dir)
    return adapter.load_session(session_id)


# ---------------------------------------------------------------------------
# HTTP record helpers (unchanged)
# ---------------------------------------------------------------------------

def _read_jsonl(path: Path) -> list[dict]:
    entries = []
    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                entry["_fileLine"] = lineno
                entries.append(entry)
            except json.JSONDecodeError:
                pass
    return entries


def get_message_http(
    session_id: str,
    message_id: str,
    projects_dir: Path,
    logs_dir: Path,
) -> list[dict[str, Any]] | None:
    """Find HTTP records matching an assistant message ID (msg_bdrk_xxx)."""
    session_data = get_session(session_id, projects_dir)
    if session_data is None:
        return None
    if not logs_dir.is_dir():
        return []
    matches = []
    for parsed_path in sorted(logs_dir.glob("*_parsed.jsonl")):
        for record in _read_jsonl(parsed_path):
            if record.get("claude_session_id") != session_id:
                continue
            rec_msg_id = record.get("response_json", {}).get("message", {}).get("id")
            if rec_msg_id == message_id:
                matches.append(record)
    matches.sort(key=lambda r: r.get("timestamp", ""))
    return matches


def get_message_source(
    session_id: str,
    message_id: str,
    projects_dir: Path,
) -> dict[str, Any] | None:
    """Find the source (main or subagent) of an assistant message by message.id."""
    session_data = get_session(session_id, projects_dir)
    if session_data is None:
        return None
    for entry in session_data.get("main", []):
        if entry.get("type") == "assistant" and entry.get("message", {}).get("id") == message_id:
            return {"source": "main"}
    for sa in session_data.get("subagents", []):
        for entry in sa.get("entries", []):
            if entry.get("type") == "assistant" and entry.get("message", {}).get("id") == message_id:
                return {"source": "subagent", "agentId": sa.get("agentId", "")}
    return {}


def get_logs(
    logs_dir: Path,
    session_filter: str | None = None,
) -> dict[str, Any]:
    """Return all parsed log records from *_parsed.jsonl files."""
    if not logs_dir.is_dir():
        return {"records": [], "sessions": []}
    all_records: list[dict] = []
    for parsed_path in sorted(logs_dir.glob("*_parsed.jsonl")):
        all_records.extend(_read_jsonl(parsed_path))
    sessions = sorted({r.get("claude_session_id", "") for r in all_records if r.get("claude_session_id")})
    if session_filter:
        all_records = [r for r in all_records if r.get("claude_session_id") == session_filter]
    all_records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return {"records": all_records, "sessions": sessions}


def _read_auth_token_from_config() -> str | None:
    """Read AUTHORIZATION token from ~/.config/mcopilot-cli/.config.yaml."""
    config_path = Path.home() / ".config" / "mcopilot-cli" / ".config.yaml"
    try:
        for line in config_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("AUTHORIZATION:"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return None


def _parse_x_client_token_from_env() -> str | None:
    """Parse X-Client-Token from ANTHROPIC_CUSTOM_HEADERS environment variable.

    ANTHROPIC_CUSTOM_HEADERS format:
        X-Repo-Url: xxx
        X-Branch: xxx
        X-Client-Token: <token-value>
        ...
    """
    custom_headers = os.environ.get("ANTHROPIC_CUSTOM_HEADERS", "")
    for line in custom_headers.split("\n"):
        line = line.strip()
        if line.startswith("X-Client-Token:"):
            parts = line.split(":", 1)
            if len(parts) == 2:
                return parts[1].strip()
    return None


def get_req_resp_sessions(logs_dir: Path) -> dict[str, Any]:
    """Return all session IDs and their available date files under logs_dir."""
    if not logs_dir.is_dir():
        return {"sessions": []}
    sessions = []
    for session_dir in sorted(logs_dir.iterdir()):
        if not session_dir.is_dir():
            continue
        dates = sorted(
            p.stem for p in session_dir.glob("*.jsonl")
            if not p.name.endswith("_parsed.jsonl")
        )
        if dates:
            sessions.append({"id": session_dir.name, "dates": dates})
    return {"sessions": sessions}


def _extract_sse_message_id(sse_events: list[str]) -> str | None:
    """Parse SSE events and return message.id from message_start event."""
    for ev in sse_events:
        for line in ev.split("\n"):
            if not line.startswith("data:"):
                continue
            raw = line[len("data:"):].strip()
            try:
                d = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if d.get("type") == "message_start":
                return d.get("message", {}).get("id")
    return None


def get_req_resp_records(logs_dir: Path, session_id: str, date: str) -> list[dict]:
    """Return raw records from logs_dir/<session_id>/<date>.jsonl."""
    jsonl_path = logs_dir / session_id / f"{date}.jsonl"
    if not jsonl_path.exists():
        return []
    records = _read_jsonl(jsonl_path)
    for r in records:
        if r.get("is_sse") and r.get("sse_events"):
            r["_message_id"] = _extract_sse_message_id(r["sse_events"])
        else:
            r["_message_id"] = None
    return records


# ---------------------------------------------------------------------------
# Recording status API
# ---------------------------------------------------------------------------

def get_recording_status(logs_dir: Path, config_path: Path | None = None) -> dict[str, Any]:
    """Return recording config and health status for the viewer status panel."""
    try:
        from ccwhat.config import DEFAULT_CONFIG_PATH, load_config
        cfg_path = config_path or DEFAULT_CONFIG_PATH
        cfg = load_config(cfg_path)
    except Exception:
        cfg = None
        cfg_path = None
    latest_ts: str | None = None
    if logs_dir.is_dir():
        jsonl_files = sorted(logs_dir.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        for jf in jsonl_files[:1]:
            latest_ts = jf.stat().st_mtime.__str__()
    if cfg is None:
        return {
            "configValid": False,
            "configPath": str(cfg_path) if cfg_path else None,
            "domains": [],
            "paths": [],
            "rawLogDir": str(logs_dir),
            "latestRawLogTimestamp": latest_ts,
            "redactionSummary": "Default header redaction active",
            "maxBodyBytes": None,
            "preset": None,
        }
    return {
        "configValid": cfg.is_valid_for_recording(),
        "configPath": str(cfg_path),
        "domains": cfg.effective_domains(),
        "paths": cfg.effective_paths(),
        "rawLogDir": str(logs_dir),
        "latestRawLogTimestamp": latest_ts,
        "redactionSummary": f"{len(cfg.redact_headers)} sensitive headers redacted by default",
        "maxBodyBytes": cfg.max_body_bytes,
        "preset": cfg.preset,
    }


# ---------------------------------------------------------------------------
# Scoped search helpers
# ---------------------------------------------------------------------------

SEARCH_SCOPES = {"current_session", "current_project", "all_projects"}
DEFAULT_SEARCH_LIMIT = 50
MAX_SEARCH_LIMIT = 200


def _plain_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return " ".join(_plain_text(v) for v in value)
    if isinstance(value, dict):
        return " ".join(f"{k} {_plain_text(v)}" for k, v in value.items())
    return str(value)


def _short_snippet(text: Any, query: str, *, max_len: int = 110) -> str:
    clean = re.sub(r"\s+", " ", _plain_text(text)).strip()
    if len(clean) <= max_len:
        return clean
    pos = clean.lower().find(query.lower())
    if pos < 0:
        return clean[:max_len - 1] + "…"
    start = max(0, pos - max_len // 3)
    end = min(len(clean), start + max_len)
    start = max(0, end - max_len)
    prefix = "…" if start else ""
    suffix = "…" if end < len(clean) else ""
    return prefix + clean[start:end].strip() + suffix


def _search_result_key(result: dict[str, Any]) -> tuple[str, str, str]:
    typ = str(result.get("type") or "")
    session_id = str(result.get("sessionId") or "")
    if typ == "task":
        return (typ, session_id, str(result.get("taskId") or ""))
    if typ == "session":
        return (typ, session_id, "")
    snippet = re.sub(r"\s+", " ", str(result.get("snippet") or "")).strip().lower()
    return (typ, session_id, snippet[:100])


def _dedupe_search_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for result in results:
        key = _search_result_key(result)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped


def _field_matches(fields: dict[str, Any], query: str) -> list[str]:
    q = query.lower()
    return [name for name, value in fields.items() if q in _plain_text(value).lower()]


def _session_info_id(session_info: Any) -> str:
    if isinstance(session_info, dict):
        return str(session_info.get("id") or session_info.get("sessionId") or "")
    return str(session_info or "")


def _iter_session_candidates(
    projects: list[dict[str, Any]],
    *,
    scope: str,
    project_dir: str,
    session_id: str,
) -> tuple[list[dict[str, Any]], str | None]:
    candidates: list[dict[str, Any]] = []
    for project in projects:
        pdir = str(project.get("projectDir") or "")
        if scope == "current_project" and pdir != project_dir:
            continue
        for info in project.get("sessions", []) or []:
            sid = _session_info_id(info)
            if not sid:
                continue
            if scope == "current_session" and sid != session_id:
                continue
            candidates.append({
                "sessionId": sid,
                "projectDir": pdir,
                "session": info if isinstance(info, dict) else {"id": sid},
            })
    if scope == "current_session" and session_id and not candidates:
        return [{"sessionId": session_id, "projectDir": project_dir, "session": {"id": session_id}}], None
    if scope == "current_project" and project_dir and not any(str(p.get("projectDir") or "") == project_dir for p in projects):
        return [], f"project not found: {project_dir}"
    return candidates, None


def _search_session_metadata(candidate: dict[str, Any], query: str) -> list[dict[str, Any]]:
    info = candidate.get("session") or {}
    fields = {
        "sessionId": candidate["sessionId"],
        "projectDir": candidate["projectDir"],
        "title": info.get("title") if isinstance(info, dict) else "",
        "displayName": info.get("displayName") if isinstance(info, dict) else "",
        "firstTimestamp": info.get("firstTimestamp") if isinstance(info, dict) else "",
        "lastTimestamp": info.get("lastTimestamp") if isinstance(info, dict) else "",
    }
    matched = _field_matches(fields, query)
    if not matched:
        return []
    return [{
        "type": "session",
        "sessionId": candidate["sessionId"],
        "projectDir": candidate["projectDir"],
        "displayName": fields.get("displayName") or "",
        "title": fields.get("title") or "",
        "matchedFields": matched,
        "snippet": _short_snippet(" ".join(_plain_text(fields[name]) for name in matched), query),
        "timestamp": fields.get("lastTimestamp") or fields.get("firstTimestamp") or "",
    }]


def _search_session_content(
    session_data: dict[str, Any],
    project_dir: str,
    query: str,
    session_info: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    report_session = normalize_session_for_report(session_data)
    session_id = str(session_data.get("sessionId") or report_session.session_id or "")
    info = session_info or {}
    display_name = str(session_data.get("displayName") or info.get("displayName") or "")
    title = str(session_data.get("title") or info.get("title") or "")
    event_to_turn: dict[str, str] = {}
    for turn in report_session.turns:
        for event_id in turn.event_ids:
            event_to_turn[event_id] = turn.turn_id
    for event in report_session.events:
        fields = {
            "content": event.content,
            "summary": event.summary,
            "toolName": event.tool_name,
            "role": event.role,
            "kind": event.kind,
        }
        matched = _field_matches(fields, query)
        if not matched:
            continue
        results.append({
            "type": "event",
            "sessionId": session_id,
            "projectDir": project_dir,
            "displayName": display_name,
            "title": title,
            "eventId": event.event_id,
            "turnId": event_to_turn.get(event.event_id),
            "timestamp": event.timestamp or "",
            "matchedFields": matched,
            "snippet": _short_snippet(" ".join(_plain_text(fields[name]) for name in matched), query),
        })
    for turn in report_session.turns:
        fields = {
            "userSummary": turn.user_summary,
            "assistantSummary": turn.assistant_summary,
        }
        matched = _field_matches(fields, query)
        if not matched:
            continue
        results.append({
            "type": "turn",
            "sessionId": session_id,
            "projectDir": project_dir,
            "displayName": display_name,
            "title": title,
            "turnId": turn.turn_id,
            "eventId": (turn.event_ids or [None])[0],
            "timestamp": turn.started_at or turn.ended_at or "",
            "matchedFields": matched,
            "snippet": _short_snippet(" ".join(_plain_text(fields[name]) for name in matched), query),
        })
    return results


def _dataset_registry_task_results(
    *,
    registry_root: Path | None,
    candidate_session_ids: set[str],
    query: str,
) -> list[dict[str, Any]]:
    from ccwhat.task_dataset import default_dataset_registry_root

    root = (registry_root or default_dataset_registry_root()).expanduser()
    if not root.is_dir():
        return []
    results: list[dict[str, Any]] = []
    for dataset_dir in sorted(root.iterdir(), key=lambda p: p.name, reverse=True):
        if not dataset_dir.is_dir():
            continue
        manifest_path = dataset_dir / "manifest.json"
        dataset_path = dataset_dir / "dataset.jsonl"
        if not manifest_path.is_file() or not dataset_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            project_dir = str((manifest.get("session") or {}).get("project_dir") or "")
            for raw_line in dataset_path.read_text(encoding="utf-8").splitlines():
                if not raw_line.strip():
                    continue
                row = json.loads(raw_line)
                metadata = row.get("metadata") or {}
                session_id = str(metadata.get("session_id") or "")
                if session_id not in candidate_session_ids:
                    continue
                trace_path = str(metadata.get("trace_path") or "")
                trace = {}
                if trace_path:
                    trace_file = dataset_dir / trace_path
                    if trace_file.is_file():
                        trace = json.loads(trace_file.read_text(encoding="utf-8"))
                fields = {
                    "taskId": row.get("id"),
                    "title": (row.get("input") or {}).get("instruction"),
                    "taskType": metadata.get("task_type"),
                    "status": metadata.get("status"),
                    "startEventId": metadata.get("start_event_id"),
                    "endEventId": metadata.get("end_event_id"),
                    "commands": trace.get("commands"),
                    "testCommands": trace.get("test_commands"),
                    "filesRead": (trace.get("files") or {}).get("read"),
                    "filesChanged": (trace.get("files") or {}).get("changed"),
                    "errors": trace.get("errors"),
                    "finalClaim": trace.get("final_claim"),
                }
                matched = _field_matches(fields, query)
                if not matched:
                    continue
                results.append({
                    "type": "task",
                    "sessionId": session_id,
                    "projectDir": project_dir,
                    "taskId": str(row.get("id") or ""),
                    "title": _plain_text(fields["title"])[:120],
                    "taskType": str(metadata.get("task_type") or ""),
                    "eventId": str(metadata.get("start_event_id") or ""),
                    "matchedFields": matched,
                    "snippet": _short_snippet(" ".join(_plain_text(fields[name]) for name in matched), query),
                    "timestamp": str((manifest.get("created_at") or "")),
                    "source": "dataset",
                    "datasetId": dataset_dir.name,
                })
        except (OSError, json.JSONDecodeError):
            continue
    return results


# ---------------------------------------------------------------------------
# FastAPI application and compatibility server
class ViewerBackend:
    def __init__(
        self,
        viewer_dir: Path,
        projects_dir: Path,
        logs_dir: Path,
        config_path: Path,
        analyzer_cmd: str | None = None,
        analyzer_agent: str | None = None,
        analyzer_timeout: float | None = None,
        adapter: AgentAdapter | None = None,
        dataset_registry_root: Path | None = None,
    ) -> None:
        self.viewer_dir = viewer_dir
        self.projects_dir = projects_dir
        self.logs_dir = logs_dir
        self.config_path = config_path
        self.analyzer_cmd = analyzer_cmd
        self.analyzer_agent = analyzer_agent
        self.analyzer_timeout = analyzer_timeout
        self.adapter = adapter
        self.dataset_registry_root = dataset_registry_root
        self.report_store: dict[str, dict[str, Any]] = {}
        self.replay_store: dict[str, dict[str, Any]] = {}

    def _sessions_data(self) -> list[dict[str, Any]]:
        if self.adapter is not None:
            return self.adapter.list_projects()
        return get_projects(self.projects_dir)

    def _session_data(self, session_id: str) -> dict[str, Any] | None:
        if self.adapter is not None:
            return self.adapter.load_session(session_id)
        return get_session(session_id, self.projects_dir)

    def _agent_name(self) -> str | None:
        if self.adapter is not None:
            return self.adapter.name
        return None

    def get_projects_response(self) -> tuple[int, Any]:
        try:
            projects = self._sessions_data()
        except AdapterNotImplementedError as exc:
            return 501, {"error": str(exc), "agent": self._agent_name() or "claude"}
        for project in projects:
            project["agent"] = self._agent_name() or "claude"
        return 200, projects

    def get_session_response(self, session_id: str) -> tuple[int, dict[str, Any]]:
        if not re.match(r"^[0-9a-zA-Z_-]{20,64}$", session_id):
            return 400, {"error": "invalid session id"}
        try:
            session = self._session_data(session_id)
        except AdapterNotImplementedError as exc:
            return 501, {"error": str(exc), "agent": self._agent_name() or "claude"}
        if not session:
            return 404, {"error": "session not found"}
        report_session = normalize_session_for_report(session)
        session["agent"] = session.get("agent") or report_session.primary_agent_type or self._agent_name() or "claude"
        session["events"] = [
            {
                "id": event.event_id,
                "agentId": event.agent_id,
                "timestamp": event.timestamp,
                "role": event.role,
                "kind": event.kind,
                "content": event.content,
                "summary": event.summary,
                "toolName": event.tool_name,
                "toolCallId": event.tool_call_id,
                "parentId": event.parent_event_id,
                "usage": event.usage,
                "raw": event.raw,
            }
            for event in report_session.events
        ]
        session["turns"] = [
            {
                "id": turn.turn_id,
                "agentId": turn.agent_id,
                "startedAt": turn.started_at,
                "endedAt": turn.ended_at,
                "userSummary": turn.user_summary,
                "assistantSummary": turn.assistant_summary,
                "events": [{"id": event_id} for event_id in turn.event_ids],
                "usage": turn.usage,
            }
            for turn in report_session.turns
        ]
        return 200, session

    def get_logs_response(self, session_id: str | None) -> tuple[int, dict[str, Any]]:
        return 200, get_logs(self.logs_dir, session_id)

    def search_response(self, params: Any) -> tuple[int, dict[str, Any]]:
        raw_query = params.get("q", "")
        normalized_query = re.sub(r"\s+", " ", raw_query).strip()
        if len(normalized_query) < 2:
            return 400, {"ok": False, "error": "query must be at least 2 characters"}

        scope = params.get("scope", "current_session") or "current_session"
        if scope not in SEARCH_SCOPES:
            return 400, {"ok": False, "error": "invalid search scope"}

        project_dir = params.get("project", "").strip()
        session_id = params.get("session", "").strip()
        if scope == "current_session":
            if not re.fullmatch(r"[0-9a-zA-Z_-]{20,64}", session_id):
                return 400, {"ok": False, "error": "current_session scope requires a valid session"}
        elif scope == "current_project" and not project_dir:
            return 400, {"ok": False, "error": "current_project scope requires project"}

        try:
            limit = int(params.get("limit") or DEFAULT_SEARCH_LIMIT)
        except ValueError:
            return 400, {"ok": False, "error": "limit must be a number"}
        if limit < 1:
            return 400, {"ok": False, "error": "limit must be at least 1"}
        limit = min(limit, MAX_SEARCH_LIMIT)

        try:
            projects = self._sessions_data()
        except AdapterNotImplementedError as exc:
            return 501, {"ok": False, "error": str(exc), "agent": self._agent_name() or "claude"}

        candidates, source_error = _iter_session_candidates(
            projects,
            scope=scope,
            project_dir=project_dir,
            session_id=session_id,
        )
        if source_error:
            return 404, {"ok": False, "error": source_error}
        if not candidates:
            return 200, {
                "ok": True,
                "query": normalized_query,
                "scope": scope,
                "results": [],
                "truncated": False,
                "warnings": [{"message": "no searchable sessions found"}],
            }

        results: list[dict[str, Any]] = []
        warnings: list[dict[str, str]] = []
        searchable_session_ids: set[str] = set()

        for candidate in candidates:
            if len(results) > limit:
                break
            results.extend(_search_session_metadata(candidate, normalized_query))
            sid = candidate["sessionId"]
            try:
                session_data = self._session_data(sid)
                if session_data is None:
                    warnings.append({"sessionId": sid, "projectDir": candidate["projectDir"], "message": "session not found"})
                    continue
                searchable_session_ids.add(sid)
                results.extend(_search_session_content(
                    session_data,
                    candidate["projectDir"],
                    normalized_query,
                    session_info=candidate.get("session") if isinstance(candidate.get("session"), dict) else None,
                ))
            except Exception as exc:
                warnings.append({"sessionId": sid, "projectDir": candidate["projectDir"], "message": str(exc)})

        searchable_session_ids.update(candidate["sessionId"] for candidate in candidates)
        results.extend(_dataset_registry_task_results(
            registry_root=self.dataset_registry_root,
            candidate_session_ids=searchable_session_ids,
            query=normalized_query,
        ))

        results = _dedupe_search_results(results)
        results.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
        truncated = len(results) > limit
        return 200, {
            "ok": True,
            "query": normalized_query,
            "scope": scope,
            "results": results[:limit],
            "truncated": truncated,
            "warnings": warnings,
        }

    def replay_status_response(self, record_key: str | None) -> tuple[int, dict[str, Any]]:
        record_key = (record_key or "").strip()
        if not record_key:
            return 400, {"error": "missing recordKey parameter"}
        session = self.replay_store.get(f"rk:{record_key}")
        if not session:
            return 200, {"ok": True, "hasReplay": False}
        return 200, {
            "ok": True,
            "hasReplay": True,
            "originalText": session["originalText"],
            "editedText": session["editedText"],
            "result": session.get("result"),
            "isLoading": session.get("isLoading", False),
            "error": session.get("error"),
            "appliedEdits": session.get("appliedEdits", []),
        }

    @staticmethod
    def _extract_msg_text_no_thinking(msg: dict[str, Any]) -> str:
        """Extract message text, skipping thinking blocks."""
        if not msg:
            return ""
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if block.get("type") == "thinking":
                    continue
                if block.get("type") == "text" and block.get("text"):
                    parts.append(block["text"])
                elif block.get("type") == "tool_result" and block.get("content"):
                    tool_content = block["content"]
                    if isinstance(tool_content, str):
                        parts.append(f"[Tool Result] {tool_content}")
                    elif isinstance(tool_content, list):
                        texts = [c.get("text", "") for c in tool_content if c.get("type") == "text"]
                        parts.append(f"[Tool Result] {''.join(texts)}")
                elif block.get("type") == "tool_use":
                    parts.append(f"[Tool Use: {block.get('name', '')}] {json.dumps(block.get('input', {}))}")
            return "\n\n".join(parts)
        return ""

    def create_replay_session_response(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        record = payload.get("record", {})
        req_json = payload.get("reqJson", {})
        original_text = payload.get("originalText", "")
        record_key = payload.get("recordKey", "")

        if not record or not req_json:
            return 400, {"ok": False, "error": "missing record or reqJson"}

        session_id = uuid.uuid4().hex
        session_data = {
            "record": record,
            "reqJson": req_json,
            "originalText": original_text,
            "editedText": original_text,
            "isLoading": False,
            "result": None,
            "error": None,
            "appliedEdits": [],
        }
        self.replay_store[session_id] = session_data
        if record_key:
            self.replay_store[f"rk:{record_key}"] = session_data

        return 200, {"ok": True, "sessionId": session_id}

    def send_replay_response(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        session_id = payload.get("sessionId", "")
        edits = payload.get("edits", [])  # [{msgIndex, editedText}]

        if not session_id or session_id not in self.replay_store:
            return 404, {"ok": False, "error": "session not found"}

        session = self.replay_store[session_id]
        session["isLoading"] = True

        # Deep copy to avoid mutating stored original
        req_body = json.loads(json.dumps(session["reqJson"]))
        msgs = req_body.get("messages", [])

        # Apply edits: record originalText before each replacement
        applied_edits = []
        for edit in edits:
            raw_idx = edit.get("msgIndex", 0)
            edited_text = edit.get("editedText", "")
            idx = max(0, min(raw_idx, len(msgs) - 1)) if msgs else 0
            if not msgs:
                continue
            msg = msgs[idx]
            original_text = self._extract_msg_text_no_thinking(msg)
            msg["content"] = edited_text
            applied_edits.append({
                "msgIndex": idx,
                "role": msg.get("role", ""),
                "originalText": original_text,
                "editedText": edited_text,
            })

        api_url = os.environ.get("CLAUDE_API_URL", "https://mcli.sankuai.com/v1/messages")
        if "?" not in api_url:
            api_url += "?beta=true"

        record = session["record"]
        orig_headers = record.get("request", {}).get("headers", {})
        hop_by_hop = {"host", "content-length", "accept-encoding", "connection", "transfer-encoding", "keep-alive"}
        headers = {k: v for k, v in orig_headers.items() if k.lower() not in hop_by_hop}

        fresh_token = _parse_x_client_token_from_env()
        if fresh_token:
            headers["X-Client-Token"] = fresh_token

        auth_token = _read_auth_token_from_config() or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        req_body["stream"] = False
        headers["Accept"] = "application/json"

        try:
            data = json.dumps(req_body).encode("utf-8")
            req = urllib.request.Request(api_url, data=data, headers=headers, method="POST")
            response = urllib.request.urlopen(req, timeout=600)
            status = response.getcode()
            if status != 200:
                error_body = response.read().decode("utf-8", errors="replace")[:500]
                response.close()
                raise Exception(f"API returned status {status}: {error_body}")
            response_data = response.read()
            response.close()
            result = json.loads(response_data)
            session["result"] = result
            session["appliedEdits"] = applied_edits
            session["isLoading"] = False
            return 200, {"ok": True, "result": result, "appliedEdits": applied_edits}
        except Exception as exc:
            session["isLoading"] = False
            session["error"] = str(exc)
            return 500, {"ok": False, "error": str(exc)}

    def rename_session_response(self, session_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if not re.fullmatch(r"[0-9a-zA-Z_-]{20,64}", session_id):
            return 400, {"ok": False, "error": "invalid session id", "code": "invalid_title"}
        raw_title = payload.get("title", "")
        title = str(raw_title).strip() if raw_title else ""
        if not title:
            return 400, {"ok": False, "error": "title is required and must not be empty", "code": "invalid_title"}
        adapter = self.adapter
        if adapter is None:
            return 501, {"ok": False, "error": "rename not supported for this agent", "code": "rename_not_supported"}
        if not adapter.can_rename_session:
            return 501, {"ok": False, "error": "rename not supported for this agent", "code": "rename_not_supported"}

        try:
            result = adapter.rename_session(session_id, title)
        except SessionRenameError as exc:
            status_map = {
                "invalid_title": 400,
                "session_not_found": 404,
                "rename_not_supported": 501,
                "native_title_unavailable": 500,
                "native_title_write_failed": 500,
            }
            return status_map.get(exc.code, 500), {"ok": False, "error": exc.message, "code": exc.code}

        return 200, {
            "ok": True,
            "agent": adapter.name,
            "sessionId": session_id,
            "title": result["title"],
            "displayName": result["displayName"],
            "canRenameSession": result["canRenameSession"],
        }

    def analyze_response(self, path: str, payload: dict[str, Any], total_started: float) -> tuple[int, dict[str, Any]]:
        session_id = str(payload.get("sessionId", "")).strip()
        if not re.fullmatch(r"[0-9a-zA-Z_-]{20,64}", session_id):
            return 400, {"ok": False, "error": "invalid session id"}
        mode = str(payload.get("mode", "")).strip()
        custom_prompt = str(payload.get("customPrompt", "")).strip()

        session = self._session_data(session_id)
        if session is None:
            return 404, {"ok": False, "error": "session not found"}

        if path == "/api/task-segments":
            from ccwhat.task_segments import segment_session

            started = time.monotonic()
            try:
                result = segment_session(session)
            except Exception as exc:
                return 500, {"ok": False, "error": f"task segmentation failed: {exc}"}
            elapsed_ms = int((time.monotonic() - started) * 1000)
            tasks_json = []
            for idx, task in enumerate(result.tasks, 1):
                tasks_json.append({
                    "taskId": task.task_id,
                    "title": f"任务 {idx}",
                    "taskType": task.task_type,
                    "status": task.status,
                    "startEventId": task.start_event_id,
                    "endEventId": task.end_event_id,
                    "isAmbiguous": task.is_ambiguous,
                    "finalClaim": task.final_claim,
                    "boundaryReasons": task.boundary_reasons,
                    "evidence": {
                        "filesRead": task.evidence.files_read,
                        "filesChanged": task.evidence.files_changed,
                        "commands": task.evidence.commands,
                        "testCommands": task.evidence.test_commands,
                        "errors": task.evidence.errors,
                        "skills": task.evidence.skills,
                        "subagentIds": task.evidence.subagent_ids,
                        "finalClaims": task.evidence.final_claims,
                        "todosUser": task.evidence.todos_user,
                    },
                    "fileWeights": task.file_weights,
                })
            return 200, {
                "ok": True,
                "sessionId": result.session_id,
                "summary": result.summary,
                "tasks": tasks_json,
                "isAmbiguous": result.is_ambiguous,
                "elapsedMs": elapsed_ms,
                "debugBoundaries": [
                    {"eventId": boundary.event_id, "score": boundary.score,
                     "shouldSplit": boundary.should_split, "reasons": boundary.reasons}
                    for boundary in result.debug_boundaries
                ],
            }

        if mode not in ("yuanxi", "generic"):
            return 400, {"ok": False, "error": "mode is required (yuanxi or generic)", "code": "invalid_mode"}

        from ccwhat.analyzers.registry import get as get_analyzer_spec
        from ccwhat.session_report import build_generic_html_report, build_html_session_report

        report_session = normalize_session_for_report(session)
        report_started = time.monotonic()
        effective_agent = self.analyzer_agent or self._agent_name() or report_session.primary_agent_type or "claude"
        if mode == "generic":
            result = build_generic_html_report(
                session,
                custom_prompt=custom_prompt,
                analyzer_cmd=self.analyzer_cmd,
                analyzer_agent=effective_agent,
                analyzer_timeout=self.analyzer_timeout,
            )
        else:
            result = build_html_session_report(
                session,
                custom_prompt=custom_prompt,
                analyzer_cmd=self.analyzer_cmd,
                analyzer_agent=effective_agent,
                analyzer_timeout=self.analyzer_timeout,
            )
        report_id = uuid.uuid4().hex
        report_html = str(result.get("reportHtml") or "")
        self.report_store[report_id] = {"html": report_html, "mode": mode, "sessionId": session_id}
        analyzer_spec = get_analyzer_spec(effective_agent)
        return 200, {
            "ok": True,
            "reportType": result["reportType"],
            "reportMode": result.get("reportMode", mode),
            "reportUrl": f"/api/analysis-report/{report_id}",
            "exportUrl": f"/api/analysis-report/{report_id}/export",
            "summary": result.get("summary"),
            "elapsedMs": result["elapsedMs"],
            "truncated": bool((result.get("compression") or {}).get("omittedEvents")),
            "compression": result.get("compression"),
            "diagnosisStatus": result.get("diagnosisStatus"),
            "llmStatus": result.get("llmStatus"),
            "buildMs": int((time.monotonic() - report_started) * 1000),
            "totalMs": int((time.monotonic() - total_started) * 1000),
            "analyzerAgent": effective_agent,
            "analyzerOutputMode": analyzer_spec.output_mode if analyzer_spec else "unknown",
            "experimental": analyzer_spec.experimental if analyzer_spec else False,
        }

    def save_task_dataset_response(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        session_id = str(payload.get("sessionId", "")).strip()
        if not re.fullmatch(r"[0-9a-zA-Z_-]{20,64}", session_id):
            return 400, {"ok": False, "error": "invalid session id"}
        session = self._session_data(session_id)
        if session is None:
            return 404, {"ok": False, "error": "session not found"}

        from ccwhat.task_dataset import DatasetRegistryError, save_task_dataset_from_request

        try:
            saved = save_task_dataset_from_request(
                payload=payload,
                session=session,
                registry_root=self.dataset_registry_root,
            )
        except DatasetRegistryError as exc:
            return exc.status, {"ok": False, "error": str(exc)}
        return 200, {
            "ok": True,
            "datasetId": saved.dataset_id,
            "datasetPath": str(saved.dataset_path),
            "downloadUrl": saved.download_url,
        }


def _json(data: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=data, status_code=status_code)


async def _read_json_body(request: Request) -> dict[str, Any] | None:
    body = await request.body()
    if not body:
        return {}
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _attachment_response(data: bytes, filename: str, media_type: str) -> Response:
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def create_app(
    projects_dir: Path,
    logs_dir: Path,
    config_path: Path | None = None,
    analyzer_cmd: str | None = None,
    analyzer_agent: str | None = None,
    analyzer_timeout: float | None = None,
    adapter: AgentAdapter | None = None,
    dataset_registry_root: Path | None = None,
) -> FastAPI:
    config_path = config_path or (Path.home() / ".ccwhat" / "config.json")
    backend = ViewerBackend(
        Path(__file__).parent,
        projects_dir,
        logs_dir,
        config_path,
        analyzer_cmd=analyzer_cmd,
        analyzer_agent=analyzer_agent,
        analyzer_timeout=analyzer_timeout,
        adapter=adapter,
        dataset_registry_root=dataset_registry_root,
    )
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.state.viewer_backend = backend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def strip_trailing_slash(request: Request, call_next: Any) -> Response:
        raw_path = request.scope.get("raw_path", b"")
        raw_path_text = raw_path.decode("utf-8", errors="ignore") if isinstance(raw_path, bytes) else str(raw_path)
        if raw_path_text.startswith("/api/task-datasets/") and raw_path_text.endswith("/download") and ".." in raw_path_text:
            return _json({"ok": False, "error": "invalid dataset id"}, 400)
        path = request.scope.get("path", "")
        if path != "/" and path.endswith("/"):
            request.scope["path"] = path.rstrip("/")
        return await call_next(request)

    @app.get("/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(backend.viewer_dir / "index.html", media_type="text/html")

    @app.get("/claude-log.html", include_in_schema=False)
    async def claude_log() -> FileResponse:
        return FileResponse(backend.viewer_dir / "claude-log.html", media_type="text/html")

    @app.get("/req-resp.html", include_in_schema=False)
    async def req_resp_html() -> FileResponse:
        return FileResponse(backend.viewer_dir / "req-resp.html", media_type="text/html")

    @app.get("/api/replay/status", include_in_schema=False)
    async def replay_status(request: Request) -> JSONResponse:
        status, data = backend.replay_status_response(request.query_params.get("recordKey"))
        return _json(data, status)

    @app.get("/api/viewer/status", include_in_schema=False)
    async def viewer_status() -> JSONResponse:
        return _json({"ok": True, "agent": backend._agent_name() or "claude", "projectsDir": str(backend.projects_dir)})

    @app.get("/api/recording/status", include_in_schema=False)
    async def recording_status() -> JSONResponse:
        return _json(get_recording_status(backend.logs_dir, backend.config_path))

    @app.get("/api/search", include_in_schema=False)
    async def search(request: Request) -> JSONResponse:
        status, data = await run_in_threadpool(backend.search_response, request.query_params)
        return _json(data, status)

    @app.get("/api/projects", include_in_schema=False)
    async def projects() -> JSONResponse:
        status, data = await run_in_threadpool(backend.get_projects_response)
        return _json(data, status)

    @app.get("/api/session/{session_id}", include_in_schema=False)
    async def session(session_id: str) -> JSONResponse:
        status, data = await run_in_threadpool(backend.get_session_response, session_id)
        return _json(data, status)

    @app.get("/api/logs", include_in_schema=False)
    async def logs(request: Request) -> JSONResponse:
        status, data = await run_in_threadpool(backend.get_logs_response, request.query_params.get("session"))
        return _json(data, status)

    @app.get("/api/message-http/{session_id}/{message_id:path}", include_in_schema=False)
    async def message_http(session_id: str, message_id: str) -> JSONResponse:
        if not re.fullmatch(r"[0-9a-f-]{36}", session_id):
            return _json({"error": "invalid session id"}, 400)
        data = await run_in_threadpool(get_message_http, session_id, message_id, backend.projects_dir, backend.logs_dir)
        if data is None:
            return _json({"error": "message not found"}, 404)
        return _json({"records": data})

    @app.get("/api/message-source/{session_id}/{message_id:path}", include_in_schema=False)
    async def message_source(session_id: str, message_id: str) -> JSONResponse:
        if not re.fullmatch(r"[0-9a-f-]{36}", session_id):
            return _json({"error": "invalid session id"}, 400)
        data = await run_in_threadpool(get_message_source, session_id, message_id, backend.projects_dir)
        if data is None:
            return _json({"error": "session not found"}, 404)
        return _json(data)

    @app.get("/api/req-resp/sessions", include_in_schema=False)
    async def req_resp_sessions() -> JSONResponse:
        data = await run_in_threadpool(get_req_resp_sessions, backend.logs_dir)
        return _json(data)

    @app.get("/api/req-resp/records", include_in_schema=False)
    async def req_resp_records(request: Request) -> JSONResponse:
        session_id = request.query_params.get("session")
        date = request.query_params.get("date")
        if not session_id or not date:
            return _json({"error": "session and date are required"}, 400)
        data = await run_in_threadpool(
            get_req_resp_records,
            backend.logs_dir,
            session_id,
            date,
        )
        return _json({"records": data})

    @app.get("/api/export", include_in_schema=False)
    async def export_sessions(request: Request) -> Response:
        def build_export() -> tuple[int, dict[str, Any] | bytes, str]:
            from ccwhat.exporter import build_tar_gz_bytes, default_filename

            session_ids = [s.strip() for s in (request.query_params.get("sessions") or "").split(",") if s.strip()]
            if not session_ids:
                return 400, {"error": "sessions parameter is required"}, ""
            invalid = [s for s in session_ids if not re.fullmatch(r"[0-9a-f-]{36}", s)]
            if invalid:
                return 400, {"error": f"invalid session id(s): {', '.join(invalid)}"}, ""
            first_session = session_ids[0] if len(session_ids) == 1 else None
            filename = request.query_params.get("filename", "").strip() or default_filename(first_session, len(session_ids))
            filename = Path(filename).name.replace('"', "_").replace("\r", "_").replace("\n", "_")
            included_keys = {key.strip() for key in (request.query_params.get("include") or "claudeLogs,subagentLogs,reqResp").split(",")}
            content_options = {
                "claudeLogs": "claudeLogs" in included_keys,
                "subagentLogs": "subagentLogs" in included_keys,
                "reqResp": "reqResp" in included_keys,
            }
            req_resp_dates: dict[str, list[str]] = {
                item["id"]: item["dates"]
                for item in get_req_resp_sessions(backend.logs_dir)["sessions"]
            }
            try:
                data, _ = build_tar_gz_bytes(
                    session_ids,
                    backend.projects_dir,
                    backend.logs_dir,
                    req_resp_dates,
                    get_session,
                    content_options,
                )
            except ValueError as exc:
                return 404, {"error": str(exc)}, ""
            return 200, data, filename

        status, payload, filename = await run_in_threadpool(build_export)
        if isinstance(payload, dict):
            return _json(payload, status)
        return _attachment_response(payload, filename, "application/gzip")

    @app.get("/api/task-datasets/{dataset_id:path}/download", include_in_schema=False)
    async def task_dataset_download(dataset_id: str) -> Response:
        dataset_id = dataset_id.strip("/")
        from ccwhat.task_dataset import DatasetRegistryError, build_dataset_tar_gz

        try:
            data, filename = await run_in_threadpool(
                lambda: build_dataset_tar_gz(dataset_id=dataset_id, registry_root=backend.dataset_registry_root)
            )
        except DatasetRegistryError as exc:
            return _json({"ok": False, "error": str(exc)}, exc.status)
        return _attachment_response(data, filename, "application/gzip")

    @app.get("/api/analysis-report/{report_id}/export", include_in_schema=False)
    async def analysis_report_export(report_id: str) -> Response:
        report = backend.report_store.get(report_id)
        if not report:
            return _json({"error": "report not found or expired"}, 404)
        report_mode = report.get("mode", "report")
        filename = f"session-report-{report_mode}-{report_id[:8]}.html"
        return _attachment_response(str(report["html"]).encode("utf-8"), filename, "text/html; charset=utf-8")

    @app.get("/api/analysis-report/{report_id}", include_in_schema=False)
    async def analysis_report(report_id: str) -> Response:
        report = backend.report_store.get(report_id)
        if not report:
            return _json({"error": "report not found or expired"}, 404)
        return HTMLResponse(str(report["html"]))

    @app.post("/api/replay/session", include_in_schema=False)
    async def replay_session(request: Request) -> JSONResponse:
        payload = await _read_json_body(request)
        if payload is None:
            return _json({"ok": False, "error": "invalid JSON body"}, 400)
        status, data = await run_in_threadpool(backend.create_replay_session_response, payload)
        return _json(data, status)

    @app.post("/api/replay/send", include_in_schema=False)
    async def replay_send(request: Request) -> JSONResponse:
        payload = await _read_json_body(request)
        if payload is None:
            return _json({"ok": False, "error": "invalid JSON body"}, 400)
        status, data = await run_in_threadpool(backend.send_replay_response, payload)
        return _json(data, status)

    @app.post("/api/session/{session_id}/rename", include_in_schema=False)
    async def rename_session(session_id: str, request: Request) -> JSONResponse:
        payload = await _read_json_body(request)
        if payload is None:
            return _json({"ok": False, "error": "invalid JSON body", "code": "invalid_title"}, 400)
        status, data = await run_in_threadpool(backend.rename_session_response, session_id, payload)
        return _json(data, status)

    @app.post("/api/analyze", include_in_schema=False)
    async def analyze(request: Request) -> JSONResponse:
        total_started = time.monotonic()
        payload = await _read_json_body(request)
        if payload is None:
            return _json({"ok": False, "error": "invalid JSON body"}, 400)
        status, data = await run_in_threadpool(backend.analyze_response, request.url.path, payload, total_started)
        return _json(data, status)

    @app.post("/api/task-segments", include_in_schema=False)
    async def task_segments(request: Request) -> JSONResponse:
        total_started = time.monotonic()
        payload = await _read_json_body(request)
        if payload is None:
            return _json({"ok": False, "error": "invalid JSON body"}, 400)
        try:
            status, data = await run_in_threadpool(backend.analyze_response, request.url.path, payload, total_started)
        except Exception as exc:
            status, data = 500, {"ok": False, "error": f"task segmentation failed: {exc}"}
        return _json(data, status)

    @app.post("/api/save-task-dataset", include_in_schema=False)
    async def save_task_dataset_route(request: Request) -> JSONResponse:
        payload = await _read_json_body(request)
        if payload is None:
            return _json({"ok": False, "error": "invalid JSON body"}, 400)
        status, data = await run_in_threadpool(backend.save_task_dataset_response, payload)
        return _json(data, status)

    @app.options("/{path:path}", include_in_schema=False)
    async def options_catch_all(path: str) -> Response:
        return Response(status_code=204)

    @app.get("/{path:path}", include_in_schema=False)
    async def get_catch_all(path: str) -> JSONResponse:
        return _json({"error": "not found"}, 404)

    @app.post("/{path:path}", include_in_schema=False)
    async def post_catch_all(path: str) -> JSONResponse:
        return _json({"ok": False, "error": "not found"}, 404)

    return app


def _make_handler(
    projects_dir: Path,
    logs_dir: Path,
    config_path: Path | None = None,
    analyzer_cmd: str | None = None,
    analyzer_agent: str | None = None,
    analyzer_timeout: float | None = None,
    adapter: AgentAdapter | None = None,
    dataset_registry_root: Path | None = None,
) -> type[BaseHTTPRequestHandler]:
    config_path = config_path or (Path.home() / ".ccwhat" / "config.json")
    app = create_app(
        projects_dir,
        logs_dir,
        config_path,
        analyzer_cmd=analyzer_cmd,
        analyzer_agent=analyzer_agent,
        analyzer_timeout=analyzer_timeout,
        adapter=adapter,
        dataset_registry_root=dataset_registry_root,
    )
    from fastapi.testclient import TestClient

    client = TestClient(app)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

        def _forward(self) -> None:
            if self.path.startswith("/api/task-datasets/") and self.path.endswith("/download") and ".." in self.path:
                body = json.dumps({"ok": False, "error": "invalid dataset id"}, ensure_ascii=False).encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
                return

            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length else b""
            headers = {key: value for key, value in self.headers.items()}
            response = client.request(
                self.command,
                self.path,
                content=body,
                headers=headers,
                follow_redirects=False,
            )
            self.send_response(response.status_code)
            skipped_headers = {"connection", "content-encoding", "transfer-encoding", "content-length"}
            for key, value in response.headers.items():
                if key.lower() not in skipped_headers:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)

        def do_GET(self) -> None:
            self._forward()

        def do_POST(self) -> None:
            self._forward()

        def do_OPTIONS(self) -> None:
            self._forward()

    return Handler


class ViewerServer:
    daemon_threads = True

    def __init__(
        self,
        app: FastAPI,
        handler_factory: Callable[[], type[BaseHTTPRequestHandler]],
        port: int,
    ) -> None:
        self.app = app
        self._handler_factory = handler_factory
        self._request_handler_class: type[BaseHTTPRequestHandler] | None = None
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", port))
        self.server_address = self._socket.getsockname()
        self.server_port = int(self.server_address[1])
        config = uvicorn.Config(app, host="127.0.0.1", port=self.server_port, log_level="warning", access_log=False)
        self._server = uvicorn.Server(config)

    @property
    def RequestHandlerClass(self) -> type[BaseHTTPRequestHandler]:
        if self._request_handler_class is None:
            self._request_handler_class = self._handler_factory()
        return self._request_handler_class

    def serve_forever(self) -> None:
        self._server.run(sockets=[self._socket])

    def shutdown(self) -> None:
        self._server.should_exit = True

    def server_close(self) -> None:
        self._socket.close()


def viewer_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/claude-log.html"


def create_server(
    port: int,
    projects_dir: Path,
    logs_dir: Path,
    config_path: Path | None = None,
    analyzer_cmd: str | None = None,
    analyzer_agent: str | None = None,
    analyzer_timeout: float | None = None,
    adapter: AgentAdapter | None = None,
    dataset_registry_root: Path | None = None,
) -> ViewerServer:
    config_path = config_path or (Path.home() / ".ccwhat" / "config.json")
    app = create_app(
        projects_dir,
        logs_dir,
        config_path,
        analyzer_cmd=analyzer_cmd,
        analyzer_agent=analyzer_agent,
        analyzer_timeout=analyzer_timeout,
        adapter=adapter,
        dataset_registry_root=dataset_registry_root,
    )
    handler_factory = lambda: _make_handler(
        projects_dir,
        logs_dir,
        config_path,
        analyzer_cmd=analyzer_cmd,
        analyzer_agent=analyzer_agent,
        analyzer_timeout=analyzer_timeout,
        adapter=adapter,
        dataset_registry_root=dataset_registry_root,
    )
    return ViewerServer(app, handler_factory, port)


def open_viewer(port: int) -> None:
    webbrowser.open(viewer_url(port))


def run_server(
    port: int,
    projects_dir: Path,
    logs_dir: Path,
    config_path: Path | None = None,
    open_browser: bool = False,
    analyzer_cmd: str | None = None,
    analyzer_agent: str | None = None,
    analyzer_timeout: float | None = None,
    adapter: AgentAdapter | None = None,
    dataset_registry_root: Path | None = None,
) -> None:
    server = create_server(
        port,
        projects_dir,
        logs_dir,
        config_path=config_path,
        analyzer_cmd=analyzer_cmd,
        analyzer_agent=analyzer_agent,
        analyzer_timeout=analyzer_timeout,
        adapter=adapter,
        dataset_registry_root=dataset_registry_root,
    )
    url = viewer_url(server.server_port)
    print(f"CCWhat viewer running at {url}")
    if open_browser:
        open_viewer(server.server_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped")
    finally:
        server.server_close()


# Direct CLI (python3 viewer/server.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agent session viewer API server")
    parser.add_argument("--port", type=int, default=7789)
    parser.add_argument("--projects-dir", type=Path, default=Path.home() / ".claude" / "projects")
    parser.add_argument("--logs-dir", type=Path, default=Path("./logs"))
    args = parser.parse_args()
    run_server(args.port, args.projects_dir, args.logs_dir)
