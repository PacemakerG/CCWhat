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
        assert task["task_id"] == "task-001"
        assert task["run_id"] == run.run_id
        assert task["agent"] == "claude"
        assert task["workspace"] == str(workspace.resolve())
        assert task["started_at"]
        assert task["finished_at"]
        assert task["start_tree"]
        assert task["end_tree"]
        assert task["start_tree"] != task["end_tree"]
        assert set(task.keys()) == {
            "task_id", "run_id", "agent", "workspace",
            "started_at", "finished_at", "start_tree", "end_tree",
        }
        assert (task_dir / "task.diff").exists()
        diff_text = (task_dir / "task.diff").read_text(encoding="utf-8")
        assert "README.md" in diff_text
        assert "-before" in diff_text
        assert "+after" in diff_text
        assert not (task_dir / "diff.patch").exists()
        assert not (task_dir / "diff_total.patch").exists()
        assert not (task_dir / "task_trace.json").exists()
        assert not (task_dir / "repo_before.tar.gz").exists()
        assert not (task_dir / "repo_after.tar.gz").exists()
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
        settings_payload = json.loads(settings.read_text(encoding="utf-8"))
        assert "PostToolUse" not in settings_payload.get("hooks", {})
        assert not (workspace / ".claude" / "hooks" / "ccwhat-diff-hook.sh").exists()

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
        assert "tool.execute.after" not in plugin_text
        assert "detectFileOperation" not in plugin_text
        assert "CCWHAT_ENABLED" not in plugin_text

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
        assert (task_dir / "task.diff").exists()
        diff_text = (task_dir / "task.diff").read_text(encoding="utf-8")
        assert "README.md" in diff_text
        assert "-before" in diff_text
        assert "+after hook" in diff_text
        task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        assert task["start_tree"]
        assert task["end_tree"]
        assert task["start_tree"] != task["end_tree"]


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
        assert (task_dir / "task.diff").exists()
        diff_text = (task_dir / "task.diff").read_text(encoding="utf-8")
        assert "README.md" in diff_text
        assert "-before" in diff_text
        assert "+after codex" in diff_text
        task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        assert task["start_tree"]
        assert task["end_tree"]
        assert task["start_tree"] != task["end_tree"]


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
        assert task["task_id"] == "task-001"
        assert task["start_tree"]
        assert task["end_tree"]
        assert (task_dir / "task.diff").exists()


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



def test_task_diff_excludes_pre_task_dirty_changes() -> None:
    """task.diff only contains changes between start and finish, not pre-existing dirty state."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = root / "repo"
        workspace.mkdir()
        _init_repo(workspace)

        # pre-task dirty change: modify uv.lock before starting task
        (workspace / "uv.lock").write_text("pre-task dirty\n", encoding="utf-8")

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
            assert call_controller(port, token, "start", {"title": "t"})["ok"] is True
            (workspace / "README.md").write_text("changed during task\n", encoding="utf-8")
            assert call_controller(port, token, "finish", {})["ok"] is True
        finally:
            controller.stop()

        task_dir = registry.run_dir(run.run_id) / "tasks" / "task-001"
        diff_text = (task_dir / "task.diff").read_text(encoding="utf-8")
        assert "README.md" in diff_text
        assert "uv.lock" not in diff_text


def test_task_diff_captures_bash_and_untracked() -> None:
    """task.diff captures bash-created changes and untracked files."""
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
            assert call_controller(port, token, "start", {"title": "t"})["ok"] is True
            # bash-style changes: new untracked file + modify existing
            (workspace / "new_file.txt").write_text("new content\n", encoding="utf-8")
            (workspace / "README.md").write_text("via bash edit\n", encoding="utf-8")
            assert call_controller(port, token, "finish", {})["ok"] is True
        finally:
            controller.stop()

        task_dir = registry.run_dir(run.run_id) / "tasks" / "task-001"
        diff_text = (task_dir / "task.diff").read_text(encoding="utf-8")
        assert "new_file.txt" in diff_text
        assert "README.md" in diff_text
        assert "+new content" in diff_text


def test_user_git_index_unchanged_by_runtime() -> None:
    """Runtime operations do not pollute the user's .git/index."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = root / "repo"
        workspace.mkdir()
        _init_repo(workspace)

        user_index_before = (workspace / ".git" / "index").read_bytes()

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
            assert call_controller(port, token, "start", {"title": "t"})["ok"] is True
            (workspace / "README.md").write_text("changed\n", encoding="utf-8")
            assert call_controller(port, token, "finish", {})["ok"] is True
        finally:
            controller.stop()

        user_index_after = (workspace / ".git" / "index").read_bytes()
        assert user_index_before == user_index_after
        # isolated index exists, user index untouched
        assert (workspace / ".git" / "index.ccwhat").exists()


def test_claude_integration_cleans_legacy_posttooluse_hook() -> None:
    """Upgrading from old version removes ccwhat-diff-hook.sh and PostToolUse entry."""
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        claude_dir = workspace / ".claude"
        hooks_dir = claude_dir / "hooks"
        hooks_dir.mkdir(parents=True)
        settings_path = claude_dir / "settings.local.json"

        # simulate legacy install: diff hook file + PostToolUse entry
        legacy_hook = hooks_dir / "ccwhat-diff-hook.sh"
        legacy_hook.write_text("#!/bin/bash\n# legacy\n", encoding="utf-8")
        legacy_settings = {
            "hooks": {
                "UserPromptSubmit": [],
                "PostToolUse": [
                    {
                        "matcher": "Write|Edit|MultiEdit|Bash",
                        "hooks": [{"type": "command", "command": str(legacy_hook), "timeout": 5}],
                    }
                ],
            }
        }
        settings_path.write_text(json.dumps(legacy_settings), encoding="utf-8")

        install_claude_integration(workspace)

        assert not legacy_hook.exists()
        new_settings = json.loads(settings_path.read_text(encoding="utf-8"))
        assert "PostToolUse" not in new_settings.get("hooks", {})
        assert "UserPromptSubmit" in new_settings.get("hooks", {})
