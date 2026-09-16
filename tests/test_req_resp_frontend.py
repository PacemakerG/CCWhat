"""Regression checks for req-resp viewer replay UI helpers."""

from __future__ import annotations

from pathlib import Path


HTML = (Path(__file__).resolve().parents[1] / "viewer" / "req-resp.html").read_text(
    encoding="utf-8"
)
SERVER = (Path(__file__).resolve().parents[1] / "viewer" / "server.py").read_text(
    encoding="utf-8"
)


def _function_snippet(name: str) -> str:
    start = HTML.index(f"function {name}")
    next_start = HTML.find("\nfunction ", start + len("function "))
    if next_start == -1:
        return HTML[start:]
    return HTML[start:next_start]


def test_replay_user_text_filters_leading_system_blocks() -> None:
    snippet = _function_snippet("extractReplayUserText")
    assert "stripLeadingSystemText(block.text)" in snippet
    assert "block?.type !== 'text'" in snippet
    assert "hasToolResultContent(msg)" in snippet
    assert "tool_result" not in snippet


def test_replay_target_uses_last_request_message() -> None:
    snippet = _function_snippet("findReplayTargetMessage")
    assert "messages[messages.length - 1]" in snippet
    assert "findReplayUserMessage" not in snippet


def test_tool_result_replay_uses_raw_target_text() -> None:
    snippet = _function_snippet("extractReplayTargetText")
    assert "msg.role === 'user' && !hasToolResultContent(msg)" in snippet
    assert "extractRawReplayText(msg)" in snippet


def test_replay_send_uses_filtered_original_text() -> None:
    snippet = _function_snippet("sendReplayFromModal")
    assert "findReplayTargetMessage(msgs)" in snippet
    assert "extractReplayTargetText(userMsg)" in snippet
    assert "content.find" not in snippet


def test_replay_diff_reconstructs_original_sse_response() -> None:
    snippet = _function_snippet("renderReplayDiffView")
    assert "parseSseEvents(currentModalRecord.sse_events)" in snippet
    assert "convertOriginalResponseToResult" in snippet
    assert "renderResponseMarkdownNoThinking(originalResult)" in snippet


def test_replay_send_does_not_rewrite_request_when_unedited() -> None:
    snippet = _function_snippet("sendReplayFromModal")
    assert "if (!useOriginal)" in snippet
    assert "path: record._edit_targets[idx].path" in snippet
