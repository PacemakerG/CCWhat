"""Tests for Marker-scoped OpenSpec graph synchronization."""

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


_SEQUENCE = [
    ("apply", "apply-1-start"),
    ("apply", "apply-1-end"),
    ("verify", "verify-1-start"),
    ("verify", "verify-1-end"),
    ("apply", "apply-2-start"),
    ("apply", "apply-2-end"),
    ("verify", "verify-2-start"),
    ("verify", "verify-2-end"),
]


def _make_change(root: Path) -> Path:
    change = root / "openspec" / "changes" / "demo-change"
    (change / "specs" / "demo").mkdir(parents=True)
    (change / ".openspec.yaml").write_text("schema: spec-driven\n", encoding="utf-8")
    (change / "proposal.md").write_text("## Why\n\nDemo.\n", encoding="utf-8")
    (change / "design.md").write_text("## Context\n\nDemo.\n", encoding="utf-8")
    (change / "specs" / "demo" / "spec.md").write_text("## ADDED Requirements\n\n### Requirement: Demo\n", encoding="utf-8")
    (change / "tasks.md").write_text("## 1. Work\n\n- [x] 1.1 Demo task\n", encoding="utf-8")
    return change


def _bash(tool_id: str, timestamp: str, command: str) -> dict:
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "message": {"content": [{"type": "tool_use", "id": tool_id, "name": "Bash", "input": {"command": command}}]},
    }


def _write_repeated_marked_session(projects_dir: Path, session_id: str = "session-marker-0000001") -> None:
    project = projects_dir / "demo-project"
    project.mkdir(parents=True)
    rows = []
    timestamp = 1
    for action, marker_id in _SEQUENCE:
        phase = "start" if marker_id.endswith("start") else "end"
        rows.append(_bash(
            f"toolu_{marker_id}",
            f"2026-07-09T00:00:{timestamp:02d}Z",
            f"ccwhat openspec-mark --change demo-change --action {action} --phase {phase} --marker-id {marker_id}",
        ))
        timestamp += 1
        if phase == "start":
            if action == "apply":
                rows.append({
                    "type": "assistant",
                    "timestamp": f"2026-07-09T00:00:{timestamp:02d}Z",
                    "message": {"content": [{"type": "tool_use", "id": f"toolu_edit_{timestamp}", "name": "Edit", "input": {"file_path": f"ccwhat/demo-{timestamp}.py", "old_string": "old", "new_string": "new"}}]},
                })
            else:
                rows.append(_bash(f"toolu_test_{timestamp}", f"2026-07-09T00:00:{timestamp:02d}Z", "uv run python -m unittest tests.test_openspec_graph"))
            timestamp += 1
    (project / f"{session_id}.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _write_markers(root: Path) -> None:
    for action, marker_id in _SEQUENCE:
        write_openspec_marker(
            change="demo-change",
            action=action,
            phase="start" if marker_id.endswith("start") else "end",
            marker_id=marker_id,
            cwd=root,
        )


class OpenSpecGraphSyncTests(unittest.TestCase):
    def test_sync_records_the_observed_action_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            change = _make_change(root)
            projects_dir = root / "projects"
            _write_repeated_marked_session(projects_dir)
            _write_markers(root)

            outputs = sync_openspec_graph(
                change="demo-change",
                session_id="session-marker-0000001",
                projects_dir=projects_dir,
                cwd=root,
            )

            self.assertEqual(set(outputs), {"event_graph", "action_graph", "diagnosis"})
            event_graph = json.loads((change / "graph" / "event_graph.json").read_text(encoding="utf-8"))
            action_graph = json.loads((change / "graph" / "action_graph.json").read_text(encoding="utf-8"))
            actions = action_graph["actions"]

            self.assertEqual([item["action_id"] for item in actions], ["apply-1", "verify-1", "apply-2", "verify-2"])
            self.assertEqual([item["label"] for item in actions], ["Apply #1", "Verify #1", "Apply #2", "Verify #2"])
            self.assertEqual([(edge["from"], edge["to"], edge["type"]) for edge in action_graph["edges"]], [
                ("apply-1", "verify-1", "next"),
                ("verify-1", "apply-2", "next"),
                ("apply-2", "verify-2", "next"),
            ])
            self.assertEqual(
                {event_id for action in actions for event_id in action["event_ids"]},
                {node["node_id"] for node in event_graph["nodes"]},
            )
            self.assertTrue(all(edge["type"] == "timeline" for edge in event_graph["edges"]))
            self.assertTrue(all("action_segment_id" not in node["data"] for node in event_graph["nodes"]))
            self.assertEqual(event_graph["metadata"]["source_kind"], "marker_scoped_session")
            self.assertNotIn("dataset_id", event_graph["metadata"])

    def test_sync_rejects_incomplete_marker_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_change(root)
            projects_dir = root / "projects"
            _write_repeated_marked_session(projects_dir)
            write_openspec_marker(change="demo-change", action="apply", phase="start", marker_id="apply-1-start", cwd=root)

            with self.assertRaisesRegex(ValueError, "incomplete Marker boundaries"):
                sync_openspec_graph(
                    change="demo-change",
                    session_id="session-marker-0000001",
                    projects_dir=projects_dir,
                    cwd=root,
                )

    def test_marker_cli_allows_repeated_actions_but_not_marker_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            change = _make_change(root)
            previous = Path.cwd()
            try:
                os.chdir(root)
                runner = CliRunner()
                first = runner.invoke(cli, ["openspec-mark", "--change", "demo-change", "--action", "apply", "--phase", "start", "--marker-id", "apply-1-start"])
                repeated = runner.invoke(cli, ["openspec-mark", "--change", "demo-change", "--action", "apply", "--phase", "start", "--marker-id", "apply-2-start"])
                duplicate_id = runner.invoke(cli, ["openspec-mark", "--change", "demo-change", "--action", "apply", "--phase", "end", "--marker-id", "apply-1-start"])
            finally:
                os.chdir(previous)

            self.assertEqual(first.exit_code, 0, first.output)
            self.assertEqual(repeated.exit_code, 0, repeated.output)
            self.assertNotEqual(duplicate_id.exit_code, 0)
            markers = [json.loads(line) for line in (change / "graph/markers.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([item["marker_id"] for item in markers], ["apply-1-start", "apply-2-start"])

    def test_viewer_loads_dynamic_graph_and_feedback_keeps_action_binding(self) -> None:
        session_id = "session-marker-0000001"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            change = _make_change(root)
            projects_dir = root / "projects"
            _write_repeated_marked_session(projects_dir, session_id=session_id)
            _write_markers(root)
            sync_openspec_graph(change="demo-change", session_id=session_id, projects_dir=projects_dir, cwd=root)

            status, graph_payload = _load_openspec_graph_response("demo-change", root)
            self.assertEqual(status, 200)
            self.assertEqual(graph_payload["actionGraph"]["actions"][0]["action_id"], "apply-1")
            apply_event = next(
                node["node_id"]
                for node in graph_payload["eventGraph"]["nodes"]
                if node["type"] == "file_edit"
            )
            analyzer_output = json.dumps({
                "symptoms": [{"type": "wrong_output", "summary": "implementation is wrong"}],
                "suspicious_actions": [{"action_id": "apply-1", "reason": "source edit"}],
                "suspicious_events": [{"event_id": apply_event, "action_id": "apply-1", "reason": "wrong edit"}],
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
            self.assertEqual(payload["diagnosis"]["suspicious_events"][0]["action_id"], "apply-1")
            analyze.assert_called_once()
            prompt = analyze.call_args.args[0]
            self.assertIn(str((change / "graph/action_graph.json").resolve()), prompt)
            self.assertIn(str((change / "graph/event_graph.json").resolve()), prompt)
            self.assertNotIn('"nodes":', prompt)


if __name__ == "__main__":
    unittest.main()
