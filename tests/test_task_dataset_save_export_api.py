"""API tests for saving and downloading Task Dataset v1 from the viewer."""

from __future__ import annotations

import http.client
import io
import json
import tarfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from ccwhat.task_dataset import build_dataset_tar_gz, validate_dataset_path
from ccwhat.runtime.infra.registry import RunRegistry


SESSION_ID = "aabb1122aabb1122aabb1122"

SESSION_FIXTURE = {
    "sessionId": SESSION_ID,
    "projectDir": "/tmp/ccwhat-test-project",
    "agent": "claude",
    "main": [
        {
            "type": "user",
            "content": "Build Dataset save",
            "timestamp": "2026-06-14T00:00:01Z",
            "_fileLine": 1,
        },
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Done"}]},
            "timestamp": "2026-06-14T00:00:02Z",
            "_fileLine": 2,
        },
    ],
    "subagents": [],
}


def _make_test_server(
    registry_root: Path,
    session_data: dict | None = SESSION_FIXTURE,
    runtime_registry_root: Path | None = None,
):
    from ccwhat.adapters.base import AgentAdapter
    from tests.http_compat import make_handler as _make_handler

    class _MockAdapter(AgentAdapter):
        @property
        def name(self):
            return "claude"

        def default_projects_dir(self):
            return Path(".")

        def list_projects(self):
            return []

        def list_sessions(self):
            return []

        def load_session(self, session_id):
            if session_data is None:
                return None
            return session_data if session_id == SESSION_ID else None

        def raw_to_normalized_events(self, raw, session_id):
            return []

    handler = _make_handler(
        Path("."),
        Path("."),
        adapter=_MockAdapter(),
        dataset_registry_root=registry_root,
        runtime_registry_root=runtime_registry_root,
    )
    server = HTTPServer(("127.0.0.1", 0), handler)
    return server, server.server_address[1]


def _start(server):
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    return thread


def _post(port: int, path: str, body: dict) -> tuple[int, dict]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(
        "POST",
        path,
        body=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    resp = conn.getresponse()
    data = json.loads(resp.read())
    return resp.status, data


def _get(port: int, path: str) -> tuple[int, bytes, dict[str, str]]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    headers = {key.lower(): value for key, value in resp.getheaders()}
    return resp.status, resp.read(), headers


def _task_segments_payload() -> dict:
    tasks = [{
        "taskId": "task-001",
        "title": "任务 1",
        "taskType": "feature",
        "status": "unevaluated",
        "startEventId": "main:1",
        "endEventId": "main:2",
        "boundaryReasons": ["test fixture"],
        "evidence": {
            "filesRead": [],
            "filesChanged": [],
            "commands": [],
            "testCommands": [],
            "errors": [],
        },
        "fileWeights": {},
    }]
    return {
        "sessionId": SESSION_ID,
        "taskSource": "taskSegments",
        "source": {
            "kind": "taskSegments",
            "sourceSchemaVersion": "task-segmentation-v1",
            "payload": {
                "sessionId": SESSION_ID,
                "schemaVersion": "task-segmentation-v1",
                "tasks": tasks,
                "summary": {"taskCount": 1},
            },
            "provenance": {
                "source": "auto",
                "sessionId": SESSION_ID,
                "sourceTraceId": "trace-fixture",
            },
            "sourceTrace": {
                "sessionId": SESSION_ID,
                "sourceTraceId": "trace-fixture",
                "eventIds": ["main:1", "main:2"],
            },
        },
        "download": False,
        "includeRawSession": False,
        "includeReqResp": False,
    }


def _overlay_payload() -> dict:
    payload = _task_segments_payload()
    overlay = payload["source"]["payload"]
    overlay.update({
        "overlayId": "overlay-aabb1122",
        "schemaVersion": "task-trace-overlay-v1",
        "saved": True,
        "dirty": False,
        "updatedAt": "2026-06-14T00:00:00Z",
    })
    return {
        "sessionId": SESSION_ID,
        "taskSource": "activeOverlay",
        "source": {
            "kind": "overlay",
            "overlayVersion": "task-trace-overlay-v1",
            "payload": overlay,
            "provenance": {
                "source": "edited",
                "sessionId": SESSION_ID,
                "sourceTraceId": "overlay-fixture",
                "saved": True,
                "savedAt": "2026-06-14T00:00:00Z",
            },
            "sourceTrace": {
                "sessionId": SESSION_ID,
                "sourceTraceId": "overlay-fixture",
                "eventIds": ["main:1", "main:2"],
            },
        },
        "download": False,
        "includeRawSession": False,
        "includeReqResp": False,
    }


def _runtime_payload(run_id: str) -> dict:
    return {
        "sessionId": SESSION_ID,
        "taskSource": "runtimeTasks",
        "source": {
            "kind": "runtimeTasks",
            "payload": {
                "runId": run_id,
                "taskIds": ["task-001"],
            },
        },
        "download": False,
        "includeRawSession": False,
        "includeReqResp": False,
    }


class TestTaskDatasetSaveApi(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.registry_root = Path(self.tmp.name) / "datasets"
        self.runtime_registry_root = Path(self.tmp.name) / "runtime"
        self.server, self.port = _make_test_server(
            self.registry_root,
            runtime_registry_root=self.runtime_registry_root,
        )

    def tearDown(self) -> None:
        self.server.server_close()
        self.tmp.cleanup()

    def test_save_task_segments_success_writes_valid_registry_dataset(self) -> None:
        _start(self.server)
        status, data = _post(self.port, "/api/save-task-dataset", _task_segments_payload())

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertRegex(data["datasetId"], r"^dataset-\d{8}-\d{6}-aabb1122$")
        self.assertEqual(data["downloadUrl"], f"/api/task-datasets/{data['datasetId']}/download")
        dataset_dir = Path(data["datasetPath"])
        self.assertTrue((dataset_dir / "manifest.json").is_file())
        self.assertTrue((dataset_dir / "dataset.jsonl").is_file())
        self.assertTrue((dataset_dir / "scores.jsonl").is_file())
        self.assertTrue((dataset_dir / "traces" / "trace-task-001.json").is_file())
        result = validate_dataset_path(dataset_dir)
        self.assertTrue(result.ok, result.errors)
        trace = json.loads(
            (dataset_dir / "traces" / "trace-task-001.json").read_text(encoding="utf-8")
        )
        self.assertFalse(trace["task_diff"]["available"])

    def test_save_runtime_tasks_uses_common_dataset_with_git_diff(self) -> None:
        runtime_registry = RunRegistry(self.runtime_registry_root)
        run = runtime_registry.create_run(
            agent="claude",
            workspace=Path(SESSION_FIXTURE["projectDir"]),
            target_args=("claude",),
            proxy_port=11001,
            viewer_port=11002,
            control_port=11003,
        )
        task_dir = runtime_registry.run_dir(run.run_id) / "tasks" / "task-001"
        task_dir.mkdir(parents=True)
        (task_dir / "task.json").write_text(json.dumps({
            "schema": "ccwhat-runtime-task-v1",
            "task_id": "task-001",
            "run_id": run.run_id,
            "agent": "claude",
            "workspace": SESSION_FIXTURE["projectDir"],
            "title": "Build Dataset save",
            "status": "finalized",
            "started_at": "2026-06-14T00:00:00Z",
            "finished_at": "2026-06-14T00:00:03Z",
            "start_tree": "before",
            "end_tree": "after",
            "paths": {"task_diff": "task.diff"},
        }), encoding="utf-8")
        diff = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
        (task_dir / "task.diff").write_text(diff, encoding="utf-8")

        _start(self.server)
        status, data = _post(self.port, "/api/save-task-dataset", _runtime_payload(run.run_id))

        self.assertEqual(status, 200, data)
        dataset_dir = Path(data["datasetPath"])
        row = json.loads((dataset_dir / "dataset.jsonl").read_text(encoding="utf-8"))
        trace = json.loads(
            (dataset_dir / "traces" / "trace-task-001.json").read_text(encoding="utf-8")
        )
        self.assertEqual(row["metadata"]["task_source"], "runtimeTasks")
        self.assertEqual(trace["task_diff"]["source"], "isolated_git_index")
        self.assertEqual(
            (dataset_dir / "diffs" / "trace-task-001.diff").read_text(encoding="utf-8"),
            diff,
        )
        self.assertTrue(validate_dataset_path(dataset_dir).ok)
        tar_bytes, _ = build_dataset_tar_gz(
            dataset_id=data["datasetId"],
            registry_root=self.registry_root,
        )
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as archive:
            self.assertIn(
                "ccwhat-dataset/diffs/trace-task-001.diff",
                archive.getnames(),
            )

    def test_save_overlay_success_uses_full_saved_overlay_payload(self) -> None:
        _start(self.server)
        status, data = _post(self.port, "/api/save-task-dataset", _overlay_payload())

        self.assertEqual(status, 200)
        dataset_dir = Path(data["datasetPath"])
        row = json.loads((dataset_dir / "dataset.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(row["metadata"]["task_source"], "activeOverlay")

    def test_missing_session_returns_404(self) -> None:
        _start(self.server)
        payload = _task_segments_payload()
        payload["sessionId"] = "missingmissingmissing12"
        payload["source"]["provenance"]["sessionId"] = payload["sessionId"]
        payload["source"]["payload"]["sessionId"] = payload["sessionId"]
        payload["source"]["sourceTrace"]["sessionId"] = payload["sessionId"]
        status, data = _post(self.port, "/api/save-task-dataset", payload)

        self.assertEqual(status, 404)
        self.assertFalse(data["ok"])

    def test_no_source_payload_returns_400(self) -> None:
        _start(self.server)
        status, data = _post(self.port, "/api/save-task-dataset", {
            "sessionId": SESSION_ID,
            "taskSource": "taskSegments",
        })

        self.assertEqual(status, 400)
        self.assertFalse(data["ok"])

    def test_raw_inclusion_returns_400_without_saving(self) -> None:
        _start(self.server)
        payload = _task_segments_payload()
        payload["includeRawSession"] = True
        status, data = _post(self.port, "/api/save-task-dataset", payload)

        self.assertEqual(status, 400)
        self.assertIn("raw source inclusion", data["error"])
        self.assertFalse(self.registry_root.exists())

    def test_raw_session_string_true_returns_400_without_saving(self) -> None:
        _start(self.server)
        payload = _task_segments_payload()
        payload["includeRawSession"] = "TrUe"
        status, data = _post(self.port, "/api/save-task-dataset", payload)

        self.assertEqual(status, 400)
        self.assertIn("raw source inclusion", data["error"])
        self.assertFalse(self.registry_root.exists())

    def test_req_resp_string_true_returns_400_without_saving(self) -> None:
        _start(self.server)
        payload = _task_segments_payload()
        payload["includeReqResp"] = "true"
        status, data = _post(self.port, "/api/save-task-dataset", payload)

        self.assertEqual(status, 400)
        self.assertIn("raw source inclusion", data["error"])
        self.assertFalse(self.registry_root.exists())

    def test_task_source_kind_mismatch_returns_400(self) -> None:
        _start(self.server)
        payload = _task_segments_payload()
        payload["source"]["kind"] = "overlay"
        status, data = _post(self.port, "/api/save-task-dataset", payload)

        self.assertEqual(status, 400)
        self.assertIn("source.kind", data["error"])
        self.assertFalse(self.registry_root.exists())

    def test_provenance_session_mismatch_returns_400(self) -> None:
        _start(self.server)
        payload = _task_segments_payload()
        payload["source"]["provenance"]["sessionId"] = "other-session"
        status, data = _post(self.port, "/api/save-task-dataset", payload)

        self.assertEqual(status, 400)
        self.assertIn("session provenance", data["error"])

    def test_overlay_version_missing_returns_400(self) -> None:
        _start(self.server)
        payload = _overlay_payload()
        payload["source"].pop("overlayVersion")
        payload["source"]["payload"].pop("schemaVersion")
        status, data = _post(self.port, "/api/save-task-dataset", payload)

        self.assertEqual(status, 400)
        self.assertIn("overlay version", data["error"])

    def test_unaligned_task_boundary_returns_400(self) -> None:
        _start(self.server)
        payload = _task_segments_payload()
        payload["source"]["payload"]["tasks"][0]["startEventId"] = "main:99"
        status, data = _post(self.port, "/api/save-task-dataset", payload)

        self.assertEqual(status, 400)
        self.assertIn("source trace cannot be aligned", data["error"])


class TestTaskDatasetDownloadApi(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.registry_root = Path(self.tmp.name) / "datasets"
        self.server, self.port = _make_test_server(self.registry_root)

    def tearDown(self) -> None:
        self.server.server_close()
        self.tmp.cleanup()

    def test_download_saved_dataset_tar_gz_with_fixed_root(self) -> None:
        _start(self.server)
        status, data = _post(self.port, "/api/save-task-dataset", _task_segments_payload())
        self.assertEqual(status, 200)

        _start(self.server)
        status, body, headers = _get(self.port, data["downloadUrl"])
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "application/gzip")
        self.assertIn(f'{data["datasetId"]}.tar.gz', headers["content-disposition"])

        tar_path = Path(self.tmp.name) / "download.tar.gz"
        tar_path.write_bytes(body)
        with tarfile.open(tar_path, "r:gz") as tar:
            names = sorted(tar.getnames())
        self.assertIn("ccwhat-dataset/manifest.json", names)
        self.assertIn("ccwhat-dataset/dataset.jsonl", names)
        self.assertIn("ccwhat-dataset/scores.jsonl", names)
        self.assertIn("ccwhat-dataset/traces/trace-task-001.json", names)
        self.assertNotIn("ccwhat-dataset/README.md", names)
        self.assertTrue(validate_dataset_path(tar_path).ok)

    def test_download_rejects_path_traversal_dataset_id(self) -> None:
        _start(self.server)
        status, body, _headers = _get(self.port, "/api/task-datasets/../secret/download")

        self.assertEqual(status, 400)
        self.assertIn("invalid dataset id", json.loads(body)["error"])


if __name__ == "__main__":
    unittest.main()
