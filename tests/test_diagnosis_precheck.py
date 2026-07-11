"""Tests for deterministic graph-diagnosis prechecks."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ccwhat.diagnosis.precheck import FINDING_FIELDS, check_artifacts, check_basic_verify, run_prechecks


def _action_graph(*actions: tuple[str, str, list[str]]) -> dict:
    return {
        "actions": [
            {
                "action_id": action_id,
                "type": action_type,
                "status": "observed" if event_ids else "not_observed",
                "event_ids": event_ids,
            }
            for action_id, action_type, event_ids in actions
        ]
    }


def _node(
    event_id: str,
    type: str,
    *,
    tool: str = "",
    call_id: str = "",
    command: str = "",
    error: bool = False,
) -> dict:
    return {
        "node_id": event_id,
        "type": type,
        "label": command or type,
        "data": {
            "tool_name": tool,
            "tool_call_id": call_id,
            "command": command or None,
            "files": ["ccwhat/demo.py"] if type == "file_edit" else [],
            "result_summary": "FAILED test" if error else "passed",
            "is_error": error,
        },
    }


class ArtifactPrecheckTests(unittest.TestCase):
    def test_reports_only_observed_missing_artifact_with_fixed_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            findings = check_artifacts(root, _action_graph(
                ("tasks-1", "tasks", ["E1"]),
                ("design-1", "design", []),
            ))

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["type"], "artifact_missing")
        self.assertEqual(findings[0]["action_id"], "tasks-1")
        self.assertEqual(set(findings[0]), FINDING_FIELDS)

    def test_valid_artifacts_produce_no_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "specs/demo").mkdir(parents=True)
            (root / "proposal.md").write_text("## Why\n\nDemo\n", encoding="utf-8")
            (root / "specs/demo/spec.md").write_text("### Requirement: Demo\n", encoding="utf-8")
            (root / "design.md").write_text("## Context\n\nDemo\n", encoding="utf-8")
            (root / "tasks.md").write_text("- [ ] 1.1 Demo\n", encoding="utf-8")
            graph = _action_graph(
                ("proposal-1", "proposal", ["E1"]),
                ("specs-1", "specs", ["E2"]),
                ("design-1", "design", ["E3"]),
                ("tasks-1", "tasks", ["E4"]),
            )
            findings = check_artifacts(root, graph)

        self.assertEqual(findings, [])

    def test_run_prechecks_numbers_findings_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph = _action_graph(("proposal-1", "proposal", ["E1"]))
            findings = run_prechecks(tmp, graph, {"nodes": []})

        self.assertEqual(findings[0]["finding_id"], "PF-001")


class BasicVerifyPrecheckTests(unittest.TestCase):
    def test_missing_verification_after_edit(self) -> None:
        action_graph = _action_graph(("apply-1", "apply", ["E1"]))
        findings = check_basic_verify(action_graph, {"nodes": [_node("E1", "file_edit", tool="Edit")]})

        self.assertEqual([item["type"] for item in findings], ["verification_missing"])
        self.assertEqual(findings[0]["event_ids"], ["E1"])

    def test_failed_verification_references_call_and_result(self) -> None:
        action_graph = _action_graph(
            ("apply-1", "apply", ["E1"]),
            ("verify-1", "verify", ["E2", "E3"]),
        )
        event_graph = {"nodes": [
            _node("E1", "file_edit", tool="Edit"),
            _node("E2", "command", tool="Bash", call_id="tool-test", command="pytest"),
            _node("E3", "tool_result", call_id="tool-test", error=True),
        ]}

        findings = check_basic_verify(action_graph, event_graph)

        self.assertEqual([item["type"] for item in findings], ["verification_failed"])
        self.assertEqual(findings[0]["event_ids"], ["E2", "E3"])
        self.assertEqual(findings[0]["action_id"], "verify-1")

    def test_missing_result_is_reported(self) -> None:
        action_graph = _action_graph(
            ("apply-1", "apply", ["E1"]),
            ("verify-1", "verify", ["E2"]),
        )
        nodes = [
            _node("E1", "file_edit", tool="Edit"),
            _node("E2", "command", tool="Bash", call_id="tool-test", command="npm test"),
        ]

        findings = check_basic_verify(action_graph, {"nodes": nodes})

        self.assertEqual([item["type"] for item in findings], ["verification_result_missing"])

    def test_verification_before_last_edit_is_stale(self) -> None:
        action_graph = _action_graph(
            ("verify-1", "verify", ["E1", "E2"]),
            ("apply-1", "apply", ["E3"]),
        )
        nodes = [
            _node("E1", "command", tool="Bash", call_id="tool-test", command="pytest"),
            _node("E2", "tool_result", call_id="tool-test"),
            _node("E3", "file_edit", tool="Edit"),
        ]

        findings = check_basic_verify(action_graph, {"nodes": nodes})

        self.assertEqual([item["type"] for item in findings], ["verification_stale"])
        self.assertEqual(findings[0]["event_ids"], ["E1", "E3"])

    def test_non_error_result_after_last_edit_produces_no_finding(self) -> None:
        action_graph = _action_graph(
            ("apply-1", "apply", ["E1"]),
            ("verify-1", "verify", ["E2", "E3"]),
        )
        nodes = [
            _node("E1", "file_edit", tool="Edit"),
            _node("E2", "command", tool="Bash", call_id="tool-test", command="pytest"),
            _node("E3", "tool_result", call_id="tool-test"),
        ]

        findings = check_basic_verify(action_graph, {"nodes": nodes})

        self.assertEqual(findings, [])

    def test_latest_success_supersedes_earlier_failed_verification(self) -> None:
        action_graph = _action_graph(
            ("apply-1", "apply", ["E1"]),
            ("verify-1", "verify", ["E2", "E3", "E4", "E5"]),
        )
        nodes = [
            _node("E1", "file_edit", tool="Edit"),
            _node("E2", "command", tool="Bash", call_id="tool-fail", command="pytest"),
            _node("E3", "tool_result", call_id="tool-fail", error=True),
            _node("E4", "command", tool="Bash", call_id="tool-pass", command="pytest"),
            _node("E5", "tool_result", call_id="tool-pass"),
        ]

        findings = check_basic_verify(action_graph, {"nodes": nodes})

        self.assertEqual(findings, [])

    def test_zero_failed_text_is_not_failure(self) -> None:
        action_graph = _action_graph(
            ("apply-1", "apply", ["E1"]),
            ("verify-1", "verify", ["E2", "E3"]),
        )
        result = _node("E3", "tool_result", call_id="tool-pass")
        result["data"]["result_summary"] = "12 passed, 0 failed"
        result["label"] = "12 passed, 0 failed"
        nodes = [
            _node("E1", "file_edit", tool="Edit"),
            _node("E2", "command", tool="Bash", call_id="tool-pass", command="pytest"),
            result,
        ]

        findings = check_basic_verify(action_graph, {"nodes": nodes})

        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
