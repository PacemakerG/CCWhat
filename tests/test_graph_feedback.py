"""Tests for Session graph user-feedback diagnosis."""

from __future__ import annotations

import json
import subprocess
import unittest

from ccwhat.diagnosis.feedback import (
    analyze_graph_feedback,
    build_compact_graph_context,
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


class GraphFeedbackTests(unittest.TestCase):
    def test_compact_context_keeps_graph_ids_and_tool_evidence(self) -> None:
        context = json.loads(build_compact_graph_context(ACTION_GRAPH, EVENT_GRAPH))

        self.assertEqual(context["actions"][0]["event_ids"], ["E40"])
        self.assertEqual(context["events"][0]["event_id"], "E40")
        self.assertIn("new_string", context["events"][0]["tool_input"])

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

        result = analyze_graph_feedback(
            feedback="The routing test failed",
            action_graph=ACTION_GRAPH,
            event_graph=EVENT_GRAPH,
            analyzer_agent="claude",
            runner=runner,
        )

        self.assertTrue(result["available"])
        self.assertEqual(result["suspicious_events"][0]["event_id"], "E41")
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][0][0].endswith("claude"))
        self.assertEqual(calls[0][0][1], "-p")
        self.assertIn("The routing test failed", calls[0][1]["input"])

    def test_analyzer_failure_returns_structured_unavailable_result(self) -> None:
        def runner(command, **kwargs):
            raise FileNotFoundError(command[0])

        result = analyze_graph_feedback(
            feedback="wrong output",
            action_graph=ACTION_GRAPH,
            event_graph=EVENT_GRAPH,
            analyzer_agent="claude",
            runner=runner,
        )

        self.assertFalse(result["available"])
        self.assertEqual(result["code"], "analyzer_not_found")
        self.assertFalse(result["suspicious_events"])


if __name__ == "__main__":
    unittest.main()
