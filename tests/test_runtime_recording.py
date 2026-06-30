from __future__ import annotations

import json
import io
import os
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from ccwhat.cli import cli
from ccwhat.config import RecordingConfig
from ccwhat.runtime.integrations.claude import (
    ClaudeIntegrationConflict,
    install_claude_integration,
)
from ccwhat.runtime.integrations.codex import (
    CodexIntegrationConflict,
    _hook_command as codex_hook_command,
    install_codex_integration,
)
from ccwhat.runtime.integrations.opencode import (
    OpenCodeIntegrationConflict,
    install_opencode_integration,
)
from ccwhat.runtime.integrations.claude import _hook_content as claude_hook_content
from ccwhat.runtime.http.client import call_controller
from ccwhat.runtime.http.controller import RuntimeController
from ccwhat.runtime.hooks.claude import main as claude_hook_main
from ccwhat.runtime.hooks.codex import main as codex_hook_main
from ccwhat.runtime.infra.ports import allocate_port, resolve_runtime_ports
from ccwhat.runtime.infra.registry import RunRegistry


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, stdout=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    (path / "README.md").write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, stdout=subprocess.PIPE)


def test_run_registry_isolates_active_tasks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        registry = RunRegistry(Path(tmp))
        run_a = registry.create_run(
            agent="claude",
            workspace=Path(tmp),
            target_args=("claude",),
            proxy_port=11001,
            viewer_port=11002,
            control_port=11003,
        )
        run_b = registry.create_run(
            agent="claude",
            workspace=Path(tmp),
            target_args=("claude",),
            proxy_port=12001,
            viewer_port=12002,
            control_port=12003,
        )

        registry.set_active_task(run_a.run_id, "task-001")

        assert registry.run_path(run_a.run_id).parent.parent.name == "claude"
        assert registry.load(run_a.run_id).active_task_id == "task-001"
        assert registry.load(run_b.run_id).active_task_id is None
        assert registry.run_path(run_a.run_id) != registry.run_path(run_b.run_id)


def test_run_registry_loads_legacy_flat_runtime_runs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        registry = RunRegistry(Path(tmp))
        run = registry.create_run(
            agent="claude",
            workspace=Path(tmp),
            target_args=("claude",),
            proxy_port=11001,
            viewer_port=11002,
            control_port=11003,
        )
        flat_dir = Path(tmp) / run.run_id
        flat_dir.mkdir()
        current_path = registry.run_path(run.run_id)
        flat_path = flat_dir / "run.json"
        flat_path.write_text(current_path.read_text(encoding="utf-8"), encoding="utf-8")
        current_path.unlink()

        assert registry.load(run.run_id).run_id == run.run_id
        assert registry.run_path(run.run_id) == flat_path


def test_runtime_ports_allocate_distinct_ports_and_keep_explicit_values() -> None:
    proxy, viewer, control = resolve_runtime_ports(proxy_port=None, viewer_port=None, need_viewer=True)
    assert len({proxy, viewer, control}) == 3

    explicit_proxy = allocate_port()
    explicit_viewer = allocate_port({explicit_proxy})
    proxy, viewer, control = resolve_runtime_ports(
        proxy_port=explicit_proxy,
        viewer_port=explicit_viewer,
        need_viewer=True,
    )
    assert proxy == explicit_proxy
    assert viewer == explicit_viewer
    assert control not in {explicit_proxy, explicit_viewer}


def test_controller_start_finish_writes_runtime_task_staging() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = root / "repo"
        workspace.mkdir()
        _init_repo(workspace)

        registry = RunRegistry(root / "runtime")
        port = allocate_port()
        run = registry.create_run(
            agent="claude",
            workspace=workspace,
            target_args=("claude",),
            proxy_port=11001,
            viewer_port=11002,
            control_port=port,
        )
        controller = RuntimeController(registry, run.run_id, port)
        controller.start()
        try:
            token = str(run.control["token"])
            started = call_controller(
                port,
                token,
                "start",
                {"title": "ignored runtime task"},
            )
            assert started["ok"] is True

            # note command removed - verify it's rejected
            noted = call_controller(
                port,
                token,
                "note",
                {"raw_args": "important runtime note"},
            )
            assert noted["ok"] is False  # note command no longer supported

            (workspace / "README.md").write_text("after\n", encoding="utf-8")
            finished = call_controller(
                port,
                token,
                "finish",
                {},
            )
            assert finished["ok"] is True
            second = call_controller(
                port,
                token,
                "start",
                {"title": "ignored second task"},
            )
            assert second["ok"] is True
        finally:
            controller.stop()

        task_dir = registry.run_dir(run.run_id) / "tasks" / "task-001"
        task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        second_task_dir = registry.run_dir(run.run_id) / "tasks" / "task-002"
        second_task = json.loads((second_task_dir / "task.json").read_text(encoding="utf-8"))
        assert task["title"] == "Task1"
        assert second_task["title"] == "Task2"
        assert task["status"] == "finalized"
        # repo snapshots and diff removed - evidence_availability should be false
        assert task["evidence_availability"]["repo_before"] is False
        assert task["evidence_availability"]["repo_after"] is False
        assert task["evidence_availability"]["diff"] is False
        assert task["evidence_availability"]["control_events"] is False
        # step diff.patch is empty (no record_step calls), but total diff captures README change
        assert task["evidence_availability"]["diff_total"] is True
        assert task["paths"]["diff_total"] == "diff_total.patch"
        assert (task_dir / "diff_total.patch").exists()
        # repo snapshots and control_events no longer created
        assert not (task_dir / "repo_before.tar.gz").exists()
        assert not (task_dir / "repo_after.tar.gz").exists()
        assert not (task_dir / "diff.patch").exists()
        assert not (task_dir / "control_events.jsonl").exists()


def test_controller_rejects_errors() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = root / "repo"
        workspace.mkdir()
        _init_repo(workspace)
        registry = RunRegistry(root / "runtime")
        port = allocate_port()
        run = registry.create_run(
            agent="claude",
            workspace=workspace,
            target_args=("claude",),
            proxy_port=11001,
            viewer_port=None,
            control_port=port,
        )
        controller = RuntimeController(registry, run.run_id, port)
        controller.start()
        try:
            token = str(run.control["token"])
            assert call_controller(port, token, "finish", {})["ok"] is False
            assert call_controller(port, token, "start", {})["ok"] is True
            assert call_controller(port, token, "start", {})["ok"] is False
        finally:
            controller.stop()


def test_controller_rejects_non_git_workspace_on_start() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = root / "not-git"
        workspace.mkdir()
        registry = RunRegistry(root / "runtime")
        port = allocate_port()
        run = registry.create_run(
            agent="claude",
            workspace=workspace,
            target_args=("claude",),
            proxy_port=11001,
            viewer_port=None,
            control_port=port,
        )
        controller = RuntimeController(registry, run.run_id, port)
        controller.start()
        try:
            result = call_controller(port, str(run.control["token"]), "start", {})
        finally:
            controller.stop()

        assert result["ok"] is False
        assert "not a git repository" in result["error"]
        assert not (registry.run_dir(run.run_id) / "tasks").exists()


def test_claude_integration_generates_managed_files_and_detects_conflicts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        written = install_claude_integration(workspace)

        start_command = workspace / ".claude" / "commands" / "ccwhat" / "start.md"
        finish_command = workspace / ".claude" / "commands" / "ccwhat" / "finish.md"
        hook = workspace / ".claude" / "hooks" / "ccwhat-runtime-hook.sh"
        settings = workspace / ".claude" / "settings.local.json"
        assert start_command in written
        start_text = start_command.read_text(encoding="utf-8")
        assert "CCWHAT_COMMAND=start" in start_text
        assert "argument-hint" not in start_text
        assert finish_command.exists()
        assert hook.exists()
        assert "UserPromptSubmit" in settings.read_text(encoding="utf-8")

        start_command.write_text("user file\n", encoding="utf-8")
        try:
            install_claude_integration(workspace)
        except ClaudeIntegrationConflict as exc:
            assert "refusing to overwrite" in str(exc)
        else:
            raise AssertionError("expected ClaudeIntegrationConflict")


def test_codex_integration_generates_managed_files_and_detects_conflicts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = root / "workspace"
        home = root / "codex-home"
        workspace.mkdir()
        written = install_codex_integration(workspace, home=home)

        start_prompt = home / "prompts" / "ccwhat-start.md"
        finish_prompt = home / "prompts" / "ccwhat-finish.md"
        start_source_command = workspace / ".agents" / "skills" / "source-command-ccwhat-start" / "SKILL.md"
        finish_source_command = workspace / ".agents" / "skills" / "source-command-ccwhat-finish" / "SKILL.md"
        hooks = workspace / ".codex" / "hooks.json"
        start_text = start_prompt.read_text(encoding="utf-8")
        source_command_text = start_source_command.read_text(encoding="utf-8")
        assert start_prompt in written
        assert start_text.startswith("---\ndescription: CCWhat Task start\n")
        assert "CCWHAT_COMMAND=start" in start_text
        assert "argument-hint" not in start_text
        assert finish_prompt.exists()
        assert start_source_command in written
        assert 'name: "source-command-ccwhat-start"' in source_command_text
        assert "CCWHAT_COMMAND=start" in source_command_text
        assert "Optional input" not in source_command_text
        assert finish_source_command.exists()
        assert hooks.exists()
        hooks_payload = json.loads(hooks.read_text(encoding="utf-8"))
        submit_hooks = hooks_payload["hooks"]["UserPromptSubmit"]
        assert "ccwhat.runtime.codex_hook" in json.dumps(submit_hooks)

        obsolete_prompt = home / "prompts" / "ccwhat-note.md"
        obsolete_source = workspace / ".agents" / "skills" / "source-command-ccwhat-note" / "SKILL.md"
        obsolete_prompt.write_text("<!-- CCWHAT MANAGED CODEX RUNTIME TASK COMMAND v1 -->\n", encoding="utf-8")
        obsolete_source.parent.mkdir(parents=True)
        obsolete_source.write_text("<!-- CCWHAT MANAGED CODEX RUNTIME TASK COMMAND v1 -->\n", encoding="utf-8")
        install_codex_integration(workspace, home=home)
        assert not obsolete_prompt.exists()
        assert not obsolete_source.exists()

        start_source_command.write_text("user file\n", encoding="utf-8")
        try:
            install_codex_integration(workspace, home=home)
        except CodexIntegrationConflict as exc:
            assert "refusing to overwrite" in str(exc)
        else:
            raise AssertionError("expected CodexIntegrationConflict")


def test_opencode_integration_generates_managed_files_and_detects_conflicts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        written = install_opencode_integration(workspace)

        start_command = workspace / ".opencode" / "command" / "ccwhat-start.md"
        finish_command = workspace / ".opencode" / "command" / "ccwhat-finish.md"
        plugin = workspace / ".opencode" / "plugin" / "ccwhat-runtime.js"
        start_text = start_command.read_text(encoding="utf-8")
        plugin_text = plugin.read_text(encoding="utf-8")
        assert start_command in written
        assert finish_command.exists()
        assert all(":" not in path.name for path in written)
        assert "CCWHAT_COMMAND=start" in start_text
        assert "Reply exactly with: 收到" in start_text
        assert "command.execute.before" in plugin_text
        assert "opencode_command_execute_before" in plugin_text
        assert "ccwhat:start" in plugin_text
        assert "ccwhat:finish" in plugin_text
        assert "tool.execute.after" in plugin_text
        assert "detectFileOperation" in plugin_text
        assert "CCWHAT_ENABLED" in plugin_text
        assert "action" in plugin_text

        start_command.write_text("user file\n", encoding="utf-8")
        try:
            install_opencode_integration(workspace)
        except OpenCodeIntegrationConflict as exc:
            assert "refusing to overwrite" in str(exc)
        else:
            raise AssertionError("expected OpenCodeIntegrationConflict")


def test_opencode_integration_removes_legacy_colon_commands_on_posix() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        command_dir = workspace / ".opencode" / "command"
        command_dir.mkdir(parents=True)
        marker = "<!-- CCWHAT MANAGED OPENCODE RUNTIME TASK COMMAND v1 -->\nold\n"
        legacy_start = command_dir / "ccwhat:start.md"
        legacy_finish = command_dir / "ccwhat:finish.md"
        legacy_start.write_text(marker, encoding="utf-8")
        legacy_finish.write_text(marker, encoding="utf-8")

        install_opencode_integration(workspace)

        assert not legacy_start.exists()
        assert not legacy_finish.exists()


def test_runtime_hook_commands_quote_windows_python_paths() -> None:
    with mock.patch("sys.executable", r"C:\Program Files\Python313\python.exe"), \
         mock.patch("ccwhat.runtime.platform.os.name", "nt"):
        assert codex_hook_command().startswith(r'"C:\Program Files\Python313\python.exe" -m ')
        assert "exec 'C:\\Program Files\\Python313\\python.exe' -m ccwhat.runtime.claude_hook" in claude_hook_content()


def test_claude_hook_command_drives_controller_and_staging() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = root / "repo"
        workspace.mkdir()
        _init_repo(workspace)

        registry = RunRegistry(root / "runtime")
        port = allocate_port()
        run = registry.create_run(
            agent="claude",
            workspace=workspace,
            target_args=("claude",),
            proxy_port=11001,
            viewer_port=11002,
            control_port=port,
        )
        controller = RuntimeController(registry, run.run_id, port)
        controller.start()
        env = {
            "CCWHAT_RUNTIME_CONTROL_PORT": str(port),
            "CCWHAT_RUNTIME_TOKEN": str(run.control["token"]),
        }
        try:
            with mock.patch.dict(os.environ, env), \
                 mock.patch("sys.stdin", io.StringIO('{"prompt":"CCWHAT_COMMAND=start\\nCCWHAT_ARGS=ignored hook task"}')), \
                 mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                assert claude_hook_main() == 2
                assert "decision" in stdout.getvalue()

            (workspace / "README.md").write_text("after hook\n", encoding="utf-8")
            with mock.patch.dict(os.environ, env), \
                 mock.patch("sys.stdin", io.StringIO('{"prompt":"CCWHAT_COMMAND=finish\\nCCWHAT_ARGS="}')), \
                 mock.patch("sys.stdout", new_callable=io.StringIO):
                assert claude_hook_main() == 2
        finally:
            controller.stop()

        task_dir = registry.run_dir(run.run_id) / "tasks" / "task-001"
        assert (task_dir / "task.json").exists()
        # repo snapshots, diff, and control_events no longer created
        assert not (task_dir / "control_events.jsonl").exists()
        assert not (task_dir / "repo_before.tar.gz").exists()
        assert not (task_dir / "repo_after.tar.gz").exists()
        assert not (task_dir / "diff.patch").exists()
        task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        assert task["title"] == "Task1"
        assert task["status"] == "finalized"


def test_codex_hook_command_drives_controller_and_staging() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = root / "repo"
        workspace.mkdir()
        _init_repo(workspace)

        registry = RunRegistry(root / "runtime")
        port = allocate_port()
        run = registry.create_run(
            agent="codex",
            workspace=workspace,
            target_args=("codex",),
            proxy_port=11001,
            viewer_port=11002,
            control_port=port,
        )
        controller = RuntimeController(registry, run.run_id, port)
        controller.start()
        env = {
            "CCWHAT_RUNTIME_CONTROL_PORT": str(port),
            "CCWHAT_RUNTIME_TOKEN": str(run.control["token"]),
        }
        try:
            with mock.patch.dict(os.environ, env), \
                 mock.patch("sys.stdin", io.StringIO('{"prompt":"CCWHAT_COMMAND=start\\nCCWHAT_ARGS=ignored codex task"}')), \
                 mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                assert codex_hook_main() == 0
                assert '"decision": "block"' in stdout.getvalue()

            (workspace / "README.md").write_text("after codex\n", encoding="utf-8")
            with mock.patch.dict(os.environ, env), \
                 mock.patch("sys.stdin", io.StringIO('{"prompt":"CCWHAT_COMMAND=finish\\nCCWHAT_ARGS="}')), \
                 mock.patch("sys.stdout", new_callable=io.StringIO):
                assert codex_hook_main() == 0
        finally:
            controller.stop()

        task_dir = registry.run_dir(run.run_id) / "tasks" / "task-001"
        assert (task_dir / "task.json").exists()
        # repo snapshots, diff, and control_events no longer created
        assert not (task_dir / "control_events.jsonl").exists()
        assert not (task_dir / "repo_before.tar.gz").exists()
        assert not (task_dir / "repo_after.tar.gz").exists()
        assert not (task_dir / "diff.patch").exists()
        task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        assert task["title"] == "Task1"
        assert task["status"] == "finalized"
        # control_events no longer created, so no event assertions


def test_codex_hook_short_text_fallback_drives_controller() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = root / "repo"
        workspace.mkdir()
        _init_repo(workspace)

        registry = RunRegistry(root / "runtime")
        port = allocate_port()
        run = registry.create_run(
            agent="codex",
            workspace=workspace,
            target_args=("codex",),
            proxy_port=11001,
            viewer_port=11002,
            control_port=port,
        )
        controller = RuntimeController(registry, run.run_id, port)
        controller.start()
        env = {
            "CCWHAT_RUNTIME_CONTROL_PORT": str(port),
            "CCWHAT_RUNTIME_TOKEN": str(run.control["token"]),
        }
        try:
            with mock.patch.dict(os.environ, env), \
                 mock.patch("sys.stdin", io.StringIO('{"prompt":"ccwhat start ignored fallback task"}')), \
                 mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                assert codex_hook_main() == 0
                assert '"decision": "block"' in stdout.getvalue()

            (workspace / "README.md").write_text("after fallback\n", encoding="utf-8")
            with mock.patch.dict(os.environ, env), \
                 mock.patch("sys.stdin", io.StringIO('{"prompt":"ccwhat finish"}')), \
                 mock.patch("sys.stdout", new_callable=io.StringIO):
                assert codex_hook_main() == 0
        finally:
            controller.stop()

        task_dir = registry.run_dir(run.run_id) / "tasks" / "task-001"
        task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        assert task["title"] == "Task1"
        assert task["status"] == "finalized"


def test_top_level_claude_run_creates_runtime_and_injects_env() -> None:
    runner = CliRunner()
    captured_env: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmp:
        runtime_root = Path(tmp) / "runtime"
        registry = RunRegistry(runtime_root)

        def fake_popen(args, env=None, **kwargs):
            captured_env.update(env or {})
            proc = mock.MagicMock()
            proc.pid = 1234
            proc.wait.return_value = 0
            return proc

        with runner.isolated_filesystem():
            _init_repo(Path.cwd())
            with mock.patch("ccwhat.commands.run.load_config", return_value=RecordingConfig(preset="claude")), \
                 mock.patch("ccwhat.commands.run.RunRegistry", return_value=registry), \
                 mock.patch("ccwhat.commands.run.RuntimeController") as controller_cls, \
                 mock.patch("ccwhat.commands.run.install_claude_integration") as install_integration, \
                 mock.patch("ccwhat.commands.run.resolve_runtime_ports", return_value=(19001, 19002, 19003)), \
                 mock.patch("ccwhat.commands.run._proxy_is_running", return_value=True), \
                 mock.patch("ccwhat.commands.run._start_managed_web", return_value=None), \
                 mock.patch("ccwhat.commands.run.subprocess.Popen", side_effect=fake_popen):
                controller_cls.return_value.start.return_value = None
                controller_cls.return_value.stop.return_value = None
                result = runner.invoke(cli, ["--", "claude"])

        assert result.exit_code == 0
        install_integration.assert_called_once()
        assert captured_env["CCWHAT_RUNTIME_CONTROL_PORT"] == "19003"
        assert captured_env["CCWHAT_RUNTIME_RUN_ID"]
        run_path = next(runtime_root.glob("*/*/run.json"))
        run = json.loads(run_path.read_text(encoding="utf-8"))
        assert run["proxy"]["port"] == 19001
        assert run["viewer"]["port"] == 19002
        assert run["control"]["port"] == 19003
        assert run["agent_process"]["pid"] == 1234


def test_top_level_codex_run_creates_runtime_and_injects_env() -> None:
    runner = CliRunner()
    captured_env: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmp:
        runtime_root = Path(tmp) / "runtime"
        registry = RunRegistry(runtime_root)

        def fake_popen(args, env=None, **kwargs):
            captured_env.update(env or {})
            proc = mock.MagicMock()
            proc.pid = 2345
            proc.wait.return_value = 0
            return proc

        with runner.isolated_filesystem():
            _init_repo(Path.cwd())
            with mock.patch("ccwhat.commands.run.load_config", return_value=RecordingConfig(preset="codex")), \
                 mock.patch("ccwhat.commands.run.RunRegistry", return_value=registry), \
                 mock.patch("ccwhat.commands.run.RuntimeController") as controller_cls, \
                 mock.patch("ccwhat.commands.run.install_codex_integration") as install_integration, \
                 mock.patch("ccwhat.commands.run.resolve_runtime_ports", return_value=(19101, 19102, 19103)), \
                 mock.patch("ccwhat.commands.run._proxy_is_running", return_value=True), \
                 mock.patch("ccwhat.commands.run._start_managed_web", return_value=None), \
                 mock.patch("ccwhat.commands.run.subprocess.Popen", side_effect=fake_popen):
                controller_cls.return_value.start.return_value = None
                controller_cls.return_value.stop.return_value = None
                result = runner.invoke(cli, ["--", "codex"])

        assert result.exit_code == 0
        install_integration.assert_called_once()
        assert captured_env["CCWHAT_RUNTIME_CONTROL_PORT"] == "19103"
        assert captured_env["CCWHAT_RUNTIME_RUN_ID"]
        run_path = next(runtime_root.glob("*/*/run.json"))
        run = json.loads(run_path.read_text(encoding="utf-8"))
        assert run["agent"] == "codex"
        assert run["proxy"]["port"] == 19101
        assert run["viewer"]["port"] == 19102
        assert run["control"]["port"] == 19103
        assert run["agent_process"]["pid"] == 2345


def test_top_level_opencode_run_creates_runtime_and_injects_env() -> None:
    runner = CliRunner()
    captured_env: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmp:
        runtime_root = Path(tmp) / "runtime"
        registry = RunRegistry(runtime_root)

        def fake_popen(args, env=None, **kwargs):
            captured_env.update(env or {})
            proc = mock.MagicMock()
            proc.pid = 3456
            proc.wait.return_value = 0
            return proc

        with runner.isolated_filesystem():
            _init_repo(Path.cwd())
            with mock.patch("ccwhat.commands.run.load_config", return_value=RecordingConfig(preset="opencode")), \
                 mock.patch("ccwhat.commands.run.RunRegistry", return_value=registry), \
                 mock.patch("ccwhat.commands.run.RuntimeController") as controller_cls, \
                 mock.patch("ccwhat.commands.run.install_opencode_integration") as install_integration, \
                 mock.patch("ccwhat.commands.run.resolve_runtime_ports", return_value=(19201, 19202, 19203)), \
                 mock.patch("ccwhat.commands.run._proxy_is_running", return_value=True), \
                 mock.patch("ccwhat.commands.run._start_managed_web", return_value=None), \
                 mock.patch("ccwhat.commands.run.subprocess.Popen", side_effect=fake_popen):
                controller_cls.return_value.start.return_value = None
                controller_cls.return_value.stop.return_value = None
                result = runner.invoke(cli, ["--", "opencode"])

        assert result.exit_code == 0
        install_integration.assert_called_once()
        assert captured_env["CCWHAT_RUNTIME_CONTROL_PORT"] == "19203"
        assert captured_env["CCWHAT_RUNTIME_RUN_ID"]
        run_path = next(runtime_root.glob("*/*/run.json"))
        run = json.loads(run_path.read_text(encoding="utf-8"))
        assert run["agent"] == "opencode"
        assert run["proxy"]["port"] == 19201
        assert run["viewer"]["port"] == 19202
        assert run["control"]["port"] == 19203
        assert run["agent_process"]["pid"] == 3456


# ---------------------------------------------------------------------------
# trace_extractor tests
# ---------------------------------------------------------------------------

from datetime import datetime, timezone

from ccwhat.runtime.core.trace_extractor import extract_task_trace, find_session_log_paths


def _write_session_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _claude_entry(ts: str, etype: str, text: str) -> dict:
    return {"type": etype, "timestamp": ts, "content": text}


def _now_ts() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def test_trace_extractor_time_window() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        projects_dir = Path(tmp) / "projects"
        workspace = "/fake/workspace"
        project_dir = projects_dir / "-fake-workspace"
        session_jsonl = project_dir / "abcd1234-0000-0000-0000-000000000001.jsonl"

        entries = [
            _claude_entry("2026-01-01T10:00:00Z", "user", "before task"),
            _claude_entry("2026-01-01T10:01:00Z", "user", "inside task: fix bug"),
            _claude_entry("2026-01-01T10:02:00Z", "user", "still inside"),
            _claude_entry("2026-01-01T10:10:00Z", "user", "after task"),
        ]
        _write_session_jsonl(session_jsonl, entries)

        trace = extract_task_trace(
            workspace=workspace,
            started_at="2026-01-01T10:00:30Z",
            finished_at="2026-01-01T10:03:00Z",
            agent="claude",
            projects_dir=projects_dir,
        )
        assert trace is not None
        event_texts = [e["text"] for e in trace["events"] if e.get("text")]
        assert any("inside task" in t for t in event_texts)
        assert not any("before task" in t for t in event_texts)
        assert not any("after task" in t for t in event_texts)
        assert trace["time_window"]["started_at"] == "2026-01-01T10:00:30Z"


def test_trace_extractor_missing_log_returns_log_not_found() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        projects_dir = Path(tmp) / "projects"
        projects_dir.mkdir()
        trace = extract_task_trace(
            workspace="/no/such/workspace",
            started_at="2026-01-01T10:00:00Z",
            finished_at="2026-01-01T10:01:00Z",
            agent="claude",
            projects_dir=projects_dir,
        )
        assert trace["extraction_status"] == "log_not_found"
        assert trace["extraction_status_reason"] is not None
        assert trace["events"] == []
        assert trace["commands"] == []


def test_trace_extractor_unsupported_agent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        projects_dir = Path(tmp) / "projects"
        projects_dir.mkdir()
        trace = extract_task_trace(
            workspace="/any/workspace",
            started_at="2026-01-01T10:00:00Z",
            finished_at="2026-01-01T10:01:00Z",
            agent="codex",
            projects_dir=projects_dir,
        )
        assert trace["extraction_status"] == "unsupported_agent"
        assert trace["extraction_status_reason"] is not None
        assert trace["agent"] == "codex"
        assert trace["events"] == []
        assert trace["commands"] == []
        assert trace["files"] == {"read": [], "changed": []}


def test_trace_extractor_invalid_time_bounds() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        projects_dir = Path(tmp) / "projects"
        projects_dir.mkdir()
        trace = extract_task_trace(
            workspace="/any/workspace",
            started_at="invalid-timestamp",
            finished_at="2026-01-01T10:01:00Z",
            agent="claude",
            projects_dir=projects_dir,
        )
        assert trace["extraction_status"] == "invalid_time_bounds"
        assert trace["extraction_status_reason"] is not None


def test_task_trace_written_on_finish() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = root / "repo"
        workspace.mkdir()
        _init_repo(workspace)

        projects_dir = root / "claude_projects"
        project_dir = projects_dir / workspace.as_posix().replace("/", "-")
        session_jsonl = project_dir / "abcd1234-0000-0000-0000-000000000002.jsonl"

        registry = RunRegistry(root / "runtime")
        port = allocate_port()
        run = registry.create_run(
            agent="claude",
            workspace=workspace,
            target_args=("claude",),
            proxy_port=11101,
            viewer_port=11102,
            control_port=port,
        )

        with mock.patch(
            "ccwhat.runtime.core.trace_extractor._CLAUDE_PROJECTS_DIR", projects_dir
        ):
            controller = RuntimeController(registry, run.run_id, port)
            controller.start()
            try:
                token = str(run.control["token"])
                call_controller(port, token, "start", {"title": "fix bug"})
                # Write session entries AFTER start so timestamps fall within task window
                entries = [
                    _claude_entry(_now_ts(), "user", "run tests"),
                    _claude_entry(_now_ts(), "assistant", "done"),
                ]
                _write_session_jsonl(session_jsonl, entries)
                (workspace / "README.md").write_text("changed\n", encoding="utf-8")
                call_controller(port, token, "finish", {})
            finally:
                controller.stop()

        task_dir = registry.run_dir(run.run_id) / "tasks" / "task-001"
        task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        assert task["evidence_availability"]["task_trace"] is True
        assert "task_trace" in task["paths"]
        trace_path = task_dir / "task_trace.json"
        assert trace_path.exists()
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        assert trace["task_id"] == "task-001"
        assert trace["run_id"] == run.run_id
        assert "events" in trace
        assert "commands" in trace
        assert "errors" in trace


def test_task_trace_missing_log_degrades_gracefully() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = root / "repo"
        workspace.mkdir()
        _init_repo(workspace)

        empty_projects_dir = root / "no_claude_projects"
        empty_projects_dir.mkdir()

        registry = RunRegistry(root / "runtime")
        port = allocate_port()
        run = registry.create_run(
            agent="claude",
            workspace=workspace,
            target_args=("claude",),
            proxy_port=11201,
            viewer_port=11202,
            control_port=port,
        )

        with mock.patch(
            "ccwhat.runtime.core.trace_extractor._CLAUDE_PROJECTS_DIR", empty_projects_dir
        ):
            controller = RuntimeController(registry, run.run_id, port)
            controller.start()
            try:
                token = str(run.control["token"])
                call_controller(port, token, "start", {"title": "task without log"})
                call_controller(port, token, "finish", {})
            finally:
                controller.stop()

        task_dir = registry.run_dir(run.run_id) / "tasks" / "task-001"
        task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        assert task["status"] == "finalized"
        assert task["evidence_availability"]["task_trace"] is True
        assert (task_dir / "task_trace.json").exists()
        trace = json.loads((task_dir / "task_trace.json").read_text(encoding="utf-8"))
        assert trace["extraction_status"] == "log_not_found"


def test_task_json_instruction_and_expected_tests() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = root / "repo"
        workspace.mkdir()
        _init_repo(workspace)

        projects_dir = root / "claude_projects"
        project_dir = projects_dir / workspace.as_posix().replace("/", "-")
        session_jsonl = project_dir / "abcd1234-0000-0000-0000-000000000003.jsonl"

        registry = RunRegistry(root / "runtime")
        port = allocate_port()
        run = registry.create_run(
            agent="claude",
            workspace=workspace,
            target_args=("claude",),
            proxy_port=11301,
            viewer_port=11302,
            control_port=port,
        )

        task_dir = registry.run_dir(run.run_id) / "tasks" / "task-001"

        with mock.patch(
            "ccwhat.runtime.core.trace_extractor._CLAUDE_PROJECTS_DIR", projects_dir
        ):
            controller = RuntimeController(registry, run.run_id, port)
            controller.start()
            try:
                token = str(run.control["token"])
                call_controller(port, token, "start", {"title": "short title"})

                task_before = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
                assert task_before["instruction"] == "short title"
                assert task_before["success_criteria"] is None
                assert task_before["expected_tests"] == []

                # Write session entries with current timestamps so they fall in task window
                entries = [_claude_entry(_now_ts(), "user", "add unit tests for parser")]
                _write_session_jsonl(session_jsonl, entries)

                call_controller(port, token, "finish", {})
            finally:
                controller.stop()

        task_after = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        assert task_after["instruction"] == "add unit tests for parser"


def test_step_diff_captures_bash_mv_and_sed_via_sync() -> None:
    """sync_step captures mv/sed changes that bypass Write/Edit hooks,
    and incremental step diffs do not duplicate previous steps."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = root / "repo"
        workspace.mkdir()
        _init_repo(workspace)
        (workspace / "old.md").write_text("hello\n", encoding="utf-8")
        (workspace / "config.py").write_text("VERSION = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=workspace, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=workspace, capture_output=True, check=True)

        registry = RunRegistry(root / "runtime")
        port = allocate_port()
        run = registry.create_run(
            agent="opencode", workspace=workspace, target_args=("opencode",),
            proxy_port=11301, viewer_port=None, control_port=port,
        )
        controller = RuntimeController(registry, run.run_id, port)
        controller.start()
        try:
            token = str(run.control["token"])
            call_controller(port, token, "start", {"title": "mv and sed"})

            # bash mv: rename old.md -> new.md, reported via /step action=sync
            subprocess.run(["mv", "old.md", "new.md"], cwd=workspace, capture_output=True, check=True)
            call_controller(port, token, "step", {"tool_name": "bash", "file_path": "", "action": "sync"})

            # bash sed: modify config.py, reported via /step action=sync
            subprocess.run(["sed", "-i", "", "s/VERSION = 1/VERSION = 2/", "config.py"],
                           cwd=workspace, capture_output=True, check=True)
            call_controller(port, token, "step", {"tool_name": "bash", "file_path": "", "action": "sync"})

            call_controller(port, token, "finish", {})
        finally:
            controller.stop()

        task_dir = registry.run_dir(run.run_id) / "tasks" / "task-001"
        task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))

        # Step diff and total diff both generated
        assert task["evidence_availability"]["diff"] is True
        assert task["evidence_availability"]["diff_total"] is True

        step_patch = (task_dir / "diff.patch").read_text(encoding="utf-8")
        total_patch = (task_dir / "diff_total.patch").read_text(encoding="utf-8")

        # mv captured as a rename (in both step and total)
        assert "rename from old.md" in step_patch
        assert "rename to new.md" in step_patch
        assert "rename from old.md" in total_patch

        # sed captured as content change (in both)
        assert "-VERSION = 1" in step_patch
        assert "+VERSION = 2" in step_patch
        assert "-VERSION = 1" in total_patch
        assert "+VERSION = 2" in total_patch


def test_step_diff_incremental_does_not_duplicate() -> None:
    """Each step diff contains only that step's change, not prior steps'."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = root / "repo"
        workspace.mkdir()
        _init_repo(workspace)
        (workspace / "a.py").write_text("a\n", encoding="utf-8")
        (workspace / "b.py").write_text("b\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=workspace, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=workspace, capture_output=True, check=True)

        registry = RunRegistry(root / "runtime")
        port = allocate_port()
        run = registry.create_run(
            agent="opencode", workspace=workspace, target_args=("opencode",),
            proxy_port=11302, viewer_port=None, control_port=port,
        )
        controller = RuntimeController(registry, run.run_id, port)
        controller.start()
        try:
            token = str(run.control["token"])
            call_controller(port, token, "start", {"title": "two edits"})

            (workspace / "a.py").write_text("a1\n", encoding="utf-8")
            call_controller(port, token, "step", {"tool_name": "edit", "file_path": "a.py", "action": "add"})

            (workspace / "b.py").write_text("b1\n", encoding="utf-8")
            call_controller(port, token, "step", {"tool_name": "edit", "file_path": "b.py", "action": "add"})

            call_controller(port, token, "finish", {})
        finally:
            controller.stop()

        task_dir = registry.run_dir(run.run_id) / "tasks" / "task-001"
        step_patch = (task_dir / "diff.patch").read_text(encoding="utf-8")

        # Step 1 section contains a.py change but not b.py
        step1 = step_patch.split("# Step 2:")[0]
        assert "a.py" in step1
        assert "b.py" not in step1

        # Step 2 section contains b.py change but not a.py's old content
        step2 = step_patch.split("# Step 2:")[1]
        assert "b.py" in step2
        assert "+a1" not in step2  # a.py's change must not leak into step 2
