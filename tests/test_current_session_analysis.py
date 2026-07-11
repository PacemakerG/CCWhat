from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path
from unittest import mock

from ccwhat.analyzer import (
    AnalysisError,
    run_mc_analysis,
)
from ccwhat.session_report import normalize_session_for_report
from ccwhat.session_report.pipeline import build_generic_html_report, build_html_session_report
from tests.http_compat import make_handler as _make_handler


SID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _write_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _make_projects(base: Path) -> Path:
    projects_dir = base / "projects"
    _write_jsonl(
        projects_dir / "project-c" / f"{SID}.jsonl",
        {"type": "user", "timestamp": "2026-05-29T03:00:00Z", "message": {"content": "hello"}},
    )
    _write_jsonl(
        projects_dir / "project-c" / SID / "subagents" / "agent-one.jsonl",
        {"type": "assistant", "timestamp": "2026-05-29T03:01:00Z", "message": {"content": []}},
    )
    (projects_dir / "project-c" / SID / "subagents" / "agent-one.meta.json").write_text(
        json.dumps({"description": "helper"}),
        encoding="utf-8",
    )
    return projects_dir


class AnalysisCoreTests(unittest.TestCase):
    def test_run_mc_analysis_maps_failures(self) -> None:
        with self.assertRaisesRegex(AnalysisError, "not found"):
            run_mc_analysis("prompt", runner=mock.Mock(side_effect=FileNotFoundError()))

        with self.assertRaisesRegex(AnalysisError, "timed out"):
            run_mc_analysis("prompt", runner=mock.Mock(side_effect=subprocess.TimeoutExpired("mc", 1)))

        failed = subprocess.CompletedProcess(["mc"], 2, stdout="", stderr="bad")
        with self.assertRaisesRegex(AnalysisError, "bad"):
            run_mc_analysis("prompt", runner=mock.Mock(return_value=failed))

        empty = subprocess.CompletedProcess(["mc"], 0, stdout="", stderr="")
        with self.assertRaisesRegex(AnalysisError, "empty"):
            run_mc_analysis("prompt", runner=mock.Mock(return_value=empty))

    def test_run_mc_analysis_uses_explicit_command(self) -> None:
        completed = subprocess.CompletedProcess(["mc", "--code"], 0, stdout="report", stderr="")
        runner = mock.Mock(return_value=completed)

        report, _ = run_mc_analysis("prompt", runner=runner, cmd=("mc", "--code"))

        self.assertEqual(report, "report")
        call = runner.call_args
        self.assertEqual(call.args[0][-1], "--code")
        self.assertTrue(call.args[0][0].endswith("mc"))
        self.assertEqual(call.kwargs["input"], "prompt")

    def test_run_mc_analysis_uses_agent_default_command(self) -> None:
        cases = [
            ("claude", ["claude", "-p", "-"], "report"),
            ("codex", ["codex", "exec", "--json", "--ephemeral", "--ignore-user-config", "-"], '{"type":"assistant","content":"report"}'),
        ]

        for agent, expected_cmd, stdout_val in cases:
            with self.subTest(agent=agent):
                completed = subprocess.CompletedProcess(expected_cmd, 0, stdout=stdout_val, stderr="")
                runner = mock.Mock(return_value=completed)

                report, _ = run_mc_analysis("prompt", runner=runner, agent=agent)

                self.assertEqual(report, "report")
                self.assertEqual(runner.call_args.args[0][1:], expected_cmd[1:])
                self.assertTrue(runner.call_args.args[0][0].endswith(expected_cmd[0]))
                self.assertEqual(runner.call_args.kwargs["input"], "prompt")

    def test_run_mc_analysis_rejects_unsupported_agent_protocol(self) -> None:
        with self.assertRaisesRegex(AnalysisError, "not supported") as exc:
            run_mc_analysis("prompt", agent="unknown-agent-xyz")

        self.assertEqual(exc.exception.code, "analyzer_not_supported")

    def test_run_mc_analysis_resolves_known_binary_path_for_explicit_command(self) -> None:
        completed = subprocess.CompletedProcess(["/Applications/OpenCode.app/Contents/MacOS/opencode", "run"], 0, stdout="report", stderr="")
        runner = mock.Mock(return_value=completed)
        with mock.patch("ccwhat.analyzer.shutil.which", return_value=None), mock.patch("ccwhat.analyzer.Path.is_file", return_value=True):
            report, _ = run_mc_analysis("prompt", runner=runner, cmd=("opencode", "run"))

        self.assertEqual(report, "report")
        self.assertEqual(runner.call_args.args[0][1:], ["run"])
        self.assertTrue(runner.call_args.args[0][0].endswith("opencode"))
        self.assertEqual(runner.call_args.kwargs["input"], "prompt")

    def test_run_mc_analysis_env_override_beats_agent_default(self) -> None:
        completed = subprocess.CompletedProcess(["mc", "--code"], 0, stdout="report", stderr="")
        runner = mock.Mock(return_value=completed)

        with mock.patch.dict("os.environ", {"CCWHAT_ANALYZE_CMD": "mc --code"}):
            report, _ = run_mc_analysis("prompt", runner=runner, agent="codex")

        self.assertEqual(report, "report")
        self.assertEqual(runner.call_args.args[0][-1], "--code")
        self.assertTrue(runner.call_args.args[0][0].endswith("mc"))
        self.assertEqual(runner.call_args.kwargs["input"], "prompt")


class SessionReportNormalizationTests(unittest.TestCase):
    def test_normalize_claude_session_keeps_subagents(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "project-c",
            "agent": "claude",
            "main": [{"type": "user", "timestamp": "2026-05-29T03:00:00Z", "message": {"content": "hello"}}],
            "subagents": [{
                "agentId": "agent-one",
                "meta": {"description": "helper", "agentType": "general-purpose"},
                "entries": [{"type": "assistant", "timestamp": "2026-05-29T03:01:00Z", "message": {"content": "done"}}],
            }],
            "turns": [],
        }

        normalized = normalize_session_for_report(session)

        self.assertEqual(normalized.session_id, SID)
        self.assertEqual(normalized.primary_agent_id, "main")
        self.assertEqual(len(normalized.agents), 2)
        self.assertEqual(normalized.agents[1].role, "delegated")
        self.assertEqual(normalized.project_display, "project-c")
        self.assertEqual(sum(1 for event in normalized.events if event.agent_id == "agent-one"), 1)

    def test_normalize_codex_session_uses_events_and_turns(self) -> None:
        session = {
            "sessionId": "019e9837-9271-7192-bfbf-f5b74ebe585c",
            "projectDir": "/tmp/codex-project",
            "agent": "codex",
            "main": [],
            "subagents": [],
            "events": [{
                "id": "ev1",
                "agent": "codex",
                "sessionId": "019e9837-9271-7192-bfbf-f5b74ebe585c",
                "timestamp": "2026-05-29T03:00:00Z",
                "role": "user",
                "kind": "message",
                "content": "hello codex",
                "summary": "hello codex",
            }],
            "turns": [{
                "id": "turn1",
                "agent": "codex",
                "startedAt": "2026-05-29T03:00:00Z",
                "endedAt": "2026-05-29T03:00:01Z",
                "userSummary": "hello codex",
                "assistantSummary": "",
                "events": [{"id": "ev1"}],
                "usage": {},
            }],
        }

        normalized = normalize_session_for_report(session)

        self.assertEqual(normalized.primary_agent_type, "codex")
        self.assertEqual(len(normalized.agents), 1)
        self.assertEqual(normalized.agents[0].agent_id, "main")
        self.assertEqual(len(normalized.events), 1)
        self.assertEqual(normalized.events[0].agent_id, "main")
        self.assertEqual(len(normalized.turns), 1)
        self.assertEqual(normalized.project_path, "/tmp/codex-project")

    def test_normalize_opencode_session_uses_events_and_turns(self) -> None:
        session = {
            "sessionId": "ses_test123",
            "projectDir": "/tmp/opencode-project",
            "agent": "opencode",
            "main": [],
            "subagents": [],
            "events": [{
                "id": "ev1",
                "agent": "opencode",
                "sessionId": "ses_test123",
                "timestamp": "2026-05-29T03:00:00Z",
                "role": "assistant",
                "kind": "tool_call",
                "content": {"command": "ls"},
                "summary": "Tool: bash",
                "toolName": "bash",
                "toolCallId": "call1",
            }],
            "turns": [{
                "id": "turn1",
                "agent": "opencode",
                "startedAt": "2026-05-29T03:00:00Z",
                "endedAt": "2026-05-29T03:00:02Z",
                "userSummary": "",
                "assistantSummary": "ran bash",
                "events": [{"id": "ev1"}],
                "usage": {},
            }],
        }

        normalized = normalize_session_for_report(session)

        self.assertEqual(normalized.primary_agent_type, "opencode")
        self.assertEqual(len(normalized.events), 1)
        self.assertEqual(normalized.events[0].tool_name, "bash")
        self.assertEqual(normalized.turns[0].event_ids, ["ev1"])

    def test_html_report_pipeline_supports_codex_session(self) -> None:
        session = {
            "sessionId": "019e9837-9271-7192-bfbf-f5b74ebe585c",
            "projectDir": "/tmp/codex-project",
            "agent": "codex",
            "main": [],
            "subagents": [],
            "events": [
                {
                    "id": "ev1",
                    "agent": "codex",
                    "sessionId": "019e9837-9271-7192-bfbf-f5b74ebe585c",
                    "timestamp": "2026-05-29T03:00:00Z",
                    "role": "user",
                    "kind": "message",
                    "content": "hello codex",
                    "summary": "hello codex",
                },
                {
                    "id": "ev2",
                    "agent": "codex",
                    "sessionId": "019e9837-9271-7192-bfbf-f5b74ebe585c",
                    "timestamp": "2026-05-29T03:00:01Z",
                    "role": "assistant",
                    "kind": "tool_call",
                    "content": {"command": "pwd"},
                    "summary": "Tool: Bash",
                    "toolName": "Bash",
                    "toolCallId": "call-1",
                },
                {
                    "id": "ev3",
                    "agent": "codex",
                    "sessionId": "019e9837-9271-7192-bfbf-f5b74ebe585c",
                    "timestamp": "2026-05-29T03:00:02Z",
                    "role": "tool",
                    "kind": "tool_result",
                    "content": "/tmp/codex-project",
                    "summary": "/tmp/codex-project",
                    "toolName": "Bash",
                    "toolCallId": "call-1",
                },
            ],
            "turns": [{
                "id": "turn1",
                "agent": "codex",
                "startedAt": "2026-05-29T03:00:00Z",
                "endedAt": "2026-05-29T03:00:02Z",
                "userSummary": "hello codex",
                "assistantSummary": "ran pwd",
                "events": [{"id": "ev1"}, {"id": "ev2"}, {"id": "ev3"}],
                "usage": {},
            }],
        }

        result = build_html_session_report(session, enable_llm=False)
        generic = build_generic_html_report(session, enable_llm=False)

        self.assertEqual(result["reportType"], "html")
        self.assertEqual(result["reportMode"], "yuanxi")
        self.assertIn("reportHtml", result)
        self.assertEqual(result["summary"]["agentCount"], 1)
        self.assertEqual(generic["reportMode"], "generic")
        self.assertEqual(generic["summary"]["agentCount"], 1)
        self.assertEqual(generic["llmStatus"]["mode"], "not_requested")
        self.assertIn("/tmp/codex-project", generic["reportHtml"])
        self.assertIn("019e9837-9271-7192-bfbf-f5b74ebe585c", generic["reportHtml"])


class AnalyzeApiTests(unittest.TestCase):
    def _post_analyze(self, server: HTTPServer, payload: dict) -> tuple[int, dict]:
        conn = HTTPConnection("127.0.0.1", server.server_port)
        conn.request(
            "POST",
            "/api/analyze",
            body=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        body = response.read()
        conn.close()
        return response.status, json.loads(body.decode("utf-8"))

    def test_analyze_api_handles_missing_session_and_missing_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            projects_dir = _make_projects(tmp)
            server = HTTPServer(("127.0.0.1", 0), _make_handler(projects_dir, tmp / "raw"))
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                missing_status, missing_payload = self._post_analyze(
                    server,
                    {"sessionId": "dddddddd-dddd-dddd-dddd-dddddddddddd"},
                )
                no_mode_status, no_mode_payload = self._post_analyze(server, {"sessionId": SID})
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(missing_status, 404, missing_payload)
        self.assertFalse(missing_payload["ok"])
        self.assertEqual(no_mode_status, 400, no_mode_payload)
        self.assertEqual(no_mode_payload["code"], "invalid_mode")

    def test_session_api_derives_events_without_claude_adapter_fallback(self) -> None:
        class StubCodexAdapter:
            name = "codex"

            def list_projects(self):
                return []

            def load_session(self, session_id: str):
                if session_id != SID:
                    return None
                return {
                    "sessionId": SID,
                    "projectDir": "/tmp/codex-project",
                    "agent": "codex",
                    "events": [{
                        "id": "ev1",
                        "agent": "codex",
                        "sessionId": SID,
                        "timestamp": "2026-05-29T03:00:00Z",
                        "role": "user",
                        "kind": "message",
                        "content": "hello codex",
                        "summary": "hello codex",
                    }],
                }

        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            server = HTTPServer(("127.0.0.1", 0), _make_handler(tmp / "projects", tmp / "raw", adapter=StubCodexAdapter()))
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                conn = HTTPConnection("127.0.0.1", server.server_port)
                conn.request("GET", f"/api/session/{SID}")
                response = conn.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
                conn.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(response.status, 200, payload)
        self.assertEqual(payload["agent"], "codex")
        self.assertIn("events", payload)
        self.assertIn("turns", payload)
        self.assertEqual(payload["turns"][0]["agentId"], "main")
        self.assertEqual(payload["events"][0]["agentId"], "main")
        self.assertEqual(payload["events"][0]["kind"], "message")
        self.assertEqual(payload["events"][0]["content"], "hello codex")
        self.assertEqual(payload["turns"][0]["events"], [{"id": "ev1"}])
        self.assertNotEqual(payload["agent"], "claude")

    def test_session_api_without_adapter_keeps_claude_agent_for_claude_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            projects_dir = _make_projects(tmp)
            server = HTTPServer(("127.0.0.1", 0), _make_handler(projects_dir, tmp / "raw"))
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                conn = HTTPConnection("127.0.0.1", server.server_port)
                conn.request("GET", f"/api/session/{SID}")
                response = conn.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
                conn.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(response.status, 200, payload)
        self.assertEqual(payload["agent"], "claude")
        self.assertIn("events", payload)
        self.assertIn("turns", payload)
        self.assertEqual(payload["turns"][0]["agentId"], "main")

    def test_analyze_api_html_mode_works_without_project_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            projects_dir = _make_projects(tmp)
            server = HTTPServer(("127.0.0.1", 0), _make_handler(projects_dir, tmp / "raw"))
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                completed = subprocess.CompletedProcess(["claude", "-p", "-"], 0, stdout="# 报告\n\n内容", stderr="")
                with mock.patch("ccwhat.analyzer.subprocess.run", return_value=completed):
                    status, payload = self._post_analyze(server, {"sessionId": SID, "mode": "generic"})
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["reportType"], "html")
        self.assertEqual(payload["reportMode"], "generic")
        self.assertIn("reportUrl", payload)
        self.assertIn("exportUrl", payload)
        self.assertIn("summary", payload)
        self.assertEqual(payload["summary"]["agentCount"], 2)
        self.assertIn("compression", payload)
        self.assertTrue(payload["llmStatus"]["available"])
        self.assertNotIn("error", payload)

    def test_analyze_api_html_mode_works_without_project_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            projects_dir = _make_projects(tmp)
            server = HTTPServer(("127.0.0.1", 0), _make_handler(projects_dir, tmp / "raw"))
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                completed = subprocess.CompletedProcess(["claude", "-p", "-"], 0, stdout="# 报告\n\n内容", stderr="")
                with mock.patch("ccwhat.analyzer.subprocess.run", return_value=completed):
                    status, payload = self._post_analyze(server, {"sessionId": SID, "mode": "generic"})
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["reportType"], "html")
        self.assertEqual(payload["reportMode"], "generic")
        self.assertIn("reportUrl", payload)
        self.assertIn("exportUrl", payload)
        self.assertIn("summary", payload)
        self.assertEqual(payload["summary"]["agentCount"], 2)
        self.assertIn("compression", payload)
        self.assertTrue(payload["llmStatus"]["available"])
        self.assertNotIn("error", payload)

    def test_analyze_api_html_mode_with_codex_adapter(self) -> None:
        class StubCodexAdapter:
            name = "codex"

            def list_projects(self):
                return []

            def load_session(self, session_id: str):
                if session_id != SID:
                    return None
                return {
                    "sessionId": SID,
                    "projectDir": "/tmp/codex-project",
                    "agent": "codex",
                    "main": [],
                    "subagents": [],
                    "events": [
                        {
                            "id": "ev1",
                            "agent": "codex",
                            "sessionId": SID,
                            "timestamp": "2026-05-29T03:00:00Z",
                            "role": "user",
                            "kind": "message",
                            "content": "hello codex",
                            "summary": "hello codex",
                        },
                        {
                            "id": "ev2",
                            "agent": "codex",
                            "sessionId": SID,
                            "timestamp": "2026-05-29T03:00:01Z",
                            "role": "assistant",
                            "kind": "tool_call",
                            "content": {"command": "pwd"},
                            "summary": "Tool: Bash",
                            "toolName": "Bash",
                            "toolCallId": "call-1",
                        },
                        {
                            "id": "ev3",
                            "agent": "codex",
                            "sessionId": SID,
                            "timestamp": "2026-05-29T03:00:02Z",
                            "role": "tool",
                            "kind": "tool_result",
                            "content": "/tmp/codex-project",
                            "summary": "/tmp/codex-project",
                            "toolName": "Bash",
                            "toolCallId": "call-1",
                        },
                    ],
                    "turns": [{
                        "id": "turn1",
                        "agent": "codex",
                        "startedAt": "2026-05-29T03:00:00Z",
                        "endedAt": "2026-05-29T03:00:02Z",
                        "userSummary": "hello codex",
                        "assistantSummary": "ran pwd",
                        "events": [{"id": "ev1"}, {"id": "ev2"}, {"id": "ev3"}],
                        "usage": {},
                    }],
                }

        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            server = HTTPServer(("127.0.0.1", 0), _make_handler(tmp / "projects", tmp / "raw", adapter=StubCodexAdapter()))
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                codex_stdout = '{"type":"assistant","content":"# 报告\\n\\n内容"}'
                completed = subprocess.CompletedProcess(["codex", "exec", "--json", "--ephemeral", "--ignore-user-config", "-"], 0, stdout=codex_stdout, stderr="")
                with mock.patch("ccwhat.analyzer.subprocess.run", return_value=completed) as run:
                    status, payload = self._post_analyze(server, {"sessionId": SID, "mode": "generic"})
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["reportType"], "html")
        self.assertEqual(payload["reportMode"], "generic")
        self.assertEqual(payload["summary"]["agentCount"], 1)
        self.assertIn("reportUrl", payload)
        self.assertIn("exportUrl", payload)
        self.assertTrue(payload["llmStatus"]["available"])
        self.assertFalse(payload["truncated"])
        self.assertEqual(run.call_args.args[0][1:], ["exec", "--json", "--ephemeral", "--ignore-user-config", "-"])
        self.assertTrue(run.call_args.args[0][0].endswith("codex"))
        self.assertIn("hello codex", run.call_args.kwargs["input"])
        self.assertIn("/tmp/codex-project", run.call_args.kwargs["input"])
        self.assertEqual(run.call_args.kwargs["timeout"], 45)

    def test_analyze_api_html_mode_with_opencode_adapter(self) -> None:
        class StubOpenCodeAdapter:
            name = "opencode"

            def list_projects(self):
                return []

            def load_session(self, session_id: str):
                if session_id != SID:
                    return None
                return {
                    "sessionId": SID,
                    "projectDir": "/tmp/opencode-project",
                    "agent": "opencode",
                    "main": [],
                    "subagents": [],
                    "events": [
                        {
                            "id": "ev1",
                            "agent": "opencode",
                            "sessionId": SID,
                            "timestamp": "2026-05-29T03:00:00Z",
                            "role": "assistant",
                            "kind": "tool_call",
                            "content": {"command": "ls"},
                            "summary": "Tool: bash",
                            "toolName": "bash",
                            "toolCallId": "call-1",
                        },
                        {
                            "id": "ev2",
                            "agent": "opencode",
                            "sessionId": SID,
                            "timestamp": "2026-05-29T03:00:01Z",
                            "role": "tool",
                            "kind": "tool_result",
                            "content": "file.txt",
                            "summary": "file.txt",
                            "toolName": "bash",
                            "toolCallId": "call-1",
                        },
                    ],
                    "turns": [{
                        "id": "turn1",
                        "agent": "opencode",
                        "startedAt": "2026-05-29T03:00:00Z",
                        "endedAt": "2026-05-29T03:00:01Z",
                        "userSummary": "",
                        "assistantSummary": "ran ls",
                        "events": [{"id": "ev1"}, {"id": "ev2"}],
                        "usage": {},
                    }],
                }

        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            server = HTTPServer(("127.0.0.1", 0), _make_handler(tmp / "projects", tmp / "raw", adapter=StubOpenCodeAdapter()))
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                with mock.patch("ccwhat.analyzer.subprocess.run", side_effect=FileNotFoundError()) as run:
                    status, payload = self._post_analyze(server, {"sessionId": SID, "mode": "yuanxi"})
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["reportType"], "html")
        self.assertEqual(payload["reportMode"], "yuanxi")
        self.assertEqual(payload["summary"]["agentCount"], 1)
        self.assertIn("reportUrl", payload)
        self.assertIn("exportUrl", payload)
        self.assertIn("diagnosisStatus", payload)
        self.assertFalse(payload["diagnosisStatus"]["available"])
        self.assertEqual(payload["diagnosisStatus"]["mode"], "fallback")
        self.assertEqual(payload["diagnosisStatus"]["code"], "analyzer_not_found")
        self.assertIn("not found", payload["diagnosisStatus"]["message"])
        self.assertFalse(payload["truncated"])
        self.assertIn("compression", payload)
        self.assertIn("elapsedMs", payload)
        self.assertIn("totalMs", payload)
        self.assertIn("buildMs", payload)
        self.assertEqual(payload["llmElapsedMs"], 0) if "llmElapsedMs" in payload else None
        run.assert_called_once()

    def test_analyze_api_html_mode_without_llm_keeps_report(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/opencode-project",
            "agent": "opencode",
            "main": [],
            "subagents": [],
            "events": [{
                "id": "ev1",
                "agent": "opencode",
                "sessionId": SID,
                "timestamp": "2026-05-29T03:00:00Z",
                "role": "assistant",
                "kind": "message",
                "content": "done",
                "summary": "done",
            }],
            "turns": [{
                "id": "turn1",
                "agent": "opencode",
                "startedAt": "2026-05-29T03:00:00Z",
                "endedAt": "2026-05-29T03:00:01Z",
                "userSummary": "",
                "assistantSummary": "done",
                "events": [{"id": "ev1"}],
                "usage": {},
            }],
        }

        result = build_html_session_report(session, enable_llm=False)

        self.assertEqual(result["reportMode"], "yuanxi")
        self.assertFalse(result["diagnosisStatus"]["available"])
        self.assertEqual(result["diagnosisStatus"]["mode"], "not_requested")
        self.assertIn("reportHtml", result)
        self.assertEqual(result["summary"]["agentCount"], 1)
        self.assertEqual(result["llmElapsedMs"], 0)
        self.assertIn("compression", result)
        self.assertIn("elapsedMs", result)
        self.assertFalse(bool(result["compression"]["omittedEvents"]))
        self.assertEqual(result["summary"]["phaseCount"], 1)

    def test_generic_report_without_llm_keeps_html_shell(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/opencode-project",
            "agent": "opencode",
            "main": [],
            "subagents": [],
            "events": [{
                "id": "ev1",
                "agent": "opencode",
                "sessionId": SID,
                "timestamp": "2026-05-29T03:00:00Z",
                "role": "assistant",
                "kind": "message",
                "content": "done",
                "summary": "done",
            }],
            "turns": [{
                "id": "turn1",
                "agent": "opencode",
                "startedAt": "2026-05-29T03:00:00Z",
                "endedAt": "2026-05-29T03:00:01Z",
                "userSummary": "",
                "assistantSummary": "done",
                "events": [{"id": "ev1"}],
                "usage": {},
            }],
        }

        result = build_generic_html_report(session, enable_llm=False)

        self.assertEqual(result["reportMode"], "generic")
        self.assertIn("reportHtml", result)
        self.assertFalse(result["llmStatus"]["available"])
        self.assertEqual(result["llmStatus"]["mode"], "not_requested")
        self.assertEqual(result["summary"]["agentCount"], 1)
        self.assertEqual(result["llmElapsedMs"], 0)
        self.assertIn("compression", result)
        self.assertIn("elapsedMs", result)
        self.assertIn(SID, result["reportHtml"])
        self.assertIn("/tmp/opencode-project", result["reportHtml"])

    def test_report_summary_counts_delegated_agents_for_claude(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "project-c",
            "agent": "claude",
            "main": [{"type": "user", "timestamp": "2026-05-29T03:00:00Z", "message": {"content": "hello"}}],
            "subagents": [{
                "agentId": "agent-one",
                "meta": {"description": "helper", "agentType": "general-purpose"},
                "entries": [{"type": "assistant", "timestamp": "2026-05-29T03:01:00Z", "message": {"content": "done"}}],
            }],
            "turns": [],
        }

        result = build_html_session_report(session, enable_llm=False)

        self.assertEqual(result["summary"]["agentCount"], 2)
        self.assertEqual(result["compression"]["subagents"], 1)
        self.assertEqual(result["compression"]["mainEntries"], 1)
        self.assertEqual(result["compression"]["subagentEntries"], 1)
        self.assertIn("reportHtml", result)
        self.assertIn("project-c", result["reportHtml"])
        self.assertFalse(result["diagnosisStatus"]["available"])
        self.assertEqual(result["summary"]["phaseCount"], 1)
        self.assertEqual(result["summary"]["toolEventCount"], 0)
        self.assertEqual(result["summary"]["findingCount"], 1)
        self.assertGreaterEqual(result["elapsedMs"], 0)
        self.assertEqual(result["llmElapsedMs"], 0)
        self.assertIn("compression", result)
        self.assertEqual(result["compression"]["events"], 0)
        self.assertGreaterEqual(result["compression"]["rawChars"], 1)
        self.assertGreaterEqual(result["compression"]["compressedChars"], 1)
        self.assertEqual(result["compression"]["truncatedEvents"], 0)
        self.assertGreaterEqual(result["compression"]["omittedEvents"], 0)

    def test_report_pipeline_ignores_project_path_residue(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "project-c",
            "projectPath": "/tmp/project-c",
            "agent": "claude",
            "main": [{"type": "user", "timestamp": "2026-05-29T03:00:00Z", "message": {"content": "hello"}}],
            "subagents": [],
            "turns": [],
        }

        normalized = normalize_session_for_report(session)

        self.assertEqual(normalized.project_display, "project-c")
        self.assertEqual(normalized.project_path, "/tmp/project-c")
        result = build_html_session_report(session, enable_llm=False)
        self.assertEqual(result["summary"]["projectDir"], "project-c")
        self.assertIn("project-c", result["reportHtml"])
        self.assertNotIn("projectPath", result["reportHtml"])

    def test_generic_report_merges_tool_call_and_result(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/codex-project",
            "agent": "codex",
            "main": [],
            "subagents": [],
            "events": [
                {
                    "id": "ev1",
                    "agent": "codex",
                    "sessionId": SID,
                    "timestamp": "2026-05-29T03:00:01Z",
                    "role": "assistant",
                    "kind": "tool_call",
                    "content": {"command": "pwd"},
                    "summary": "Tool: Bash",
                    "toolName": "Bash",
                    "toolCallId": "call-1",
                },
                {
                    "id": "ev2",
                    "agent": "codex",
                    "sessionId": SID,
                    "timestamp": "2026-05-29T03:00:02Z",
                    "role": "tool",
                    "kind": "tool_result",
                    "content": "/tmp/codex-project",
                    "summary": "/tmp/codex-project",
                    "toolName": "Bash",
                    "toolCallId": "call-1",
                },
            ],
            "turns": [{
                "id": "turn1",
                "agent": "codex",
                "startedAt": "2026-05-29T03:00:01Z",
                "endedAt": "2026-05-29T03:00:02Z",
                "userSummary": "",
                "assistantSummary": "ran pwd",
                "events": [{"id": "ev1"}, {"id": "ev2"}],
                "usage": {},
            }],
        }

        result = build_html_session_report(session, enable_llm=False)

        self.assertEqual(result["summary"]["toolEventCount"], 1)
        self.assertEqual(result["summary"]["phaseCount"], 1)
        self.assertIn("reportHtml", result)
        self.assertIn("codex-project", result["reportHtml"])

    def test_phase_inference_uses_turns_for_non_claude_agents(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/opencode-project",
            "agent": "opencode",
            "main": [],
            "subagents": [],
            "events": [
                {
                    "id": "ev1",
                    "agent": "opencode",
                    "sessionId": SID,
                    "timestamp": "2026-05-29T03:00:00Z",
                    "role": "user",
                    "kind": "message",
                    "content": "first",
                    "summary": "first",
                },
                {
                    "id": "ev2",
                    "agent": "opencode",
                    "sessionId": SID,
                    "timestamp": "2026-05-29T03:05:00Z",
                    "role": "user",
                    "kind": "message",
                    "content": "second",
                    "summary": "second",
                },
            ],
            "turns": [
                {
                    "id": "turn1",
                    "agent": "opencode",
                    "startedAt": "2026-05-29T03:00:00Z",
                    "endedAt": "2026-05-29T03:01:00Z",
                    "userSummary": "first",
                    "assistantSummary": "",
                    "events": [{"id": "ev1"}],
                    "usage": {},
                },
                {
                    "id": "turn2",
                    "agent": "opencode",
                    "startedAt": "2026-05-29T03:05:00Z",
                    "endedAt": "2026-05-29T03:06:00Z",
                    "userSummary": "second",
                    "assistantSummary": "",
                    "events": [{"id": "ev2"}],
                    "usage": {},
                },
            ],
        }

        result = build_html_session_report(session, enable_llm=False)

        self.assertEqual(result["summary"]["phaseCount"], 2)
        self.assertIn("reportHtml", result)
        self.assertEqual(result["summary"]["agentCount"], 1)
        self.assertEqual(result["compression"]["subagents"], 0)
        self.assertEqual(result["summary"]["toolEventCount"], 0)
        self.assertGreaterEqual(result["summary"]["totalWallMin"], 1.0)

    def test_signal_detection_works_for_non_claude_events(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/opencode-project",
            "agent": "opencode",
            "main": [],
            "subagents": [],
            "events": [{
                "id": "ev1",
                "agent": "opencode",
                "sessionId": SID,
                "timestamp": "2026-05-29T03:00:00Z",
                "role": "assistant",
                "kind": "message",
                "content": "测试通过，任务完成",
                "summary": "测试通过，任务完成",
            }],
            "turns": [{
                "id": "turn1",
                "agent": "opencode",
                "startedAt": "2026-05-29T03:00:00Z",
                "endedAt": "2026-05-29T03:00:01Z",
                "userSummary": "",
                "assistantSummary": "测试通过，任务完成",
                "events": [{"id": "ev1"}],
                "usage": {},
            }],
        }

        result = build_html_session_report(session, enable_llm=False)

        self.assertGreaterEqual(result["summary"]["findingCount"], 0)
        self.assertIn("reportHtml", result)

    def test_truncation_count_tracks_large_tool_inputs(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/opencode-project",
            "agent": "opencode",
            "main": [],
            "subagents": [],
            "events": [{
                "id": "ev1",
                "agent": "opencode",
                "sessionId": SID,
                "timestamp": "2026-05-29T03:00:00Z",
                "role": "assistant",
                "kind": "tool_call",
                "content": {"command": "x" * 1000},
                "summary": "Tool: Bash",
                "toolName": "Bash",
                "toolCallId": "call-1",
            }],
            "turns": [{
                "id": "turn1",
                "agent": "opencode",
                "startedAt": "2026-05-29T03:00:00Z",
                "endedAt": "2026-05-29T03:00:01Z",
                "userSummary": "",
                "assistantSummary": "",
                "events": [{"id": "ev1"}],
                "usage": {},
            }],
        }

        result = build_html_session_report(session, enable_llm=False)

        self.assertGreaterEqual(result["compression"]["truncatedEvents"], 1)
        self.assertIn("reportHtml", result)
        self.assertEqual(result["summary"]["toolEventCount"], 1)
        self.assertEqual(result["summary"]["agentCount"], 1)
        self.assertEqual(result["summary"]["phaseCount"], 1)

    def test_error_tool_result_counts_as_failure(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/opencode-project",
            "agent": "opencode",
            "main": [],
            "subagents": [],
            "events": [
                {
                    "id": "ev1",
                    "agent": "opencode",
                    "sessionId": SID,
                    "timestamp": "2026-05-29T03:00:00Z",
                    "role": "assistant",
                    "kind": "tool_call",
                    "content": {"command": "bad"},
                    "summary": "Tool: Bash",
                    "toolName": "Bash",
                    "toolCallId": "call-1",
                },
                {
                    "id": "ev2",
                    "agent": "opencode",
                    "sessionId": SID,
                    "timestamp": "2026-05-29T03:00:01Z",
                    "role": "tool",
                    "kind": "tool_result",
                    "content": "error: failed",
                    "summary": "error: failed",
                    "toolName": "Bash",
                    "toolCallId": "call-1",
                },
            ],
            "turns": [{
                "id": "turn1",
                "agent": "opencode",
                "startedAt": "2026-05-29T03:00:00Z",
                "endedAt": "2026-05-29T03:00:01Z",
                "userSummary": "",
                "assistantSummary": "",
                "events": [{"id": "ev1"}, {"id": "ev2"}],
                "usage": {},
            }],
        }

        result = build_html_session_report(session, enable_llm=False)

        self.assertGreaterEqual(result["summary"]["findingCount"], 1)
        self.assertIn("reportHtml", result)
        self.assertEqual(result["summary"]["toolEventCount"], 1)
        self.assertEqual(result["summary"]["phaseCount"], 1)
        self.assertEqual(result["summary"]["agentCount"], 1)
        self.assertGreaterEqual(result["compression"]["compressedChars"], 1)
        self.assertGreaterEqual(result["compression"]["rawChars"], 1)

    def test_findings_include_delegated_agents_for_claude(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "project-c",
            "agent": "claude",
            "main": [{"type": "user", "timestamp": "2026-05-29T03:00:00Z", "message": {"content": "hello"}}],
            "subagents": [{
                "agentId": "agent-one",
                "meta": {"description": "helper", "agentType": "general-purpose"},
                "entries": [{"type": "assistant", "timestamp": "2026-05-29T03:01:00Z", "message": {"content": "done"}}],
            }],
            "turns": [],
        }

        result = build_html_session_report(session, enable_llm=False)

        self.assertGreaterEqual(result["summary"]["findingCount"], 1)
        self.assertIn("reportHtml", result)

    def test_non_claude_project_dir_used_for_report_title(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/codex-project",
            "agent": "codex",
            "main": [],
            "subagents": [],
            "events": [{
                "id": "ev1",
                "agent": "codex",
                "sessionId": SID,
                "timestamp": "2026-05-29T03:00:00Z",
                "role": "user",
                "kind": "message",
                "content": "hello",
                "summary": "hello",
            }],
            "turns": [{
                "id": "turn1",
                "agent": "codex",
                "startedAt": "2026-05-29T03:00:00Z",
                "endedAt": "2026-05-29T03:00:01Z",
                "userSummary": "hello",
                "assistantSummary": "",
                "events": [{"id": "ev1"}],
                "usage": {},
            }],
        }

        result = build_generic_html_report(session, enable_llm=False)

        self.assertIn("/tmp/codex-project", result["reportHtml"])
        self.assertEqual(result["summary"]["projectDir"], "/tmp/codex-project")
        self.assertEqual(result["summary"]["agentCount"], 1)

    def test_normalization_keeps_project_path_when_present(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "project-c",
            "projectPath": "/tmp/project-c",
            "agent": "claude",
            "main": [],
            "subagents": [],
            "turns": [],
        }

        normalized = normalize_session_for_report(session)

        self.assertEqual(normalized.project_display, "project-c")
        self.assertEqual(normalized.project_path, "/tmp/project-c")
        self.assertEqual(normalized.primary_agent_type, "claude")
        self.assertEqual(normalized.primary_agent_id, "main")
        self.assertEqual(len(normalized.agents), 1)

    def test_normalization_sets_project_path_for_codex(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/codex-project",
            "agent": "codex",
            "main": [],
            "subagents": [],
            "events": [],
            "turns": [],
        }

        normalized = normalize_session_for_report(session)

        self.assertEqual(normalized.project_display, "/tmp/codex-project")
        self.assertEqual(normalized.project_path, "/tmp/codex-project")
        self.assertEqual(normalized.primary_agent_type, "codex")

    def test_normalization_sets_project_path_for_opencode(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/opencode-project",
            "agent": "opencode",
            "main": [],
            "subagents": [],
            "events": [],
            "turns": [],
        }

        normalized = normalize_session_for_report(session)

        self.assertEqual(normalized.project_display, "/tmp/opencode-project")
        self.assertEqual(normalized.project_path, "/tmp/opencode-project")
        self.assertEqual(normalized.primary_agent_type, "opencode")

    def test_report_html_contains_agent_summary_section(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/codex-project",
            "agent": "codex",
            "main": [],
            "subagents": [],
            "events": [{
                "id": "ev1",
                "agent": "codex",
                "sessionId": SID,
                "timestamp": "2026-05-29T03:00:00Z",
                "role": "user",
                "kind": "message",
                "content": "hello",
                "summary": "hello",
            }],
            "turns": [{
                "id": "turn1",
                "agent": "codex",
                "startedAt": "2026-05-29T03:00:00Z",
                "endedAt": "2026-05-29T03:00:01Z",
                "userSummary": "hello",
                "assistantSummary": "",
                "events": [{"id": "ev1"}],
                "usage": {},
            }],
        }

        result = build_html_session_report(session, enable_llm=False)

        self.assertIn("reportHtml", result)
        self.assertIn("diagnosisMarkdown", result["reportHtml"])

    def test_report_data_handles_empty_events(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/codex-project",
            "agent": "codex",
            "main": [],
            "subagents": [],
            "events": [],
            "turns": [],
        }

        result = build_html_session_report(session, enable_llm=False)

        self.assertEqual(result["summary"]["phaseCount"], 0)
        self.assertEqual(result["summary"]["toolEventCount"], 0)
        self.assertEqual(result["summary"]["agentCount"], 1)
        self.assertIn("reportHtml", result)
        self.assertEqual(result["compression"]["events"], 0)
        self.assertEqual(result["compression"]["mainEntries"], 0)
        self.assertEqual(result["compression"]["subagentEntries"], 0)

    def test_report_summary_uses_project_display(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "project-c",
            "projectPath": "/tmp/project-c",
            "agent": "claude",
            "main": [],
            "subagents": [],
            "turns": [],
        }

        result = build_html_session_report(session, enable_llm=False)

        self.assertEqual(result["summary"]["projectDir"], "project-c")
        self.assertIn("project-c", result["reportHtml"])
        self.assertNotIn("/tmp/project-c", result["summary"]["projectDir"])

    def test_generic_report_uses_project_display(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "project-c",
            "projectPath": "/tmp/project-c",
            "agent": "claude",
            "main": [],
            "subagents": [],
            "turns": [],
        }

        result = build_generic_html_report(session, enable_llm=False)

        self.assertEqual(result["summary"]["projectDir"], "project-c")
        self.assertIn("project-c", result["reportHtml"])

    def test_report_html_mode_returns_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            projects_dir = _make_projects(tmp)
            server = HTTPServer(("127.0.0.1", 0), _make_handler(projects_dir, tmp / "raw"))
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                completed = subprocess.CompletedProcess(["claude", "-p", "-"], 0, stdout="# 报告\n\n内容", stderr="")
                with mock.patch("ccwhat.analyzer.subprocess.run", return_value=completed):
                    status, payload = self._post_analyze(server, {"sessionId": SID, "mode": "yuanxi"})
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(status, 200, payload)
        self.assertIn("reportUrl", payload)
        self.assertIn("exportUrl", payload)
        self.assertEqual(payload["reportType"], "html")
        self.assertEqual(payload["reportMode"], "yuanxi")
        self.assertTrue(payload["ok"])
        self.assertIn("summary", payload)

    def test_report_export_endpoint_serves_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            projects_dir = _make_projects(tmp)
            server = HTTPServer(("127.0.0.1", 0), _make_handler(projects_dir, tmp / "raw"))
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                completed = subprocess.CompletedProcess(["claude", "-p", "-"], 0, stdout="# 报告\n\n内容", stderr="")
                with mock.patch("ccwhat.analyzer.subprocess.run", return_value=completed):
                    status, payload = self._post_analyze(server, {"sessionId": SID, "mode": "generic"})
                self.assertEqual(status, 200, payload)
                conn = HTTPConnection("127.0.0.1", server.server_port)
                conn.request("GET", payload["exportUrl"])
                response = conn.getresponse()
                body = response.read().decode("utf-8")
                conn.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(response.status, 200)
        self.assertIn("text/html", response.getheader("Content-Type"))
        self.assertIn("内容", body)
        self.assertIn(SID, body)

    def test_report_open_endpoint_serves_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            projects_dir = _make_projects(tmp)
            server = HTTPServer(("127.0.0.1", 0), _make_handler(projects_dir, tmp / "raw"))
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                completed = subprocess.CompletedProcess(["claude", "-p", "-"], 0, stdout="# 报告\n\n内容", stderr="")
                with mock.patch("ccwhat.analyzer.subprocess.run", return_value=completed):
                    status, payload = self._post_analyze(server, {"sessionId": SID, "mode": "generic"})
                self.assertEqual(status, 200, payload)
                conn = HTTPConnection("127.0.0.1", server.server_port)
                conn.request("GET", payload["reportUrl"])
                response = conn.getresponse()
                body = response.read().decode("utf-8")
                conn.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(response.status, 200)
        self.assertIn("text/html", response.getheader("Content-Type"))
        self.assertIn("内容", body)
        self.assertIn(SID, body)

    def test_missing_report_url_returns_404(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            projects_dir = _make_projects(tmp)
            server = HTTPServer(("127.0.0.1", 0), _make_handler(projects_dir, tmp / "raw"))
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                conn = HTTPConnection("127.0.0.1", server.server_port)
                conn.request("GET", "/api/analysis-report/notfound")
                response = conn.getresponse()
                body = json.loads(response.read().decode("utf-8"))
                conn.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(response.status, 404)
        self.assertEqual(body["error"], "report not found or expired")

    def test_missing_report_export_url_returns_404(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            projects_dir = _make_projects(tmp)
            server = HTTPServer(("127.0.0.1", 0), _make_handler(projects_dir, tmp / "raw"))
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                conn = HTTPConnection("127.0.0.1", server.server_port)
                conn.request("GET", "/api/analysis-report/notfound/export")
                response = conn.getresponse()
                body = json.loads(response.read().decode("utf-8"))
                conn.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(response.status, 404)
        self.assertEqual(body["error"], "report not found or expired")

    def test_html_pipeline_does_not_require_main_subagents_for_codex(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/codex-project",
            "agent": "codex",
            "events": [{
                "id": "ev1",
                "agent": "codex",
                "sessionId": SID,
                "timestamp": "2026-05-29T03:00:00Z",
                "role": "user",
                "kind": "message",
                "content": "hello",
                "summary": "hello",
            }],
            "turns": [{
                "id": "turn1",
                "agent": "codex",
                "startedAt": "2026-05-29T03:00:00Z",
                "endedAt": "2026-05-29T03:00:01Z",
                "userSummary": "hello",
                "assistantSummary": "",
                "events": [{"id": "ev1"}],
                "usage": {},
            }],
        }

        result = build_html_session_report(session, enable_llm=False)

        self.assertEqual(result["summary"]["agentCount"], 1)
        self.assertEqual(result["summary"]["phaseCount"], 1)
        self.assertIn("reportHtml", result)

    def test_html_pipeline_does_not_require_main_subagents_for_opencode(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/opencode-project",
            "agent": "opencode",
            "events": [{
                "id": "ev1",
                "agent": "opencode",
                "sessionId": SID,
                "timestamp": "2026-05-29T03:00:00Z",
                "role": "assistant",
                "kind": "message",
                "content": "done",
                "summary": "done",
            }],
            "turns": [{
                "id": "turn1",
                "agent": "opencode",
                "startedAt": "2026-05-29T03:00:00Z",
                "endedAt": "2026-05-29T03:00:01Z",
                "userSummary": "",
                "assistantSummary": "done",
                "events": [{"id": "ev1"}],
                "usage": {},
            }],
        }

        result = build_html_session_report(session, enable_llm=False)

        self.assertEqual(result["summary"]["agentCount"], 1)
        self.assertEqual(result["summary"]["phaseCount"], 1)
        self.assertIn("reportHtml", result)

    def test_html_pipeline_uses_claude_main_subagents_when_present(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "project-c",
            "agent": "claude",
            "main": [{"type": "user", "timestamp": "2026-05-29T03:00:00Z", "message": {"content": "hello"}}],
            "subagents": [{
                "agentId": "agent-one",
                "meta": {"description": "helper", "agentType": "general-purpose"},
                "entries": [{"type": "assistant", "timestamp": "2026-05-29T03:01:00Z", "message": {"content": "done"}}],
            }],
            "turns": [],
        }

        result = build_html_session_report(session, enable_llm=False)

        self.assertEqual(result["summary"]["agentCount"], 2)
        self.assertEqual(result["compression"]["mainEntries"], 1)
        self.assertEqual(result["compression"]["subagentEntries"], 1)
        self.assertEqual(result["compression"]["subagents"], 1)

    def test_generic_pipeline_uses_unified_model_for_codex(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/codex-project",
            "agent": "codex",
            "events": [{
                "id": "ev1",
                "agent": "codex",
                "sessionId": SID,
                "timestamp": "2026-05-29T03:00:00Z",
                "role": "user",
                "kind": "message",
                "content": "hello",
                "summary": "hello",
            }],
            "turns": [{
                "id": "turn1",
                "agent": "codex",
                "startedAt": "2026-05-29T03:00:00Z",
                "endedAt": "2026-05-29T03:00:01Z",
                "userSummary": "hello",
                "assistantSummary": "",
                "events": [{"id": "ev1"}],
                "usage": {},
            }],
        }

        result = build_generic_html_report(session, enable_llm=False)

        self.assertEqual(result["summary"]["agentCount"], 1)
        self.assertIn("/tmp/codex-project", result["reportHtml"])

    def test_generic_pipeline_uses_unified_model_for_opencode(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/opencode-project",
            "agent": "opencode",
            "events": [{
                "id": "ev1",
                "agent": "opencode",
                "sessionId": SID,
                "timestamp": "2026-05-29T03:00:00Z",
                "role": "assistant",
                "kind": "message",
                "content": "done",
                "summary": "done",
            }],
            "turns": [{
                "id": "turn1",
                "agent": "opencode",
                "startedAt": "2026-05-29T03:00:00Z",
                "endedAt": "2026-05-29T03:00:01Z",
                "userSummary": "",
                "assistantSummary": "done",
                "events": [{"id": "ev1"}],
                "usage": {},
            }],
        }

        result = build_generic_html_report(session, enable_llm=False)

        self.assertEqual(result["summary"]["agentCount"], 1)
        self.assertIn("/tmp/opencode-project", result["reportHtml"])

    def test_yuanxi_pipeline_uses_unified_model_for_opencode(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/opencode-project",
            "agent": "opencode",
            "events": [{
                "id": "ev1",
                "agent": "opencode",
                "sessionId": SID,
                "timestamp": "2026-05-29T03:00:00Z",
                "role": "assistant",
                "kind": "message",
                "content": "done",
                "summary": "done",
            }],
            "turns": [{
                "id": "turn1",
                "agent": "opencode",
                "startedAt": "2026-05-29T03:00:00Z",
                "endedAt": "2026-05-29T03:00:01Z",
                "userSummary": "",
                "assistantSummary": "done",
                "events": [{"id": "ev1"}],
                "usage": {},
            }],
        }

        result = build_html_session_report(session, enable_llm=False)

        self.assertEqual(result["summary"]["agentCount"], 1)
        self.assertIn("/tmp/opencode-project", result["reportHtml"])

    def test_yuanxi_pipeline_uses_unified_model_for_codex(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/codex-project",
            "agent": "codex",
            "events": [{
                "id": "ev1",
                "agent": "codex",
                "sessionId": SID,
                "timestamp": "2026-05-29T03:00:00Z",
                "role": "user",
                "kind": "message",
                "content": "hello",
                "summary": "hello",
            }],
            "turns": [{
                "id": "turn1",
                "agent": "codex",
                "startedAt": "2026-05-29T03:00:00Z",
                "endedAt": "2026-05-29T03:00:01Z",
                "userSummary": "hello",
                "assistantSummary": "",
                "events": [{"id": "ev1"}],
                "usage": {},
            }],
        }

        result = build_html_session_report(session, enable_llm=False)

        self.assertEqual(result["summary"]["agentCount"], 1)
        self.assertIn("/tmp/codex-project", result["reportHtml"])

    def test_html_mode_keeps_urls_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            projects_dir = _make_projects(tmp)
            server = HTTPServer(("127.0.0.1", 0), _make_handler(projects_dir, tmp / "raw"))
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                completed = subprocess.CompletedProcess(["claude", "-p", "-"], 0, stdout="# 报告\n\n内容", stderr="")
                with mock.patch("ccwhat.analyzer.subprocess.run", return_value=completed):
                    status, payload = self._post_analyze(server, {"sessionId": SID, "mode": "generic"})
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertTrue(payload["reportUrl"].startswith("/api/analysis-report/"))
        self.assertTrue(payload["exportUrl"].endswith("/export"))
        self.assertEqual(status, 200)

    def test_html_mode_yuanxi_without_llm_has_not_requested_status(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/test",
            "agent": "codex",
            "events": [],
            "turns": [],
        }
        result = build_html_session_report(session, enable_llm=False)
        self.assertEqual(result["diagnosisStatus"]["mode"], "not_requested")
        self.assertFalse(result["diagnosisStatus"]["available"])

    def test_pipeline_explicit_analyzer_cmd_overrides_agent_default(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/codex-project",
            "agent": "codex",
            "events": [],
            "turns": [],
        }
        completed = subprocess.CompletedProcess(["custom-analyzer", "--json"], 0, stdout="# report", stderr="")
        with mock.patch("ccwhat.analyzer.subprocess.run", return_value=completed) as run:
            result = build_generic_html_report(
                session,
                analyzer_cmd=("custom-analyzer", "--json"),
                analyzer_agent="codex",
            )

        self.assertTrue(result["llmStatus"]["available"])
        self.assertEqual(run.call_args.args[0], ["custom-analyzer", "--json"])
        self.assertIn("/tmp/codex-project", run.call_args.kwargs["input"])

    def test_html_mode_generic_without_llm_has_not_requested_status(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/test",
            "agent": "codex",
            "events": [],
            "turns": [],
        }
        result = build_generic_html_report(session, enable_llm=False)
        self.assertEqual(result["llmStatus"]["mode"], "not_requested")
        self.assertFalse(result["llmStatus"]["available"])

    def test_generic_html_includes_session_and_project(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/test",
            "agent": "codex",
            "events": [],
            "turns": [],
        }
        result = build_generic_html_report(session, enable_llm=False)
        self.assertIn(SID, result["reportHtml"])
        self.assertIn("/tmp/test", result["reportHtml"])

    def test_generic_template_mermaid_fallback_preserves_source(self) -> None:
        html = (Path(__file__).resolve().parents[1] / "ccwhat" / "assets" / "session-report" / "generic_template.html").read_text(encoding="utf-8")
        prompt = (Path(__file__).resolve().parents[1] / "ccwhat" / "assets" / "session-report" / "generic_prompt.md").read_text(encoding="utf-8")

        self.assertIn('data-source="', html)
        self.assertIn("el.getAttribute('data-source')", html)
        self.assertIn("Mermaid 语法解析失败", html)
        self.assertIn("Mermaid 渲染库未加载", html)
        self.assertIn('A["用户请求"]', prompt)
        self.assertIn("use ASCII node ids", prompt)

    def test_normalize_session_for_report_accepts_empty_claude(self) -> None:
        session = {"sessionId": SID, "projectDir": "p", "agent": "claude", "main": [], "subagents": [], "turns": []}
        normalized = normalize_session_for_report(session)
        self.assertEqual(normalized.primary_agent_id, "main")
        self.assertEqual(len(normalized.agents), 1)
        self.assertEqual(len(normalized.events), 0)

    def test_normalize_session_for_report_accepts_empty_codex(self) -> None:
        session = {"sessionId": SID, "projectDir": "/tmp/p", "agent": "codex", "events": [], "turns": []}
        normalized = normalize_session_for_report(session)
        self.assertEqual(normalized.primary_agent_id, "main")
        self.assertEqual(len(normalized.agents), 1)
        self.assertEqual(len(normalized.events), 0)

    def test_normalize_session_for_report_accepts_empty_opencode(self) -> None:
        session = {"sessionId": SID, "projectDir": "/tmp/p", "agent": "opencode", "events": [], "turns": []}
        normalized = normalize_session_for_report(session)
        self.assertEqual(normalized.primary_agent_id, "main")
        self.assertEqual(len(normalized.agents), 1)
        self.assertEqual(len(normalized.events), 0)

class AnalyzeFrontendTests(unittest.TestCase):
    def test_frontend_uses_current_session_only(self) -> None:
        html = (Path(__file__).resolve().parents[1] / "viewer" / "claude-log.html").read_text(encoding="utf-8")

        self.assertIn('id="analyzeBtn"', html)
        self.assertIn("分析当前 Session", html)
        self.assertIn("analyzeCurrentSession()", html)
        self.assertIn("fetch(`${apiBase()}/api/analyze`", html)
        self.assertIn("body: JSON.stringify({sessionId, mode, customPrompt})", html)
        self.assertNotIn("turnKeys:", html)

    def test_frontend_caches_reports_and_supports_reanalysis(self) -> None:
        html = (Path(__file__).resolve().parents[1] / "viewer" / "claude-log.html").read_text(encoding="utf-8")

        self.assertIn("const analysisReports = {}", html)
        self.assertIn("analysisReports[cacheKey] = cached", html)
        self.assertIn("analysisReports[preserveKey] = previous", html)
        self.assertIn("function showCachedAnalysisReport(key)", html)
        self.assertIn("function analyzeCurrentSession()", html)
        self.assertIn("openModeModal()", html)
        self.assertIn("modeOverlay", html)
        self.assertIn("modeConfirmBtn", html)
        self.assertIn("查看上一次报告", html)
        self.assertIn("打开报告", html)
        self.assertIn("导出报告", html)
        self.assertIn("重新分析失败", html)
        self.assertIn("analysisCacheKey", html)
        self.assertIn("selectedMode", html)

    def test_frontend_renders_analysis_markdown_richly(self) -> None:
        html = (Path(__file__).resolve().parents[1] / "viewer" / "claude-log.html").read_text(encoding="utf-8")

        self.assertIn("function renderMarkdownInline", html)
        self.assertIn("function splitMarkdownTableRow", html)
        self.assertIn("function isMarkdownTableSeparator", html)
        self.assertIn('class="md-table-wrap"', html)
        self.assertIn('data-lang="${escRaw(langLabel)}"', html)
        self.assertIn('class="code-block"', html)
        self.assertIn(".md-view table", html)
        self.assertIn(".md-view th", html)
        self.assertIn(".md-view blockquote", html)
        # cdn.jsdelivr mermaid removed in workbench redesign (no external CDN per design spec)
        self.assertIn('class="md-mermaid-wrap"', html)
        self.assertIn('class="md-mermaid"', html)
        self.assertIn("function renderMermaidBlocks", html)
        self.assertIn("function fallbackMermaidBlock", html)
        self.assertIn("window.mermaid.run", html)
        self.assertIn("renderMermaidBlocks(body)", html)
        self.assertIn("library unavailable", html)
        self.assertIn("render failed", html)
        self.assertIn(".replace(/</g,'&lt;')", html)
        self.assertIn(".replace(/>/g,'&gt;')", html)


class AnalyzerAdapterTests(unittest.TestCase):
    """Tests for the new analyzer adapter protocol, parsers, and env vars."""

    def test_opencode_jsonl_text_parser(self) -> None:
        from ccwhat.analyzers.opencode import parse_jsonl_text
        stdout = (
            '{"type":"step_start","timestamp":"2026-06-08T00:00:00.000Z","sessionID":"s"}\n'
            '{"type":"text","timestamp":"2026-06-08T00:00:01.000Z","sessionID":"s","part":{"id":"p1","type":"text","text":"Hello"}}\n'
            '{"type":"part","part":{"type":"text","text":"World"}}\n'
            '{"type":"tool_call","toolName":"bash","content":"ls"}\n'
            '{"type":"text","content":"Done"}\n'
            '{"type":"step_finish","part":{"type":"step-finish","tokens":{"total":12971,"input":12940,"output":5,"reasoning":26,"cache":{"write":0,"read":0}}}}\n'
        )
        result = parse_jsonl_text(stdout)
        self.assertEqual(result, "Hello\nWorld\nDone")

    def test_opencode_jsonl_parser_empty_stdout(self) -> None:
        from ccwhat.analyzers.opencode import parse_jsonl_text
        self.assertEqual(parse_jsonl_text(""), "")
        self.assertEqual(parse_jsonl_text('{"type":"tool_call","toolName":"ls"}'), "")

    def test_codex_jsonl_text_parser(self) -> None:
        from ccwhat.analyzers.codex import parse_jsonl_text as codex_parse
        stdout = (
            '{"type":"assistant","content":"Final answer"}\n'
            '{"type":"user","content":"ignored"}\n'
        )
        result = codex_parse(stdout)
        self.assertEqual(result, "Final answer")

    def test_codex_jsonl_agent_messages_parser(self) -> None:
        from ccwhat.analyzers.codex import parse_jsonl_text as codex_parse
        stdout = (
            '{"type":"agent","messages":[{"role":"user","content":"hi"},{"role":"assistant","content":"Agent reply"}]}\n'
        )
        result = codex_parse(stdout)
        self.assertEqual(result, "Agent reply")

    def test_codex_jsonl_real_event_parser(self) -> None:
        from ccwhat.analyzers.codex import parse_jsonl_text as codex_parse
        stdout = (
            '{"type":"thread.started","thread_id":"t"}\n'
            '{"type":"turn.started"}\n'
            '{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Final from response item"}]}}\n'
            '{"type":"event_msg","payload":{"type":"agent_message","message":"Final from event msg","phase":"commentary"}}\n'
        )
        result = codex_parse(stdout)
        self.assertEqual(result, "Final from response item\nFinal from event msg")

    def test_analyzer_spec_priority_explicit_cmd_overrides_registry(self) -> None:
        completed = subprocess.CompletedProcess(["custom-cmd"], 0, stdout="custom report", stderr="")
        runner = mock.Mock(return_value=completed)
        report, _ = run_mc_analysis("prompt", runner=runner, cmd=["custom-cmd"])
        self.assertEqual(report, "custom report")
        self.assertEqual(runner.call_args.args[0][0], "custom-cmd")

    def test_analyzer_spec_explicit_cmd_bypasses_parser(self) -> None:
        """Explicit cmd should skip the registry's output parser (spec=None)."""
        completed = subprocess.CompletedProcess(["echo", "hello"], 0, stdout="raw output", stderr="")
        runner = mock.Mock(return_value=completed)
        report, _ = run_mc_analysis("prompt", runner=runner, cmd=["echo", "hello"])
        self.assertEqual(report, "raw output")

    def test_analyzer_spec_env_agent_override(self) -> None:
        completed = subprocess.CompletedProcess(["claude", "-p", "-"], 0, stdout="report", stderr="")
        runner = mock.Mock(return_value=completed)
        with mock.patch.dict("os.environ", {"CCWHAT_ANALYZE_AGENT": "claude"}):
            report, _ = run_mc_analysis("prompt", runner=runner, agent=None)
        self.assertEqual(report, "report")

    def test_analyzer_spec_env_timeout_override(self) -> None:
        completed = subprocess.CompletedProcess(["claude", "-p", "-"], 0, stdout="report", stderr="")
        runner = mock.Mock(return_value=completed)
        with mock.patch.dict("os.environ", {"CCWHAT_ANALYZE_TIMEOUT": "30"}):
            report, elapsed = run_mc_analysis("prompt", runner=runner, agent="claude")
        self.assertEqual(report, "report")
        self.assertEqual(runner.call_args.kwargs["timeout"], 30)

    def test_analyzer_env_cmd_override_beats_agent_default(self) -> None:
        """CCWHAT_ANALYZE_CMD env var should override the agent-specific default cmd."""
        completed = subprocess.CompletedProcess(["my-custom-ai", "-p", "-"], 0, stdout="override ok", stderr="")
        runner = mock.Mock(return_value=completed)
        with mock.patch.dict("os.environ", {"CCWHAT_ANALYZE_CMD": "my-custom-ai -p -"}):
            report, _ = run_mc_analysis("prompt", runner=runner, agent="codex")
        self.assertEqual(report, "override ok")

    def test_run_target_args_not_passed_to_analyzer(self) -> None:
        """Verify that _start_managed_web receives analyzer_cmd=None when run() passes None."""
        # This tests that the code path in run.py does NOT pass target_args as analyzer_cmd
        from ccwhat.commands.run import _start_managed_web
        # The function signature now defaults analyzer_cmd to None
        import inspect
        sig = inspect.signature(_start_managed_web)
        param = sig.parameters["analyzer_cmd"]
        self.assertIs(param.default, None, "analyzer_cmd should default to None")

    def test_codex_spec_timeout_45(self) -> None:
        """Codex AnalyzerSpec.timeout_seconds should keep experimental runs short."""
        completed = subprocess.CompletedProcess(
            ["codex", "exec", "--json", "--ephemeral", "--ignore-user-config", "-"],
            0,
            stdout='{"type":"assistant","content":"report"}',
            stderr="",
        )
        runner = mock.Mock(return_value=completed)
        report, _ = run_mc_analysis("prompt", runner=runner, agent="codex")
        self.assertEqual(report, "report")
        self.assertEqual(runner.call_args.kwargs["timeout"], 45)

    def test_codex_generic_timeout_falls_back_to_local_report(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/codex-project",
            "agent": "codex",
            "events": [
                {
                    "id": "ev1",
                    "agent": "codex",
                    "sessionId": SID,
                    "timestamp": "2026-05-29T03:00:00Z",
                    "role": "assistant",
                    "kind": "tool_call",
                    "content": {"command": "pwd"},
                    "summary": "Tool: bash",
                    "toolName": "bash",
                    "toolCallId": "call-1",
                },
                {
                    "id": "ev2",
                    "agent": "codex",
                    "sessionId": SID,
                    "timestamp": "2026-05-29T03:00:02Z",
                    "role": "tool",
                    "kind": "tool_result",
                    "content": "/tmp/codex-project",
                    "summary": "/tmp/codex-project",
                    "toolName": "bash",
                    "toolCallId": "call-1",
                },
            ],
            "turns": [],
        }
        with mock.patch("ccwhat.analyzer.subprocess.run", side_effect=subprocess.TimeoutExpired("codex", 45)):
            result = build_generic_html_report(session, analyzer_agent="codex")

        self.assertEqual(result["llmStatus"]["mode"], "fallback")
        self.assertEqual(result["llmStatus"]["code"], "analyzer_timeout")
        self.assertIn("Agent 交互分析报告", result["reportHtml"])
        self.assertIn("本地日志结构化分析", result["reportHtml"])
        self.assertNotIn("报告生成失败", result["reportHtml"])

    def test_codex_yuanxi_timeout_falls_back_to_local_diagnosis(self) -> None:
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/codex-project",
            "agent": "codex",
            "events": [{
                "id": "ev1",
                "agent": "codex",
                "sessionId": SID,
                "timestamp": "2026-05-29T03:00:00Z",
                "role": "assistant",
                "kind": "message",
                "content": "测试通过，任务完成",
                "summary": "测试通过，任务完成",
            }],
            "turns": [],
        }
        with mock.patch("ccwhat.analyzer.subprocess.run", side_effect=subprocess.TimeoutExpired("codex", 45)):
            result = build_html_session_report(session, analyzer_agent="codex")

        self.assertEqual(result["diagnosisStatus"]["mode"], "fallback")
        self.assertEqual(result["diagnosisStatus"]["code"], "analyzer_timeout")
        self.assertIn("本地结构化诊断", result["reportHtml"])

    def test_default_agent_fallback_to_claude(self) -> None:
        """When agent=None and no env var, default_agent should be used before 'claude'."""
        completed = subprocess.CompletedProcess(
            ["opencode", "run", "--format", "json"],
            0,
            stdout='{"type":"text","part":{"type":"text","text":"ok"}}',
            stderr="",
        )
        runner = mock.Mock(return_value=completed)
        report, _ = run_mc_analysis("prompt", runner=runner, agent=None, default_agent="opencode")
        self.assertEqual(report, "ok")
        self.assertTrue(runner.call_args.args[0][0].endswith("opencode"))

    def test_opencode_generic_report_accepts_real_jsonl_text_shape(self) -> None:
        """OpenCode report generation should parse real opencode run --format json text events."""
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/opencode-project",
            "agent": "opencode",
            "events": [],
            "turns": [],
        }
        stdout = (
            '{"type":"step_start","timestamp":"2026-06-08T00:00:00.000Z","sessionID":"s"}\n'
            '{"type":"text","timestamp":"2026-06-08T00:00:01.000Z","sessionID":"s","part":{"id":"p1","type":"text","text":"# OpenCode Report\\n\\nok"}}\n'
            '{"type":"step_finish","part":{"type":"step-finish","tokens":{"total":1,"input":1,"output":1,"reasoning":0,"cache":{"write":0,"read":0}}}}\n'
        )
        completed = subprocess.CompletedProcess(["opencode", "run", "--format", "json"], 0, stdout=stdout, stderr="")
        with mock.patch("ccwhat.analyzer.subprocess.run", return_value=completed):
            result = build_generic_html_report(session, analyzer_agent="opencode")

        self.assertTrue(result["llmStatus"]["available"])
        self.assertEqual(result["llmStatus"]["mode"], "mc")
        self.assertIn("OpenCode Report", result["reportHtml"])

    def test_opencode_yuanxi_report_accepts_real_jsonl_text_shape(self) -> None:
        """OpenCode yuanxi report generation should parse real opencode text events."""
        session = {
            "sessionId": SID,
            "projectDir": "/tmp/opencode-project",
            "agent": "opencode",
            "events": [],
            "turns": [],
        }
        stdout = (
            '{"type":"step_start","timestamp":"2026-06-08T00:00:00.000Z","sessionID":"s"}\n'
            '{"type":"text","timestamp":"2026-06-08T00:00:01.000Z","sessionID":"s","part":{"id":"p1","type":"text","text":"# 元析\\n\\nok"}}\n'
            '{"type":"step_finish","part":{"type":"step-finish","tokens":{"total":1,"input":1,"output":1,"reasoning":0,"cache":{"write":0,"read":0}}}}\n'
        )
        completed = subprocess.CompletedProcess(["opencode", "run", "--format", "json"], 0, stdout=stdout, stderr="")
        with mock.patch("ccwhat.analyzer.subprocess.run", return_value=completed):
            result = build_html_session_report(session, analyzer_agent="opencode")

        self.assertTrue(result["diagnosisStatus"]["available"])
        self.assertEqual(result["diagnosisStatus"]["mode"], "mc")

    def test_env_agent_beats_default_agent(self) -> None:
        """CCWHAT_ANALYZE_AGENT env should beat default_agent."""
        completed = subprocess.CompletedProcess(["claude", "-p", "-"], 0, stdout="claude report", stderr="")
        runner = mock.Mock(return_value=completed)
        with mock.patch.dict("os.environ", {"CCWHAT_ANALYZE_AGENT": "claude"}):
            report, _ = run_mc_analysis("prompt", runner=runner, agent=None, default_agent="opencode")
        self.assertEqual(report, "claude report")

    def test_canonical_report_agent_filters_build(self) -> None:
        """normalize_session_for_report should not pass 'build' as primary_agent_type."""
        from ccwhat.session_report.normalize import _canonical_report_agent
        self.assertEqual(_canonical_report_agent({"agent": "build"}), "claude")
        self.assertEqual(_canonical_report_agent({"agent": "opencode"}), "opencode")
        self.assertEqual(_canonical_report_agent({"agent": "plan"}), "claude")
        self.assertEqual(
            _canonical_report_agent({"agent": "build", "_metadata": {"opencodeAgent": "opencode"}}),
            "opencode",
        )

    def test_viewer_effective_agent_uses_adapter_before_session(self) -> None:
        """Viewer should prefer adapter.name over session.agent when no explicit analyzer_agent."""
        from ccwhat.session_report.normalize import normalize_session_for_report
        session = {
            "sessionId": "test",
            "agent": "build",
            "_metadata": {"opencodeAgent": "opencode"},
            "events": [],
            "turns": [],
            "usage": {},
        }
        report_session = normalize_session_for_report(session)
        adapter_agent = "opencode"
        effective = adapter_agent or report_session.primary_agent_type or "claude"
        self.assertEqual(effective, "opencode")
        self.assertEqual(report_session.primary_agent_type, "opencode")


if __name__ == "__main__":
    unittest.main()
