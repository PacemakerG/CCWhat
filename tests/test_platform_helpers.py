from __future__ import annotations

from ccwhat.runtime.platform import mitmdump_missing_message, quote_command


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
