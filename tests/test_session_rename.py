"""Tests for session rename: adapter rename, viewer API, and frontend elements."""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ccwhat.adapters.base import AgentAdapter, SessionRenameError
from ccwhat.adapters.claude import ClaudeAdapter
from ccwhat.adapters.codex import CodexAdapter
from ccwhat.adapters.opencode import OpenCodeAdapter


# ---------------------------------------------------------------------------
# 6.1 Adapter interface tests: title/displayName/canRenameSession
# ---------------------------------------------------------------------------


class TestAdapterTitleMetadata(unittest.TestCase):
    """Verify adapters return title, displayName, canRenameSession in session data."""

    def test_claude_adapter_can_rename_is_false(self):
        adapter = ClaudeAdapter(Path("/nonexistent"))
        self.assertFalse(adapter.can_rename_session)

    def test_codex_adapter_can_rename_is_true(self):
        adapter = CodexAdapter(Path("/nonexistent"))
        self.assertTrue(adapter.can_rename_session)

    def test_opencode_adapter_can_rename_is_true(self):
        adapter = OpenCodeAdapter(Path("/nonexistent"))
        self.assertTrue(adapter.can_rename_session)

    def test_claude_rename_raises_unsupported(self):
        adapter = ClaudeAdapter(Path("/nonexistent"))
        with self.assertRaises(SessionRenameError) as ctx:
            adapter.rename_session("some-id", "New Title")
        self.assertEqual(ctx.exception.code, "rename_not_supported")

    def test_claude_list_projects_includes_title_fields(self):
        with TemporaryDirectory() as tmp:
            pd = Path(tmp)
            proj = pd / "my-project"
            proj.mkdir()
            sid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
            (proj / f"{sid}.jsonl").write_text(
                json.dumps({"type": "user", "content": "hi", "timestamp": "2025-01-01T00:00:00Z"}) + "\n"
            )
            adapter = ClaudeAdapter(pd)
            projects = adapter.list_projects()
            self.assertEqual(len(projects), 1)
            sess = projects[0]["sessions"][0]
            self.assertIn("title", sess)
            self.assertIn("displayName", sess)
            self.assertIn("canRenameSession", sess)
            self.assertEqual(sess["title"], "")
            self.assertEqual(sess["displayName"], sid[:8])
            self.assertFalse(sess["canRenameSession"])

    def test_claude_load_session_includes_title_fields(self):
        with TemporaryDirectory() as tmp:
            pd = Path(tmp)
            proj = pd / "my-project"
            proj.mkdir()
            sid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
            (proj / f"{sid}.jsonl").write_text(
                json.dumps({"type": "user", "content": "hi", "timestamp": "2025-01-01T00:00:00Z"}) + "\n"
            )
            adapter = ClaudeAdapter(pd)
            data = adapter.load_session(sid)
            self.assertIsNotNone(data)
            self.assertEqual(data["title"], "")
            self.assertEqual(data["displayName"], sid[:8])
            self.assertFalse(data["canRenameSession"])


class TestSessionIdRemainsUniqueKey(unittest.TestCase):
    """6.1.1 — session id is always the unique identifier, not title/displayName."""

    def test_codex_load_session_uses_session_id(self):
        """load_session requires session_id, not displayName."""
        with TemporaryDirectory() as tmp:
            pd = Path(tmp)
            adapter = CodexAdapter(pd)
            # Should return None for nonexistent session (searched by id, not title)
            result = adapter.load_session("nonexistent-title-not-id")
            self.assertIsNone(result)

    def test_opencode_load_session_uses_session_id(self):
        """load_session requires session_id, not displayName."""
        with TemporaryDirectory() as tmp:
            pd = Path(tmp)
            db_path = pd / "opencode.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "CREATE TABLE session (id TEXT PRIMARY KEY, title TEXT, directory TEXT, "
                "agent TEXT, model TEXT, time_created REAL, time_updated REAL, "
                "tokens_input INT, tokens_output INT, tokens_reasoning INT, "
                "tokens_cache_read INT, tokens_cache_write INT, cost REAL, project_id TEXT)"
            )
            conn.execute(
                "INSERT INTO session (id, title, directory, agent) VALUES (?, ?, ?, ?)",
                ("real-session-id", "My Title", "/tmp/proj", "opencode"),
            )
            conn.commit()
            conn.close()
            adapter = OpenCodeAdapter(pd)
            # Load by id works
            result = adapter.load_session("real-session-id")
            # Title is not a lookup key
            result_by_title = adapter.load_session("My Title")
            self.assertIsNone(result_by_title)


# ---------------------------------------------------------------------------
# 6.2 Codex SQLite rename tests
# ---------------------------------------------------------------------------


class TestCodexRename(unittest.TestCase):
    """Codex SQLite title read/write tests."""

    def _make_codex_env(self, tmp: str, sessions: list[tuple[str, str]] | None = None):
        """Create a minimal Codex environment with rollout + SQLite."""
        pd = Path(tmp) / "sessions"
        session_dir = pd / "2025" / "06" / "03"
        session_dir.mkdir(parents=True)

        sqlite_path = Path(tmp) / "state_5.sqlite"
        conn = sqlite3.connect(str(sqlite_path))
        conn.execute(
            "CREATE TABLE threads (id TEXT PRIMARY KEY, title TEXT, cwd TEXT, "
            "model TEXT, model_provider TEXT, updated_at TEXT, tokens_used INT, "
            "created_at TEXT, rollout_path TEXT)"
        )
        sids = []
        for sid, title in (sessions or [("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "Original Title")]):
            fname = f"rollout-2025-06-03T10-00-00-{sid}.jsonl"
            (session_dir / fname).write_text(json.dumps({
                "type": "response_item",
                "timestamp": "2025-06-01T10:00:01Z",
                "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]},
            }) + "\n")
            conn.execute(
                "INSERT INTO threads (id, title, cwd) VALUES (?, ?, ?)",
                (sid, title, "/tmp/project"),
            )
            sids.append(sid)
        conn.commit()
        conn.close()

        adapter = CodexAdapter(pd)
        adapter._sqlite_path = sqlite_path
        return adapter, sids

    def test_codex_list_projects_reads_title(self):
        with TemporaryDirectory() as tmp:
            adapter, sids = self._make_codex_env(tmp)
            projects = adapter.list_projects()
            self.assertTrue(len(projects) > 0)
            sess = projects[0]["sessions"][0]
            self.assertEqual(sess["title"], "Original Title")
            self.assertEqual(sess["displayName"], "Original Title")
            self.assertTrue(sess["canRenameSession"])

    def test_codex_load_session_reads_title(self):
        with TemporaryDirectory() as tmp:
            adapter, sids = self._make_codex_env(tmp)
            data = adapter.load_session(sids[0])
            self.assertIsNotNone(data)
            self.assertEqual(data["title"], "Original Title")
            self.assertEqual(data["displayName"], "Original Title")
            self.assertTrue(data["canRenameSession"])

    def test_codex_rename_success(self):
        with TemporaryDirectory() as tmp:
            adapter, sids = self._make_codex_env(tmp)
            result = adapter.rename_session(sids[0], "New Name")
            self.assertEqual(result["title"], "New Name")
            self.assertEqual(result["displayName"], "New Name")
            self.assertTrue(result["canRenameSession"])
            # Verify DB was updated
            conn = sqlite3.connect(str(adapter._sqlite_path))
            cur = conn.execute("SELECT title FROM threads WHERE id = ?", (sids[0],))
            row = cur.fetchone()
            conn.close()
            self.assertEqual(row[0], "New Name")

    def test_codex_rename_trims_whitespace(self):
        with TemporaryDirectory() as tmp:
            adapter, sids = self._make_codex_env(tmp)
            result = adapter.rename_session(sids[0], "  Trimmed  ")
            self.assertEqual(result["title"], "Trimmed")

    def test_codex_rename_empty_title_raises(self):
        with TemporaryDirectory() as tmp:
            adapter, sids = self._make_codex_env(tmp)
            with self.assertRaises(SessionRenameError) as ctx:
                adapter.rename_session(sids[0], "   ")
            self.assertEqual(ctx.exception.code, "invalid_title")

    def test_codex_rename_row_missing(self):
        with TemporaryDirectory() as tmp:
            adapter, sids = self._make_codex_env(tmp)
            with self.assertRaises(SessionRenameError) as ctx:
                adapter.rename_session("nonexistent-id-1234-5678-abcdefabcdef", "Name")
            self.assertEqual(ctx.exception.code, "session_not_found")

    def test_codex_rename_schema_missing(self):
        with TemporaryDirectory() as tmp:
            pd = Path(tmp) / "sessions"
            pd.mkdir(parents=True)
            sqlite_path = Path(tmp) / "state_5.sqlite"
            conn = sqlite3.connect(str(sqlite_path))
            conn.execute("CREATE TABLE other_table (id TEXT)")
            conn.commit()
            conn.close()
            adapter = CodexAdapter(pd)
            adapter._sqlite_path = sqlite_path
            with self.assertRaises(SessionRenameError) as ctx:
                adapter.rename_session("any-id", "Name")
            self.assertEqual(ctx.exception.code, "native_title_unavailable")

    def test_codex_rename_db_not_found(self):
        with TemporaryDirectory() as tmp:
            pd = Path(tmp) / "sessions"
            pd.mkdir(parents=True)
            adapter = CodexAdapter(pd)
            adapter._sqlite_path = Path(tmp) / "nonexistent.sqlite"
            with self.assertRaises(SessionRenameError) as ctx:
                adapter.rename_session("any-id", "Name")
            self.assertEqual(ctx.exception.code, "native_title_unavailable")

    def test_codex_rename_readonly_db(self):
        """DB exists but is not writable."""
        with TemporaryDirectory() as tmp:
            pd = Path(tmp) / "sessions"
            pd.mkdir(parents=True)
            sqlite_path = Path(tmp) / "state_5.sqlite"
            conn = sqlite3.connect(str(sqlite_path))
            conn.execute(
                "CREATE TABLE threads (id TEXT PRIMARY KEY, title TEXT, cwd TEXT, "
                "model TEXT, model_provider TEXT, updated_at TEXT, tokens_used INT, "
                "created_at TEXT, rollout_path TEXT)"
            )
            conn.execute("INSERT INTO threads (id, title) VALUES (?, ?)", ("test-id", "Old"))
            conn.commit()
            conn.close()
            sqlite_path.chmod(0o444)
            try:
                adapter = CodexAdapter(pd)
                adapter._sqlite_path = sqlite_path
                with self.assertRaises(SessionRenameError) as ctx:
                    adapter.rename_session("test-id", "New")
                self.assertIn(ctx.exception.code, ("native_title_write_failed",))
            finally:
                sqlite_path.chmod(0o644)

    def test_codex_rename_cache_refresh(self):
        """After rename, list_projects returns new title."""
        with TemporaryDirectory() as tmp:
            adapter, sids = self._make_codex_env(tmp)
            # Prime the cache
            adapter.list_projects()
            self.assertIsNotNone(adapter._sqlite_cache)
            # Rename
            adapter.rename_session(sids[0], "Updated Title")
            # Cache should be invalidated
            self.assertIsNone(adapter._sqlite_cache)
            # Subsequent list should show new title
            projects = adapter.list_projects()
            sess = projects[0]["sessions"][0]
            self.assertEqual(sess["title"], "Updated Title")


# ---------------------------------------------------------------------------
# 6.3 OpenCode SQLite rename tests
# ---------------------------------------------------------------------------


class TestOpenCodeRename(unittest.TestCase):
    """OpenCode SQLite title read/write tests."""

    def _make_opencode_env(self, tmp: str, sessions: list[tuple[str, str]] | None = None):
        """Create a minimal OpenCode DB environment."""
        pd = Path(tmp)
        db_path = pd / "opencode.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE session (id TEXT PRIMARY KEY, title TEXT, directory TEXT, "
            "agent TEXT, model TEXT, time_created REAL, time_updated REAL, "
            "tokens_input INT, tokens_output INT, tokens_reasoning INT, "
            "tokens_cache_read INT, tokens_cache_write INT, cost REAL, project_id TEXT)"
        )
        conn.execute(
            "CREATE TABLE project (id TEXT PRIMARY KEY, name TEXT, worktree TEXT)"
        )
        conn.execute(
            "CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, role TEXT, "
            "time_created REAL)"
        )
        conn.execute(
            "CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, data TEXT, "
            "time_created REAL)"
        )
        conn.execute(
            "CREATE TABLE session_message (session_id TEXT, message_id TEXT)"
        )
        sids = []
        for sid, title in (sessions or [("oc-session-001", "OpenCode Title")]):
            conn.execute(
                "INSERT INTO session (id, title, directory, agent, time_created) VALUES (?, ?, ?, ?, ?)",
                (sid, title, "/tmp/project", "opencode", 1700000000),
            )
            sids.append(sid)
        conn.commit()
        conn.close()

        adapter = OpenCodeAdapter(pd)
        return adapter, sids

    def test_opencode_list_projects_reads_title(self):
        with TemporaryDirectory() as tmp:
            adapter, sids = self._make_opencode_env(tmp)
            projects = adapter.list_projects()
            self.assertTrue(len(projects) > 0)
            sess = projects[0]["sessions"][0]
            self.assertEqual(sess["title"], "OpenCode Title")
            self.assertEqual(sess["displayName"], "OpenCode Title")
            self.assertTrue(sess["canRenameSession"])

    def test_opencode_rename_success(self):
        with TemporaryDirectory() as tmp:
            adapter, sids = self._make_opencode_env(tmp)
            result = adapter.rename_session(sids[0], "New OC Name")
            self.assertEqual(result["title"], "New OC Name")
            self.assertEqual(result["displayName"], "New OC Name")
            self.assertTrue(result["canRenameSession"])
            # Verify DB updated
            db_path = Path(tmp) / "opencode.db"
            conn = sqlite3.connect(str(db_path))
            cur = conn.execute("SELECT title FROM session WHERE id = ?", (sids[0],))
            row = cur.fetchone()
            conn.close()
            self.assertEqual(row[0], "New OC Name")

    def test_opencode_rename_trims_whitespace(self):
        with TemporaryDirectory() as tmp:
            adapter, sids = self._make_opencode_env(tmp)
            result = adapter.rename_session(sids[0], "  Spaced  ")
            self.assertEqual(result["title"], "Spaced")

    def test_opencode_rename_empty_title_raises(self):
        with TemporaryDirectory() as tmp:
            adapter, sids = self._make_opencode_env(tmp)
            with self.assertRaises(SessionRenameError) as ctx:
                adapter.rename_session(sids[0], "")
            self.assertEqual(ctx.exception.code, "invalid_title")

    def test_opencode_rename_row_missing(self):
        with TemporaryDirectory() as tmp:
            adapter, sids = self._make_opencode_env(tmp)
            with self.assertRaises(SessionRenameError) as ctx:
                adapter.rename_session("nonexistent-session-id", "Name")
            self.assertEqual(ctx.exception.code, "session_not_found")

    def test_opencode_rename_schema_missing(self):
        with TemporaryDirectory() as tmp:
            pd = Path(tmp)
            db_path = pd / "opencode.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE other (id TEXT)")
            conn.commit()
            conn.close()
            adapter = OpenCodeAdapter(pd)
            with self.assertRaises(SessionRenameError) as ctx:
                adapter.rename_session("any-id", "Name")
            self.assertEqual(ctx.exception.code, "native_title_unavailable")

    def test_opencode_rename_db_not_found(self):
        with TemporaryDirectory() as tmp:
            pd = Path(tmp) / "subdir"
            pd.mkdir()
            adapter = OpenCodeAdapter(pd)
            with self.assertRaises(SessionRenameError) as ctx:
                adapter.rename_session("any-id", "Name")
            self.assertEqual(ctx.exception.code, "native_title_unavailable")

    def test_opencode_rename_does_not_modify_messages(self):
        """Rename must not touch message/part tables."""
        with TemporaryDirectory() as tmp:
            adapter, sids = self._make_opencode_env(tmp)
            db_path = Path(tmp) / "opencode.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute("INSERT INTO message (id, session_id, role) VALUES (?, ?, ?)",
                         ("msg1", sids[0], "user"))
            conn.execute("INSERT INTO part (id, message_id, data) VALUES (?, ?, ?)",
                         ("part1", "msg1", '{"text": "hello"}'))
            conn.commit()
            conn.close()
            adapter.rename_session(sids[0], "Renamed")
            # Verify messages unchanged
            conn = sqlite3.connect(str(db_path))
            cur = conn.execute("SELECT data FROM part WHERE id = 'part1'")
            row = cur.fetchone()
            conn.close()
            self.assertEqual(row[0], '{"text": "hello"}')


# ---------------------------------------------------------------------------
# 6.4 Viewer server API tests
# ---------------------------------------------------------------------------


class TestViewerRenameAPI(unittest.TestCase):
    """Test POST /api/session/<sessionId>/rename endpoint."""

    def _make_server(self, adapter):
        from fastapi.testclient import TestClient
        from viewer.server import create_app
        return TestClient(create_app(
            projects_dir=Path("/tmp"),
            logs_dir=Path("/tmp"),
            adapter=adapter,
        ))

    def _request(self, server, method, path, body=None):
        response = server.request(method, path, json=body)
        return response.status_code, response.json()

    def test_rename_codex_success(self):
        with TemporaryDirectory() as tmp:
            # Setup codex adapter with DB
            pd = Path(tmp) / "sessions"
            session_dir = pd / "2025" / "06" / "03"
            session_dir.mkdir(parents=True)
            sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            fname = f"rollout-2025-06-03T10-00-00-{sid}.jsonl"
            (session_dir / fname).write_text(json.dumps({
                "type": "response_item",
                "timestamp": "2025-06-01T10:00:01Z",
                "payload": {"type": "message", "role": "user",
                            "content": [{"type": "input_text", "text": "hi"}]},
            }) + "\n")
            sqlite_path = Path(tmp) / "state_5.sqlite"
            conn = sqlite3.connect(str(sqlite_path))
            conn.execute(
                "CREATE TABLE threads (id TEXT PRIMARY KEY, title TEXT, cwd TEXT, "
                "model TEXT, model_provider TEXT, updated_at TEXT, tokens_used INT, "
                "created_at TEXT, rollout_path TEXT)"
            )
            conn.execute("INSERT INTO threads (id, title, cwd) VALUES (?, ?, ?)",
                         (sid, "Old", "/tmp"))
            conn.commit()
            conn.close()

            adapter = CodexAdapter(pd)
            adapter._sqlite_path = sqlite_path
            server = self._make_server(adapter)
            status, result = self._request(server, "POST",
                                           f"/api/session/{sid}/rename",
                                           {"title": "New Name"})
            self.assertEqual(status, 200)
            self.assertTrue(result["ok"])
            self.assertEqual(result["agent"], "codex")
            self.assertEqual(result["sessionId"], sid)
            self.assertEqual(result["title"], "New Name")
            self.assertEqual(result["displayName"], "New Name")
            self.assertTrue(result["canRenameSession"])

    def test_rename_invalid_title_empty(self):
        with TemporaryDirectory() as tmp:
            pd = Path(tmp) / "sessions"
            pd.mkdir(parents=True)
            adapter = CodexAdapter(pd)
            server = self._make_server(adapter)
            status, result = self._request(server, "POST",
                                           "/api/session/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/rename",
                                           {"title": "   "})
            self.assertEqual(status, 400)
            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "invalid_title")

    def test_rename_session_not_found(self):
        with TemporaryDirectory() as tmp:
            pd = Path(tmp) / "sessions"
            session_dir = pd / "2025" / "06" / "03"
            session_dir.mkdir(parents=True)
            sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            fname = f"rollout-2025-06-03T10-00-00-{sid}.jsonl"
            (session_dir / fname).write_text(json.dumps({
                "type": "response_item", "timestamp": "2025-06-01T10:00:01Z",
                "payload": {"type": "message", "role": "user",
                            "content": [{"type": "input_text", "text": "hi"}]},
            }) + "\n")
            sqlite_path = Path(tmp) / "state_5.sqlite"
            conn = sqlite3.connect(str(sqlite_path))
            conn.execute(
                "CREATE TABLE threads (id TEXT PRIMARY KEY, title TEXT, cwd TEXT, "
                "model TEXT, model_provider TEXT, updated_at TEXT, tokens_used INT, "
                "created_at TEXT, rollout_path TEXT)"
            )
            # Note: no row inserted for the session
            conn.commit()
            conn.close()
            adapter = CodexAdapter(pd)
            adapter._sqlite_path = sqlite_path
            server = self._make_server(adapter)
            status, result = self._request(server, "POST",
                                           f"/api/session/{sid}/rename",
                                           {"title": "Name"})
            self.assertEqual(status, 404)
            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "session_not_found")

    def test_rename_claude_unsupported(self):
        with TemporaryDirectory() as tmp:
            pd = Path(tmp)
            proj = pd / "my-project"
            proj.mkdir()
            sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            (proj / f"{sid}.jsonl").write_text(
                json.dumps({"type": "user", "content": "hi", "timestamp": "2025-01-01T00:00:00Z"}) + "\n"
            )
            adapter = ClaudeAdapter(pd)
            server = self._make_server(adapter)
            status, result = self._request(server, "POST",
                                           f"/api/session/{sid}/rename",
                                           {"title": "Name"})
            self.assertEqual(status, 501)
            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "rename_not_supported")

    def test_rename_opencode_schema_missing_returns_500(self):
        """API returns 500 native_title_unavailable when session table lacks title column."""
        with TemporaryDirectory() as tmp:
            pd = Path(tmp)
            db_path = pd / "opencode.db"
            conn = sqlite3.connect(str(db_path))
            # Session table WITHOUT title column
            conn.execute(
                "CREATE TABLE session (id TEXT PRIMARY KEY, directory TEXT, "
                "agent TEXT, model TEXT, time_created REAL)"
            )
            conn.execute(
                "CREATE TABLE project (id TEXT PRIMARY KEY, name TEXT, worktree TEXT)"
            )
            sid = "oc-schema-miss-0001-0000-000000000001"
            conn.execute(
                "INSERT INTO session (id, directory, agent, time_created) VALUES (?, ?, ?, ?)",
                (sid, "/tmp/proj", "opencode", 1700000000),
            )
            conn.commit()
            conn.close()
            adapter = OpenCodeAdapter(pd)
            server = self._make_server(adapter)
            status, result = self._request(server, "POST",
                                           f"/api/session/{sid}/rename",
                                           {"title": "New Name"})
            self.assertEqual(status, 500)
            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "native_title_unavailable")

    def test_rename_codex_schema_missing_returns_500(self):
        """API returns 500 native_title_unavailable when threads table lacks title column."""
        with TemporaryDirectory() as tmp:
            pd = Path(tmp) / "sessions"
            pd.mkdir(parents=True)
            sqlite_path = Path(tmp) / "state_5.sqlite"
            conn = sqlite3.connect(str(sqlite_path))
            # threads table WITHOUT title column
            conn.execute(
                "CREATE TABLE threads (id TEXT PRIMARY KEY, cwd TEXT)"
            )
            sid = "cx-schema-miss-0001-0000-000000000001"
            conn.execute("INSERT INTO threads (id, cwd) VALUES (?, ?)", (sid, "/tmp"))
            conn.commit()
            conn.close()
            adapter = CodexAdapter(pd)
            adapter._sqlite_path = sqlite_path
            server = self._make_server(adapter)
            status, result = self._request(server, "POST",
                                           f"/api/session/{sid}/rename",
                                           {"title": "New Name"})
            self.assertEqual(status, 500)
            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "native_title_unavailable")

    def test_rename_opencode_write_failed_returns_500(self):
        """API returns 500 native_title_write_failed on SQLite write failure."""
        with TemporaryDirectory() as tmp:
            pd = Path(tmp)
            db_path = pd / "opencode.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "CREATE TABLE session (id TEXT PRIMARY KEY, title TEXT, directory TEXT, "
                "agent TEXT, model TEXT, time_created REAL, time_updated REAL, "
                "tokens_input INT, tokens_output INT, tokens_reasoning INT, "
                "tokens_cache_read INT, tokens_cache_write INT, cost REAL, project_id TEXT)"
            )
            sid = "oc-write-fail-0001-0000-000000000001"
            conn.execute(
                "INSERT INTO session (id, title, directory, agent, time_created) VALUES (?, ?, ?, ?, ?)",
                (sid, "Old", "/tmp/proj", "opencode", 1700000000),
            )
            conn.commit()
            conn.close()
            adapter = OpenCodeAdapter(pd)
            server = self._make_server(adapter)
            # Patch rename_session to raise native_title_write_failed
            def _raise_write_failed(session_id, title):
                raise SessionRenameError("native_title_write_failed", "disk full")
            adapter.rename_session = _raise_write_failed
            status, result = self._request(server, "POST",
                                           f"/api/session/{sid}/rename",
                                           {"title": "New Name"})
            self.assertEqual(status, 500)
            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "native_title_write_failed")

    def test_rename_codex_readonly_returns_500_via_api(self):
        """API returns 500 when Codex DB is read-only."""
        with TemporaryDirectory() as tmp:
            pd = Path(tmp) / "sessions"
            pd.mkdir(parents=True)
            sqlite_path = Path(tmp) / "state_5.sqlite"
            conn = sqlite3.connect(str(sqlite_path))
            conn.execute(
                "CREATE TABLE threads (id TEXT PRIMARY KEY, title TEXT, cwd TEXT)"
            )
            sid = "cx-readonly-db-0001-0000-000000000001"
            conn.execute("INSERT INTO threads (id, title, cwd) VALUES (?, ?, ?)",
                         (sid, "Old", "/tmp"))
            conn.commit()
            conn.close()
            sqlite_path.chmod(0o444)
            try:
                adapter = CodexAdapter(pd)
                adapter._sqlite_path = sqlite_path
                server = self._make_server(adapter)
                status, result = self._request(server, "POST",
                                               f"/api/session/{sid}/rename",
                                               {"title": "New Name"})
                self.assertEqual(status, 500)
                self.assertFalse(result["ok"])
                self.assertEqual(result["code"], "native_title_write_failed")
            finally:
                sqlite_path.chmod(0o644)


# ---------------------------------------------------------------------------
# 6.4b Adapter 500-class error tests (schema missing, write failures)
# ---------------------------------------------------------------------------


class TestAdapterErrorCodes(unittest.TestCase):
    """Adapter-level tests for native_title_unavailable and write_failed codes."""

    def test_opencode_title_column_missing_raises_unavailable(self):
        """Session exists but title column missing → native_title_unavailable, not session_not_found."""
        with TemporaryDirectory() as tmp:
            pd = Path(tmp)
            db_path = pd / "opencode.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "CREATE TABLE session (id TEXT PRIMARY KEY, directory TEXT, agent TEXT)"
            )
            conn.execute(
                "INSERT INTO session (id, directory, agent) VALUES (?, ?, ?)",
                ("existing-session-id-123456789012", "/tmp/proj", "opencode"),
            )
            conn.commit()
            conn.close()
            adapter = OpenCodeAdapter(pd)
            with self.assertRaises(SessionRenameError) as ctx:
                adapter.rename_session("existing-session-id-123456789012", "New Title")
            self.assertEqual(ctx.exception.code, "native_title_unavailable")
            self.assertIn("title", ctx.exception.message.lower())

    def test_codex_title_column_missing_raises_unavailable(self):
        """Thread exists but title column missing → native_title_unavailable."""
        with TemporaryDirectory() as tmp:
            pd = Path(tmp) / "sessions"
            pd.mkdir(parents=True)
            sqlite_path = Path(tmp) / "state_5.sqlite"
            conn = sqlite3.connect(str(sqlite_path))
            conn.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, cwd TEXT)")
            conn.execute("INSERT INTO threads (id, cwd) VALUES (?, ?)",
                         ("existing-thread-id-123456789012", "/tmp"))
            conn.commit()
            conn.close()
            adapter = CodexAdapter(pd)
            adapter._sqlite_path = sqlite_path
            with self.assertRaises(SessionRenameError) as ctx:
                adapter.rename_session("existing-thread-id-123456789012", "New Title")
            self.assertEqual(ctx.exception.code, "native_title_unavailable")

    def test_opencode_readonly_db_raises_write_failed(self):
        """OpenCode DB is read-only → native_title_write_failed."""
        with TemporaryDirectory() as tmp:
            pd = Path(tmp)
            db_path = pd / "opencode.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "CREATE TABLE session (id TEXT PRIMARY KEY, title TEXT, directory TEXT, "
                "agent TEXT, time_created REAL)"
            )
            conn.execute(
                "INSERT INTO session (id, title, directory, agent, time_created) VALUES (?, ?, ?, ?, ?)",
                ("oc-ro-sess-000000000000000000001", "Old", "/tmp", "opencode", 1700000000),
            )
            conn.commit()
            conn.close()
            db_path.chmod(0o444)
            try:
                adapter = OpenCodeAdapter(pd)
                with self.assertRaises(SessionRenameError) as ctx:
                    adapter.rename_session("oc-ro-sess-000000000000000000001", "New")
                self.assertEqual(ctx.exception.code, "native_title_write_failed")
            finally:
                db_path.chmod(0o644)

    def test_opencode_session_table_missing_raises_unavailable(self):
        """DB exists but session table doesn't → native_title_unavailable."""
        with TemporaryDirectory() as tmp:
            pd = Path(tmp)
            db_path = pd / "opencode.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE something_else (id TEXT)")
            conn.commit()
            conn.close()
            adapter = OpenCodeAdapter(pd)
            with self.assertRaises(SessionRenameError) as ctx:
                adapter.rename_session("any-session-id-0000000000001", "Title")
            self.assertEqual(ctx.exception.code, "native_title_unavailable")
            self.assertIn("session", ctx.exception.message.lower())

    def test_codex_threads_table_missing_raises_unavailable(self):
        """DB exists but threads table doesn't → native_title_unavailable."""
        with TemporaryDirectory() as tmp:
            pd = Path(tmp) / "sessions"
            pd.mkdir(parents=True)
            sqlite_path = Path(tmp) / "state_5.sqlite"
            conn = sqlite3.connect(str(sqlite_path))
            conn.execute("CREATE TABLE something_else (id TEXT)")
            conn.commit()
            conn.close()
            adapter = CodexAdapter(pd)
            adapter._sqlite_path = sqlite_path
            with self.assertRaises(SessionRenameError) as ctx:
                adapter.rename_session("any-id-000000000000000000001", "Title")
            self.assertEqual(ctx.exception.code, "native_title_unavailable")
            self.assertIn("threads", ctx.exception.message.lower())


# ---------------------------------------------------------------------------
# 6.5 Frontend static / DOM smoke tests
# ---------------------------------------------------------------------------


_HTML = (Path(__file__).resolve().parents[1] / "viewer" / "claude-log.html").read_text(encoding="utf-8")


class TestRenameFrontendElements(unittest.TestCase):
    """Frontend smoke tests for rename UI elements."""

    def test_session_title_bar_exists(self):
        self.assertIn('id="sessionTitleBar"', _HTML)

    def test_session_display_name_element(self):
        self.assertIn('id="sessionDisplayName"', _HTML)

    def test_session_id_label_element(self):
        self.assertIn('id="sessionIdLabel"', _HTML)

    def test_rename_button_exists(self):
        self.assertIn('id="sessionRenameBtn"', _HTML)
        self.assertIn('onclick="startSessionRename()"', _HTML)

    def test_rename_unsupported_label(self):
        self.assertIn('id="sessionRenameUnsupported"', _HTML)
        self.assertIn('不支持重命名', _HTML)

    def test_rename_form_elements(self):
        self.assertIn('id="sessionRenameForm"', _HTML)
        self.assertIn('id="sessionRenameInput"', _HTML)
        self.assertIn('id="sessionRenameSaveBtn"', _HTML)
        self.assertIn('id="sessionRenameCancelBtn"', _HTML)

    def test_rename_endpoint_called(self):
        self.assertIn('/api/session/', _HTML)
        self.assertIn('/rename', _HTML)

    def test_can_rename_session_controls_edit(self):
        """canRenameSession check in updateSessionTitleBar."""
        self.assertIn('canRenameSession', _HTML)
        self.assertIn("canRename", _HTML)

    def test_display_name_in_selector(self):
        """fmtSessionLabel uses displayName."""
        self.assertIn('s.displayName', _HTML)

    def test_save_success_updates_state(self):
        """After rename success, allProjects and selector are updated."""
        self.assertIn('sess.title = result.title', _HTML)
        self.assertIn('sess.displayName = result.displayName', _HTML)

    def test_save_failure_shows_error(self):
        """On failure, error is displayed."""
        self.assertIn('保存失败', _HTML)

    def test_session_id_not_visible_in_title_bar(self):
        """Title bar must NOT display raw session id in sessionIdLabel."""
        fn_start = _HTML.index("function updateSessionTitleBar(")
        fn_end = _HTML.index("function startSessionRename()", fn_start)
        snippet = _HTML[fn_start:fn_end]
        # Must NOT assign data.sessionId to the label element
        self.assertNotIn("idEl.textContent = data.sessionId", snippet)

    def test_cancel_does_not_call_api(self):
        """cancelSessionRename hides form without fetch."""
        # The cancel function only changes display, no fetch call
        fn_start = _HTML.index("function cancelSessionRename()")
        fn_end = _HTML.index("async function saveSessionRename()", fn_start)
        snippet = _HTML[fn_start:fn_end]
        self.assertNotIn("fetch(", snippet)

    def test_stale_session_guard_in_success_path(self):
        """saveSessionRename checks current session before updating UI on success."""
        fn_start = _HTML.index("async function saveSessionRename()")
        fn_end = _HTML.index("function onProjectChange", fn_start)
        snippet = _HTML[fn_start:fn_end]
        # Must have stale check after fetch (currentSession !== sessionId)
        self.assertIn("currentSession !== sessionId", snippet)

    def test_stale_session_guard_in_error_path(self):
        """saveSessionRename checks current session in HTTP error, catch, AND finally paths."""
        fn_start = _HTML.index("async function saveSessionRename()")
        fn_end = _HTML.index("function onProjectChange", fn_start)
        snippet = _HTML[fn_start:fn_end]
        # Must appear at least 3 times: HTTP error, catch, and finally
        # Use currentSession !== sessionId OR currentSession === sessionId
        import re
        guards = re.findall(r"currentSession\s*[!=]==\s*sessionId", snippet)
        # HTTP error guard + success guard + catch guard + finally guard = at least 4
        self.assertGreaterEqual(len(guards), 4,
            f"Expected ≥4 session guards (error, success, catch, finally), found {len(guards)}")

    def test_stale_guard_still_updates_allprojects_cache(self):
        """Even on stale session, allProjects cache is updated before guard check."""
        fn_start = _HTML.index("async function saveSessionRename()")
        fn_end = _HTML.index("function onProjectChange", fn_start)
        snippet = _HTML[fn_start:fn_end]
        # allProjects update must come before the stale guard in success path
        cache_pos = snippet.index("sess.title = result.title")
        stale_pos = snippet.index("currentSession !== sessionId", snippet.index("sess.title"))
        self.assertLess(cache_pos, stale_pos)

    def test_finally_block_guards_saveBtn_disabled(self):
        """finally block must NOT unconditionally set saveBtn.disabled = false.

        Behavioral proof: if session A's response arrives while session B is active
        and saving, it must not re-enable B's save button. This test verifies that
        the finally block contains a session equality check that gates the
        saveBtn.disabled assignment.
        """
        fn_start = _HTML.index("async function saveSessionRename()")
        fn_end = _HTML.index("function onProjectChange", fn_start)
        snippet = _HTML[fn_start:fn_end]

        # Locate the finally block
        finally_pos = snippet.index("} finally {")
        # Find the closing brace of the finally block (next "}" after the content)
        finally_body_start = finally_pos + len("} finally {")
        # Extract finally block body (until the function closes)
        brace_depth = 1
        pos = finally_body_start
        while pos < len(snippet) and brace_depth > 0:
            if snippet[pos] == '{':
                brace_depth += 1
            elif snippet[pos] == '}':
                brace_depth -= 1
            pos += 1
        finally_body = snippet[finally_body_start:pos]

        # 1. saveBtn.disabled = false must exist inside finally
        self.assertIn("saveBtn.disabled = false", finally_body,
            "finally block must contain saveBtn.disabled = false")

        # 2. There must be a session guard BEFORE the saveBtn assignment
        guard_pos = finally_body.index("currentSession === sessionId")
        btn_pos = finally_body.index("saveBtn.disabled = false")
        self.assertLess(guard_pos, btn_pos,
            "Session guard must come BEFORE saveBtn.disabled = false in finally")

        # 3. saveBtn.disabled = false must be INSIDE a conditional (indented after if)
        # Verify the assignment is inside an if-block, not at the top level of finally
        lines_before_btn = finally_body[:btn_pos].split('\n')
        # The line containing the guard should open a block
        guard_line = [l for l in lines_before_btn if "currentSession === sessionId" in l]
        self.assertTrue(len(guard_line) > 0)
        # Guard line must contain an if and opening brace
        self.assertIn("if", guard_line[0])

    def test_finally_does_not_unconditionally_modify_state(self):
        """No unconditional state mutation in finally — all mutations are guarded.

        This test extracts the finally block and verifies that every line that
        assigns to a DOM property or variable is inside a conditional block,
        not at the top level of finally.
        """
        fn_start = _HTML.index("async function saveSessionRename()")
        fn_end = _HTML.index("function onProjectChange", fn_start)
        snippet = _HTML[fn_start:fn_end]

        finally_pos = snippet.index("} finally {")
        finally_body_start = finally_pos + len("} finally {")
        brace_depth = 1
        pos = finally_body_start
        while pos < len(snippet) and brace_depth > 0:
            if snippet[pos] == '{':
                brace_depth += 1
            elif snippet[pos] == '}':
                brace_depth -= 1
            pos += 1
        finally_body = snippet[finally_body_start:pos]

        # Parse lines at brace depth 0 (top-level of finally) — these are unconditional
        import re
        depth = 0
        top_level_lines = []
        # Match actual assignments: x = y, x.prop = y — but not === or !==
        assign_re = re.compile(r'(?<![!=<>])=(?!=)')
        for line in finally_body.strip().split('\n'):
            stripped = line.strip()
            if not stripped or stripped == '}':
                if '{' not in stripped:
                    depth = max(0, depth - stripped.count('}'))
                continue
            if depth == 0 and assign_re.search(stripped) and not stripped.startswith('//'):
                # An assignment at top level — this is unconditional
                # But skip lines that are the guard declaration itself (const currentSession = ...)
                if 'const currentSession' not in stripped and 'let ' not in stripped:
                    top_level_lines.append(stripped)
            if '{' in stripped:
                depth += stripped.count('{') - stripped.count('}')
            elif '}' in stripped:
                depth -= stripped.count('}')

        self.assertEqual(top_level_lines, [],
            f"Found unconditional assignments in finally block: {top_level_lines}")

    def test_success_path_early_return_prevents_btn_restore(self):
        """On stale success, the 'return' before UI updates also skips finally btn restore.

        Verify: when stale guard triggers 'return' in success path, the finally
        guard will also block btn restoration since session still mismatches.
        """
        fn_start = _HTML.index("async function saveSessionRename()")
        fn_end = _HTML.index("function onProjectChange", fn_start)
        snippet = _HTML[fn_start:fn_end]

        # The success path has: if (currentSession !== sessionId) return;
        # After this return, finally still runs. Verify finally also checks.
        success_guard = snippet.index("currentSession !== sessionId",
                                      snippet.index("sess.title = result.title"))
        finally_guard = snippet.index("currentSession === sessionId",
                                      snippet.index("} finally {"))
        # finally guard must exist after the success guard
        self.assertGreater(finally_guard, success_guard)


# ---------------------------------------------------------------------------
# 6.5b Behavioral tests: session id hidden from default visible UI
# ---------------------------------------------------------------------------

_NODE = shutil.which("node")


def _extract_fn(html: str, fn_signature: str, end_marker: str) -> str:
    """Extract a JS function body from HTML by signature and end marker."""
    start = html.index(fn_signature)
    end = html.index(end_marker, start)
    return html[start:end]


@unittest.skipUnless(_NODE, "node not available")
class TestSessionLabelBehavior(unittest.TestCase):
    """Behavioral tests: execute fmtSessionLabel via Node.js to verify real output."""

    @classmethod
    def setUpClass(cls):
        cls._fmt_ts_code = _extract_fn(_HTML, "function fmtTs(", "function trunc(")
        cls._fn_code = _extract_fn(_HTML, "function fmtSessionLabel(", "\n\n// ── Session rename UI")
        cls._js_prefix = cls._fmt_ts_code + "\n"

    def _run_label(self, session_obj: dict) -> str:
        """Run fmtSessionLabel with a session object and return the label string."""
        js = self._js_prefix + self._fn_code + f"\nconsole.log(fmtSessionLabel({json.dumps(session_obj)}));"
        result = subprocess.run([_NODE, "-e", js], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            self.fail(f"Node.js failed: {result.stderr}")
        return result.stdout.strip()

    def test_selector_shows_displayname_not_short_id(self):
        """Selector label uses displayName, never appends [shortId]."""
        sid = "019ec10a-1234-5678-abcd-ef1234567890"
        label = self._run_label({
            "id": sid, "displayName": "My Great Session",
            "firstTimestamp": None, "lastTimestamp": None,
        })
        self.assertIn("My Great Session", label)
        self.assertNotIn("[019ec10a]", label)
        self.assertNotIn(sid[:8], label.replace("My Great Session", ""))

    def test_selector_no_short_id_with_times(self):
        """Even with timestamps, no [shortId] bracket appears."""
        sid = "019ec10a-1234-5678-abcd-ef1234567890"
        label = self._run_label({
            "id": sid, "displayName": "Debug Task",
            "firstTimestamp": "2025-06-01T10:00:00",
            "lastTimestamp": "2025-06-01T11:00:00",
        })
        self.assertIn("Debug Task", label)
        self.assertNotIn("[", label)  # No brackets at all

    def test_same_name_different_times_distinguishable(self):
        """Two sessions with same displayName but different times produce different labels."""
        sid1 = "aaaaaaaa-1111-2222-3333-444444444444"
        sid2 = "bbbbbbbb-9999-8888-7777-666666666666"
        label1 = self._run_label({
            "id": sid1, "displayName": "Same Title",
            "firstTimestamp": "2025-06-01T10:00:00", "lastTimestamp": "2025-06-01T11:00:00",
        })
        label2 = self._run_label({
            "id": sid2, "displayName": "Same Title",
            "firstTimestamp": "2025-06-02T14:00:00", "lastTimestamp": "2025-06-02T15:00:00",
        })
        self.assertNotEqual(label1, label2)
        # Distinguishing info must NOT be the session id
        self.assertNotIn(sid1[:8], label1.replace("Same Title", ""))
        self.assertNotIn(sid2[:8], label2.replace("Same Title", ""))

    def test_long_title_truncated(self):
        """Long displayName is truncated in the selector label."""
        long_name = "A" * 100
        label = self._run_label({
            "id": "019ec10a-1234-5678-abcd-ef1234567890",
            "displayName": long_name,
            "firstTimestamp": None, "lastTimestamp": None,
        })
        self.assertIn("…", label)
        self.assertLess(len(label), len(long_name))

    def test_missing_displayname_uses_non_id_fallback(self):
        """Missing displayName must not expose raw or short session id in visible label."""
        sid = "019ec10a-1234-5678-abcd-ef1234567890"
        label = self._run_label({"id": sid})
        self.assertEqual(label, "Untitled session")
        self.assertNotIn(sid, label)
        self.assertNotIn(sid[:8], label)

    def test_id_like_displayname_uses_non_id_fallback(self):
        """Adapter-provided id fallback must not become default visible UI text."""
        sid = "019ec10a-1234-5678-abcd-ef1234567890"
        raw_label = self._run_label({"id": sid, "displayName": sid})
        short_label = self._run_label({"id": sid, "displayName": sid[:8]})
        self.assertEqual(raw_label, "Untitled session")
        self.assertEqual(short_label, "Untitled session")


class TestTitleBarNoSessionId(unittest.TestCase):
    """Structural-behavioral tests: title bar must not expose raw session id."""

    def test_title_bar_uses_time_not_id(self):
        """updateSessionTitleBar computes time info for sessionIdLabel, not data.sessionId."""
        snippet = _extract_fn(_HTML, "function updateSessionTitleBar(", "function startSessionRename()")
        # Must NOT directly show session id
        self.assertNotIn("idEl.textContent = data.sessionId", snippet)
        # Must compute time-based info
        self.assertIn("_meta", snippet)
        self.assertIn("fmtTs", snippet)

    def test_fmt_session_label_no_id_slice(self):
        """fmtSessionLabel must not slice session id for bracket display."""
        snippet = _extract_fn(_HTML, "function fmtSessionLabel(", "\n\n// ── Session rename UI")
        # The old code had: const prefix = id.slice(0, 8); ... [${prefix}]
        self.assertNotIn("[${prefix}]", snippet)

    def test_rename_api_still_uses_session_id(self):
        """rename fetch URL must still use sessionId, not displayName."""
        snippet = _extract_fn(_HTML, "async function saveSessionRename()", "function onProjectChange")
        self.assertIn("${apiBase()}/api/session/${encodeURIComponent(sessionId)}/rename", snippet)
        # Must NOT use displayName in the URL
        self.assertNotIn("${displayName}", snippet)
        self.assertNotIn("/api/session/${encodeURIComponent(displayName", snippet)

    def test_allprojects_lookup_uses_session_id(self):
        """After rename, allProjects cache update must look up by session id."""
        snippet = _extract_fn(_HTML, "async function saveSessionRename()", "function onProjectChange")
        self.assertIn("=== sessionId", snippet)
        # Look up in allProjects by id, not by displayName
        self.assertIn("s.id", snippet)
        self.assertNotIn("s.displayName === result", snippet)


class TestCodexTimestampPropagation(unittest.TestCase):
    """Codex adapter must propagate created_at/updated_at for non-id disambiguation."""

    def _make_codex_with_timestamps(self, tmp: str):
        pd = Path(tmp) / "sessions"
        session_dir = pd / "2025" / "06" / "03"
        session_dir.mkdir(parents=True)
        sqlite_path = Path(tmp) / "state_5.sqlite"
        conn = sqlite3.connect(str(sqlite_path))
        conn.execute(
            "CREATE TABLE threads (id TEXT PRIMARY KEY, title TEXT, cwd TEXT, "
            "model TEXT, model_provider TEXT, updated_at TEXT, tokens_used INT, "
            "created_at TEXT, rollout_path TEXT)"
        )
        sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        fname = f"rollout-2025-06-03T10-00-00-{sid}.jsonl"
        (session_dir / fname).write_text(json.dumps({
            "type": "response_item", "timestamp": "2025-06-01T10:00:01Z",
            "payload": {"type": "message", "role": "user",
                        "content": [{"type": "input_text", "text": "hi"}]},
        }) + "\n")
        conn.execute(
            "INSERT INTO threads (id, title, cwd, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (sid, "Timestamped", "/tmp/proj", "2025-06-01T10:00:00Z", "2025-06-01T11:00:00Z"),
        )
        conn.commit()
        conn.close()
        adapter = CodexAdapter(pd)
        adapter._sqlite_path = sqlite_path
        return adapter, sid

    def test_codex_list_propagates_timestamps(self):
        """list_projects session entries include firstTimestamp/lastTimestamp from SQLite."""
        with TemporaryDirectory() as tmp:
            adapter, sid = self._make_codex_with_timestamps(tmp)
            projects = adapter.list_projects()
            sess = projects[0]["sessions"][0]
            self.assertIsNotNone(sess["firstTimestamp"])
            self.assertIsNotNone(sess["lastTimestamp"])
            self.assertIn("2025-06-01", str(sess["firstTimestamp"]))

    def test_codex_no_timestamps_when_absent(self):
        """When SQLite lacks created_at/updated_at, title/displayName remain readable."""
        with TemporaryDirectory() as tmp:
            pd = Path(tmp) / "sessions"
            session_dir = pd / "2025" / "06" / "03"
            session_dir.mkdir(parents=True)
            sqlite_path = Path(tmp) / "state_5.sqlite"
            conn = sqlite3.connect(str(sqlite_path))
            conn.execute(
                "CREATE TABLE threads (id TEXT PRIMARY KEY, title TEXT, cwd TEXT)"
            )
            sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            fname = f"rollout-2025-06-03T10-00-00-{sid}.jsonl"
            (session_dir / fname).write_text(json.dumps({
                "type": "response_item", "timestamp": "2025-06-01T10:00:01Z",
                "payload": {"type": "message", "role": "user",
                            "content": [{"type": "input_text", "text": "hi"}]},
            }) + "\n")
            conn.execute("INSERT INTO threads (id, title, cwd) VALUES (?, ?, ?)",
                         (sid, "No TS", "/tmp"))
            conn.commit()
            conn.close()
            adapter = CodexAdapter(pd)
            adapter._sqlite_path = sqlite_path
            projects = adapter.list_projects()
            sess = projects[0]["sessions"][0]
            self.assertIsNone(sess["firstTimestamp"])
            self.assertIsNone(sess["lastTimestamp"])
            self.assertEqual(sess["title"], "No TS")
            self.assertEqual(sess["displayName"], "No TS")


class TestCodexOpenCodeConsistency(unittest.TestCase):
    """Codex and OpenCode must behave consistently for session display and rename."""

    def test_both_can_rename(self):
        self.assertTrue(CodexAdapter(Path("/nonexistent")).can_rename_session)
        self.assertTrue(OpenCodeAdapter(Path("/nonexistent")).can_rename_session)

    def test_both_return_title_displayname_canRename(self):
        """Both adapters return the same metadata fields in session entries."""
        required_fields = {"id", "title", "displayName", "canRenameSession",
                           "firstTimestamp", "lastTimestamp"}
        # Codex
        with TemporaryDirectory() as tmp:
            pd = Path(tmp) / "sessions"
            session_dir = pd / "2025" / "06" / "03"
            session_dir.mkdir(parents=True)
            sqlite_path = Path(tmp) / "state_5.sqlite"
            conn = sqlite3.connect(str(sqlite_path))
            conn.execute(
                "CREATE TABLE threads (id TEXT PRIMARY KEY, title TEXT, cwd TEXT, "
                "model TEXT, model_provider TEXT, updated_at TEXT, tokens_used INT, "
                "created_at TEXT, rollout_path TEXT)"
            )
            sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            fname = f"rollout-2025-06-03T10-00-00-{sid}.jsonl"
            (session_dir / fname).write_text(json.dumps({
                "type": "response_item", "timestamp": "2025-06-01T10:00:01Z",
                "payload": {"type": "message", "role": "user",
                            "content": [{"type": "input_text", "text": "hi"}]},
            }) + "\n")
            conn.execute("INSERT INTO threads (id, title, cwd) VALUES (?, ?, ?)",
                         (sid, "Codex Title", "/tmp"))
            conn.commit()
            conn.close()
            adapter = CodexAdapter(pd)
            adapter._sqlite_path = sqlite_path
            codex_sess = adapter.list_projects()[0]["sessions"][0]
            self.assertTrue(required_fields.issubset(set(codex_sess.keys())))

        # OpenCode
        with TemporaryDirectory() as tmp:
            pd = Path(tmp)
            db_path = pd / "opencode.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "CREATE TABLE session (id TEXT PRIMARY KEY, title TEXT, directory TEXT, "
                "agent TEXT, model TEXT, time_created REAL, time_updated REAL, "
                "tokens_input INT, tokens_output INT, tokens_reasoning INT, "
                "tokens_cache_read INT, tokens_cache_write INT, cost REAL, project_id TEXT)"
            )
            conn.execute(
                "CREATE TABLE project (id TEXT PRIMARY KEY, name TEXT, worktree TEXT)"
            )
            conn.execute(
                "INSERT INTO session (id, title, directory, agent, time_created) "
                "VALUES (?, ?, ?, ?, ?)",
                ("oc-session-001", "OC Title", "/tmp/proj", "opencode", 1700000000),
            )
            conn.commit()
            conn.close()
            adapter = OpenCodeAdapter(pd)
            oc_sess = adapter.list_projects()[0]["sessions"][0]
            self.assertTrue(required_fields.issubset(set(oc_sess.keys())))

    def test_both_rename_returns_same_shape(self):
        """Both adapters' rename_session return dict has the same keys."""
        expected_keys = {"title", "displayName", "canRenameSession"}
        # Codex
        with TemporaryDirectory() as tmp:
            pd = Path(tmp) / "sessions"
            session_dir = pd / "2025" / "06" / "03"
            session_dir.mkdir(parents=True)
            sqlite_path = Path(tmp) / "state_5.sqlite"
            conn = sqlite3.connect(str(sqlite_path))
            conn.execute(
                "CREATE TABLE threads (id TEXT PRIMARY KEY, title TEXT, cwd TEXT, "
                "model TEXT, model_provider TEXT, updated_at TEXT, tokens_used INT, "
                "created_at TEXT, rollout_path TEXT)"
            )
            sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            fname = f"rollout-2025-06-03T10-00-00-{sid}.jsonl"
            (session_dir / fname).write_text(json.dumps({
                "type": "response_item", "timestamp": "2025-06-01T10:00:01Z",
                "payload": {"type": "message", "role": "user",
                            "content": [{"type": "input_text", "text": "hi"}]},
            }) + "\n")
            conn.execute("INSERT INTO threads (id, title, cwd) VALUES (?, ?, ?)",
                         (sid, "Old", "/tmp"))
            conn.commit()
            conn.close()
            adapter = CodexAdapter(pd)
            adapter._sqlite_path = sqlite_path
            result = adapter.rename_session(sid, "New")
            self.assertTrue(expected_keys.issubset(set(result.keys())))

        # OpenCode
        with TemporaryDirectory() as tmp:
            pd = Path(tmp)
            db_path = pd / "opencode.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "CREATE TABLE session (id TEXT PRIMARY KEY, title TEXT, directory TEXT, "
                "agent TEXT, model TEXT, time_created REAL, time_updated REAL, "
                "tokens_input INT, tokens_output INT, tokens_reasoning INT, "
                "tokens_cache_read INT, tokens_cache_write INT, cost REAL, project_id TEXT)"
            )
            conn.execute(
                "INSERT INTO session (id, title, directory, agent, time_created) "
                "VALUES (?, ?, ?, ?, ?)",
                ("oc-session-001", "Old", "/tmp/proj", "opencode", 1700000000),
            )
            conn.commit()
            conn.close()
            adapter = OpenCodeAdapter(pd)
            result = adapter.rename_session("oc-session-001", "New")
            self.assertTrue(expected_keys.issubset(set(result.keys())))


# ---------------------------------------------------------------------------
# 6.5c Timestamp normalization tests
# ---------------------------------------------------------------------------


@unittest.skipUnless(_NODE, "node not available")
class TestFmtTsBehavior(unittest.TestCase):
    """Behavioral tests: execute the real fmtTs from HTML via Node.js."""

    @classmethod
    def setUpClass(cls):
        cls._fn_code = _extract_fn(_HTML, "function fmtTs(", "function trunc(")

    def _run_fmtts(self, ts) -> str:
        js = self._fn_code + f"\nprocess.stdout.write(fmtTs({json.dumps(ts)}));"
        result = subprocess.run([_NODE, "-e", js], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            self.fail(f"Node.js failed: {result.stderr}")
        return result.stdout

    def test_unix_seconds_number(self):
        """1700000000 (seconds) must NOT show 1970."""
        out = self._run_fmtts(1700000000)
        self.assertNotIn("1970", out)
        self.assertIn("2023", out)

    def test_unix_seconds_string(self):
        """'1700000000.0' (seconds as string) must not show 1970 or Invalid Date."""
        out = self._run_fmtts("1700000000.0")
        self.assertNotIn("1970", out)
        self.assertNotIn("Invalid Date", out)
        self.assertIn("2023", out)

    def test_unix_milliseconds_number(self):
        """1700000000000 (ms) must show correct date."""
        out = self._run_fmtts(1700000000000)
        self.assertNotIn("1970", out)
        self.assertIn("2023", out)

    def test_unix_milliseconds_string(self):
        """'1700000000000' (ms as string) must show correct date."""
        out = self._run_fmtts("1700000000000")
        self.assertNotIn("1970", out)
        self.assertIn("2023", out)

    def test_iso_string(self):
        """ISO string must parse correctly."""
        out = self._run_fmtts("2025-06-03T10:00:00Z")
        self.assertIn("2025", out)
        self.assertNotIn("Invalid Date", out)

    def test_invalid_returns_empty(self):
        """Invalid date must return empty string, not 'Invalid Date'."""
        out = self._run_fmtts("not-a-date")
        self.assertEqual(out, "")
        self.assertNotIn("Invalid Date", out)

    def test_empty_returns_empty(self):
        """Empty/null/undefined must return empty string."""
        self.assertEqual(self._run_fmtts(""), "")
        self.assertEqual(self._run_fmtts(None), "")
        self.assertEqual(self._run_fmtts(0), "")

    def test_no_invalid_date_in_selector_with_bad_ts(self):
        """fmtSessionLabel with invalid timestamp must not show 'Invalid Date'."""
        fmt_ts = _extract_fn(_HTML, "function fmtTs(", "function trunc(")
        label_fn = _extract_fn(_HTML, "function fmtSessionLabel(", "\n\n// ── Session rename UI")
        js = fmt_ts + "\n" + label_fn + (
            "\nprocess.stdout.write(fmtSessionLabel({"
            'id: "019ec10a-1234-5678-abcd-ef1234567890", '
            'displayName: "Bad TS", '
            'firstTimestamp: "not-a-date", lastTimestamp: null}));'
        )
        result = subprocess.run([_NODE, "-e", js], capture_output=True, text=True, timeout=10)
        label = result.stdout.strip()
        self.assertIn("Bad TS", label)
        self.assertNotIn("Invalid Date", label)


class TestOpenCodeTimestampNormalization(unittest.TestCase):
    """OpenCode adapter must return ISO timestamps in list and load."""

    def _make_env(self, tmp: str, time_created=1700000000, time_updated=1700003600):
        pd = Path(tmp)
        db_path = pd / "opencode.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE session (id TEXT PRIMARY KEY, title TEXT, directory TEXT, "
            "agent TEXT, model TEXT, time_created REAL, time_updated REAL, "
            "tokens_input INT, tokens_output INT, tokens_reasoning INT, "
            "tokens_cache_read INT, tokens_cache_write INT, cost REAL, project_id TEXT)"
        )
        conn.execute(
            "CREATE TABLE project (id TEXT PRIMARY KEY, name TEXT, worktree TEXT)"
        )
        conn.execute(
            "CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, role TEXT, time_created REAL)"
        )
        conn.execute(
            "CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, data TEXT, time_created REAL)"
        )
        conn.execute(
            "CREATE TABLE session_message (session_id TEXT, message_id TEXT)"
        )
        conn.execute(
            "INSERT INTO session (id, title, directory, agent, time_created, time_updated) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("oc-ts-001", "TS Test", "/tmp/proj", "opencode", time_created, time_updated),
        )
        conn.commit()
        conn.close()
        return OpenCodeAdapter(pd)

    def test_list_projects_returns_iso(self):
        with TemporaryDirectory() as tmp:
            adapter = self._make_env(tmp)
            sess = adapter.list_projects()[0]["sessions"][0]
            ts = sess["firstTimestamp"]
            self.assertIsNotNone(ts)
            self.assertIn("2023", ts)
            self.assertIn("T", ts)  # ISO format
            # Must NOT be raw epoch string
            self.assertNotEqual(ts, "1700000000.0")

    def test_list_sessions_returns_iso(self):
        with TemporaryDirectory() as tmp:
            adapter = self._make_env(tmp)
            sess = adapter.list_sessions()[0]
            ts = sess["firstTimestamp"]
            self.assertIsNotNone(ts)
            self.assertIn("2023", ts)
            self.assertIn("T", ts)

    def test_load_session_returns_iso(self):
        with TemporaryDirectory() as tmp:
            adapter = self._make_env(tmp)
            data = adapter.load_session("oc-ts-001")
            self.assertIsNotNone(data)
            ts = data["firstTimestamp"]
            self.assertIsNotNone(ts)
            self.assertIn("2023", ts)
            self.assertIn("T", ts)
            # Title bar and selector data source must be consistent
            self.assertEqual(ts, adapter.list_projects()[0]["sessions"][0]["firstTimestamp"])

    def test_load_session_includes_lastTimestamp(self):
        with TemporaryDirectory() as tmp:
            adapter = self._make_env(tmp)
            data = adapter.load_session("oc-ts-001")
            self.assertIsNotNone(data.get("lastTimestamp"))
            self.assertIn("2023", data["lastTimestamp"])

    def test_null_timestamps_return_none(self):
        with TemporaryDirectory() as tmp:
            pd = Path(tmp)
            db_path = pd / "opencode.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "CREATE TABLE session (id TEXT PRIMARY KEY, title TEXT, directory TEXT, "
                "agent TEXT, model TEXT, time_created REAL, time_updated REAL, "
                "tokens_input INT, tokens_output INT, tokens_reasoning INT, "
                "tokens_cache_read INT, tokens_cache_write INT, cost REAL, project_id TEXT)"
            )
            conn.execute(
                "CREATE TABLE project (id TEXT PRIMARY KEY, name TEXT, worktree TEXT)"
            )
            conn.execute(
                "CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, role TEXT, time_created REAL)"
            )
            conn.execute(
                "CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, data TEXT, time_created REAL)"
            )
            conn.execute(
                "CREATE TABLE session_message (session_id TEXT, message_id TEXT)"
            )
            conn.execute(
                "INSERT INTO session (id, title, directory, agent) VALUES (?, ?, ?, ?)",
                ("oc-null-ts", "Null TS", "/tmp/proj", "opencode"),
            )
            conn.commit()
            conn.close()
            adapter = OpenCodeAdapter(pd)
            sess = adapter.list_projects()[0]["sessions"][0]
            self.assertIsNone(sess["firstTimestamp"])
            self.assertIsNone(sess["lastTimestamp"])
            data = adapter.load_session("oc-null-ts")
            self.assertIsNone(data["firstTimestamp"])
            self.assertIsNone(data["lastTimestamp"])

    def test_invalid_timestamp_strings_return_none(self):
        """Invalid OpenCode timestamp strings must not be returned verbatim."""
        with TemporaryDirectory() as tmp:
            adapter = self._make_env(
                tmp,
                time_created="dirty-created",
                time_updated="not a timestamp",
            )
            sess = adapter.list_projects()[0]["sessions"][0]
            self.assertIsNone(sess["firstTimestamp"])
            self.assertIsNone(sess["lastTimestamp"])
            self.assertNotEqual(sess["firstTimestamp"], "dirty-created")
            data = adapter.load_session("oc-ts-001")
            self.assertIsNone(data["firstTimestamp"])
            self.assertIsNone(data["lastTimestamp"])


class TestCodexTimestampNormalization(unittest.TestCase):
    """Codex adapter must normalize SQLite timestamps to ISO."""

    def _make_env(self, tmp: str, created_at="2025-06-01T10:00:00Z", updated_at="2025-06-01T11:00:00Z"):
        pd = Path(tmp) / "sessions"
        session_dir = pd / "2025" / "06" / "03"
        session_dir.mkdir(parents=True)
        sqlite_path = Path(tmp) / "state_5.sqlite"
        conn = sqlite3.connect(str(sqlite_path))
        conn.execute(
            "CREATE TABLE threads (id TEXT PRIMARY KEY, title TEXT, cwd TEXT, "
            "model TEXT, model_provider TEXT, updated_at TEXT, tokens_used INT, "
            "created_at TEXT, rollout_path TEXT)"
        )
        sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        fname = f"rollout-2025-06-03T10-00-00-{sid}.jsonl"
        (session_dir / fname).write_text(json.dumps({
            "type": "response_item", "timestamp": "2025-06-01T10:00:01Z",
            "payload": {"type": "message", "role": "user",
                        "content": [{"type": "input_text", "text": "hi"}]},
        }) + "\n")
        conn.execute(
            "INSERT INTO threads (id, title, cwd, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (sid, "TS Test", "/tmp/proj", created_at, updated_at),
        )
        conn.commit()
        conn.close()
        adapter = CodexAdapter(pd)
        adapter._sqlite_path = sqlite_path
        return adapter, sid

    def test_list_projects_iso_string(self):
        """ISO strings pass through as valid timestamps."""
        with TemporaryDirectory() as tmp:
            adapter, sid = self._make_env(tmp)
            sess = adapter.list_projects()[0]["sessions"][0]
            self.assertIsNotNone(sess["firstTimestamp"])
            self.assertIn("2025", sess["firstTimestamp"])

    def test_list_projects_unix_seconds(self):
        """Unix seconds stored as TEXT are normalized to ISO."""
        with TemporaryDirectory() as tmp:
            adapter, sid = self._make_env(tmp, created_at="1717200000", updated_at="1717203600")
            sess = adapter.list_projects()[0]["sessions"][0]
            self.assertIsNotNone(sess["firstTimestamp"])
            self.assertIn("2024", sess["firstTimestamp"])
            self.assertNotIn("1970", sess["firstTimestamp"])

    def test_load_session_returns_normalized_timestamps(self):
        """load_session returns firstTimestamp/lastTimestamp consistent with list."""
        with TemporaryDirectory() as tmp:
            adapter, sid = self._make_env(tmp)
            data = adapter.load_session(sid)
            list_sess = adapter.list_projects()[0]["sessions"][0]
            self.assertIsNotNone(data["firstTimestamp"])
            self.assertEqual(data["firstTimestamp"], list_sess["firstTimestamp"])
            self.assertEqual(data["lastTimestamp"], list_sess["lastTimestamp"])

    def test_load_session_unix_seconds(self):
        """load_session normalizes Unix seconds from SQLite."""
        with TemporaryDirectory() as tmp:
            adapter, sid = self._make_env(tmp, created_at="1717200000", updated_at="1717203600")
            data = adapter.load_session(sid)
            self.assertIsNotNone(data["firstTimestamp"])
            self.assertIn("2024", data["firstTimestamp"])
            self.assertNotIn("1970", data["firstTimestamp"])

    def test_missing_timestamps_return_none(self):
        """When created_at/updated_at are absent, timestamps are None."""
        with TemporaryDirectory() as tmp:
            pd = Path(tmp) / "sessions"
            session_dir = pd / "2025" / "06" / "03"
            session_dir.mkdir(parents=True)
            sqlite_path = Path(tmp) / "state_5.sqlite"
            conn = sqlite3.connect(str(sqlite_path))
            conn.execute(
                "CREATE TABLE threads (id TEXT PRIMARY KEY, title TEXT, cwd TEXT)"
            )
            sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            fname = f"rollout-2025-06-03T10-00-00-{sid}.jsonl"
            (session_dir / fname).write_text(json.dumps({
                "type": "response_item", "timestamp": "2025-06-01T10:00:01Z",
                "payload": {"type": "message", "role": "user",
                            "content": [{"type": "input_text", "text": "hi"}]},
            }) + "\n")
            conn.execute("INSERT INTO threads (id, title, cwd) VALUES (?, ?, ?)",
                         (sid, "No TS", "/tmp"))
            conn.commit()
            conn.close()
            adapter = CodexAdapter(pd)
            adapter._sqlite_path = sqlite_path
            sess = adapter.list_projects()[0]["sessions"][0]
            self.assertIsNone(sess["firstTimestamp"])
            self.assertIsNone(sess["lastTimestamp"])
            data = adapter.load_session(sid)
            self.assertIsNone(data["firstTimestamp"])
            self.assertIsNone(data["lastTimestamp"])
            self.assertEqual(data["title"], "No TS")
            self.assertEqual(data["displayName"], "No TS")

    def test_invalid_timestamp_strings_return_none(self):
        """Invalid SQLite timestamp strings must not be returned verbatim."""
        with TemporaryDirectory() as tmp:
            adapter, sid = self._make_env(
                tmp,
                created_at="dirty-created",
                updated_at="not a timestamp",
            )
            sess = adapter.list_projects()[0]["sessions"][0]
            self.assertIsNone(sess["firstTimestamp"])
            self.assertIsNone(sess["lastTimestamp"])
            self.assertNotEqual(sess["firstTimestamp"], "dirty-created")
            data = adapter.load_session(sid)
            self.assertIsNone(data["firstTimestamp"])
            self.assertIsNone(data["lastTimestamp"])


class TestSelectorStillNoSessionId(unittest.TestCase):
    """Verify that timestamp fixes do not reintroduce session id display."""

    def test_fmt_session_label_still_no_bracket(self):
        snippet = _extract_fn(_HTML, "function fmtSessionLabel(", "\n\n// ── Session rename UI")
        self.assertNotIn("[${prefix}]", snippet)

    def test_title_bar_still_no_raw_id(self):
        snippet = _extract_fn(_HTML, "function updateSessionTitleBar(", "function startSessionRename()")
        self.assertNotIn("idEl.textContent = data.sessionId", snippet)

    def test_fmtts_returns_empty_not_fallback_id(self):
        """fmtTs must never return raw ts or session id as fallback."""
        snippet = _extract_fn(_HTML, "function fmtTs(", "function trunc(")
        # Old code had: catch { return ts; } — must not fall back to returning the raw input
        self.assertNotIn("return ts", snippet)
        self.assertNotIn("return String(ts)", snippet)


# ---------------------------------------------------------------------------
# 6.6 Non-regression: existing adapter tests still pass (run separately)
# ---------------------------------------------------------------------------

class TestNonRegressionImports(unittest.TestCase):
    """Verify key modules still import cleanly."""

    def test_import_adapters(self):
        from ccwhat.adapters.base import AgentAdapter, SessionRenameError
        from ccwhat.adapters.claude import ClaudeAdapter
        from ccwhat.adapters.codex import CodexAdapter
        from ccwhat.adapters.opencode import OpenCodeAdapter
        from ccwhat.adapters.registry import create_adapter

    def test_import_viewer_server(self):
        from viewer.server import create_server


if __name__ == "__main__":
    unittest.main()
