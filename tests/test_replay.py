from __future__ import annotations

import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ccwhat.replay import apply_edits, edit_targets, recorded_body, replay_headers, send_replay
from viewer.server import ViewerBackend, get_req_resp_records


@pytest.fixture(autouse=True)
def clean_replay_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    for key in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_CUSTOM_HEADERS",
                "OPENAI_BASE_URL", "OPENAI_API_KEY", "CCWHAT_REPLAY_HEADERS", "HTTP_PROXY", "HTTPS_PROXY",
                "http_proxy", "https_proxy"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def upstream():
    captured = []
    replies = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            captured.append({"path": self.path, "headers": dict(self.headers),
                             "body": self.rfile.read(int(self.headers["Content-Length"]))})
            status, headers, body = replies.pop(0)
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", captured, replies
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def record(url, body, headers=None):
    return {"url": url, "method": "POST", "timestamp": "2026-09-16T00:00:00Z", "domain": "test",
            "request": {"headers": headers or {}, "body": json.dumps(body, ensure_ascii=False, indent=2)}}


@pytest.mark.parametrize("body", [
    {"model": "any", "messages": [{"role": "user", "content": "你好"}], "stream": True},
    {"model": "any", "input": "你好", "stream": False},
    {"model": "any", "input": [{"role": "user", "content": [{"type": "input_text", "text": "你好"}]}],
     "stream": True, "store": False, "previous_response_id": "resp_original"},
])
def test_replay_uses_original_endpoint_and_reserializes_body(upstream, monkeypatch, body):
    origin, captured, replies = upstream
    monkeypatch.setenv("CLAUDE_API_URL", "https://wrong.example/messages")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "wrong-provider-token")
    monkeypatch.setenv("CCWHAT_REPLAY_HEADERS", json.dumps({origin: {"Authorization": "Bearer fresh"}}))
    rec = record(origin + "/gateway/custom/infer?version=7", body,
                 {"authorization": "[REDACTED]", "host": "old.example", "content-length": "2",
                  "Content-Encoding": "gzip", "anthropic-version": "2023-06-01"})
    replies.append((200, {"Content-Type": "application/json"}, '{"content":[{"type":"text","text":"ok"}]}'))
    result, applied = send_replay(rec, [])
    assert result["content"][0]["text"] == "ok"
    assert applied == []
    sent = captured[0]
    assert sent["path"] == "/gateway/custom/infer?version=7"
    assert json.loads(sent["body"]) == body
    assert sent["body"] == json.dumps(body, ensure_ascii=False).encode("utf-8")
    assert sent["headers"]["Authorization"] == "Bearer fresh"
    assert "Content-Encoding" not in sent["headers"]
    assert sent["headers"]["Host"] != "old.example"


def test_replay_can_receive_stream_only_responses(upstream):
    origin, _, replies = upstream
    reply = {"type": "response.completed", "response": {"id": "resp_1", "status": "completed",
             "output": [{"type": "message", "content": [{"type": "output_text", "text": "答案"}]}]}}
    replies.append((200, {"Content-Type": "text/event-stream; charset=utf-8"},
                    "data: " + json.dumps(reply) + "\r\n\r\n"))
    result, _ = send_replay(record(origin + "/responses", {"input": "hello", "stream": True}), [])
    assert result["id"] == "resp_1"
    assert result["content"][0]["text"] == "答案"


def test_credentials_are_scoped_and_redacted_values_are_never_sent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    assert replay_headers("https://api.anthropic.com/v1/messages", {})["x-api-key"] == "anthropic-secret"
    assert replay_headers("https://api.openai.com/v1/responses", {})["authorization"] == "Bearer openai-secret"
    assert "authorization" not in replay_headers("https://other.example/v1/responses", {})
    assert "authorization" not in replay_headers(
        "https://other.example/v1/responses", {"Authorization": "[REDACTED]"})
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example/prefix/v1")
    assert replay_headers("https://gateway.example/prefix/v1/responses", {})["authorization"] == "Bearer openai-secret"
    assert "authorization" not in replay_headers("https://api.openai.com/v1/responses", {})


def test_arbitrary_gateway_auth_and_connection_headers(monkeypatch):
    monkeypatch.setenv("CCWHAT_REPLAY_HEADERS", json.dumps({"https://gateway.example": {"X-Custom-Token": "fresh"}}))
    headers = replay_headers("https://gateway.example/prefix", {
        "x-custom-token": "[REDACTED]", "Connection": "x-remove", "X-Remove": "hop", "TE": "trailers"})
    assert headers["x-custom-token"] == "fresh"
    assert "x-remove" not in headers and "te" not in headers
    assert "fresh" not in str(edit_targets({"input": "hello"}))


def test_redirect_is_not_followed_with_recorded_credentials(upstream):
    origin, captured, replies = upstream
    replies.append((307, {"Location": origin + "/other"}, "redirect"))
    with pytest.raises(Exception, match="307"):
        send_replay(record(origin + "/start", {"input": "hi"}, {"Authorization": "Bearer synthetic"}), [])
    assert len(captured) == 1


@pytest.mark.parametrize("body", [
    {"input": "original"},
    {"messages": [{"role": "user", "content": "original"}]},
    {"input": [{"type": "function_call_output", "call_id": "c", "output": "original"}]},
    {"messages": [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "original"}]}]},
])
def test_edits_change_only_selected_text(body):
    before = copy.deepcopy(body)
    target = edit_targets(body)[0]
    changed, edits = apply_edits(body, [{"path": target["path"], "editedText": "changed"}])
    assert edit_targets(changed)[0]["text"] == "changed"
    assert edits[0]["originalText"] == "original"
    assert body == before


def test_multimodal_and_tool_structures_survive_edit():
    body = {"input": [{"role": "user", "content": [
        {"type": "input_text", "text": "system prefix"},
        {"type": "input_image", "image_url": "data:image/png;base64,AAA"},
        {"type": "input_text", "text": "question"},
    ]}, {"type": "function_call", "call_id": "c", "name": "shell", "arguments": "{}"}]}
    before = copy.deepcopy(body)
    changed, _ = apply_edits(body, [{"path": ["input", 0, "content", 2, "text"], "editedText": "edited"}])
    before["input"][0]["content"][2]["text"] = "edited"
    assert changed == before
    for edit in ({"msgIndex": 0, "editedText": "bad"}, {"msgIndex": -1, "editedText": "bad"},
                 {"path": ["input", 1, "arguments"], "editedText": "bad"}):
        with pytest.raises(ValueError):
            apply_edits(body, [edit])


@pytest.mark.parametrize("mutation", [
    {"url": "file:///tmp/input"}, {"method": "DELETE"}, {"url": "https://user:secret@example.com"},
    {"request": {"body": "{}", "body_truncated": True}}, {"request": {"body": "[1]"}},
    {"request": {"body": '{"messages":'}},
])
def test_invalid_or_truncated_record_is_rejected(mutation):
    rec = record("https://api.example/infer", {"input": "hi"})
    rec.update(mutation)
    with pytest.raises(ValueError):
        recorded_body(rec)


def test_backend_uses_record_as_source_and_clears_previous_error(tmp_path, upstream):
    origin, captured, replies = upstream
    backend = ViewerBackend(tmp_path, tmp_path, tmp_path, tmp_path / "config.toml")
    rec = record(origin + "/infer", {"input": "recorded"})
    code, session = backend.create_replay_session_response({"record": rec, "reqJson": {"input": "wrong"}})
    assert code == 200
    sid = session["sessionId"]
    code, _ = backend.send_replay_response({"sessionId": sid, "edits": [{"msgIndex": 999, "editedText": "bad"}]})
    assert code == 400 and not backend.replay_store[sid]["isLoading"]
    replies.append((200, {"Content-Type": "application/json"}, '{"content":[]}'))
    code, _ = backend.send_replay_response({"sessionId": sid, "edits": []})
    assert code == 200
    assert backend.replay_store[sid]["error"] is None
    assert json.loads(captured[0]["body"])["input"] == "recorded"


def test_viewer_normalizes_non_stream_responses_and_scopes_record_keys(tmp_path):
    rec = record("https://any.example/chat/completions", {"messages": [{"role": "user", "content": "hi"}]})
    rec["response"] = {"body": json.dumps({"id": "chat_1", "choices": [{"message": {"content": "answer"}}]})}
    for session in ("one", "two"):
        directory = tmp_path / session
        directory.mkdir()
        (directory / "2026-09-16.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
    first = get_req_resp_records(tmp_path, "one", "2026-09-16")[0]
    second = get_req_resp_records(tmp_path, "two", "2026-09-16")[0]
    assert first["_record_key"] != second["_record_key"]
    assert first["_can_replay"]
    assert first["_edit_targets"][0]["text"] == "hi"
    assert first["_response"]["content"][0]["text"] == "answer"
    assert first["_message_id"] == "chat_1"
