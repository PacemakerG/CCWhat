"""API tests for scoped session/task search."""

from __future__ import annotations

import http.client
import json
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


SID_A = "aabb1122aabb1122aabb1122"
SID_B = "bbcc2233bbcc2233bbcc2233"
SID_C = "ccdd3344ccdd3344ccdd3344"


def _session(session_id: str, project_dir: str, text: str) -> dict[str, Any]:
    return {
        "sessionId": session_id,
        "projectDir": project_dir,
        "main": [
            {"type": "user", "content": text, "timestamp": "2026-01-01T00:00:00Z", "_fileLine": 1},
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": f"handled {text}"}]},
                "timestamp": "2026-01-01T00:01:00Z",
                "_fileLine": 2,
            },
        ],
        "subagents": [],
    }


def _make_server(registry_root: Path, *, fail_session: str | None = None):
    from ccwhat.adapters.base import AgentAdapter
    from tests.http_compat import make_handler as _make_handler

    sessions = {
        SID_A: _session(SID_A, "project-one", "alpha needle current session"),
        SID_B: _session(SID_B, "project-one", "beta cross session"),
        SID_C: _session(SID_C, "project-two", "gamma cross project"),
    }

    class _MockAdapter(AgentAdapter):
        @property
        def name(self):
            return "claude"

        def default_projects_dir(self):
            return Path(".")

        def list_projects(self):
            return [
                {
                    "projectDir": "project-one",
                    "sessions": [
                        {"id": SID_A, "displayName": "Current Alpha", "lastTimestamp": "2026-01-01T00:01:00Z"},
                        {"id": SID_B, "displayName": "Beta", "lastTimestamp": "2026-01-02T00:01:00Z"},
                    ],
                },
                {
                    "projectDir": "project-two",
                    "sessions": [
                        {"id": SID_C, "displayName": "Gamma", "lastTimestamp": "2026-01-03T00:01:00Z"},
                    ],
                },
            ]

        def list_sessions(self):
            return []

        def load_session(self, session_id):
            if fail_session and session_id == fail_session:
                raise OSError("cannot read fixture session")
            return sessions.get(session_id)

        def raw_to_normalized_events(self, raw, session_id):
            return []

    handler = _make_handler(
        Path("."),
        Path("."),
        adapter=_MockAdapter(),
        dataset_registry_root=registry_root,
    )
    server = HTTPServer(("127.0.0.1", 0), handler)
    return server, server.server_address[1]


def _start(server: HTTPServer) -> threading.Thread:
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    return thread


def _get(port: int, path: str) -> tuple[int, dict[str, Any]]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = json.loads(resp.read())
    conn.close()
    return resp.status, body


def _write_dataset_task(registry_root: Path) -> None:
    dataset = registry_root / "dataset-20260618-000000-aabb1122"
    traces = dataset / "traces"
    traces.mkdir(parents=True)
    (dataset / "manifest.json").write_text(json.dumps({
        "created_at": "2026-06-18T00:00:00Z",
        "session": {"project_dir": "project-one"},
    }), encoding="utf-8")
    row = {
        "id": "task-001",
        "input": {"instruction": "Implement saved dataset search"},
        "metadata": {
            "session_id": SID_A,
            "trace_path": "traces/trace-task-001.json",
            "start_event_id": "main:1",
            "end_event_id": "main:2",
            "task_type": "feature",
            "status": "unevaluated",
        },
    }
    (dataset / "dataset.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    (traces / "trace-task-001.json").write_text(json.dumps({
        "commands": ["uv run saved-search"],
        "test_commands": [],
        "files": {"read": [], "changed": ["viewer/server.py"]},
        "errors": [],
        "final_claim": "saved task source is searchable",
    }), encoding="utf-8")


class TestScopedSearchApi(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.registry_root = Path(self.tmp.name) / "datasets"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_default_scope_searches_current_session_only(self) -> None:
        server, port = _make_server(self.registry_root)
        _start(server)
        status, body = _get(port, f"/api/search?q=cross&session={SID_A}&project=project-one")
        server.server_close()
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["scope"], "current_session")
        self.assertEqual(body["results"], [])

    def test_current_session_finds_event_content(self) -> None:
        server, port = _make_server(self.registry_root)
        _start(server)
        status, body = _get(port, f"/api/search?q=needle&session={SID_A}&project=project-one")
        server.server_close()
        self.assertEqual(status, 200)
        events = [r for r in body["results"] if r["type"] == "event" and r.get("eventId")]
        self.assertTrue(events)
        self.assertEqual(events[0]["displayName"], "Current Alpha")

    def test_current_project_scope_stays_in_project(self) -> None:
        server, port = _make_server(self.registry_root)
        _start(server)
        status, body = _get(port, "/api/search?q=beta&scope=current_project&project=project-one")
        server.server_close()
        self.assertEqual(status, 200)
        self.assertTrue(any(r["sessionId"] == SID_B for r in body["results"]))
        self.assertTrue(all(r["projectDir"] == "project-one" for r in body["results"]))

    def test_all_projects_preserves_project_dir(self) -> None:
        server, port = _make_server(self.registry_root)
        _start(server)
        status, body = _get(port, "/api/search?q=gamma&scope=all_projects")
        server.server_close()
        self.assertEqual(status, 200)
        self.assertTrue(any(r["sessionId"] == SID_C and r["projectDir"] == "project-two" for r in body["results"]))

    def test_invalid_query_and_scope_return_400(self) -> None:
        server, port = _make_server(self.registry_root)
        _start(server)
        status, body = _get(port, f"/api/search?q=x&session={SID_A}")
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        server2, port2 = _make_server(self.registry_root)
        _start(server2)
        status, body = _get(port2, f"/api/search?q=alpha&scope=bad&session={SID_A}")
        server.server_close()
        server2.server_close()
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])

    def test_limit_sets_truncated_flag(self) -> None:
        server, port = _make_server(self.registry_root)
        _start(server)
        status, body = _get(port, "/api/search?q=project&scope=all_projects&limit=1")
        server.server_close()
        self.assertEqual(status, 200)
        self.assertEqual(len(body["results"]), 1)
        self.assertTrue(body["truncated"])

    def test_partial_read_failure_returns_warning(self) -> None:
        server, port = _make_server(self.registry_root, fail_session=SID_B)
        _start(server)
        status, body = _get(port, "/api/search?q=gamma&scope=all_projects")
        server.server_close()
        self.assertEqual(status, 200)
        self.assertTrue(any(w["sessionId"] == SID_B for w in body["warnings"]))
        self.assertTrue(any(r["sessionId"] == SID_C for r in body["results"]))

    def test_task_results_require_saved_dataset_source(self) -> None:
        server, port = _make_server(self.registry_root)
        _start(server)
        status, body = _get(port, f"/api/search?q=saved-search&session={SID_A}")
        server.server_close()
        self.assertEqual(status, 200)
        self.assertFalse(any(r["type"] == "task" for r in body["results"]))

        _write_dataset_task(self.registry_root)
        server2, port2 = _make_server(self.registry_root)
        _start(server2)
        status, body = _get(port2, f"/api/search?q=saved-search&session={SID_A}")
        server2.server_close()
        self.assertEqual(status, 200)
        task_results = [r for r in body["results"] if r["type"] == "task"]
        self.assertEqual(len(task_results), 1)
        self.assertEqual(task_results[0]["taskId"], "task-001")


if __name__ == "__main__":
    unittest.main()
