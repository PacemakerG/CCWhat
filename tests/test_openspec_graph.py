"""Tests for OpenSpec graph synchronization."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner

from ccwhat.cli import cli
from ccwhat.openspec_graph import sync_openspec_graph
from viewer.server import _load_openspec_graph_response


def _make_change(root: Path, name: str = "demo-change") -> Path:
    change = root / "openspec" / "changes" / name
    (change / "specs" / "demo").mkdir(parents=True)
    (change / ".openspec.yaml").write_text("schema: spec-driven\n", encoding="utf-8")
    (change / "proposal.md").write_text("## Why\n\nDemo.\n", encoding="utf-8")
    (change / "design.md").write_text("## Context\n\nDemo.\n", encoding="utf-8")
    (change / "specs" / "demo" / "spec.md").write_text("## ADDED Requirements\n\n### Requirement: Demo\n", encoding="utf-8")
    (change / "tasks.md").write_text("## 1. Work\n\n- [x] 1.1 Demo task\n", encoding="utf-8")
    return change


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
            self.assertEqual(actions["proposal"]["status"], "observed")
            self.assertEqual(actions["specs"]["status"], "observed")
            self.assertEqual(actions["apply"]["status"], "observed")
            self.assertEqual(actions["verify"]["status"], "observed")

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


if __name__ == "__main__":
    unittest.main()
