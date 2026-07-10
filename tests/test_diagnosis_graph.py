"""Tests for OpenSpec action graph diagnosis."""

from __future__ import annotations

import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner

from ccwhat.cli import cli
from ccwhat.diagnosis.action_graph import build_openspec_action_graph
from ccwhat.diagnosis.engine import DiagnosisEngine
from ccwhat.diagnosis.event_graph import build_event_graph
from ccwhat.diagnosis.mapping import map_events_to_actions
from ccwhat.diagnosis.symptoms import detect_symptoms
from ccwhat.task_dataset import build_dataset_bundle
from ccwhat.task_segments.models import EvidenceBundle, NormalizedEvent, TaskSegment, TaskSegmentationResult
from ccwhat.task_segments.events import normalize_main_entries


def _event(
    event_id: str,
    event_type: str,
    text: str = "",
    *,
    tool_name: str | None = None,
    command: str | None = None,
    files: list[str] | None = None,
    turn_index: int = 1,
    raw_ref: dict | None = None,
) -> NormalizedEvent:
    return NormalizedEvent(
        event_id=event_id,
        source="main",
        agent_id="main",
        turn_index=turn_index,
        event_type=event_type,
        text=text,
        tool_name=tool_name,
        command=command,
        files=files or [],
        timestamp=f"2026-01-01T00:00:{turn_index:02d}Z",
        raw_ref=raw_ref or {},
        metadata={},
    )


def _openspec_events(*, include_verify: bool = False, complete_tasks: bool = False) -> list[NormalizedEvent]:
    task_text = "- [x] 1.1 proposal\n" if complete_tasks else "- [ ] 1.1 proposal\n"
    events = [
        _event("main:1", "user_message", "Create an OpenSpec change", turn_index=1),
        _event("main:2", "file_edit", "proposal", tool_name="Write", files=["openspec/changes/demo/proposal.md"], turn_index=2),
        _event("main:3", "file_edit", "spec", tool_name="Write", files=["openspec/changes/demo/specs/action/spec.md"], turn_index=3),
        _event("main:4", "file_edit", "design", tool_name="Write", files=["openspec/changes/demo/design.md"], turn_index=4),
        _event("main:5", "file_edit", task_text, tool_name="Write", files=["openspec/changes/demo/tasks.md"], turn_index=5),
        _event("main:6", "file_edit", "code", tool_name="Edit", files=["ccwhat/foo.py"], turn_index=6),
    ]
    if include_verify:
        events.append(_event("main:7", "command", command="openspec validate demo --strict", tool_name="Bash", turn_index=7))
    events.append(_event("main:8", "final_claim", "Implementation complete.", turn_index=8))
    return events


def _bundle_dir(tmp_path: Path, *, include_verify: bool = False, complete_tasks: bool = False) -> Path:
    events = _openspec_events(include_verify=include_verify, complete_tasks=complete_tasks)
    task = TaskSegment(
        task_id="task-001",
        title="OpenSpec diagnosis fixture",
        task_type="feature",
        status="unevaluated",
        start_event_id="main:1",
        end_event_id="main:8",
        evidence=EvidenceBundle(
            files_changed=[
                "openspec/changes/demo/proposal.md",
                "openspec/changes/demo/specs/action/spec.md",
                "openspec/changes/demo/design.md",
                "openspec/changes/demo/tasks.md",
                "ccwhat/foo.py",
            ],
            commands=["openspec validate demo --strict"] if include_verify else [],
            final_claims=["Implementation complete."],
        ),
        final_claim="Implementation complete.",
    )
    bundle = build_dataset_bundle(
        session_metadata={"agent": "codex", "project_dir": "/repo", "repo": "CCWhat"},
        events=events,
        segmentation=TaskSegmentationResult(session_id="session-001", tasks=[task]),
        created_at="2026-07-08T00:00:00Z",
    )
    dataset_dir = tmp_path / "dataset"
    bundle.write_to_directory(dataset_dir)
    return dataset_dir


class DiagnosisGraphTests(unittest.TestCase):
    def test_claude_multi_block_entries_get_unique_ids_and_preserve_results(self) -> None:
        entries = [
            {
                "_fileLine": 1,
                "type": "assistant",
                "timestamp": "2026-01-01T00:00:00Z",
                "message": {"content": [
                    {"type": "tool_use", "id": "tool-1", "name": "Read", "input": {"file_path": "a.py"}},
                    {"type": "tool_use", "id": "tool-2", "name": "Edit", "input": {"file_path": "a.py", "new_string": "bad"}},
                ]},
            },
            {
                "_fileLine": 2,
                "type": "user",
                "timestamp": "2026-01-01T00:00:01Z",
                "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "tool-1", "content": "contents"},
                    {"type": "tool_result", "tool_use_id": "tool-2", "content": "edit failed", "is_error": True},
                ]},
            },
        ]

        events = normalize_main_entries(entries, "session-123")
        graph = build_event_graph({"events": [event.__dict__ for event in events]}).to_dict()

        self.assertEqual(len({event.event_id for event in events}), 4)
        self.assertEqual(len({node["node_id"] for node in graph["nodes"]}), 4)
        failed = next(node for node in graph["nodes"] if node["data"]["tool_call_id"] == "tool-2" and node["type"] == "tool_result")
        self.assertTrue(failed["data"]["is_error"])
        self.assertEqual(failed["data"]["result_summary"], "edit failed")
        self.assertEqual(failed["data"]["raw_ref"]["session_id"], "session-123")

    def test_event_graph_builds_core_nodes_and_edges(self) -> None:
        trace = {
            "events": [
                {"event_id": "e1", "event_type": "tool_call", "tool_name": "Read", "tool_use_id": "t1", "files": ["a.py"], "turn_index": 1},
                {"event_id": "e2", "event_type": "tool_result", "tool_use_id": "t1", "text": "contents", "turn_index": 1},
                {"event_id": "e3", "event_type": "tool_call", "tool_name": "Edit", "files": ["a.py"], "turn_index": 1},
                {"event_id": "e4", "event_type": "tool_call", "tool_name": "Bash", "command": "pytest", "turn_index": 1},
                {"event_id": "e5", "event_type": "error", "text": "FAILED test", "turn_index": 1},
                {"event_id": "e6", "event_type": "final_claim", "text": "complete", "turn_index": 1},
            ]
        }
        graph = build_event_graph(trace).to_dict()
        node_types = {node["type"] for node in graph["nodes"]}
        edge_types = {edge["type"] for edge in graph["edges"]}

        self.assertIn("file_read", node_types)
        self.assertIn("file_edit", node_types)
        self.assertIn("command", node_types)
        self.assertIn("error", node_types)
        self.assertIn("final_claim", node_types)
        self.assertIn("timeline", edge_types)
        self.assertIn("tool_result_of", edge_types)
        self.assertNotIn("reads_before_edit", edge_types)
        self.assertNotIn("edit_before_command", edge_types)
        self.assertNotIn("command_produces_error", edge_types)
        self.assertNotIn("claim_after_action", edge_types)

    def test_action_template_and_mapping(self) -> None:
        action_graph = build_openspec_action_graph()
        trace = {"events": [event.__dict__ for event in _openspec_events()]}
        map_events_to_actions(action_graph, trace)
        actions = {action.type: action for action in action_graph.actions}

        self.assertEqual([action.type for action in action_graph.actions[:7]], ["proposal", "specs", "design", "tasks", "apply", "verify", "archive"])
        self.assertEqual(len(action_graph.edges), 6)
        self.assertEqual(actions["proposal"].event_ids, ["main:2"])
        self.assertEqual(actions["specs"].event_ids, ["main:3"])
        self.assertEqual(actions["design"].event_ids, ["main:4"])
        self.assertEqual(actions["tasks"].event_ids, ["main:5"])
        self.assertEqual(actions["apply"].event_ids, ["main:6"])

    def test_final_claim_text_does_not_map_as_verify_command(self) -> None:
        action_graph = build_openspec_action_graph()
        events = [
            _event("main:1", "command", command="openspec validate demo --strict", tool_name="Bash", turn_index=1),
            _event("main:2", "assistant_text", "OpenSpec validate 通过，已完成。", turn_index=2),
        ]
        trace = {"events": [event.__dict__ for event in events]}

        map_events_to_actions(action_graph, trace)
        actions = {action.type: action for action in action_graph.actions}

        self.assertEqual(actions["verify"].event_ids, ["main:1"])

    def test_reading_openspec_artifact_does_not_mark_action_observed(self) -> None:
        action_graph = build_openspec_action_graph()
        trace = {"events": [{
            "event_id": "main:1",
            "event_type": "tool_call",
            "tool_name": "Read",
            "files": ["openspec/changes/demo/proposal.md"],
        }]}

        map_events_to_actions(action_graph, trace)
        actions = {action.type: action for action in action_graph.actions}

        self.assertEqual(actions["proposal"].status, "not_observed")
        self.assertFalse(actions["proposal"].event_ids)
        self.assertEqual(len(action_graph.actions), 7)

    def test_symptoms_for_missing_verify_and_unsupported_claim(self) -> None:
        trace = {"events": [event.__dict__ for event in _openspec_events()], "final_claim": "Implementation complete.", "changes": []}
        action_graph = build_openspec_action_graph()
        map_events_to_actions(action_graph, trace)
        symptoms = detect_symptoms(action_graph, trace)
        symptom_types = {symptom.type for symptom in symptoms}

        self.assertIn("missing_required_action", symptom_types)
        self.assertIn("unsupported_final_claim", symptom_types)

    def test_engine_generates_causal_chains(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dataset_dir = _bundle_dir(Path(tmp))
            event_graph, action_graph, diagnosis = DiagnosisEngine().diagnose_dataset_task(dataset_dir, "task-001")

        self.assertIn("nodes", event_graph)
        self.assertEqual(action_graph["workflow"], "openspec")
        self.assertTrue(diagnosis["symptoms"])
        self.assertTrue(diagnosis["causal_chains"])
        self.assertGreaterEqual(diagnosis["causal_chains"][0]["score"], 50)


class DiagnosisCliTests(unittest.TestCase):
    def test_cli_writes_outputs_for_dataset_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset_dir = _bundle_dir(root)
            output_dir = root / "out"
            result = CliRunner().invoke(cli, [
                "diagnose",
                "--dataset", str(dataset_dir),
                "--task-id", "task-001",
                "--output", str(output_dir),
                "--no-llm",
            ])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertTrue((output_dir / "event_graph.json").exists())
            self.assertTrue((output_dir / "action_graph.json").exists())
            self.assertTrue((output_dir / "diagnosis.json").exists())
            diagnosis = json.loads((output_dir / "diagnosis.json").read_text(encoding="utf-8"))
            self.assertEqual(diagnosis["task_id"], "task-001")

    def test_cli_supports_dataset_tar_and_missing_task_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset_dir = _bundle_dir(root)
            tar_path = root / "dataset.tar.gz"
            with tarfile.open(tar_path, "w:gz") as tar:
                tar.add(dataset_dir, arcname="dataset")

            result = CliRunner().invoke(cli, [
                "diagnose",
                "--dataset", str(tar_path),
                "--task-id", "missing",
                "--output", str(root / "out"),
                "--no-llm",
            ])

            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("Task id 'missing' was not found", result.output)

    def test_cli_rejects_llm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset_dir = _bundle_dir(root)
            result = CliRunner().invoke(cli, [
                "diagnose",
                "--dataset", str(dataset_dir),
                "--task-id", "task-001",
                "--output", str(root / "out"),
                "--llm",
            ])

            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("LLM diagnosis is not supported", result.output)


if __name__ == "__main__":
    unittest.main()
