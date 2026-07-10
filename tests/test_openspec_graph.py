"""Tests for OpenSpec graph synchronization."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from ccwhat.cli import cli
from ccwhat.openspec_graph import sync_openspec_graph, write_openspec_marker
from viewer.server import _load_openspec_graph_response, create_app


def _make_change(root: Path, name: str = "demo-change") -> Path:
    change = root / "openspec" / "changes" / name
    (change / "specs" / "demo").mkdir(parents=True)
    (change / ".openspec.yaml").write_text("schema: spec-driven\n", encoding="utf-8")
    (change / "proposal.md").write_text("## Why\n\nDemo.\n", encoding="utf-8")
    (change / "design.md").write_text("## Context\n\nDemo.\n", encoding="utf-8")
    (change / "specs" / "demo" / "spec.md").write_text("## ADDED Requirements\n\n### Requirement: Demo\n", encoding="utf-8")
    (change / "tasks.md").write_text("## 1. Work\n\n- [x] 1.1 Demo task\n", encoding="utf-8")
    return change


def _write_session(projects_dir: Path, session_id: str = "session-step-001") -> None:
    project = projects_dir / "demo-project"
    project.mkdir(parents=True)
    rows = [
        {
            "type": "user",
            "timestamp": "2026-07-09T00:00:01Z",
            "message": {"content": [{"type": "text", "text": "Implement OpenSpec graph."}]},
        },
        {
            "type": "assistant",
            "timestamp": "2026-07-09T00:00:02Z",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_proposal",
                        "name": "Write",
                        "input": {"file_path": "openspec/changes/demo-change/proposal.md", "content": "proposal"},
                    }
                ]
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-07-09T00:00:03Z",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_apply",
                        "name": "Edit",
                        "input": {"file_path": "ccwhat/foo.py", "old_string": "old", "new_string": "new"},
                    }
                ]
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-07-09T00:00:04Z",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_verify",
                        "name": "Bash",
                        "input": {"command": "openspec validate demo-change --strict"},
                    }
                ]
            },
        },
    ]
    (project / f"{session_id}.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _write_marked_session(projects_dir: Path, session_id: str = "session-marker-001") -> None:
    project = projects_dir / "demo-project"
    project.mkdir(parents=True)

    def bash(tool_id: str, timestamp: str, command: str) -> dict:
        return {
            "type": "assistant",
            "timestamp": timestamp,
            "message": {"content": [{"type": "tool_use", "id": tool_id, "name": "Bash", "input": {"command": command}}]},
        }

    rows = [
        {"type": "user", "timestamp": "2026-07-09T00:00:01Z", "message": {"content": [{"type": "text", "text": "Unrelated discussion."}]}},
        bash("toolu_apply_start", "2026-07-09T00:00:02Z", "ccwhat openspec-mark --change demo-change --action apply --phase start --marker-id demo-apply-start"),
        {"type": "assistant", "timestamp": "2026-07-09T00:00:03Z", "message": {"content": [{"type": "tool_use", "id": "toolu_apply", "name": "Edit", "input": {"file_path": "ccwhat/foo.py", "old_string": "old", "new_string": "new"}}]}},
        bash("toolu_apply_end", "2026-07-09T00:00:04Z", "ccwhat openspec-mark --change demo-change --action apply --phase end --marker-id demo-apply-end"),
        {"type": "user", "timestamp": "2026-07-09T00:00:05Z", "message": {"content": [{"type": "text", "text": "Another change starts now."}]}},
    ]
    (project / f"{session_id}.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


class OpenSpecGraphSyncTests(unittest.TestCase):
    def test_sync_generates_graph_files_inside_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            change = _make_change(root)

            outputs = sync_openspec_graph(
                change="demo-change",
                event_type="validate_ran",
                success=True,
                cwd=root,
            )

            self.assertEqual(outputs["diagnosis"].parent.resolve(), (change / "graph").resolve())
            self.assertTrue((change / "graph" / "events.jsonl").exists())
            self.assertTrue((change / "graph" / "event_graph.json").exists())
            self.assertTrue((change / "graph" / "action_graph.json").exists())
            self.assertTrue((change / "graph" / "diagnosis.json").exists())

            action_graph = json.loads((change / "graph" / "action_graph.json").read_text(encoding="utf-8"))
            actions = {action["type"]: action for action in action_graph["actions"]}
            event_graph = json.loads((change / "graph" / "event_graph.json").read_text(encoding="utf-8"))
            self.assertEqual(event_graph["metadata"]["source_kind"], "milestone_fallback")
            self.assertEqual(actions["proposal"]["status"], "observed")
            self.assertEqual(actions["specs"]["status"], "observed")
            self.assertEqual(actions["apply"]["status"], "observed")
            self.assertEqual(actions["verify"]["status"], "observed")

    def test_sync_uses_marker_scoped_session_events_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            change = _make_change(root)
            projects_dir = root / "projects"
            _write_marked_session(projects_dir)
            write_openspec_marker(change="demo-change", action="apply", phase="start", marker_id="demo-apply-start", cwd=root)
            write_openspec_marker(change="demo-change", action="apply", phase="end", marker_id="demo-apply-end", cwd=root)

            sync_openspec_graph(
                change="demo-change",
                session_id="session-marker-001",
                projects_dir=projects_dir,
                cwd=root,
            )

            event_graph = json.loads((change / "graph" / "event_graph.json").read_text(encoding="utf-8"))
            action_graph = json.loads((change / "graph" / "action_graph.json").read_text(encoding="utf-8"))
            node_types = {node["type"] for node in event_graph["nodes"]}
            actions = {action["type"]: action for action in action_graph["actions"]}

            self.assertEqual(event_graph["metadata"]["source_kind"], "marker_scoped_session")
            self.assertEqual(event_graph["metadata"]["source_confidence"], "high")
            self.assertIn("file_edit", node_types)
            self.assertIn("marker", node_types)
            self.assertNotIn("user_message", node_types)
            self.assertEqual(actions["proposal"]["status"], "not_observed")
            self.assertEqual(actions["apply"]["status"], "observed")
            self.assertEqual(actions["verify"]["status"], "not_observed")

    def test_sync_requires_markers_unless_full_session_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_change(root)
            projects_dir = root / "projects"
            _write_session(projects_dir)

            with self.assertRaisesRegex(ValueError, "No markers found"):
                sync_openspec_graph(
                    change="demo-change",
                    session_id="session-step-001",
                    projects_dir=projects_dir,
                    cwd=root,
                )

            sync_openspec_graph(
                change="demo-change",
                session_id="session-step-001",
                projects_dir=projects_dir,
                allow_full_session=True,
                cwd=root,
            )
            event_graph = json.loads((root / "openspec/changes/demo-change/graph/event_graph.json").read_text(encoding="utf-8"))
            self.assertEqual(event_graph["metadata"]["source_kind"], "session_full")

    def test_sync_rejects_incomplete_marker_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_change(root)
            projects_dir = root / "projects"
            _write_marked_session(projects_dir)
            write_openspec_marker(change="demo-change", action="apply", phase="start", marker_id="demo-apply-start", cwd=root)

            with self.assertRaisesRegex(ValueError, "incomplete Marker boundaries"):
                sync_openspec_graph(
                    change="demo-change",
                    session_id="session-marker-001",
                    projects_dir=projects_dir,
                    cwd=root,
                )

    def test_marker_cli_writes_one_unique_boundary_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            change = _make_change(root)
            previous = Path.cwd()
            try:
                os.chdir(root)
                result = CliRunner().invoke(cli, [
                    "openspec-mark", "--change", "demo-change", "--action", "apply", "--phase", "start", "--marker-id", "demo-apply-start",
                ])
                duplicate = CliRunner().invoke(cli, [
                    "openspec-mark", "--change", "demo-change", "--action", "apply", "--phase", "start", "--marker-id", "other-start",
                ])
            finally:
                os.chdir(previous)

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertNotEqual(duplicate.exit_code, 0)
            markers = [json.loads(line) for line in (change / "graph/markers.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(markers[0]["marker_id"], "demo-apply-start")

    def test_cli_sync_generates_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            change = _make_change(root)
            previous = Path.cwd()
            try:
                os.chdir(root)
                result = CliRunner().invoke(cli, [
                    "openspec-graph",
                    "sync",
                    "--change",
                    "demo-change",
                    "--event",
                    "task_completed",
                    "--task",
                    "1.1 Demo task",
                ])
            finally:
                os.chdir(previous)

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertTrue((change / "graph" / "diagnosis.json").exists())

    def test_viewer_api_helper_loads_graph_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_change(root)
            sync_openspec_graph(change="demo-change", event_type="validate_ran", success=True, cwd=root)

            status, payload = _load_openspec_graph_response("demo-change", root)

            self.assertEqual(status, 200)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["change"], "demo-change")
            self.assertIn("actionGraph", payload)
            self.assertIn("eventGraph", payload)
            self.assertIn("diagnosis", payload)

    def test_viewer_api_helper_rejects_invalid_change_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, payload = _load_openspec_graph_response("../demo-change", Path(tmp))

            self.assertEqual(status, 400)
            self.assertFalse(payload["ok"])

    def test_feedback_diagnosis_accepts_marker_scoped_graphs(self) -> None:
        session_id = "session-marker-0000001"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            change = _make_change(root)
            projects_dir = root / "projects"
            _write_marked_session(projects_dir, session_id=session_id)
            write_openspec_marker(change="demo-change", action="apply", phase="start", marker_id="demo-apply-start", cwd=root)
            write_openspec_marker(change="demo-change", action="apply", phase="end", marker_id="demo-apply-end", cwd=root)
            sync_openspec_graph(
                change="demo-change",
                session_id=session_id,
                projects_dir=projects_dir,
                cwd=root,
            )
            event_graph = json.loads((change / "graph" / "event_graph.json").read_text(encoding="utf-8"))
            apply_event = next(
                node["node_id"]
                for node in event_graph["nodes"]
                if node["type"] == "file_edit" and "ccwhat/foo.py" in node["data"]["files"]
            )
            analyzer_output = json.dumps({
                "symptoms": [{"type": "wrong_output", "summary": "implementation is wrong"}],
                "suspicious_actions": [{"action_id": "A5", "reason": "source edit"}],
                "suspicious_events": [{"event_id": apply_event, "action_id": "A5", "reason": "wrong edit"}],
                "missing_evidence": [],
                "summary": "Apply contains the likely issue.",
            })
            app = create_app(projects_dir, root / "logs", analyzer_agent="claude")
            backend = app.state.viewer_backend

            with mock.patch("ccwhat.diagnosis.feedback.run_mc_analysis", return_value=(analyzer_output, 12)) as analyze:
                status, payload = backend.diagnose_openspec_graph_response(
                    {"change": "demo-change", "sessionId": session_id, "feedback": "output is wrong"},
                    root,
                )

            self.assertEqual(status, 200)
            self.assertTrue(payload["diagnosis"]["available"])
            self.assertEqual(payload["diagnosis"]["suspicious_events"][0]["event_id"], apply_event)
            analyze.assert_called_once()


if __name__ == "__main__":
    unittest.main()
