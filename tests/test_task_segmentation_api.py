"""API tests for POST /api/task-segments (task 7.4)."""

from __future__ import annotations

import http.client
import json
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_test_server(session_data: dict | None = None):
    """Return (server, port) with a mock adapter that returns session_data."""
    from viewer.server import _make_handler
    from ccwhat.adapters.base import AgentAdapter

    class _MockAdapter(AgentAdapter):
        @property
        def name(self): return "claude"
        def default_projects_dir(self): return Path(".")
        def list_projects(self): return []
        def list_sessions(self): return []
        def load_session(self, session_id):
            return session_data if session_data is not None else None
        def raw_to_normalized_events(self, raw, session_id): return []

    projects_dir = Path(".")
    logs_dir = Path(".")
    handler = _make_handler(projects_dir, logs_dir, adapter=_MockAdapter())
    server = HTTPServer(("127.0.0.1", 0), handler)
    return server, server.server_address[1]


def _start(server):
    t = threading.Thread(target=server.handle_request, daemon=True)
    t.start()
    return t


def _post(port, path, body: dict) -> tuple[int, dict]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    payload = json.dumps(body).encode()
    conn.request("POST", path, body=payload, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    data = json.loads(resp.read())
    return resp.status, data


SESSION_FIXTURE = {
    "sessionId": "aabb1122aabb1122aabb1122",
    "projectDir": "test-project",
    "main": [
        {"type": "user", "content": "帮我实现功能 A", "_fileLine": 1},
        {"type": "assistant",
         "message": {"content": [{"type": "text", "text": "好的"}]},
         "_fileLine": 2},
    ],
    "subagents": [],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTaskSegmentsSuccess(unittest.TestCase):
    def setUp(self):
        self.server, self.port = _make_test_server(SESSION_FIXTURE)

    def tearDown(self):
        self.server.server_close()

    def test_success_returns_ok_and_tasks(self):
        """Success: returns ok=True, sessionId, tasks, summary."""
        _start(self.server)
        status, data = _post(self.port, "/api/task-segments",
                             {"sessionId": "aabb1122aabb1122aabb1122"})
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["sessionId"], "aabb1122aabb1122aabb1122")
        self.assertIn("tasks", data)
        self.assertIn("summary", data)
        self.assertIsInstance(data["tasks"], list)

    def test_tasks_have_required_fields(self):
        """Each task must have required fields."""
        _start(self.server)
        _, data = _post(self.port, "/api/task-segments",
                        {"sessionId": "aabb1122aabb1122aabb1122"})
        for idx, task in enumerate(data["tasks"], 1):
            self.assertIn("taskId", task)
            self.assertEqual(task["title"], f"任务 {idx}")
            self.assertIn("status", task)
            self.assertEqual(task["status"], "unevaluated")
            self.assertIn("evidence", task)
            self.assertIn("boundaryReasons", task)

    def test_no_persistence(self):
        """Calling twice returns fresh results (no stored state across calls)."""
        _start(self.server)
        _, d1 = _post(self.port, "/api/task-segments",
                      {"sessionId": "aabb1122aabb1122aabb1122"})
        server2, port2 = _make_test_server(SESSION_FIXTURE)
        _start(server2)
        _, d2 = _post(port2, "/api/task-segments",
                      {"sessionId": "aabb1122aabb1122aabb1122"})
        server2.server_close()
        self.assertEqual(len(d1["tasks"]), len(d2["tasks"]))


class TestTaskSegmentsInvalidRequest(unittest.TestCase):
    def setUp(self):
        self.server, self.port = _make_test_server(SESSION_FIXTURE)

    def tearDown(self):
        self.server.server_close()

    def test_invalid_session_id_returns_400(self):
        """Session id with invalid format returns 400."""
        _start(self.server)
        status, data = _post(self.port, "/api/task-segments", {"sessionId": "bad"})
        self.assertEqual(status, 400)
        self.assertFalse(data["ok"])

    def test_empty_session_id_returns_400(self):
        """Empty session id returns 400."""
        _start(self.server)
        status, data = _post(self.port, "/api/task-segments", {"sessionId": ""})
        self.assertEqual(status, 400)
        self.assertFalse(data["ok"])

    def test_missing_session_id_returns_400(self):
        """Missing sessionId key returns 400."""
        _start(self.server)
        status, data = _post(self.port, "/api/task-segments", {})
        self.assertEqual(status, 400)
        self.assertFalse(data["ok"])


class TestTaskSegmentsNotFound(unittest.TestCase):
    def setUp(self):
        # Adapter returns None (session not found)
        self.server, self.port = _make_test_server(session_data=None)

    def tearDown(self):
        self.server.server_close()

    def test_missing_session_returns_404(self):
        """Non-existent session returns 404."""
        _start(self.server)
        status, data = _post(self.port, "/api/task-segments",
                             {"sessionId": "aabb1122aabb1122aabb1122"})
        self.assertEqual(status, 404)
        self.assertFalse(data["ok"])


class TestTaskSegmentsBackendError(unittest.TestCase):
    def setUp(self):
        self.server, self.port = _make_test_server(SESSION_FIXTURE)

    def tearDown(self):
        self.server.server_close()

    def test_backend_exception_returns_json_error(self):
        """Backend segmentation failures return JSON instead of dropping the connection."""
        _start(self.server)
        with patch("ccwhat.task_segments.segmenter._Segmenter.run", side_effect=UnicodeDecodeError("gbk", b"\xae", 0, 1, "bad")):
            status, data = _post(self.port, "/api/task-segments",
                                 {"sessionId": "aabb1122aabb1122aabb1122"})

        self.assertEqual(status, 500)
        self.assertFalse(data["ok"])
        self.assertIn("task segmentation failed", data["error"])


class TestTaskSegmentsWrongPath(unittest.TestCase):
    def setUp(self):
        self.server, self.port = _make_test_server(SESSION_FIXTURE)

    def tearDown(self):
        self.server.server_close()

    def test_unknown_post_path_returns_404(self):
        """POST to an unknown path returns 404."""
        _start(self.server)
        status, data = _post(self.port, "/api/unknown", {"sessionId": "x" * 20})
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
