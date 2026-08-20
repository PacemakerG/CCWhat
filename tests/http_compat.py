"""Legacy HTTPServer bridge for tests that exercise the public HTTP wire format."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from ccwhat.adapters.base import AgentAdapter
from viewer.server import create_app


def make_handler(
    projects_dir: Path,
    logs_dir: Path,
    config_path: Path | None = None,
    analyzer_cmd: str | None = None,
    analyzer_agent: str | None = None,
    analyzer_timeout: float | None = None,
    adapter: AgentAdapter | None = None,
    dataset_registry_root: Path | None = None,
    runtime_registry_root: Path | None = None,
) -> type[BaseHTTPRequestHandler]:
    app = create_app(
        projects_dir,
        logs_dir,
        config_path,
        analyzer_cmd=analyzer_cmd,
        analyzer_agent=analyzer_agent,
        analyzer_timeout=analyzer_timeout,
        adapter=adapter,
        dataset_registry_root=dataset_registry_root,
        runtime_registry_root=runtime_registry_root,
    )
    client = TestClient(app)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

        def _forward(self) -> None:
            if self.path.startswith("/api/task-datasets/") and self.path.endswith("/download") and ".." in self.path:
                body = json.dumps({"ok": False, "error": "invalid dataset id"}).encode()
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            response = client.request(
                self.command,
                self.path,
                content=self.rfile.read(length) if length else b"",
                headers=dict(self.headers.items()),
                follow_redirects=False,
            )
            self.send_response(response.status_code)
            skipped = {"connection", "content-encoding", "transfer-encoding", "content-length"}
            for key, value in response.headers.items():
                if key.lower() not in skipped:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)

        do_GET = _forward
        do_POST = _forward
        do_OPTIONS = _forward

    return Handler
