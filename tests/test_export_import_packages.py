from __future__ import annotations

import importlib
import io
import json
import tarfile
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import quote

from click.testing import CliRunner

from ccwhat.commands.import_ import import_ as import_command
from ccwhat.exporter import build_tar_gz_bytes, default_filename
from tests.http_compat import make_handler as _make_handler
from viewer.server import get_session


SID_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
SID_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _write_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _make_source_data(base: Path) -> tuple[Path, Path, dict[str, list[str]]]:
    projects_dir = base / "projects"
    req_resp_dir = base / "raw"

    _write_jsonl(projects_dir / "project-a" / f"{SID_A}.jsonl", {"timestamp": "2026-05-29T01:00:00Z"})
    _write_jsonl(
        projects_dir / "project-a" / SID_A / "subagents" / "agent-one.jsonl",
        {"timestamp": "2026-05-29T01:01:00Z"},
    )
    _write_jsonl(req_resp_dir / SID_A / "2026-05-29.jsonl", {"url": "https://example.test/a"})

    _write_jsonl(projects_dir / "project-b" / f"{SID_B}.jsonl", {"timestamp": "2026-05-29T02:00:00Z"})

    return projects_dir, req_resp_dir, {SID_A: ["2026-05-29"], SID_B: []}


def _build_package(base: Path) -> bytes:
    projects_dir, req_resp_dir, req_resp_dates = _make_source_data(base)
    data, _ = build_tar_gz_bytes(
        [SID_A, SID_B],
        projects_dir,
        req_resp_dir,
        req_resp_dates,
        get_session,
    )
    return data


class ExportPackageTests(unittest.TestCase):
    def test_multi_session_archive_structure_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = _build_package(Path(tmp))

        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            names = set(tar.getnames())
            manifest = json.load(tar.extractfile("ccwhat-export/manifest.json"))  # type: ignore[arg-type]
            readme = tar.extractfile("ccwhat-export/README.md").read().decode()  # type: ignore[union-attr]
            view_command = tar.getmember("ccwhat-export/view.command")

        self.assertEqual(manifest["exportVersion"], "2.0")
        self.assertEqual(manifest["toolName"], "ccwhat")
        self.assertEqual(manifest["sessionCount"], 2)
        self.assertEqual([s["sessionId"] for s in manifest["sessions"]], [SID_A, SID_B])
        self.assertTrue(manifest["sessions"][0]["included"]["reqResp"])
        self.assertEqual(manifest["sessions"][0]["counts"]["reqRespFiles"], 1)
        self.assertFalse(manifest["sessions"][1]["included"]["reqResp"])
        self.assertEqual(manifest["sessions"][1]["counts"]["reqRespFiles"], 0)

        self.assertIn(f"ccwhat-export/sessions/{SID_A}/claude-logs/main-session.jsonl", names)
        self.assertIn(f"ccwhat-export/sessions/{SID_A}/claude-logs/subagents/agent-one.jsonl", names)
        self.assertIn(f"ccwhat-export/sessions/{SID_A}/req-resp/2026-05-29.jsonl", names)
        self.assertIn(f"ccwhat-export/sessions/{SID_B}/metadata/session.json", names)
        self.assertNotIn("ccwhat-export/claude-logs/main-session.jsonl", names)
        self.assertIn("ccwhat import", readme)
        self.assertIn("pip install ccwhat", readme)
        self.assertTrue(view_command.mode & 0o111)

    def test_view_command_uses_ccwhat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = _build_package(Path(tmp))
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            view_cmd = tar.extractfile("ccwhat-export/view.command")
            assert view_cmd is not None
            content = view_cmd.read().decode()
        self.assertIn("ccwhat import", content)
        self.assertNotIn("deep-ai-analysis", content)

    def test_default_filename_uses_short_id_or_session_count(self) -> None:
        single = default_filename(SID_A, 1)
        multi = default_filename(None, 2)

        self.assertRegex(single, r"^export-\d{8}-\d{6}-aaaaaaaa\.tar\.gz$")
        self.assertRegex(multi, r"^export-\d{8}-\d{6}-2-sessions\.tar\.gz$")


class WebExportTests(unittest.TestCase):
    def test_export_api_returns_multi_session_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            projects_dir, req_resp_dir, _ = _make_source_data(tmp / "source")
            server = HTTPServer(("127.0.0.1", 0), _make_handler(projects_dir, req_resp_dir))
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                conn = HTTPConnection("127.0.0.1", server.server_port)
                sessions = quote(f"{SID_A},{SID_B}")
                conn.request("GET", f"/api/export?sessions={sessions}")
                response = conn.getresponse()
                body = response.read()
                self.assertEqual(response.status, 200, body.decode(errors="ignore"))
                self.assertIn("2-sessions.tar.gz", response.getheader("Content-Disposition", ""))
                conn.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as tar:
            manifest = json.load(tar.extractfile("ccwhat-export/manifest.json"))  # type: ignore[arg-type]
        self.assertEqual(manifest["exportVersion"], "2.0")
        self.assertEqual(manifest["toolName"], "ccwhat")
        self.assertEqual(manifest["sessionCount"], 2)

    def test_export_modal_uses_multi_select_controls(self) -> None:
        html = (Path(__file__).resolve().parents[1] / "viewer" / "claude-log.html").read_text(encoding="utf-8")

        self.assertIn('id="exportSessionList"', html)
        self.assertIn('id="exportSelectAllBtn"', html)
        self.assertIn("selectedExportSessionIds()", html)
        self.assertIn("sessionIds.join(',')", html)
        self.assertIn("-sessions.tar.gz", html)
        self.assertNotIn('id="exportSessionSel"', html)

    def test_recording_status_api_returns_no_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            projects_dir, req_resp_dir, _ = _make_source_data(tmp / "source")
            server = HTTPServer(("127.0.0.1", 0), _make_handler(projects_dir, req_resp_dir))
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                conn = HTTPConnection("127.0.0.1", server.server_port)
                conn.request("GET", "/api/recording/status")
                response = conn.getresponse()
                body_bytes = response.read()
                conn.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(response.status, 200)
        data = json.loads(body_bytes)
        # Must have these fields
        self.assertIn("configValid", data)
        self.assertIn("domains", data)
        self.assertIn("paths", data)
        self.assertIn("rawLogDir", data)
        # Must NOT contain secrets
        body_str = body_bytes.decode()
        self.assertNotIn("authorization", body_str.lower().replace("redact", ""))
        self.assertNotIn("api-key", body_str.lower().replace("redact", "").replace("redact_headers", ""))


class ImportPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.import_module = importlib.import_module("ccwhat.commands.import_")

    def _patched_import_dirs(self, tmp: Path):
        imports_dir = tmp / "imports"
        raw_dir = imports_dir / "raw-req-resp"
        return (
            mock.patch.object(self.import_module, "_IMPORTS_DIR", imports_dir),
            mock.patch.object(self.import_module, "_RAW_IMPORTS_DIR", raw_dir),
            imports_dir,
            raw_dir,
        )

    def test_import_multi_session_package_and_prompt_once_for_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            package_path = tmp / "package.tar.gz"
            package_path.write_bytes(_build_package(tmp / "source"))
            patch_imports, patch_raw, imports_dir, raw_dir = self._patched_import_dirs(tmp)

            with patch_imports, patch_raw:
                old_log = imports_dir / "project-a" / f"{SID_A}.jsonl"
                _write_jsonl(old_log, {"old": True})

                cancelled = self.runner.invoke(import_command, [str(package_path)], input="n\n")
                self.assertEqual(cancelled.exit_code, 0, cancelled.output)
                self.assertIn("Package contains 2 session(s); 1 existing import(s) will be overwritten.", cancelled.output)
                self.assertIn("Import cancelled.", cancelled.output)
                self.assertIn('"old": true', old_log.read_text(encoding="utf-8"))
                self.assertFalse((imports_dir / "project-b" / f"{SID_B}.jsonl").exists())

                confirmed = self.runner.invoke(import_command, [str(package_path)], input="y\n")
                self.assertEqual(confirmed.exit_code, 0, confirmed.output)
                self.assertIn("Imported 2 session(s).", confirmed.output)
                self.assertTrue((imports_dir / "project-a" / f"{SID_A}.jsonl").exists())
                self.assertTrue((imports_dir / "project-b" / f"{SID_B}.jsonl").exists())
                self.assertTrue((imports_dir / "project-a" / SID_A / "subagents" / "agent-one.jsonl").exists())
                self.assertTrue((raw_dir / SID_A / "2026-05-29.jsonl").exists())

    def test_force_overwrites_existing_without_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            package_path = tmp / "package.tar.gz"
            package_path.write_bytes(_build_package(tmp / "source"))
            patch_imports, patch_raw, imports_dir, _ = self._patched_import_dirs(tmp)

            with patch_imports, patch_raw:
                old_log = imports_dir / "project-a" / f"{SID_A}.jsonl"
                _write_jsonl(old_log, {"old": True})
                result = self.runner.invoke(import_command, [str(package_path), "--force"])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertNotIn("Overwrite existing imported data?", result.output)
            self.assertNotIn('"old": true', old_log.read_text(encoding="utf-8"))

    def test_import_legacy_single_session_package(self) -> None:
        """Import should accept old deep-ai-analysis-export/ root for compatibility."""
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            package_dir = tmp / "deep-ai-analysis-export"
            package_dir.mkdir()
            (package_dir / "manifest.json").write_text(
                json.dumps({
                    "exportVersion": "1.0",
                    "sessionId": SID_A,
                    "projectDir": "legacy-project",
                }),
                encoding="utf-8",
            )
            _write_jsonl(package_dir / "claude-logs" / "main-session.jsonl", {"legacy": True})
            _write_jsonl(package_dir / "req-resp" / "2026-05-29.jsonl", {"legacyRaw": True})

            patch_imports, patch_raw, imports_dir, raw_dir = self._patched_import_dirs(tmp)
            with patch_imports, patch_raw:
                result = self.runner.invoke(import_command, [str(package_dir)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Imported 1 session(s).", result.output)
            self.assertTrue((imports_dir / "legacy-project" / f"{SID_A}.jsonl").exists())
            self.assertTrue((raw_dir / SID_A / "2026-05-29.jsonl").exists())

    def test_import_new_ccwhat_export_package(self) -> None:
        """Import should accept new ccwhat-export/ root."""
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            gz_package = tmp / "package.tar.gz"
            gz_package.write_bytes(_build_package(tmp / "source"))

            patch_imports, patch_raw, imports_dir, raw_dir = self._patched_import_dirs(tmp)
            with patch_imports, patch_raw:
                result = self.runner.invoke(import_command, [str(gz_package), "--force"])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Imported 2 session(s).", result.output)
            self.assertTrue((imports_dir / "project-a" / f"{SID_A}.jsonl").exists())

    def test_import_plain_tar_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            gz_package = tmp / "package.tar.gz"
            gz_package.write_bytes(_build_package(tmp / "source"))
            extracted = tmp / "extracted"
            extracted.mkdir()
            with tarfile.open(gz_package, "r:gz") as tar:
                tar.extractall(extracted)

            tar_path = tmp / "package.tar"
            with tarfile.open(tar_path, "w") as tar:
                tar.add(extracted / "ccwhat-export", arcname="ccwhat-export")

            patch_imports, patch_raw, imports_dir, _ = self._patched_import_dirs(tmp)
            with patch_imports, patch_raw:
                result = self.runner.invoke(import_command, [str(tar_path), "--force"])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertTrue((imports_dir / "project-a" / f"{SID_A}.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
