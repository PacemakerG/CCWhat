"""Small platform helpers for command-line integration points."""

from __future__ import annotations

import os
import shlex
import subprocess


def quote_command(args: list[str] | tuple[str, ...], *, os_name: str | None = None) -> str:
    """Return a shell command string suitable for the current platform."""
    platform = os_name or os.name
    if platform == "nt":
        return subprocess.list2cmdline([str(arg) for arg in args])
    return shlex.join([str(arg) for arg in args])


def mitmdump_missing_message() -> str:
    return (
        "Error: mitmdump command not found.\n"
        "Install mitmproxy with one of:\n"
        "  uv tool install mitmproxy\n"
        "  pipx install mitmproxy\n"
        "  py -m pip install --user mitmproxy  # Windows\n"
        "  brew install mitmproxy              # macOS with Homebrew"
    )
