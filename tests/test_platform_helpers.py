from __future__ import annotations

from ccwhat.runtime.platform import mitmdump_missing_message, quote_command


def test_process_probe_does_not_terminate_a_live_child() -> None:
    import subprocess
    import sys
    from ccwhat.runtime.platform import process_is_alive

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert process_is_alive(proc.pid)
        assert proc.poll() is None
    finally:
        proc.terminate()
        proc.wait(timeout=5)
    assert not process_is_alive(proc.pid)


def test_agent_inference_handles_executable_paths() -> None:
    from ccwhat.adapters.registry import infer_agent_from_target

    assert infer_agent_from_target((r"C:\Program Files\Codex\codex.exe",)) == "codex"
    assert infer_agent_from_target(("/opt/bin/claude",)) == "claude"
    assert infer_agent_from_target(("opencode.cmd",)) == "opencode"
    assert infer_agent_from_target(("other-cli",)) == "other-cli"


def test_quote_command_uses_windows_quoting_for_spaces() -> None:
    command = quote_command(
        [r"C:\Program Files\Python313\python.exe", "-m", "ccwhat.runtime.codex_hook"],
        os_name="nt",
    )

    assert command == r'"C:\Program Files\Python313\python.exe" -m ccwhat.runtime.codex_hook'


def test_quote_command_uses_posix_quoting_for_spaces() -> None:
    command = quote_command(
        ["/Users/example/Python Builds/python", "-m", "ccwhat.runtime.codex_hook"],
        os_name="posix",
    )

    assert command == "'/Users/example/Python Builds/python' -m ccwhat.runtime.codex_hook"


def test_mitmdump_missing_message_includes_windows_install_options() -> None:
    message = mitmdump_missing_message()

    assert "uv tool install mitmproxy" in message
    assert "pipx install mitmproxy" in message
    assert "py -m pip install --user mitmproxy" in message
    assert "brew install mitmproxy" in message
