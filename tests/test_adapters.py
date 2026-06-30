"""Tests for ccwhat.adapters — adapter interface, ClaudeAdapter, registry."""

from __future__ import annotations

import json
import sqlite3
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ccwhat.adapters.base import AdapterNotImplementedError, AgentAdapter
from ccwhat.adapters.claude import ClaudeAdapter
from ccwhat.adapters.codex import CodexAdapter
from ccwhat.adapters.opencode import OpenCodeAdapter
from ccwhat.adapters.registry import (
    create_adapter,
    infer_agent_from_target,
    is_implemented,
    normalize_agent_name,
)

# ---------------------------------------------------------------------------
# Real-style JSONL fixtures matching Claude Code log structure
# ---------------------------------------------------------------------------

FIXTURE_USER_TEXT = {
    "type": "user",
    "content": "写一个 Python 脚本读取 CSV",
    "timestamp": "2025-06-01T10:00:00Z",
}

FIXTURE_ASSISTANT_TEXT_AND_TOOL = {
    "type": "assistant",
    "timestamp": "2025-06-01T10:00:05Z",
    "message": {
        "content": [
            {"type": "text", "text": "我来帮你写一个读取 CSV 的 Python 脚本。"},
            {
                "type": "tool_use",
                "name": "bash",
                "id": "toolu_abc123",
                "input": {"command": "cat > /tmp/read_csv.py << 'EOF'\nimport csv\nwith open('data.csv') as f:\n    reader = csv.DictReader(f)\n    for row in reader:\n        print(row)\nEOF"},
            },
        ],
        "usage": {
            "input_tokens": 150,
            "output_tokens": 80,
            "cache_read_input_tokens": 30,
            "cache_creation_input_tokens": 10,
            "cache_write_input_tokens": 5,
            "reasoning_tokens": 20,
        },
    },
}

FIXTURE_TOOL_RESULT = {
    "type": "tool_result",
    "tool_name": "bash",
    "content": "脚本已创建",
    "timestamp": "2025-06-01T10:00:06Z",
}

FIXTURE_ASSISTANT_FINAL = {
    "type": "assistant",
    "timestamp": "2025-06-01T10:00:10Z",
    "message": {
        "content": [
            {"type": "text", "text": "脚本已创建完成。你可以运行 `python3 /tmp/read_csv.py` 来测试。"},
        ],
        "usage": {
            "input_tokens": 10,
            "output_tokens": 20,
        },
    },
}

FIXTURE_USER_WITH_TOOL_RESULT = {
    "type": "user",
    "timestamp": "2025-06-01T10:00:15Z",
    "message": {
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_abc123",
                "name": "bash",
                "content": "脚本已创建完成",
            },
            {"type": "text", "text": "报错了，帮忙看看"},
        ],
    },
}

FIXTURE_USER_TOOL_RESULT_ONLY = {
    "type": "user",
    "timestamp": "2025-06-01T10:00:16Z",
    "message": {
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_def456",
                "name": "read",
                "content": "Error: file not found",
            },
        ],
    },
}

FIXTURE_THINKING = {
    "type": "reasoning",
    "content": "让我想想这个问题的解决方案...",
    "timestamp": "2025-06-01T10:00:02Z",
}

FIXTURE_ERROR = {
    "type": "error",
    "content": "Connection timeout",
    "timestamp": "2025-06-01T10:00:20Z",
}

# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

class TestNormalizeAgentName(unittest.TestCase):
    def test_claude(self) -> None:
        self.assertEqual(normalize_agent_name("claude"), "claude")
        self.assertEqual(normalize_agent_name("claude-code"), "claude")
        self.assertEqual(normalize_agent_name("Claude"), "claude")
        self.assertEqual(normalize_agent_name("CLAUDE-CODE"), "claude")

    def test_codex(self) -> None:
        self.assertEqual(normalize_agent_name("codex"), "codex")

    def test_opencode(self) -> None:
        self.assertEqual(normalize_agent_name("opencode"), "opencode")
        self.assertEqual(normalize_agent_name("open-code"), "opencode")
        self.assertEqual(normalize_agent_name("open_code"), "opencode")
        self.assertEqual(normalize_agent_name("OpenCode"), "opencode")
        self.assertEqual(normalize_agent_name("OPEN-CODE"), "opencode")

    def test_unknown(self) -> None:
        self.assertEqual(normalize_agent_name("unknown-tool"), "unknown-tool")


class TestIsImplemented(unittest.TestCase):
    def test_claude_implemented(self) -> None:
        self.assertTrue(is_implemented("claude"))

    def test_codex_implemented(self) -> None:
        self.assertTrue(is_implemented("codex"))

    def test_opencode_implemented(self) -> None:
        self.assertTrue(is_implemented("opencode"))

    def test_unknown_not_implemented(self) -> None:
        self.assertFalse(is_implemented("unknown"))


class TestCreateAdapter(unittest.TestCase):
    def test_create_claude_adapter(self) -> None:
        adapter = create_adapter("claude")
        self.assertIsInstance(adapter, ClaudeAdapter)
        self.assertEqual(adapter.name, "claude")

    def test_create_claude_code_adapter(self) -> None:
        adapter = create_adapter("claude-code")
        self.assertIsInstance(adapter, ClaudeAdapter)

    def test_create_codex_adapter(self) -> None:
        adapter = create_adapter("codex")
        self.assertIsInstance(adapter, CodexAdapter)
        self.assertEqual(adapter.name, "codex")

    def test_create_opencode_adapter(self) -> None:
        adapter = create_adapter("opencode")
        self.assertIsInstance(adapter, OpenCodeAdapter)
        self.assertEqual(adapter.name, "opencode")

    def test_create_open_code_alias(self) -> None:
        adapter = create_adapter("open-code")
        self.assertIsInstance(adapter, OpenCodeAdapter)

    def test_create_open_code_underscore_alias(self) -> None:
        adapter = create_adapter("open_code")
        self.assertIsInstance(adapter, OpenCodeAdapter)

    def test_create_unknown_raises(self) -> None:
        with self.assertRaises(AdapterNotImplementedError):
            create_adapter("unknown-tool")

    def test_create_with_projects_dir(self) -> None:
        path = Path("/tmp/test-projects")
        adapter = create_adapter("claude", projects_dir=path)
        self.assertEqual(adapter.projects_dir, path)


class TestInferAgentFromTarget(unittest.TestCase):
    def test_infer_claude(self) -> None:
        self.assertEqual(infer_agent_from_target(("claude",)), "claude")
        self.assertEqual(infer_agent_from_target(("claude-code",)), "claude")

    def test_infer_codex(self) -> None:
        self.assertEqual(infer_agent_from_target(("codex",)), "codex")

    def test_infer_opencode(self) -> None:
        self.assertEqual(infer_agent_from_target(("opencode",)), "opencode")

    def test_infer_unknown_returns_as_is(self) -> None:
        self.assertEqual(infer_agent_from_target(("my-ai",)), "my-ai")

    def test_infer_empty_defaults_to_claude(self) -> None:
        self.assertEqual(infer_agent_from_target(()), "claude")


# ---------------------------------------------------------------------------
# ClaudeAdapter basic tests
# ---------------------------------------------------------------------------

class TestClaudeAdapterBasic(unittest.TestCase):
    def make_session_file(self, dir: Path, session_id: str, entries: list[dict]) -> Path:
        path = dir / f"{session_id}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return path

    def make_subagent_file(self, dir: Path, session_id: str, agent_id: str, entries: list[dict]) -> Path:
        sub_dir = dir / session_id / "subagents"
        sub_dir.mkdir(parents=True, exist_ok=True)
        path = sub_dir / f"agent-{agent_id}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        meta_path = sub_dir / f"agent-{agent_id}.meta.json"
        with meta_path.open("w", encoding="utf-8") as f:
            json.dump({"description": f"Sub-agent {agent_id}"}, f)
        return path

    def test_list_projects_empty_dir(self) -> None:
        with TemporaryDirectory() as tmp:
            adapter = ClaudeAdapter(Path(tmp))
            self.assertEqual(adapter.list_projects(), [])

    def test_list_projects_with_sessions(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            proj_dir = tmp_path / "my-project"
            proj_dir.mkdir()
            sid = "550e8400-e29b-41d4-a716-446655440000"
            self.make_session_file(proj_dir, sid, [FIXTURE_USER_TEXT, FIXTURE_ASSISTANT_TEXT_AND_TOOL])
            adapter = ClaudeAdapter(tmp_path)
            projects = adapter.list_projects()
            self.assertEqual(len(projects), 1)
            self.assertEqual(projects[0]["projectDir"], "my-project")
            self.assertEqual(len(projects[0]["sessions"]), 1)
            self.assertEqual(projects[0]["sessions"][0]["id"], sid)

    def test_list_projects_ignores_non_uuid_jsonl(self) -> None:
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "project").mkdir()
            (Path(tmp) / "project" / "not-a-uuid.jsonl").write_text(
                json.dumps({"type": "user"}) + "\n"
            )
            self.assertEqual(ClaudeAdapter(Path(tmp)).list_projects(), [])

    def test_load_session_found(self) -> None:
        with TemporaryDirectory() as tmp:
            proj = Path(tmp) / "p"
            proj.mkdir()
            sid = "550e8400-e29b-41d4-a716-446655440000"
            self.make_session_file(proj, sid, [FIXTURE_USER_TEXT])
            session = ClaudeAdapter(Path(tmp)).load_session(sid)
            self.assertIsNotNone(session)
            self.assertEqual(session["sessionId"], sid)
            self.assertEqual(session["projectDir"], "p")
            self.assertEqual(session["agent"], "claude")

    def test_load_session_not_found(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertIsNone(ClaudeAdapter(Path(tmp)).load_session("nonexistent"))

    def test_load_session_with_subagents(self) -> None:
        with TemporaryDirectory() as tmp:
            proj = Path(tmp) / "p"
            proj.mkdir()
            sid = "550e8400-e29b-41d4-a716-446655440000"
            self.make_session_file(proj, sid, [FIXTURE_USER_TEXT])
            self.make_subagent_file(proj, sid, "sub1", [FIXTURE_ASSISTANT_TEXT_AND_TOOL])
            session = ClaudeAdapter(Path(tmp)).load_session(sid)
            self.assertIsNotNone(session)
            self.assertEqual(len(session["subagents"]), 1)
            self.assertEqual(session["subagents"][0]["agentId"], "sub1")
            self.assertEqual(len(session["subagents"][0]["entries"]), 1)

    def test_jsonl_parse_skip_bad_lines(self) -> None:
        with TemporaryDirectory() as tmp:
            proj = Path(tmp) / "p"
            proj.mkdir()
            sid = "550e8400-e29b-41d4-a716-446655440000"
            path = proj / f"{sid}.jsonl"
            with path.open("w") as f:
                f.write(json.dumps(FIXTURE_USER_TEXT) + "\n")
                f.write("not valid json\n")
                f.write(json.dumps(FIXTURE_ASSISTANT_TEXT_AND_TOOL) + "\n")
            session = ClaudeAdapter(Path(tmp)).load_session(sid)
            self.assertEqual(len(session["main"]), 2)

    def test_raw_to_normalized_events_implements_abstract(self) -> None:
        adapter = ClaudeAdapter()
        events = adapter.raw_to_normalized_events(FIXTURE_USER_TEXT, "session-1")
        self.assertIsInstance(events, list)
        self.assertGreater(len(events), 0)


# ---------------------------------------------------------------------------
# Event normalization tests with real-style fixtures
# ---------------------------------------------------------------------------

class TestEventNormalization(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = ClaudeAdapter()

    def test_user_text_message(self) -> None:
        events = self.adapter.raw_to_normalized_events(FIXTURE_USER_TEXT, "sid-1")
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["kind"], "message")
        self.assertEqual(ev["role"], "user")
        self.assertIn("CSV", ev["content"])
        self.assertEqual(ev["agent"], "claude")
        self.assertEqual(ev["sessionId"], "sid-1")
        self.assertTrue(len(ev["id"]) > 0)

    def test_assistant_splits_text_and_tool_use(self) -> None:
        events = self.adapter.raw_to_normalized_events(FIXTURE_ASSISTANT_TEXT_AND_TOOL, "sid-1")
        self.assertEqual(len(events), 2)
        kinds = [e["kind"] for e in events]
        self.assertEqual(kinds, ["message", "tool_call"])
        self.assertEqual(events[0]["role"], "assistant")
        self.assertEqual(events[0]["content"], "我来帮你写一个读取 CSV 的 Python 脚本。")
        self.assertEqual(events[1]["kind"], "tool_call")
        self.assertEqual(events[1]["toolName"], "bash")
        self.assertEqual(events[1]["toolCallId"], "toolu_abc123")
        self.assertIsInstance(events[1]["content"], dict)

    def test_user_with_tool_result_and_text(self) -> None:
        events = self.adapter.raw_to_normalized_events(FIXTURE_USER_WITH_TOOL_RESULT, "sid-1")
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["kind"], "tool_result")
        self.assertEqual(events[0]["role"], "tool")
        self.assertEqual(events[0]["toolName"], "bash")
        self.assertEqual(events[0]["toolCallId"], "toolu_abc123")
        self.assertEqual(events[1]["kind"], "message")
        self.assertEqual(events[1]["role"], "user")
        self.assertIn("报错了", events[1]["content"])

    def test_user_with_tool_result_only(self) -> None:
        events = self.adapter.raw_to_normalized_events(FIXTURE_USER_TOOL_RESULT_ONLY, "sid-1")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "tool_result")
        self.assertEqual(events[0]["toolName"], "read")
        self.assertEqual(events[0]["toolCallId"], "toolu_def456")

    def test_tool_result_entry(self) -> None:
        events = self.adapter.raw_to_normalized_events(FIXTURE_TOOL_RESULT, "sid-1")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "tool_result")
        self.assertEqual(events[0]["toolName"], "bash")

    def test_reasoning(self) -> None:
        events = self.adapter.raw_to_normalized_events(FIXTURE_THINKING, "sid-1")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "reasoning")
        self.assertEqual(events[0]["role"], "assistant")

    def test_error(self) -> None:
        events = self.adapter.raw_to_normalized_events(FIXTURE_ERROR, "sid-1")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "error")
        self.assertEqual(events[0]["role"], "system")

    def test_events_have_id(self) -> None:
        events = self.adapter.raw_to_normalized_events(FIXTURE_USER_TEXT, "sid-1")
        self.assertIn("id", events[0])
        self.assertIsInstance(events[0]["id"], str)
        self.assertNotEqual(events[0]["id"], "")

    def test_events_have_turnId_none_initially(self) -> None:
        events = self.adapter.raw_to_normalized_events(FIXTURE_USER_TEXT, "sid-1")
        self.assertIsNone(events[0]["turnId"])

    def test_raw_reference_preserved(self) -> None:
        events = self.adapter.raw_to_normalized_events(FIXTURE_USER_TEXT, "sid-1")
        self.assertIs(events[0]["raw"], FIXTURE_USER_TEXT)


# ---------------------------------------------------------------------------
# Usage mapping tests
# ---------------------------------------------------------------------------

class TestUsageMapping(unittest.TestCase):
    def test_cache_creation_input_tokens_mapped(self) -> None:
        events = ClaudeAdapter().raw_to_normalized_events(FIXTURE_ASSISTANT_TEXT_AND_TOOL, "sid-1")
        msg_ev = events[0]
        u = msg_ev["usage"]
        self.assertEqual(u["inputTokens"], 150)
        self.assertEqual(u["outputTokens"], 80)
        self.assertEqual(u["cacheReadTokens"], 30)
        self.assertEqual(u["cacheCreationTokens"], 10)
        self.assertEqual(u["cacheWriteTokens"], 5)
        self.assertEqual(u["reasoningTokens"], 20)
        self.assertEqual(u["totalTokens"], 230)
        self.assertEqual(u["scope"], "event")
        self.assertEqual(u["source"], "agent_log")

    def test_usage_missing_fields_empty(self) -> None:
        events = ClaudeAdapter().raw_to_normalized_events(FIXTURE_USER_TEXT, "sid-1")
        u = events[0]["usage"]
        self.assertIsNone(u.get("inputTokens"))
        self.assertIsNone(u.get("outputTokens"))
        self.assertIsNone(u.get("totalTokens"))
        self.assertIsNone(u.get("cacheReadTokens"))
        self.assertIsNone(u.get("cacheCreationTokens"))
        self.assertIsNone(u.get("cacheWriteTokens"))

    def test_no_cache_hit_rate_default(self) -> None:
        events = ClaudeAdapter().raw_to_normalized_events(FIXTURE_ASSISTANT_TEXT_AND_TOOL, "sid-1")
        u = events[0]["usage"]
        self.assertNotIn("cacheHitRate", u)

    def test_total_tokens_derived_when_no_raw_total(self) -> None:
        events = ClaudeAdapter().raw_to_normalized_events(FIXTURE_ASSISTANT_FINAL, "sid-1")
        u = events[0]["usage"]
        self.assertEqual(u["inputTokens"], 10)
        self.assertEqual(u["outputTokens"], 20)
        self.assertEqual(u["totalTokens"], 30)

    def test_raw_usage_preserved(self) -> None:
        events = ClaudeAdapter().raw_to_normalized_events(FIXTURE_ASSISTANT_TEXT_AND_TOOL, "sid-1")
        u = events[0]["usage"]
        self.assertIsNotNone(u["raw"])
        self.assertEqual(u["raw"]["input_tokens"], 150)


# ---------------------------------------------------------------------------
# Turn aggregation tests
# ---------------------------------------------------------------------------

class TestTurnAggregation(unittest.TestCase):
    def make_session_file(self, dir: Path, session_id: str, entries: list[dict]) -> Path:
        path = dir / f"{session_id}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return path

    def test_session_returns_turns(self) -> None:
        with TemporaryDirectory() as tmp:
            proj = Path(tmp) / "p"
            proj.mkdir()
            sid = "550e8400-e29b-41d4-a716-446655440000"
            self.make_session_file(proj, sid, [
                FIXTURE_USER_TEXT,
                FIXTURE_THINKING,
                FIXTURE_ASSISTANT_TEXT_AND_TOOL,
                FIXTURE_TOOL_RESULT,
            ])
            session = ClaudeAdapter(Path(tmp)).load_session(sid)
            self.assertIn("turns", session)
            self.assertGreaterEqual(len(session["turns"]), 1)

    def test_turn_structure(self) -> None:
        with TemporaryDirectory() as tmp:
            proj = Path(tmp) / "p"
            proj.mkdir()
            sid = "550e8400-e29b-41d4-a716-446655440000"
            self.make_session_file(proj, sid, [
                FIXTURE_USER_TEXT,
                FIXTURE_ASSISTANT_TEXT_AND_TOOL,
            ])
            turn = ClaudeAdapter(Path(tmp)).load_session(sid)["turns"][0]
            self.assertIn("id", turn)
            self.assertIn("sessionId", turn)
            self.assertEqual(turn["agent"], "claude")
            self.assertIn("startedAt", turn)
            self.assertIn("endedAt", turn)
            self.assertIn("events", turn)
            self.assertIn("usage", turn)

    def test_turn_events_order(self) -> None:
        with TemporaryDirectory() as tmp:
            proj = Path(tmp) / "p"
            proj.mkdir()
            sid = "550e8400-e29b-41d4-a716-446655440000"
            self.make_session_file(proj, sid, [
                FIXTURE_USER_TEXT,
                FIXTURE_ASSISTANT_TEXT_AND_TOOL,
            ])
            turn = ClaudeAdapter(Path(tmp)).load_session(sid)["turns"][0]
            ev_kinds = [e["kind"] for e in turn["events"]]
            self.assertEqual(ev_kinds, ["message", "message", "tool_call"])

    def test_user_summary_in_turn(self) -> None:
        with TemporaryDirectory() as tmp:
            proj = Path(tmp) / "p"
            proj.mkdir()
            sid = "550e8400-e29b-41d4-a716-446655440000"
            self.make_session_file(proj, sid, [
                FIXTURE_USER_TEXT,
                FIXTURE_ASSISTANT_TEXT_AND_TOOL,
            ])
            turn = ClaudeAdapter(Path(tmp)).load_session(sid)["turns"][0]
            self.assertIn("userSummary", turn)
            self.assertIn("assistantSummary", turn)

    def test_turn_usage_no_cache_hit_rate(self) -> None:
        with TemporaryDirectory() as tmp:
            proj = Path(tmp) / "p"
            proj.mkdir()
            sid = "550e8400-e29b-41d4-a716-446655440000"
            self.make_session_file(proj, sid, [
                FIXTURE_USER_TEXT,
                FIXTURE_ASSISTANT_FINAL,
            ])
            turn = ClaudeAdapter(Path(tmp)).load_session(sid)["turns"][0]
            self.assertNotIn("cacheHitRate", turn["usage"])

    def test_turn_usage_aggregates(self) -> None:
        with TemporaryDirectory() as tmp:
            proj = Path(tmp) / "p"
            proj.mkdir()
            sid = "550e8400-e29b-41d4-a716-446655440000"
            self.make_session_file(proj, sid, [
                FIXTURE_USER_TEXT,
                FIXTURE_ASSISTANT_FINAL,
            ])
            turn = ClaudeAdapter(Path(tmp)).load_session(sid)["turns"][0]
            self.assertGreater(turn["usage"]["totalTokens"], 0)

    def test_multiple_turns(self) -> None:
        with TemporaryDirectory() as tmp:
            proj = Path(tmp) / "p"
            proj.mkdir()
            sid = "550e8400-e29b-41d4-a716-446655440000"
            user2 = dict(FIXTURE_USER_TEXT)
            user2["content"] = "第二条消息"
            self.make_session_file(proj, sid, [
                FIXTURE_USER_TEXT,
                FIXTURE_ASSISTANT_TEXT_AND_TOOL,
                FIXTURE_TOOL_RESULT,
                user2,
                FIXTURE_ASSISTANT_FINAL,
            ])
            turns = ClaudeAdapter(Path(tmp)).load_session(sid)["turns"]
            self.assertGreaterEqual(len(turns), 2)

    def test_event_turnId_filled_after_aggregation(self) -> None:
        with TemporaryDirectory() as tmp:
            proj = Path(tmp) / "p"
            proj.mkdir()
            sid = "550e8400-e29b-41d4-a716-446655440000"
            self.make_session_file(proj, sid, [
                FIXTURE_USER_TEXT,
                FIXTURE_ASSISTANT_TEXT_AND_TOOL,
            ])
            session = ClaudeAdapter(Path(tmp)).load_session(sid)
            for ev in session["events"]:
                self.assertIsNotNone(ev["turnId"])


# ---------------------------------------------------------------------------
# CLI tests — web command agent parameter and projects-dir priority
# ---------------------------------------------------------------------------

class TestWebCommandAgentParam(unittest.TestCase):
    def test_web_with_agent_claude_creates_claude_adapter(self) -> None:
        from unittest import mock
        from click.testing import CliRunner
        from ccwhat.commands.web_server import web_server
        with mock.patch("ccwhat.commands.web_server._port_in_use", return_value=True), \
             mock.patch("webbrowser.open"):
            runner = CliRunner()
            result = runner.invoke(web_server, ["--agent", "claude", "--port", "19999"])
            self.assertEqual(result.exit_code, 0)
            self.assertIn("Viewer", result.output)

    def test_web_with_agent_codex_creates_codex_adapter(self) -> None:
        from unittest import mock
        from click.testing import CliRunner
        from ccwhat.commands.web_server import web_server
        with mock.patch("ccwhat.commands.web_server._port_in_use", return_value=True), \
             mock.patch("webbrowser.open"):
            runner = CliRunner()
            result = runner.invoke(web_server, ["--agent", "codex", "--port", "19998"])
            self.assertEqual(result.exit_code, 0)
            self.assertIn("Viewer", result.output)

    def test_web_with_agent_opencode_creates_opencode_adapter(self) -> None:
        from unittest import mock
        from click.testing import CliRunner
        from ccwhat.commands.web_server import web_server
        with mock.patch("ccwhat.commands.web_server._port_in_use", return_value=True), \
             mock.patch("webbrowser.open"):
            runner = CliRunner()
            result = runner.invoke(web_server, ["--agent", "opencode", "--port", "19997"])
            self.assertEqual(result.exit_code, 0)
            self.assertIn("Viewer", result.output)

    def test_web_with_explicit_projects_dir(self) -> None:
        from unittest import mock
        from click.testing import CliRunner
        from ccwhat.commands.web_server import web_server
        with mock.patch("ccwhat.commands.web_server._port_in_use", return_value=True), \
             mock.patch("webbrowser.open"):
            runner = CliRunner()
            with TemporaryDirectory() as tmp:
                result = runner.invoke(web_server, [
                    "--agent", "claude",
                    "--projects-dir", tmp,
                    "--port", "19996",
                ])
                self.assertEqual(result.exit_code, 0)
                self.assertIn("Viewer", result.output)

    def test_web_reports_unbindable_windows_port(self) -> None:
        from unittest import mock
        from click.testing import CliRunner
        from ccwhat.commands.web_server import web_server

        class FakeWinError10013(OSError):
            winerror = 10013

        with mock.patch("ccwhat.commands.web_server._port_in_use", return_value=False), \
             mock.patch("ccwhat.commands.web_server.port_bind_error", return_value=FakeWinError10013(13, "bind denied")):
            runner = CliRunner()
            result = runner.invoke(web_server, ["--agent", "codex", "--port", "19995"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("TCP excluded port range", result.output)
        self.assertIn("ccwhat web --port <other-port>", result.output)


class TestRunAgentInferenceAndFallback(unittest.TestCase):
    def test_top_level_passthrough_invokes_run_with_claude(self) -> None:
        from unittest import mock
        from click.testing import CliRunner
        from ccwhat.cli import cli
        fake_run = mock.Mock(run_id="run-test", control={"token": "token"})
        fake_registry = mock.Mock()
        fake_registry.create_run.return_value = fake_run
        with mock.patch("ccwhat.commands.run.RunRegistry", return_value=fake_registry), \
             mock.patch("ccwhat.commands.run.RuntimeController"), \
             mock.patch("ccwhat.commands.run.install_claude_integration"), \
             mock.patch("ccwhat.commands.run._proxy_is_running", return_value=True), \
             mock.patch("ccwhat.commands.run._start_managed_web", return_value=None), \
            mock.patch("ccwhat.commands.run.subprocess.Popen") as mp:
            m = mock.MagicMock()
            m.pid = 4567
            m.wait.return_value = 0
            mp.return_value = m
            runner = CliRunner()
            result = runner.invoke(cli, ["--no-setup", "--no-web", "--port", "19995", "--", "claude"])
            self.assertEqual(result.exit_code, 0)

    def test_top_level_passthrough_codex_works_no_warning(self) -> None:
        from unittest import mock
        from click.testing import CliRunner
        from ccwhat.cli import cli
        fake_run = mock.Mock(run_id="run-test", control={"token": "token"})
        fake_registry = mock.Mock()
        fake_registry.create_run.return_value = fake_run
        with mock.patch("ccwhat.commands.run.RunRegistry", return_value=fake_registry), \
             mock.patch("ccwhat.commands.run.RuntimeController"), \
             mock.patch("ccwhat.commands.run.install_codex_integration"), \
             mock.patch("ccwhat.commands.run._proxy_is_running", return_value=True), \
             mock.patch("ccwhat.commands.run._start_managed_web", return_value=None), \
            mock.patch("ccwhat.commands.run.subprocess.Popen") as mp:
            m = mock.MagicMock()
            m.pid = 4568
            m.wait.return_value = 0
            mp.return_value = m
            runner = CliRunner()
            result = runner.invoke(cli, ["--no-setup", "--no-web", "--port", "19994", "--", "codex"])
            self.assertEqual(result.exit_code, 0)
            self.assertNotIn("Warning", result.output)

    def test_top_level_passthrough_opencode_works_no_warning(self) -> None:
        from unittest import mock
        from click.testing import CliRunner
        from ccwhat.cli import cli
        with mock.patch("ccwhat.commands.run._proxy_is_running", return_value=True), \
             mock.patch("ccwhat.commands.run._start_managed_web", return_value=None), \
             mock.patch("ccwhat.commands.run.subprocess.Popen") as mp:
            m = mock.MagicMock()
            m.pid = 4569
            m.wait.return_value = 0
            mp.return_value = m
            runner = CliRunner()
            result = runner.invoke(cli, ["--no-setup", "--no-web", "--port", "19993", "--", "opencode"])
            self.assertEqual(result.exit_code, 0)
            self.assertNotIn("Warning", result.output)


# ---------------------------------------------------------------------------
# AgentAdapter interface conformance
# ---------------------------------------------------------------------------

class TestAgentAdapterInterface(unittest.TestCase):
    def test_adapter_has_raw_to_normalized_events(self) -> None:
        adapter = ClaudeAdapter()
        self.assertTrue(hasattr(adapter, "raw_to_normalized_events"))
        self.assertTrue(callable(adapter.raw_to_normalized_events))

    def test_raw_to_normalized_events_returns_list(self) -> None:
        adapter = ClaudeAdapter()
        result = adapter.raw_to_normalized_events({"type": "user", "content": "hi"}, "s")
        self.assertIsInstance(result, list)

    def test_adapter_has_all_abstract_methods(self) -> None:
        adapter = ClaudeAdapter()
        self.assertTrue(hasattr(adapter, "name"))
        self.assertTrue(hasattr(adapter, "default_projects_dir"))
        self.assertTrue(hasattr(adapter, "list_projects"))
        self.assertTrue(hasattr(adapter, "list_sessions"))
        self.assertTrue(hasattr(adapter, "load_session"))


# ---------------------------------------------------------------------------
# CodexAdapter tests
# ---------------------------------------------------------------------------

class TestCodexAdapter(unittest.TestCase):
    CODEX_USER = {
        "type": "response_item",
        "timestamp": "2025-06-01T10:00:00Z",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Hello codex"}],
        },
    }

    CODEX_ASSISTANT = {
        "type": "response_item",
        "timestamp": "2025-06-01T10:00:02Z",
        "payload": {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Hello! How can I help?"}],
        },
    }

    CODEX_FUNC_CALL = {
        "type": "response_item",
        "timestamp": "2025-06-01T10:00:03Z",
        "payload": {
            "type": "function_call",
            "name": "bash",
            "call_id": "call_123",
            "arguments": json.dumps({"command": "echo hi"}),
        },
    }

    CODEX_FUNC_OUTPUT = {
        "type": "response_item",
        "timestamp": "2025-06-01T10:00:04Z",
        "payload": {
            "type": "function_call_output",
            "call_id": "call_123",
            "output": "hi\n",
        },
    }

    CODEX_REASONING = {
        "type": "response_item",
        "timestamp": "2025-06-01T10:00:01Z",
        "payload": {
            "type": "reasoning",
            "summary": ["thinking about the problem"],
        },
    }

    CODEX_EVENT_USER_MSG = {
        "type": "event_msg",
        "timestamp": "2025-06-01T10:00:00Z",
        "payload": {"type": "user_message", "message": "Hello from event"},
    }

    CODEX_EVENT_AGENT_MSG = {
        "type": "event_msg",
        "timestamp": "2025-06-01T10:00:02Z",
        "payload": {"type": "agent_message", "message": "Hi from agent", "phase": "reply"},
    }

    CODEX_TOKEN_COUNT = {
        "type": "event_msg",
        "timestamp": "2025-06-01T10:00:05Z",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cached_input_tokens": 30,
                }
            },
        },
    }

    CODEX_TURN_CONTEXT = {
        "type": "turn_context",
        "timestamp": "2025-06-01T10:00:00Z",
        "payload": {"cwd": "/home/user/project", "model": "claude-sonnet-4-20250514"},
    }

    CODEX_SESSION_META = {
        "type": "session_meta",
        "timestamp": "2025-06-01T09:59:00Z",
        "payload": {"id": "session-uuid", "cwd": "/home/user/project"},
    }

    def test_list_projects_empty_dir(self) -> None:
        with TemporaryDirectory() as tmp:
            adapter = CodexAdapter(Path(tmp))
            self.assertEqual(adapter.list_projects(), [])

    def test_list_projects_with_session(self) -> None:
        with TemporaryDirectory() as tmp:
            pd = Path(tmp)
            session_dir = pd / "2025" / "06" / "01"
            session_dir.mkdir(parents=True)
            fname = "rollout-2025-06-01T10-00-00-019e9837-9271-7192-bfbf-f5b74ebe585c.jsonl"
            (session_dir / fname).write_text(json.dumps(self.CODEX_USER) + "\n")
            adapter = CodexAdapter(pd)
            projects = adapter.list_projects()
            self.assertEqual(len(projects), 1)
            self.assertIn("sessions", projects[0])

    def test_list_sessions(self) -> None:
        with TemporaryDirectory() as tmp:
            pd = Path(tmp)
            session_dir = pd / "2025" / "06" / "01"
            session_dir.mkdir(parents=True)
            fname = "rollout-2025-06-01T10-00-00-019e9837-9271-7192-bfbf-f5b74ebe585c.jsonl"
            (session_dir / fname).write_text(json.dumps(self.CODEX_USER) + "\n")
            adapter = CodexAdapter(pd)
            sessions = adapter.list_sessions()
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0]["id"], "019e9837-9271-7192-bfbf-f5b74ebe585c")

    def test_load_session_found(self) -> None:
        with TemporaryDirectory() as tmp:
            pd = Path(tmp)
            session_dir = pd / "2025" / "06" / "01"
            session_dir.mkdir(parents=True)
            sid = "019e9837-9271-7192-bfbf-f5b74ebe585c"
            fname = f"rollout-2025-06-01T10-00-00-{sid}.jsonl"
            (session_dir / fname).write_text(
                json.dumps(self.CODEX_USER) + "\n" +
                json.dumps(self.CODEX_ASSISTANT) + "\n"
            )
            adapter = CodexAdapter(pd)
            session = adapter.load_session(sid)
            self.assertIsNotNone(session)
            self.assertEqual(session["sessionId"], sid)
            self.assertEqual(session["agent"], "codex")
            self.assertIn("events", session)
            self.assertIn("turns", session)
            self.assertIn("usage", session)
            self.assertEqual(session["main"], [])
            self.assertEqual(session["subagents"], [])

    def test_load_session_not_found(self) -> None:
        with TemporaryDirectory() as tmp:
            adapter = CodexAdapter(Path(tmp))
            self.assertIsNone(adapter.load_session("nonexistent"))

    def test_raw_user_message(self) -> None:
        events = CodexAdapter().raw_to_normalized_events(self.CODEX_USER, "sid")
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["kind"], "message")
        self.assertEqual(ev["role"], "user")
        self.assertIn("Hello codex", ev["content"])

    def test_raw_assistant_message(self) -> None:
        events = CodexAdapter().raw_to_normalized_events(self.CODEX_ASSISTANT, "sid")
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["kind"], "message")
        self.assertEqual(ev["role"], "assistant")
        self.assertIn("Hello! How can I help?", ev["content"])

    def test_raw_function_call(self) -> None:
        events = CodexAdapter().raw_to_normalized_events(self.CODEX_FUNC_CALL, "sid")
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["kind"], "tool_call")
        self.assertEqual(ev["toolName"], "bash")
        self.assertEqual(ev["toolCallId"], "call_123")
        self.assertIsInstance(ev["content"], dict)

    def test_raw_function_call_output(self) -> None:
        events = CodexAdapter().raw_to_normalized_events(self.CODEX_FUNC_OUTPUT, "sid")
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["kind"], "tool_result")
        self.assertEqual(ev["role"], "tool")
        self.assertEqual(ev["toolCallId"], "call_123")

    def test_raw_reasoning(self) -> None:
        events = CodexAdapter().raw_to_normalized_events(self.CODEX_REASONING, "sid")
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["kind"], "reasoning")
        self.assertEqual(ev["role"], "assistant")

    def test_event_user_message(self) -> None:
        events = CodexAdapter().raw_to_normalized_events(self.CODEX_EVENT_USER_MSG, "sid")
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["kind"], "message")
        self.assertEqual(ev["role"], "user")
        self.assertIn("Hello from event", ev["content"])

    def test_event_agent_message(self) -> None:
        events = CodexAdapter().raw_to_normalized_events(self.CODEX_EVENT_AGENT_MSG, "sid")
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["kind"], "message")
        self.assertEqual(ev["role"], "assistant")
        self.assertIn("Hi from agent", ev["content"])

    def test_token_count_event(self) -> None:
        events = CodexAdapter().raw_to_normalized_events(self.CODEX_TOKEN_COUNT, "sid")
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["kind"], "metadata")
        self.assertEqual(ev["usage"]["inputTokens"], 100)
        self.assertEqual(ev["usage"]["outputTokens"], 50)
        self.assertEqual(ev["usage"]["cachedInputTokens"], 30)

    def test_turn_context_event(self) -> None:
        events = CodexAdapter().raw_to_normalized_events(self.CODEX_TURN_CONTEXT, "sid")
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["kind"], "metadata")

    def test_session_meta_event(self) -> None:
        events = CodexAdapter().raw_to_normalized_events(self.CODEX_SESSION_META, "sid")
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["kind"], "metadata")

    def test_patch_apply_end_event_preserves_payload(self) -> None:
        entry = {
            "type": "event_msg",
            "timestamp": "2025-06-01T10:00:00Z",
            "payload": {
                "type": "patch_apply_end",
                "changes": {
                    "src/app.py": {"unified_diff": "@@\n-old\n+new\n"},
                    "src/new.py": {"content": "new file"},
                },
            },
        }
        events = CodexAdapter().raw_to_normalized_events(entry, "sid")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "metadata")
        self.assertEqual(events[0]["summary"], "patch_apply_end")
        self.assertEqual(events[0]["content"]["changes"]["src/new.py"]["content"], "new file")

    def test_events_have_required_fields(self) -> None:
        events = CodexAdapter().raw_to_normalized_events(self.CODEX_USER, "sid")
        ev = events[0]
        for key in ("id", "agent", "sessionId", "turnId", "timestamp", "role", "kind",
                     "content", "summary", "toolName", "toolCallId", "parentId", "usage", "raw"):
            self.assertIn(key, ev)

    def test_raw_event_ids_are_stable(self) -> None:
        adapter = CodexAdapter()
        first = adapter.raw_to_normalized_events(self.CODEX_FUNC_CALL, "sid")
        second = adapter.raw_to_normalized_events(self.CODEX_FUNC_CALL, "sid")

        self.assertEqual([ev["id"] for ev in first], [ev["id"] for ev in second])

    def test_load_session_event_and_turn_ids_are_stable(self) -> None:
        with TemporaryDirectory() as tmp:
            pd = Path(tmp)
            session_dir = pd / "2025" / "06" / "01"
            session_dir.mkdir(parents=True)
            sid = "019e9837-9271-7192-bfbf-f5b74ebe585c"
            fname = f"rollout-2025-06-01T10-00-00-{sid}.jsonl"
            (session_dir / fname).write_text(
                json.dumps(self.CODEX_USER) + "\n" +
                json.dumps(self.CODEX_FUNC_CALL) + "\n" +
                json.dumps(self.CODEX_FUNC_OUTPUT) + "\n" +
                json.dumps(self.CODEX_ASSISTANT) + "\n"
            )
            adapter = CodexAdapter(pd)

            first = adapter.load_session(sid)
            second = adapter.load_session(sid)

            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            self.assertEqual(
                [ev["id"] for ev in first["events"]],
                [ev["id"] for ev in second["events"]],
            )
            self.assertEqual(
                [turn["id"] for turn in first["turns"]],
                [turn["id"] for turn in second["turns"]],
            )

    def test_adapter_implements_interface(self) -> None:
        adapter = CodexAdapter()
        for attr in ("name", "default_projects_dir", "list_projects", "list_sessions", "load_session"):
            self.assertTrue(hasattr(adapter, attr))
        self.assertEqual(adapter.name, "codex")

    def test_developer_and_environment_context_are_metadata(self) -> None:
        developer_entry = {
            "type": "response_item",
            "timestamp": "2025-06-01T10:00:00Z",
            "payload": {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": "<skills_instructions>huge system text</skills_instructions>"}],
            },
        }
        environment_entry = {
            "type": "response_item",
            "timestamp": "2025-06-01T10:00:01Z",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "<environment_context><cwd>/tmp/project</cwd></environment_context>"}],
            },
        }

        dev_events = CodexAdapter().raw_to_normalized_events(developer_entry, "sid")
        env_events = CodexAdapter().raw_to_normalized_events(environment_entry, "sid")

        self.assertEqual(dev_events[0]["kind"], "metadata")
        self.assertIsNone(dev_events[0]["role"])
        self.assertIsNone(dev_events[0]["content"])
        self.assertEqual(env_events[0]["kind"], "metadata")
        self.assertIsNone(env_events[0]["role"])
        self.assertIsNone(env_events[0]["content"])

    def test_sqlite_metadata_uses_real_codex_schema(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state_5.sqlite"
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "CREATE TABLE threads ("
                "id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL, created_at INTEGER NOT NULL, "
                "updated_at INTEGER NOT NULL, source TEXT NOT NULL, model_provider TEXT NOT NULL, "
                "cwd TEXT NOT NULL, title TEXT NOT NULL, sandbox_policy TEXT NOT NULL, "
                "approval_mode TEXT NOT NULL, tokens_used INTEGER NOT NULL DEFAULT 0, "
                "has_user_event INTEGER NOT NULL DEFAULT 0, archived INTEGER DEFAULT 0, model TEXT)"
            )
            conn.execute(
                "INSERT INTO threads (id, rollout_path, created_at, updated_at, source, model_provider, cwd, title, "
                "sandbox_policy, approval_mode, tokens_used, has_user_event, archived, model) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "thread-1",
                    "/tmp/rollout.jsonl",
                    1780000000,
                    1780000100,
                    "cli",
                    "openai",
                    "/tmp/codex-project",
                    "Codex session",
                    "workspace-write",
                    "on-request",
                    1234,
                    1,
                    0,
                    "gpt-5",
                ),
            )
            conn.commit()
            conn.close()

            adapter = CodexAdapter()
            adapter._sqlite_path = db_path
            meta = adapter._load_sqlite_metadata()

        self.assertEqual(meta["thread-1"]["provider"], "openai")
        self.assertEqual(meta["thread-1"]["cwd"], "/tmp/codex-project")
        self.assertEqual(meta["thread-1"]["tokens_used"], 1234)


# ---------------------------------------------------------------------------
# OpenCodeAdapter tests
# ---------------------------------------------------------------------------

class TestOpenCodeAdapter(unittest.TestCase):
    def _create_db(self, tmp: str) -> Path:
        db_path = Path(tmp) / "opencode.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE session ("
            "id TEXT PRIMARY KEY, project_id TEXT, directory TEXT, title TEXT, "
            "agent TEXT, model TEXT, time_created INTEGER, time_updated INTEGER, "
            "tokens_input INTEGER, tokens_output INTEGER, "
            "tokens_reasoning INTEGER, "
            "tokens_cache_read INTEGER, tokens_cache_write INTEGER, "
            "cost REAL"
            ")"
        )
        conn.execute(
            "CREATE TABLE message ("
            "id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, "
            "time_updated INTEGER, data TEXT"
            ")"
        )
        conn.execute(
            "CREATE TABLE part ("
            "id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT, "
            "time_created INTEGER, time_updated INTEGER, data TEXT"
            ")"
        )
        conn.execute(
            "CREATE TABLE project ("
            "id TEXT PRIMARY KEY, worktree TEXT, name TEXT, time_created INTEGER, "
            "time_updated INTEGER, sandboxes TEXT"
            ")"
        )
        conn.execute(
            "CREATE TABLE session_message ("
            "id TEXT PRIMARY KEY, session_id TEXT, type TEXT, time_created INTEGER, "
            "time_updated INTEGER, data TEXT, seq INTEGER"
            ")"
        )
        conn.commit()
        conn.close()
        return db_path

    def _insert_session(
        self, db: Path, sid: str, project_id: str = "p1", directory: str = "/tmp/test",
        title: str = "Test Session", agent: str = "opencode",
        model: str = '{"id":"gpt-4","providerID":"openai"}',
        tokens_input: int | None = 1000, tokens_output: int | None = 500,
        tokens_reasoning: int | None = 0, tokens_cache_read: int | None = 0,
    ) -> None:
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO session (id, project_id, directory, title, agent, model, "
            "time_created, time_updated, tokens_input, tokens_output, "
            "tokens_reasoning, tokens_cache_read) "
            "VALUES (?, ?, ?, ?, ?, ?, 1000000, 1000100, ?, ?, ?, ?)",
            (sid, project_id, directory, title, agent, model,
             tokens_input, tokens_output, tokens_reasoning, tokens_cache_read),
        )
        conn.commit()
        conn.close()

    def _insert_message(
        self, db: Path, mid: str, sid: str, role: str,
        time_created: int, data: dict | None = None,
    ) -> None:
        conn = sqlite3.connect(str(db))
        if data is None:
            data = {"role": role}
        conn.execute(
            "INSERT INTO message (id, session_id, time_created, time_updated, data) "
            "VALUES (?, ?, ?, ?, ?)",
            (mid, sid, time_created, time_created, json.dumps(data)),
        )
        conn.commit()
        conn.close()

    def _insert_part(
        self, db: Path, pid: str, mid: str, sid: str, ptype: str,
        text: str = "", time_created: int = 1000050, time_updated: int | None = None,
        extra: dict | None = None,
    ) -> None:
        conn = sqlite3.connect(str(db))
        data: dict = {"type": ptype}
        if text:
            data["text"] = text
        if extra:
            data.update(extra)
        conn.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (pid, mid, sid, time_created, time_updated if time_updated is not None else time_created, json.dumps(data)),
        )
        conn.commit()
        conn.close()

    def test_list_projects_empty_db(self) -> None:
        with TemporaryDirectory() as tmp:
            db = self._create_db(tmp)
            adapter = OpenCodeAdapter(db)
            self.assertEqual(adapter.list_projects(), [])

    def test_list_projects_with_session(self) -> None:
        with TemporaryDirectory() as tmp:
            db = self._create_db(tmp)
            self._insert_session(db, "ses_test123", directory="/tmp/test")
            adapter = OpenCodeAdapter(db)
            projects = adapter.list_projects()
            self.assertGreater(len(projects), 0)

    def test_list_sessions(self) -> None:
        with TemporaryDirectory() as tmp:
            db = self._create_db(tmp)
            self._insert_session(db, "ses_test123", directory="/tmp/test", tokens_input=500, tokens_output=100)
            adapter = OpenCodeAdapter(db)
            sessions = adapter.list_sessions()
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0]["id"], "ses_test123")
            self.assertEqual(sessions[0]["tokensInput"], 500)

    def test_list_sessions_no_usage_fake(self) -> None:
        with TemporaryDirectory() as tmp:
            db = self._create_db(tmp)
            self._insert_session(db, "ses_nousage_ls", directory="/tmp/nousage",
                                 tokens_input=None, tokens_output=None)
            adapter = OpenCodeAdapter(db)
            sessions = adapter.list_sessions()
            found = [s for s in sessions if s["id"] == "ses_nousage_ls"]
            self.assertEqual(len(found), 1)
            self.assertNotIn("tokensInput", found[0])
            self.assertNotIn("tokensOutput", found[0])

    def test_load_session_not_found(self) -> None:
        with TemporaryDirectory() as tmp:
            db = self._create_db(tmp)
            adapter = OpenCodeAdapter(db)
            self.assertIsNone(adapter.load_session("nonexistent"))

    def test_load_session_with_user_and_assistant(self) -> None:
        with TemporaryDirectory() as tmp:
            db = self._create_db(tmp)
            sid = "ses_test123"
            self._insert_session(db, sid, directory="/tmp/test", agent="build")

            mid_user = "msg_user_1"
            mid_assistant = "msg_asst_1"
            user_data = {"role": "user"}
            asst_data = {"role": "assistant", "tokens": {"total": 600, "input": 500, "output": 100}}
            self._insert_message(db, mid_user, sid, "user", 1000000, user_data)
            self._insert_message(db, mid_assistant, sid, "assistant", 1000050, asst_data)

            self._insert_part(db, "prt_u1", mid_user, sid, "text", "Hello from user")
            self._insert_part(db, "prt_a1", mid_assistant, sid, "text", "Hello from assistant")

            adapter = OpenCodeAdapter(db)
            session = adapter.load_session(sid)
            self.assertIsNotNone(session)
            self.assertEqual(session["sessionId"], sid)
            self.assertEqual(session["agent"], "opencode")
            self.assertEqual(session["_metadata"]["opencodeAgent"], "build")
            self.assertIn("events", session)
            self.assertIn("turns", session)
            self.assertIn("usage", session)
            self.assertGreater(len(session["events"]), 0)
            self.assertEqual(session["main"], [])
            self.assertEqual(session["subagents"], [])

    def test_load_session_after_list_projects_from_another_thread(self) -> None:
        """Threaded viewer may serve /api/projects and /api/session on different threads."""
        with TemporaryDirectory() as tmp:
            db = self._create_db(tmp)
            sid = "ses_threaded_open"
            self._insert_session(db, sid, directory="/tmp/threaded", agent="build")
            self._insert_message(db, "msg_thread_user", sid, "user", 1000000, {"role": "user"})
            self._insert_part(db, "prt_thread_user", "msg_thread_user", sid, "text", "hello")

            adapter = OpenCodeAdapter(db)
            self.assertGreater(len(adapter.list_projects()), 0)

            loaded: list[dict | None] = []
            errors: list[BaseException] = []

            def _load() -> None:
                try:
                    loaded.append(adapter.load_session(sid))
                except BaseException as exc:
                    errors.append(exc)

            t = threading.Thread(target=_load)
            t.start()
            t.join(timeout=5)

            self.assertFalse(t.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(len(loaded), 1)
            self.assertIsNotNone(loaded[0])
            self.assertEqual(loaded[0]["sessionId"], sid)

    def test_load_session_with_tool_parts(self) -> None:
        with TemporaryDirectory() as tmp:
            db = self._create_db(tmp)
            sid = "ses_tool_test"
            mid = "msg_asst_tool"
            self._insert_session(db, sid)
            asst_data = {"role": "assistant"}
            self._insert_message(db, mid, sid, "assistant", 1000050, asst_data)

            self._insert_part(db, "prt_t1", mid, sid, "tool", time_created=1000051, extra={
                "tool": "bash",
                "callID": "call_bash_1",
                "state": {
                    "status": "completed",
                    "input": {"command": "echo hello"},
                    "output": "hello\n",
                },
            })
            self._insert_part(db, "prt_r1", mid, sid, "reasoning", time_created=1000052,
                              text="thinking step")

            adapter = OpenCodeAdapter(db)
            session = adapter.load_session(sid)
            self.assertIsNotNone(session)
            kinds = [e["kind"] for e in session["events"]]
            self.assertIn("tool_call", kinds)
            self.assertIn("reasoning", kinds)

    def test_opencode_tool_timestamps_build_report_phases(self) -> None:
        from ccwhat.session_report.core import build_report_data

        with TemporaryDirectory() as tmp:
            db = self._create_db(tmp)
            sid = "ses_tool_time_test"
            user_mid = "msg_user"
            tool_mid = "msg_asst_tool"
            self._insert_session(db, sid)
            self._insert_message(db, user_mid, sid, "user", 1780676608727, {"role": "user"})
            self._insert_part(db, "prt_user", user_mid, sid, "text", "run git clone", time_created=1780676608727)
            self._insert_message(db, tool_mid, sid, "assistant", 1780676610000, {"role": "assistant"})
            self._insert_part(db, "prt_tool", tool_mid, sid, "tool", time_created=1780676613435, time_updated=1780676688822, extra={
                "tool": "bash",
                "callID": "call_bash_1",
                "state": {
                    "status": "completed",
                    "input": {"command": "git clone repo"},
                    "output": "done\n",
                    "time": {"start": 1780676688807, "end": 1780676688820},
                },
            })

            adapter = OpenCodeAdapter(db)
            session = adapter.load_session(sid)
            data = build_report_data(session)

            self.assertGreater(data.summary["phaseCount"], 0)
            self.assertGreater(data.summary["totalWallMin"], 0)
            self.assertGreater(data.summary["toolEventCount"], 0)
            self.assertGreaterEqual(data.tool_events[0]["duration_ms"], 13)

    def test_raw_to_normalized_events_user_text(self) -> None:
        entry = {
            "time_created": 1000000,
            "message_id": "msg_1",
            "message_data": {"role": "user"},
            "parts": [{"data": {"type": "text", "text": "Hello"}}],
        }
        events = OpenCodeAdapter().raw_to_normalized_events(entry, "sid")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["role"], "user")
        self.assertEqual(events[0]["kind"], "message")
        self.assertEqual(events[0]["content"], "Hello")

    def test_raw_to_normalized_events_assistant_text(self) -> None:
        entry = {
            "time_created": 1000050,
            "message_id": "msg_2",
            "message_data": {"role": "assistant"},
            "parts": [{"data": {"type": "text", "text": "Hi there"}}],
        }
        events = OpenCodeAdapter().raw_to_normalized_events(entry, "sid")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["role"], "assistant")
        self.assertEqual(events[0]["kind"], "message")
        self.assertEqual(events[0]["content"], "Hi there")

    def test_raw_to_normalized_events_tool(self) -> None:
        entry = {
            "time_created": 1000050,
            "message_id": "msg_3",
            "message_data": {"role": "assistant"},
            "parts": [{
                "data": {
                    "type": "tool",
                    "tool": "bash",
                    "callID": "call_1",
                    "state": {
                        "status": "completed",
                        "input": {"command": "ls"},
                        "output": "file.txt\n",
                    },
                },
            }],
        }
        events = OpenCodeAdapter().raw_to_normalized_events(entry, "sid")
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["kind"], "tool_call")
        self.assertEqual(events[0]["toolName"], "bash")
        self.assertEqual(events[1]["kind"], "tool_result")
        self.assertEqual(events[1]["role"], "tool")

    def test_raw_event_ids_are_stable(self) -> None:
        entry = {
            "time_created": 1000050,
            "message_id": "msg_stable_tool",
            "message_data": {"role": "assistant"},
            "parts": [{
                "id": "part_tool_1",
                "data": {
                    "type": "tool",
                    "tool": "bash",
                    "callID": "call_stable",
                    "state": {
                        "status": "completed",
                        "input": {"command": "pwd"},
                        "output": "/tmp\n",
                    },
                },
            }],
        }
        adapter = OpenCodeAdapter()
        first = adapter.raw_to_normalized_events(entry, "sid")
        second = adapter.raw_to_normalized_events(entry, "sid")

        self.assertEqual([ev["id"] for ev in first], [ev["id"] for ev in second])
        self.assertEqual(len({ev["id"] for ev in first}), len(first))

    def test_raw_to_normalized_events_reasoning(self) -> None:
        entry = {
            "time_created": 1000040,
            "message_id": "msg_4",
            "message_data": {"role": "assistant"},
            "parts": [{"data": {"type": "reasoning", "text": "thinking..."}}],
        }
        events = OpenCodeAdapter().raw_to_normalized_events(entry, "sid")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "reasoning")

    def test_raw_to_normalized_events_step(self) -> None:
        entry = {
            "time_created": 1000045,
            "message_id": "msg_5",
            "message_data": {"role": "assistant"},
            "parts": [{"data": {"type": "step-start"}}],
        }
        events = OpenCodeAdapter().raw_to_normalized_events(entry, "sid")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "step")

    def test_session_usage_from_db(self) -> None:
        with TemporaryDirectory() as tmp:
            db = self._create_db(tmp)
            sid = "ses_usage1"
            self._insert_session(db, sid, tokens_input=1500, tokens_output=300,
                                 tokens_reasoning=50, tokens_cache_read=200)
            self._insert_message(db, "msg_1", sid, "user", 1000000, {"role": "user"})
            self._insert_part(db, "prt_1", "msg_1", sid, "text", "hello")

            adapter = OpenCodeAdapter(db)
            session = adapter.load_session(sid)
            self.assertEqual(session["usage"]["inputTokens"], 1500)
            self.assertEqual(session["usage"]["outputTokens"], 300)
            self.assertEqual(session["usage"]["reasoningTokens"], 50)
            self.assertEqual(session["usage"]["cacheReadTokens"], 200)

    def test_load_session_event_and_turn_ids_are_stable(self) -> None:
        with TemporaryDirectory() as tmp:
            db = self._create_db(tmp)
            sid = "ses_stable_ids"
            self._insert_session(db, sid)
            self._insert_message(db, "msg_stable_user", sid, "user", 1000000, {"role": "user"})
            self._insert_part(db, "part_stable_user", "msg_stable_user", sid, "text", "hello")
            self._insert_message(db, "msg_stable_assistant", sid, "assistant", 1000050, {"role": "assistant"})
            self._insert_part(db, "part_stable_tool", "msg_stable_assistant", sid, "tool", time_created=1000051, extra={
                "tool": "bash",
                "callID": "call_stable",
                "state": {
                    "status": "completed",
                    "input": {"command": "echo hello"},
                    "output": "hello\n",
                },
            })

            adapter = OpenCodeAdapter(db)
            first = adapter.load_session(sid)
            second = adapter.load_session(sid)

            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            self.assertEqual(
                [ev["id"] for ev in first["events"]],
                [ev["id"] for ev in second["events"]],
            )
            self.assertEqual(
                [turn["id"] for turn in first["turns"]],
                [turn["id"] for turn in second["turns"]],
            )

    def test_adapter_implements_interface(self) -> None:
        adapter = OpenCodeAdapter()
        for attr in ("name", "default_projects_dir", "list_projects", "list_sessions", "load_session"):
            self.assertTrue(hasattr(adapter, attr))
        self.assertEqual(adapter.name, "opencode")

    def test_list_projects_returns_sessions(self) -> None:
        with TemporaryDirectory() as tmp:
            db = self._create_db(tmp)
            sid = "ses_proj1"
            self._insert_session(db, sid, directory="/tmp/testproj", title="Test Project Session")
            self._insert_message(db, "msg_p1", sid, "user", 1000000, {"role": "user"})
            self._insert_part(db, "prt_p1", "msg_p1", sid, "text", "hello")
            adapter = OpenCodeAdapter(db)
            projects = adapter.list_projects()
            self.assertGreater(len(projects), 0)
            for proj in projects:
                for s in proj.get("sessions", []):
                    self.assertIn("id", s)
                    self.assertIn("title", s)
                    self.assertIn("agent", s)
                    self.assertIn("firstTimestamp", s)
                    self.assertIn("lastTimestamp", s)
                    self.assertIn("tokensInput", s)
                    self.assertEqual(1000, s["tokensInput"])
                    self.assertIn("tokensOutput", s)
                    self.assertEqual(500, s["tokensOutput"])

    def test_list_projects_no_usage_fake_session(self) -> None:
        with TemporaryDirectory() as tmp:
            db = self._create_db(tmp)
            sid = "ses_nousage_p"
            self._insert_session(db, sid, directory="/tmp/nousage",
                                 title="No Usage Session",
                                 tokens_input=None, tokens_output=None)
            self._insert_message(db, "msg_nup1", sid, "user", 1000000, {"role": "user"})
            self._insert_part(db, "prt_nup1", "msg_nup1", sid, "text", "hi")
            adapter = OpenCodeAdapter(db)
            projects = adapter.list_projects()
            found = False
            for proj in projects:
                for s in proj.get("sessions", []):
                    if s["id"] == sid:
                        found = True
                        self.assertNotIn("tokensInput", s)
                        self.assertNotIn("tokensOutput", s)
            self.assertTrue(found)

    def test_no_usage_does_not_fake_zero_session(self) -> None:
        with TemporaryDirectory() as tmp:
            db = self._create_db(tmp)
            sid = "ses_no_usage"
            self._insert_session(db, sid, directory="/tmp/nousage", tokens_input=None, tokens_output=None)
            self._insert_message(db, "msg_nu1", sid, "user", 1000000, {"role": "user"})
            self._insert_part(db, "prt_nu1", "msg_nu1", sid, "text", "hello")
            adapter = OpenCodeAdapter(db)
            session = adapter.load_session(sid)
            usage = session["usage"]
            self.assertNotIn("inputTokens", usage)
            self.assertNotIn("outputTokens", usage)
            self.assertNotIn("totalTokens", usage)

    def test_no_cache_hit_rate_opencode(self) -> None:
        with TemporaryDirectory() as tmp:
            db = self._create_db(tmp)
            sid = "ses_nocache_op"
            self._insert_session(db, sid, tokens_input=500, tokens_output=100)
            self._insert_message(db, "msg_nc1", sid, "user", 1000000, {"role": "user"})
            self._insert_part(db, "prt_nc1", "msg_nc1", sid, "text", "hello")
            adapter = OpenCodeAdapter(db)
            session = adapter.load_session(sid)
            self.assertNotIn("cacheHitRate", session["usage"])

    def test_function_call_bad_json_doesnt_crash(self) -> None:
        bad_json = {
            "type": "response_item",
            "timestamp": "2025-06-01T10:00:03Z",
            "payload": {
                "type": "function_call",
                "name": "bash",
                "call_id": "call_bad",
                "arguments": "{bad json}",
            },
        }
        events = CodexAdapter().raw_to_normalized_events(bad_json, "sid")
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["kind"], "tool_call")
        self.assertEqual(ev["toolName"], "bash")
        self.assertIsInstance(ev["content"], str)

    def test_project_dir_from_cwd(self) -> None:
        with TemporaryDirectory() as tmp:
            pd = Path(tmp)
            session_dir = pd / "2025" / "06" / "01"
            session_dir.mkdir(parents=True)
            sid = "019e9837-9271-7192-bfbf-f5b74ebe585c"
            fname = f"rollout-2025-06-01T10-00-00-{sid}.jsonl"
            with (session_dir / fname).open("w", encoding="utf-8") as f:
                f.write(json.dumps({
                    "type": "turn_context",
                    "timestamp": "2025-06-01T10:00:00Z",
                    "payload": {"cwd": "/home/user/myproject", "model": "claude-sonnet"},
                }) + "\n")
                f.write(json.dumps({
                    "type": "response_item",
                    "timestamp": "2025-06-01T10:00:01Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "hello"}],
                    },
                }) + "\n")
            adapter = CodexAdapter(pd)
            session = adapter.load_session(sid)
            self.assertIsNotNone(session)
            self.assertEqual(session["projectDir"], "/home/user/myproject")

    def test_project_dir_from_cwd_xml_tag(self) -> None:
        with TemporaryDirectory() as tmp:
            pd = Path(tmp)
            session_dir = pd / "2025" / "06" / "02"
            session_dir.mkdir(parents=True)
            sid = "119e9837-9271-7192-bfbf-f5b74ebe585c"
            fname = f"rollout-2025-06-02T10-00-00-{sid}.jsonl"
            with (session_dir / fname).open("w", encoding="utf-8") as f:
                f.write(json.dumps({
                    "type": "response_item",
                    "timestamp": "2025-06-01T10:00:01Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "<cwd>/tmp/otherproject</cwd> do something"}],
                    },
                }) + "\n")
            adapter = CodexAdapter(pd)
            session = adapter.load_session(sid)
            self.assertIsNotNone(session)
            self.assertEqual(session["projectDir"], "/tmp/otherproject")

    def test_no_usage_does_not_fake_zero_session_codex(self) -> None:
        with TemporaryDirectory() as tmp:
            pd = Path(tmp)
            session_dir = pd / "2025" / "06" / "03"
            session_dir.mkdir(parents=True)
            sid = "229e9837-9271-7192-bfbf-f5b74ebe585c"
            fname = f"rollout-2025-06-03T10-00-00-{sid}.jsonl"
            with (session_dir / fname).open("w", encoding="utf-8") as f:
                f.write(json.dumps({
                    "type": "response_item",
                    "timestamp": "2025-06-01T10:00:01Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "hi"}],
                    },
                }) + "\n")
            adapter = CodexAdapter(pd)
            session = adapter.load_session(sid)
            usage = session["usage"]
            self.assertNotIn("inputTokens", usage)
            self.assertNotIn("outputTokens", usage)
            self.assertNotIn("totalTokens", usage)

    def test_no_cache_hit_rate_codex(self) -> None:
        with TemporaryDirectory() as tmp:
            pd = Path(tmp)
            session_dir = pd / "2025" / "06" / "03"
            session_dir.mkdir(parents=True)
            sid = "339e9837-9271-7192-bfbf-f5b74ebe585c"
            fname = f"rollout-2025-06-03T10-00-00-{sid}.jsonl"
            with (session_dir / fname).open("w", encoding="utf-8") as f:
                f.write(json.dumps({
                    "type": "response_item",
                    "timestamp": "2025-06-01T10:00:01Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "hi"}],
                    },
                }) + "\n")
            adapter = CodexAdapter(pd)
            session = adapter.load_session(sid)
            self.assertNotIn("cacheHitRate", session["usage"])
