from __future__ import annotations

import json

from ccwhat.parsers.sse_parser import parse_response, parse_sse_events, parse_sse_record


def events(*values):
    return ["data: " + json.dumps(value, ensure_ascii=False) for value in values]


def test_anthropic_content_initial_values_deltas_tools_thinking_and_usage():
    parsed = parse_sse_events(events(
        {"type": "message_start", "message": {"id": "msg_a", "usage": {"input_tokens": 7}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": "考"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "虑"}},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": "你"}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "好"}},
        {"type": "content_block_start", "index": 2, "content_block": {"type": "tool_use", "id": "tool_1", "name": "run", "input": {}}},
        {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": '{"cmd":'}},
        {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": '"pwd"}'}},
        {"type": "content_block_start", "index": 3, "content_block": {"type": "tool_use", "name": "noop", "input": {"x": 1}}},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    ))
    assert parsed["id"] == "msg_a"
    assert parsed["usage"] == {"input_tokens": 7, "output_tokens": 5}
    assert parsed["content"][0]["thinking"] == "考虑"
    assert parsed["content"][1]["text"] == "你好"
    assert parsed["content"][2]["input"] == {"cmd": "pwd"}
    assert parsed["content"][3]["input"] == {"x": 1}


def test_chat_tools_reasoning_and_usage_chunks_without_choices():
    parsed = parse_sse_events(events(
        {"id": "chat_1", "choices": [{"index": 0, "delta": {"reasoning_content": "private reasoning"}}]},
        {"choices": [{"index": 0, "delta": {"content": "answer", "tool_calls": [
            {"index": 0, "id": "call_a", "function": {"name": "read", "arguments": '{"file":'}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '"a.py"}'}},
            {"index": 1, "id": "call_b", "function": {"name": "write", "arguments": '{}'}}]}, "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 30, "completion_tokens": 9}},
    ))
    assert parsed["content"][0] == {"type": "thinking", "thinking": "private reasoning"}
    assert parsed["content"][1] == {"type": "text", "text": "answer"}
    assert parsed["content"][2]["input"] == {"file": "a.py"}
    assert parsed["content"][3]["id"] == "call_b"
    assert parsed["usage"]["input_tokens"] == 30
    assert parsed["usage"]["output_tokens"] == 9


def test_responses_incremental_and_terminal_snapshot_do_not_duplicate():
    output = [
        {"type": "message", "content": [{"type": "output_text", "text": "hello"}]},
        {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "read", "arguments": '{"x":1}'},
    ]
    stream = events(
        {"type": "response.created", "response": {"id": "resp_1", "output": []}},
        {"type": "response.output_text.delta", "output_index": 0, "content_index": 0, "delta": "hello"},
        {"type": "response.output_item.added", "output_index": 1,
         "item": {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "read", "arguments": ""}},
        {"type": "response.function_call_arguments.delta", "output_index": 1, "delta": '{"x":1}'},
        {"type": "response.completed", "response": {"id": "resp_1", "status": "completed", "output": output}},
    )
    parsed = parse_sse_events(stream)
    assert parsed["content"][0]["text"] == "hello"
    assert len(parsed["content"]) == 2
    assert parsed["content"][1]["id"] == "call_1"
    assert parsed["content"][1]["input"] == {"x": 1}
    partial = parse_sse_events(stream[:-1])
    assert partial["content"] == parsed["content"]


def test_multiline_sse_crlf_comments_and_done():
    raw = ': heartbeat\r\nevent: message\r\ndata: {"choices":\r\ndata: [{"message":{},"delta":{"content":"中文"}}]}\r\n\r\ndata: [DONE]\r\n\r\n'
    parsed = parse_sse_events([raw])
    assert parsed["content"] == [{"type": "text", "text": "中文"}]


def test_record_keeps_generic_session_id_and_case_insensitive_legacy_alias():
    raw = {"timestamp": "now", "url": "https://any.example/infer", "method": "POST", "domain": "any.example",
           "session_id": "local-opencode", "request": {"body": "{}", "headers": {}},
           "sse_events": events({"type": "message_start", "message": {"id": "msg_1"}},
                                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": "not lost"}})}
    parsed = parse_sse_record(raw)
    assert parsed["session_id"] == "local-opencode"
    assert parsed["response_json"]["message"]["content"][0]["text"] == "not lost"
    raw.pop("session_id")
    raw["request"]["headers"] = {"x-claude-code-session-id": "legacy"}
    assert parse_sse_record(raw)["claude_session_id"] == "legacy"


def test_non_stream_responses_and_error_are_preserved():
    parsed = parse_response({"id": "r", "output": [{"type": "message", "content": [{"type": "output_text", "text": "yes"}]}]})
    assert parsed["content"] == [{"type": "text", "text": "yes"}]
    error = {"type": "response.failed", "response": {"error": {"message": "failed"}}}
    assert parse_sse_events(events(error))["error"]["message"] == "failed"
