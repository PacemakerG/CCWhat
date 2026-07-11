"""Tests for Session graph user-feedback diagnosis."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from ccwhat.diagnosis.feedback import (
    analyze_graph_feedback,
    build_graph_attribution_prompt,
    parse_graph_attribution_output,
    validate_graph_attribution_result,
)


ACTION_GRAPH = {
    "workflow": "openspec",
    "actions": [
        {"action_id": "A5", "type": "apply", "status": "observed", "event_ids": ["E40"], "evidence": []},
        {"action_id": "A6", "type": "verify", "status": "failed", "event_ids": ["E41"], "evidence": []},
    ],
    "edges": [],
}
EVENT_GRAPH = {
    "nodes": [
        {
            "node_id": "E40",
            "type": "file_edit",
            "label": "Edit routing.py",
            "data": {"files": ["routing.py"], "tool_name": "Edit", "tool_input": {"new_string": "wrong"}},
        },
        {
            "node_id": "E41",
            "type": "tool_result",
            "label": "FAILED routing test",
            "data": {"result_summary": "FAILED routing test", "is_error": True},
        },
    ],
    "edges": [],
}


@contextmanager
def _diagnosis_files():
    with tempfile.TemporaryDirectory() as tmp:
        change_root = Path(tmp) / "openspec/changes/demo"
        graph_dir = change_root / "graph"
        graph_dir.mkdir(parents=True)
        action_path = graph_dir / "action_graph.json"
        event_path = graph_dir / "event_graph.json"
        action_path.write_text(json.dumps(ACTION_GRAPH), encoding="utf-8")
        event_path.write_text(json.dumps(EVENT_GRAPH), encoding="utf-8")
        yield {
            "action_graph_path": action_path,
            "event_graph_path": event_path,
            "change_root": change_root,
        }


class GraphFeedbackTests(unittest.TestCase):
    def test_prompt_requires_simplified_chinese_output(self) -> None:
        with _diagnosis_files() as paths:
            prompt = build_graph_attribution_prompt(
                "按钮没有生效",
                **paths,
                precheck_findings=[],
            )

        self.assertIn("必须使用简体中文", prompt)
        self.assertIn("Action ID 和 Event ID 保持原样", prompt)

    def test_prompt_passes_paths_and_findings_without_graph_body(self) -> None:
        with _diagnosis_files() as paths:
            prompt = build_graph_attribution_prompt(
                "按钮没有生效",
                **paths,
                precheck_findings=[{
                    "finding_id": "PF-001",
                    "type": "verification_missing",
                    "action_id": "A5",
                    "event_ids": ["E40"],
                    "target": "routing.py",
                    "expected": "修改后验证",
                    "observed": "没有验证",
                }],
            )

        self.assertIn(str(paths["action_graph_path"].resolve()), prompt)
        self.assertIn(str(paths["event_graph_path"].resolve()), prompt)
        self.assertIn("verification_missing", prompt)
        self.assertNotIn("Edit routing.py", prompt)
        self.assertNotIn('"nodes"', prompt)

    def test_parse_accepts_markdown_json_fence(self) -> None:
        parsed = parse_graph_attribution_output('```json\n{"summary":"ok"}\n```')
        self.assertEqual(parsed["summary"], "ok")

    def test_validate_removes_fabricated_ids_and_corrects_mapping(self) -> None:
        result = validate_graph_attribution_result(
            {
                "symptoms": [{"type": "wrong_output", "summary": "wrong route"}],
                "suspicious_actions": [
                    {"action_id": "A5", "reason": "edited route"},
                    {"action_id": "A99", "reason": "invented"},
                ],
                "suspicious_events": [
                    {"event_id": "E40", "action_id": "A6", "reason": "wrong implementation"},
                    {"event_id": "E999", "action_id": "A5", "reason": "invented"},
                ],
                "missing_evidence": [],
                "summary": "Apply is suspicious.",
            },
            ACTION_GRAPH,
            EVENT_GRAPH,
        )

        self.assertEqual(result["status"], "complete")
        self.assertEqual([item["action_id"] for item in result["suspicious_actions"]], ["A5"])
        self.assertEqual([item["event_id"] for item in result["suspicious_events"]], ["E40"])
        self.assertEqual(result["suspicious_events"][0]["action_id"], "A5")
        self.assertTrue(result["suspicious_events"][0]["mapping_adjusted"])
        self.assertTrue(any("A99" in item for item in result["missing_evidence"]))
        self.assertTrue(any("E999" in item for item in result["missing_evidence"]))

    def test_analyze_reuses_local_analyzer_runner_once(self) -> None:
        raw = json.dumps({
            "symptoms": [{"type": "validation_failed", "summary": "test failed"}],
            "suspicious_actions": [{"action_id": "A6", "reason": "failed verification"}],
            "suspicious_events": [{"event_id": "E41", "action_id": "A6", "reason": "failed result"}],
            "missing_evidence": [],
            "summary": "Verification failed.",
        })
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, stdout=raw, stderr="")

        with _diagnosis_files() as paths:
            result = analyze_graph_feedback(
                feedback="The routing test failed",
                action_graph=ACTION_GRAPH,
                event_graph=EVENT_GRAPH,
                **paths,
                analyzer_agent="claude",
                runner=runner,
            )

        self.assertTrue(result["available"])
        self.assertEqual(result["suspicious_events"][0]["event_id"], "E41")
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][0][0].endswith("claude"))
        self.assertEqual(calls[0][0][1], "-p")
        self.assertIn("The routing test failed", calls[0][1]["input"])
        self.assertIn("verification_missing", calls[0][1]["input"])

    def test_analyzer_failure_returns_structured_unavailable_result(self) -> None:
        def runner(command, **kwargs):
            raise FileNotFoundError(command[0])

        with _diagnosis_files() as paths:
            result = analyze_graph_feedback(
                feedback="wrong output",
                action_graph=ACTION_GRAPH,
                event_graph=EVENT_GRAPH,
                **paths,
                analyzer_agent="claude",
                runner=runner,
            )

        self.assertFalse(result["available"])
        self.assertEqual(result["code"], "analyzer_not_found")
        self.assertFalse(result["suspicious_events"])

    def test_hidden_error_can_be_returned_when_precheck_is_empty(self) -> None:
        action_graph = {
            "actions": [{"action_id": "A5", "type": "apply", "status": "observed", "event_ids": ["E40"]}],
            "edges": [],
        }
        event_graph = {
            "nodes": [{"node_id": "E40", "type": "assistant_text", "label": "implementation choice", "data": {}}],
            "edges": [],
        }
        raw = json.dumps({
            "symptoms": [{"type": "wrong_output", "summary": "需求理解偏差"}],
            "suspicious_actions": [{"action_id": "A5", "reason": "实现方向与需求不一致"}],
            "suspicious_events": [{"event_id": "E40", "action_id": "A5", "reason": "错误实现决策"}],
            "missing_evidence": [],
            "summary": "存在隐性实现偏差。",
        })
        with tempfile.TemporaryDirectory() as tmp:
            change_root = Path(tmp) / "change"
            graph_dir = change_root / "graph"
            graph_dir.mkdir(parents=True)
            action_path = graph_dir / "action_graph.json"
            event_path = graph_dir / "event_graph.json"
            action_path.write_text(json.dumps(action_graph), encoding="utf-8")
            event_path.write_text(json.dumps(event_graph), encoding="utf-8")
            calls = []

            def runner(command, **kwargs):
                calls.append(kwargs["input"])
                return subprocess.CompletedProcess(command, 0, stdout=raw, stderr="")

            result = analyze_graph_feedback(
                feedback="按钮行为不符合需求",
                action_graph=action_graph,
                event_graph=event_graph,
                action_graph_path=action_path,
                event_graph_path=event_path,
                change_root=change_root,
                analyzer_agent="claude",
                runner=runner,
            )

        self.assertTrue(result["available"])
        self.assertEqual(result["suspicious_events"][0]["event_id"], "E40")
        self.assertIn('"precheck_findings": []', calls[0])

    def test_first_parse_fails_then_fix_succeeds(self) -> None:
        """Unescaped quotes cause first parse failure, format fix recovers."""
        raw_valid = json.dumps({
            "symptoms": [{"type": "validation_failed", "summary": "test failed"}],
            "suspicious_actions": [{"action_id": "A6", "reason": "failed verification"}],
            "suspicious_events": [{"event_id": "E41", "action_id": "A6", "reason": "failed result"}],
            "missing_evidence": [],
            "summary": "Verification failed.",
        })
        raw_broken = '{"summary": "contains unescaped "quotes" inside"}'

        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            # First call returns broken JSON, second call returns valid JSON
            if len(calls) == 1:
                return subprocess.CompletedProcess(command, 0, stdout=raw_broken, stderr="")
            return subprocess.CompletedProcess(command, 0, stdout=raw_valid, stderr="")

        with _diagnosis_files() as paths:
            result = analyze_graph_feedback(
                feedback="The routing test failed",
                action_graph=ACTION_GRAPH,
                event_graph=EVENT_GRAPH,
                **paths,
                analyzer_agent="claude",
                runner=runner,
            )

        self.assertTrue(result["available"])
        self.assertEqual(result["suspicious_events"][0]["event_id"], "E41")
        # One main analysis + one format fix = 2 calls
        self.assertEqual(len(calls), 2)

    def test_first_parse_ok_only_one_call(self) -> None:
        """First parse succeeds → no second Analyzer call."""
        raw_valid = json.dumps({
            "symptoms": [{"type": "validation_failed", "summary": "test failed"}],
            "suspicious_actions": [{"action_id": "A6", "reason": "failed verification"}],
            "suspicious_events": [{"event_id": "E41", "action_id": "A6", "reason": "failed result"}],
            "missing_evidence": [],
            "summary": "Verification failed.",
        })

        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, stdout=raw_valid, stderr="")

        with _diagnosis_files() as paths:
            result = analyze_graph_feedback(
                feedback="The routing test failed",
                action_graph=ACTION_GRAPH,
                event_graph=EVENT_GRAPH,
                **paths,
                analyzer_agent="claude",
                runner=runner,
            )

        self.assertTrue(result["available"])
        self.assertEqual(len(calls), 1)

    def test_fix_also_fails_degrades(self) -> None:
        """Both first and fix attempt return broken JSON → unavailable."""
        raw_broken = '{"summary": "contains unescaped "quotes" inside"}'

        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, stdout=raw_broken, stderr="")

        with _diagnosis_files() as paths:
            result = analyze_graph_feedback(
                feedback="The routing test failed",
                action_graph=ACTION_GRAPH,
                event_graph=EVENT_GRAPH,
                **paths,
                analyzer_agent="claude",
                runner=runner,
            )

        self.assertFalse(result["available"])
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["code"], "invalid_analyzer_json")
        self.assertEqual(len(calls), 2)

    def test_missing_graph_path_returns_structured_unavailable_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = analyze_graph_feedback(
                feedback="wrong output",
                action_graph=ACTION_GRAPH,
                event_graph=EVENT_GRAPH,
                action_graph_path=root / "missing-action.json",
                event_graph_path=root / "missing-event.json",
                change_root=root,
            )

        self.assertFalse(result["available"])
        self.assertEqual(result["code"], "diagnosis_input_unavailable")


if __name__ == "__main__":
    unittest.main()
