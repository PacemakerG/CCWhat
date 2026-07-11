"""Tests for ccwhat run command — proxy lifecycle, env injection, command passthrough."""

from __future__ import annotations

import os
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from ccwhat.cli import cli
from ccwhat.commands.run import run
from ccwhat.config import RecordingConfig, save_config


class FakeWinError10013(PermissionError):
    @property
    def winerror(self) -> int:
        return 10013


class RunCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self._port_bind_error_patcher = mock.patch("ccwhat.commands.run.port_bind_error", return_value=None)
        self._port_bind_error_patcher.start()

    def tearDown(self) -> None:
        self._port_bind_error_patcher.stop()

    def _make_config(self, tmp: Path) -> Path:
        config_path = tmp / "config.toml"
        cfg = RecordingConfig(preset="claude", onboarding_complete=True)
        save_config(cfg, config_path)
        return config_path

    def test_missing_target_command_fails(self) -> None:
        result = self.runner.invoke(run, [])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("ccwhat -- <command>", result.output)

    def test_run_injects_proxy_env_vars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = self._make_config(tmp_path)

            captured_env: dict = {}

            def fake_popen(args, env=None, **kwargs):
                captured_env.update(env or {})
                m = mock.MagicMock()
                m.wait.return_value = 0
                return m

            with mock.patch("ccwhat.commands.run._proxy_is_running", return_value=True), \
                 mock.patch("ccwhat.commands.run._start_managed_web", return_value=None), \
                 mock.patch("ccwhat.commands.run.subprocess.Popen", side_effect=fake_popen):
                result = self.runner.invoke(run, [
                    "--config", str(config_path),
                    "--output", tmp,
                    "--", "echo", "hello",
                ])

        self.assertIn("HTTPS_PROXY", captured_env)
        self.assertIn("HTTP_PROXY", captured_env)
        self.assertIn("NODE_EXTRA_CA_CERTS", captured_env)
        self.assertIn("127.0.0.1:7788", captured_env["HTTPS_PROXY"])

    def test_run_preserves_existing_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = self._make_config(tmp_path)
            captured_env: dict = {}

            def fake_popen(args, env=None, **kwargs):
                captured_env.update(env or {})
                m = mock.MagicMock()
                m.wait.return_value = 0
                return m

            with mock.patch("ccwhat.commands.run._proxy_is_running", return_value=True), \
                 mock.patch("ccwhat.commands.run._start_managed_web", return_value=None), \
                 mock.patch("ccwhat.commands.run.subprocess.Popen", side_effect=fake_popen), \
                 mock.patch.dict(os.environ, {"MY_CUSTOM_VAR": "hello"}):
                self.runner.invoke(run, [
                    "--config", str(config_path),
                    "--output", tmp,
                    "--", "echo",
                ])

        self.assertEqual(captured_env.get("MY_CUSTOM_VAR"), "hello")

    def test_run_no_proxy_reuse_when_already_running(self) -> None:
        """When proxy already running, run does not start another."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = self._make_config(tmp_path)

            started_proxies: list = []

            def fake_start_proxy(*args, **kwargs):
                started_proxies.append(True)
                m = mock.MagicMock()
                return m

            def fake_popen(args, env=None, **kwargs):
                m = mock.MagicMock()
                m.wait.return_value = 0
                return m

            with mock.patch("ccwhat.commands.run._proxy_is_running", return_value=True), \
                 mock.patch("ccwhat.commands.run._start_managed_proxy", side_effect=fake_start_proxy), \
                 mock.patch("ccwhat.commands.run._start_managed_web", return_value=None), \
                 mock.patch("ccwhat.commands.run.subprocess.Popen", side_effect=fake_popen):
                self.runner.invoke(run, [
                    "--config", str(config_path),
                    "--output", tmp,
                    "--", "echo",
                ])

        self.assertEqual(len(started_proxies), 0)

    def test_run_propagates_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = self._make_config(tmp_path)

            def fake_popen(args, env=None, **kwargs):
                m = mock.MagicMock()
                m.wait.return_value = 42
                return m

            with mock.patch("ccwhat.commands.run._proxy_is_running", return_value=True), \
                 mock.patch("ccwhat.commands.run._start_managed_web", return_value=None), \
                 mock.patch("ccwhat.commands.run.subprocess.Popen", side_effect=fake_popen):
                result = self.runner.invoke(run, [
                    "--config", str(config_path),
                    "--output", tmp,
                    "--", "fake-cmd",
                ])

        self.assertEqual(result.exit_code, 42)

    def test_no_setup_flag_skips_payload_recording(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            captured_env: dict = {}

            def fake_popen(args, env=None, **kwargs):
                if "mitmdump" not in str(args):
                    captured_env.update(env or {})
                m = mock.MagicMock()
                m.wait.return_value = 0
                return m

            with mock.patch("ccwhat.commands.run._proxy_is_running", return_value=False), \
                 mock.patch("ccwhat.commands.run._start_managed_proxy") as mock_start, \
                 mock.patch("ccwhat.commands.run._start_managed_web", return_value=None), \
                 mock.patch("ccwhat.commands.run.subprocess.Popen", side_effect=fake_popen):
                mock_start.return_value = mock.MagicMock()
                result = self.runner.invoke(run, [
                    "--no-setup", "--output", tmp, "--", "echo",
                ])

        self.assertIn("payload recording disabled", result.output.lower() + result.output)

    def test_run_auto_detects_domains_when_config_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            started: dict[str, list[str]] = {}

            def fake_start_proxy(port, output, domains, paths, *args):
                started["domains"] = domains
                started["paths"] = paths
                return mock.MagicMock()

            def fake_popen(args, env=None, **kwargs):
                m = mock.MagicMock()
                m.wait.return_value = 0
                return m

            with mock.patch("ccwhat.commands.run.load_config", return_value=None), \
                 mock.patch("ccwhat.commands.run._proxy_is_running", return_value=False), \
                 mock.patch("ccwhat.commands.run._start_managed_proxy", side_effect=fake_start_proxy), \
                 mock.patch("ccwhat.commands.run._start_managed_web", return_value=None), \
                 mock.patch("ccwhat.commands.run.subprocess.Popen", side_effect=fake_popen), \
                 mock.patch("ccwhat.agent_config.detect_domains", return_value=["gw.example.com"]) as detect_domains, \
                 mock.patch("ccwhat.agent_config.detect_default_paths", return_value=["/v1/messages"]):
                result = self.runner.invoke(run, [
                    "--output", tmp, "--", "opencode",
                ])

        self.assertEqual(result.exit_code, 0)
        detect_domains.assert_called_once_with("opencode")
        self.assertEqual(started["domains"], ["gw.example.com"])
        self.assertEqual(started["paths"], ["/v1/messages"])
        self.assertIn("Auto-detected domains", result.output)

    def test_run_auto_detects_when_config_has_preset_but_no_domains(self) -> None:
        cfg = RecordingConfig(preset="claude", onboarding_complete=True)
        with tempfile.TemporaryDirectory() as tmp:
            started: dict[str, list[str]] = {}

            def fake_start_proxy(port, output, domains, paths, *args):
                started["domains"] = domains
                started["paths"] = paths
                return mock.MagicMock()

            def fake_popen(args, env=None, **kwargs):
                m = mock.MagicMock()
                m.wait.return_value = 0
                return m

            with mock.patch("ccwhat.commands.run.load_config", return_value=cfg), \
                 mock.patch("ccwhat.commands.run._proxy_is_running", return_value=False), \
                 mock.patch("ccwhat.commands.run._start_managed_proxy", side_effect=fake_start_proxy), \
                 mock.patch("ccwhat.commands.run._start_managed_web", return_value=None), \
                 mock.patch("ccwhat.commands.run.subprocess.Popen", side_effect=fake_popen), \
                 mock.patch("ccwhat.agent_config.detect_domains", return_value=["mcli.sankuai.com"]) as detect_domains, \
                 mock.patch("ccwhat.agent_config.detect_default_paths", return_value=["/v1/messages"]):
                result = self.runner.invoke(run, [
                    "--output", tmp, "--", "claude",
                ])

        self.assertEqual(result.exit_code, 0)
        detect_domains.assert_called_once_with("claude")
        self.assertEqual(started["domains"], ["api.anthropic.com", "mcli.sankuai.com"])

    def test_run_merges_manual_domains_with_auto_detection(self) -> None:
        cfg = RecordingConfig(domains=["manual.example.com"], onboarding_complete=True)
        with tempfile.TemporaryDirectory() as tmp:
            started: dict[str, list[str]] = {}

            def fake_start_proxy(port, output, domains, paths, *args):
                started["domains"] = domains
                started["paths"] = paths
                return mock.MagicMock()

            def fake_popen(args, env=None, **kwargs):
                m = mock.MagicMock()
                m.wait.return_value = 0
                return m

            with mock.patch("ccwhat.commands.run.load_config", return_value=cfg), \
                 mock.patch("ccwhat.commands.run._proxy_is_running", return_value=False), \
                 mock.patch("ccwhat.commands.run._start_managed_proxy", side_effect=fake_start_proxy), \
                 mock.patch("ccwhat.commands.run._start_managed_web", return_value=None), \
                 mock.patch("ccwhat.commands.run.subprocess.Popen", side_effect=fake_popen), \
                 mock.patch("ccwhat.agent_config.detect_domains", return_value=["gw.example.com"]) as detect_domains, \
                 mock.patch("ccwhat.agent_config.detect_default_paths", return_value=["/v1/messages"]):
                result = self.runner.invoke(run, [
                    "--output", tmp, "--", "opencode",
                ])

        self.assertEqual(result.exit_code, 0)
        detect_domains.assert_called_once_with("opencode")
        self.assertEqual(started["domains"], ["manual.example.com", "gw.example.com"])

    def test_run_merges_config_paths_with_auto_detected_default_paths(self) -> None:
        cfg = RecordingConfig(paths=["/custom"], onboarding_complete=True)
        with tempfile.TemporaryDirectory() as tmp:
            started: dict[str, list[str]] = {}

            def fake_start_proxy(port, output, domains, paths, *args):
                started["domains"] = domains
                started["paths"] = paths
                return mock.MagicMock()

            def fake_popen(args, env=None, **kwargs):
                m = mock.MagicMock()
                m.wait.return_value = 0
                return m

            with mock.patch("ccwhat.commands.run.load_config", return_value=cfg), \
                 mock.patch("ccwhat.commands.run._proxy_is_running", return_value=False), \
                 mock.patch("ccwhat.commands.run._start_managed_proxy", side_effect=fake_start_proxy), \
                 mock.patch("ccwhat.commands.run._start_managed_web", return_value=None), \
                 mock.patch("ccwhat.commands.run.subprocess.Popen", side_effect=fake_popen), \
                 mock.patch("ccwhat.agent_config.detect_domains", return_value=["gw.example.com"]), \
                 mock.patch("ccwhat.agent_config.detect_default_paths", return_value=["/v1/messages"]) as default_paths:
                result = self.runner.invoke(run, [
                    "--output", tmp, "--", "opencode",
                ])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(started["domains"], ["gw.example.com"])
        self.assertEqual(started["paths"], ["/custom", "/v1/messages"])
        default_paths.assert_called_once_with("opencode")

    def test_run_starts_transparent_proxy_when_auto_detection_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            started: dict[str, list[str]] = {}

            def fake_start_proxy(port, output, domains, paths, *args):
                started["domains"] = domains
                started["paths"] = paths
                return mock.MagicMock()

            def fake_popen(args, env=None, **kwargs):
                m = mock.MagicMock()
                m.wait.return_value = 0
                return m

            with mock.patch("ccwhat.commands.run.load_config", return_value=None), \
                 mock.patch("ccwhat.commands.run._proxy_is_running", return_value=False), \
                 mock.patch("ccwhat.commands.run._start_managed_proxy", side_effect=fake_start_proxy), \
                 mock.patch("ccwhat.commands.run._start_managed_web", return_value=None), \
                 mock.patch("ccwhat.commands.run.subprocess.Popen", side_effect=fake_popen), \
                 mock.patch("ccwhat.agent_config.detect_domains", return_value=[]):
                result = self.runner.invoke(run, [
                    "--output", tmp, "--", "unknown-agent",
                ])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(started["domains"], [])
        self.assertEqual(started["paths"], [])
        self.assertIn("starting proxy without payload recording", result.output)

    def test_top_level_passthrough_invokes_run_with_claude(self) -> None:
        captured_args: list[str] = []

        def fake_popen(args, env=None, **kwargs):
            captured_args.extend(args)
            m = mock.MagicMock()
            m.wait.return_value = 0
            return m

        cfg = RecordingConfig(preset="claude", onboarding_complete=True)
        fake_run = mock.Mock(run_id="run-test", control={"token": "token"})
        fake_registry = mock.Mock()
        fake_registry.create_run.return_value = fake_run
        with mock.patch("ccwhat.commands.run.load_config", return_value=cfg), \
             mock.patch("ccwhat.commands.run.RunRegistry", return_value=fake_registry), \
             mock.patch("ccwhat.commands.run.RuntimeController"), \
             mock.patch("ccwhat.commands.run.install_claude_integration"), \
             mock.patch("ccwhat.commands.run._proxy_is_running", return_value=True), \
             mock.patch("ccwhat.commands.run._start_managed_web", return_value=None), \
             mock.patch("ccwhat.commands.run.subprocess.Popen", side_effect=fake_popen):
            result = self.runner.invoke(cli, ["--", "claude"])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(captured_args, ["claude"])

    def test_top_level_passthrough_preserves_arbitrary_cli_args(self) -> None:
        captured_args: list[str] = []

        def fake_popen(args, env=None, **kwargs):
            captured_args.extend(args)
            m = mock.MagicMock()
            m.wait.return_value = 0
            return m

        cfg = RecordingConfig(preset="claude", onboarding_complete=True)
        with mock.patch("ccwhat.commands.run.load_config", return_value=cfg), \
             mock.patch("ccwhat.commands.run._proxy_is_running", return_value=True), \
             mock.patch("ccwhat.commands.run._start_managed_web", return_value=None), \
             mock.patch("ccwhat.commands.run.subprocess.Popen", side_effect=fake_popen):
            result = self.runner.invoke(cli, ["--", "mc", "--code"])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(captured_args, ["mc", "--code"])

    def test_top_level_no_web_option_reaches_run(self) -> None:
        cfg = RecordingConfig(preset="claude", onboarding_complete=True)

        def fake_popen(args, env=None, **kwargs):
            m = mock.MagicMock()
            m.wait.return_value = 0
            return m

        fake_run = mock.Mock(run_id="run-test", control={"token": "token"})
        fake_registry = mock.Mock()
        fake_registry.create_run.return_value = fake_run
        with mock.patch("ccwhat.commands.run.load_config", return_value=cfg), \
             mock.patch("ccwhat.commands.run.RunRegistry", return_value=fake_registry), \
             mock.patch("ccwhat.commands.run.RuntimeController"), \
             mock.patch("ccwhat.commands.run.install_claude_integration"), \
             mock.patch("ccwhat.commands.run._proxy_is_running", return_value=True), \
             mock.patch("ccwhat.commands.run._start_managed_web") as start_web, \
             mock.patch("ccwhat.commands.run.subprocess.Popen", side_effect=fake_popen):
            result = self.runner.invoke(cli, ["--no-web", "--", "claude"])

        self.assertEqual(result.exit_code, 0)
        start_web.assert_not_called()


class ProxyMarkerTests(unittest.TestCase):
    """Tests for proxy marker-based compatibility detection (task 11.6)."""

    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_occupied_non_ccwhat_port_is_refused(self) -> None:
        """Port occupied without a ccwhat marker → run exits non-zero."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "config.toml"
            from ccwhat.config import RecordingConfig, save_config
            save_config(RecordingConfig(preset="claude", onboarding_complete=True), config_path)
            marker = tmp_path / "marker.pid"

            # Port appears occupied but no marker exists
            with mock.patch("ccwhat.commands.run._proxy_port_in_use", return_value=True), \
                 mock.patch("ccwhat.commands.run._marker_path", return_value=marker):
                result = self.runner.invoke(run, [
                    "--config", str(config_path), "--output", tmp, "--", "echo",
                ])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("another process", result.output)

    def test_stale_marker_is_cleaned_up(self) -> None:
        """Stale marker (dead PID) is removed and new proxy is started."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "config.toml"
            from ccwhat.config import RecordingConfig, save_config
            save_config(RecordingConfig(preset="claude", onboarding_complete=True), config_path)
            marker = tmp_path / "ccwhat-proxy-7788.pid"
            marker.write_text("999999")  # non-existent PID

            proxy_started = []

            def fake_start(*args, **kwargs):
                proxy_started.append(True)
                m = mock.MagicMock()
                return m

            def fake_popen(args, env=None, **kwargs):
                m = mock.MagicMock()
                m.wait.return_value = 0
                return m

            # Port is occupied, but marker has stale PID → should start new proxy
            with mock.patch("ccwhat.commands.run._proxy_port_in_use", return_value=True), \
                 mock.patch("ccwhat.commands.run._marker_path", return_value=marker), \
                 mock.patch("ccwhat.commands.run._start_managed_proxy", side_effect=fake_start), \
                 mock.patch("ccwhat.commands.run._start_managed_web", return_value=None), \
                 mock.patch("ccwhat.commands.run.subprocess.Popen", side_effect=fake_popen):
                self.runner.invoke(run, [
                    "--config", str(config_path), "--output", tmp, "--", "echo",
                ])

        # Stale marker should have been removed
        self.assertFalse(marker.exists())

    def test_failed_proxy_startup_cleans_marker(self) -> None:
        """If managed proxy fails to bind, marker is removed and run exits non-zero."""
        from ccwhat.commands.run import _start_managed_proxy, _marker_path
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            marker = tmp_path / "marker.pid"

            # Simulate: Popen succeeds, process immediately exits (poll() → 1),
            # port never binds
            fake_proc = mock.MagicMock()
            fake_proc.poll.return_value = 1  # exited
            fake_proc.pid = 12345

            with mock.patch("ccwhat.commands.run.subprocess.Popen", return_value=fake_proc), \
                 mock.patch("ccwhat.commands.run._proxy_port_in_use", return_value=False), \
                 mock.patch("ccwhat.commands.run.port_bind_error", return_value=None), \
                 mock.patch("ccwhat.commands.run._marker_path", return_value=marker):
                result = _start_managed_proxy(
                    7788, tmp_path, ["api.anthropic.com"], ["/v1/messages"],
                    512 * 1024, ["authorization"], ["token"], "local-test",
                )

        self.assertIsNone(result)
        self.assertFalse(marker.exists())

    def test_run_reports_unbindable_windows_port_before_starting_proxy(self) -> None:
        """A Windows excluded port should fail before launching the managed proxy."""
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            save_config(RecordingConfig(preset="claude", onboarding_complete=True), config_path)
            err = FakeWinError10013(13, "bind denied")
            with mock.patch("ccwhat.commands.run._proxy_is_running", return_value=False), \
                 mock.patch("ccwhat.commands.run.port_bind_error", return_value=err), \
                 mock.patch("ccwhat.commands.run._start_managed_proxy") as start_proxy:
                result = self.runner.invoke(run, [
                    "--no-web", "--config", str(config_path), "--output", tmp, "--", "echo",
                ])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("port 7788 cannot be bound", result.output)
        self.assertIn("WinError 10013", result.output)
        self.assertIn("TCP excluded port range", result.output)
        self.assertIn("netsh interface ipv4 show excludedportrange protocol=tcp", result.output)
        self.assertIn("ccwhat --port <other-port> -- <cli>", result.output)
        start_proxy.assert_not_called()

    def test_proxy_command_reports_unbindable_windows_port(self) -> None:
        from ccwhat.commands.proxy import proxy

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("ccwhat.commands.proxy.port_bind_error", return_value=FakeWinError10013(13, "bind denied")), \
             mock.patch("ccwhat.commands.proxy.subprocess.run") as run_proc:
            result = self.runner.invoke(proxy, [
                "--preset", "codex", "--output", tmp,
            ])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("port 7788 cannot be bound", result.output)
        self.assertIn("ccwhat proxy --port <other-port>", result.output)
        run_proc.assert_not_called()

    def test_discover_reports_unbindable_windows_port(self) -> None:
        from ccwhat.commands.discover import _start_discovery_proxy

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("ccwhat.commands.discover.port_bind_error", return_value=FakeWinError10013(13, "bind denied")), \
             mock.patch("ccwhat.commands.discover.subprocess.Popen") as popen, \
             mock.patch("ccwhat.commands.discover.click.echo") as echo:
            result = _start_discovery_proxy(7788, Path(tmp) / "out.jsonl")

        self.assertIsNone(result)
        message = echo.call_args.args[0]
        self.assertIn("port 7788 cannot be bound", message)
        self.assertIn("ccwhat discover --port <other-port>", message)
        popen.assert_not_called()

    def test_live_ccwhat_marker_enables_reuse(self) -> None:
        """Port occupied + valid marker with live PID → proxy_is_running returns True."""
        import os as _os
        from ccwhat.commands.run import _proxy_is_running
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "marker.pid"
            own_pid = _os.getpid()  # current process = definitely alive
            marker.write_text(str(own_pid))

            with mock.patch("ccwhat.commands.run._proxy_port_in_use", return_value=True), \
                 mock.patch("ccwhat.commands.run._marker_path", return_value=marker):
                result = _proxy_is_running(7788)

        self.assertTrue(result)


class ViewerRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def _make_config(self, tmp: Path) -> Path:
        config_path = tmp / "config.toml"
        save_config(RecordingConfig(preset="claude", onboarding_complete=True), config_path)
        return config_path

    def test_run_starts_and_stops_managed_viewer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._make_config(Path(tmp))
            fake_server = mock.MagicMock()

            def fake_popen(args, env=None, **kwargs):
                m = mock.MagicMock()
                m.wait.return_value = 0
                return m

            with mock.patch("ccwhat.commands.run._proxy_is_running", return_value=True), \
                 mock.patch("ccwhat.commands.run._start_managed_web", return_value=fake_server) as start_web, \
                 mock.patch("ccwhat.commands.run.subprocess.Popen", side_effect=fake_popen):
                result = self.runner.invoke(run, [
                    "--config", str(config_path), "--output", tmp, "--", "echo",
                ])

        self.assertEqual(result.exit_code, 0)
        start_web.assert_called_once()
        fake_server.shutdown.assert_called_once()
        fake_server.server_close.assert_called_once()

    def test_run_no_web_skips_viewer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._make_config(Path(tmp))

            def fake_popen(args, env=None, **kwargs):
                m = mock.MagicMock()
                m.wait.return_value = 0
                return m

            with mock.patch("ccwhat.commands.run._proxy_is_running", return_value=True), \
                 mock.patch("ccwhat.commands.run._start_managed_web") as start_web, \
                 mock.patch("ccwhat.commands.run.subprocess.Popen", side_effect=fake_popen):
                result = self.runner.invoke(run, [
                    "--no-web", "--config", str(config_path), "--output", tmp, "--", "echo",
                ])

        self.assertEqual(result.exit_code, 0)
        start_web.assert_not_called()

    def test_start_managed_web_reuses_occupied_port(self) -> None:
        from ccwhat.commands.run import _start_managed_web
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("ccwhat.commands.run._proxy_port_in_use", return_value=True), \
             mock.patch("ccwhat.commands.run._probe_viewer_agent", return_value="opencode"), \
             mock.patch("viewer.server.open_viewer") as open_viewer:
            server = _start_managed_web(7789, Path(tmp), None, ("mc", "--code"), agent_name="opencode")

        self.assertIsNone(server)
        open_viewer.assert_called_once_with(7789)

    def test_start_managed_web_refuses_mismatched_existing_viewer(self) -> None:
        from ccwhat.commands.run import _start_managed_web
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("ccwhat.commands.run._proxy_port_in_use", return_value=True), \
             mock.patch("ccwhat.commands.run._probe_viewer_agent", return_value="claude"), \
             mock.patch("viewer.server.open_viewer") as open_viewer:
            server = _start_managed_web(7789, Path(tmp), None, agent_name="opencode")

        self.assertIsNone(server)
        open_viewer.assert_not_called()

    def test_start_managed_web_reports_unbindable_windows_port(self) -> None:
        from ccwhat.commands.run import _start_managed_web
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("ccwhat.commands.run._proxy_port_in_use", return_value=False), \
             mock.patch("ccwhat.commands.run.port_bind_error", return_value=FakeWinError10013(13, "bind denied")), \
             mock.patch("viewer.server.create_server") as create_server, \
             mock.patch("ccwhat.commands.run.click.echo") as echo:
            result = _start_managed_web(7789, Path(tmp), None, agent_name="codex")

        self.assertIsNone(result)
        message = echo.call_args.args[0]
        self.assertIn("port 7789 cannot be bound", message)
        self.assertIn("ccwhat --web-port <other-port> -- <cli>", message)
        create_server.assert_not_called()

    def test_probe_viewer_agent_falls_back_to_projects(self) -> None:
        from ccwhat.commands.run import _probe_viewer_agent

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(self.payload).encode("utf-8")

        calls: list[str] = []

        def fake_urlopen(url, timeout=0.5):
            calls.append(url)
            if url.endswith("/api/viewer/status"):
                raise OSError("not found")
            return FakeResponse([{"projectDir": "/tmp/p", "agent": "opencode", "sessions": []}])

        with mock.patch("ccwhat.commands.run.urllib.request.urlopen", side_effect=fake_urlopen):
            self.assertEqual(_probe_viewer_agent(7789), "opencode")

        self.assertEqual(len(calls), 2)

    def test_web_command_opens_existing_viewer_when_port_busy(self) -> None:
        from ccwhat.commands.web_server import web_server
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("ccwhat.commands.web_server._port_in_use", return_value=True), \
             mock.patch("ccwhat.commands.web_server.webbrowser.open") as open_browser:
            result = self.runner.invoke(web_server, [
                "--projects-dir", tmp,
                "--req-resp-dir", tmp,
            ])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Viewer may already be running", result.output)
        open_browser.assert_called_once()


if __name__ == "__main__":
    unittest.main()
