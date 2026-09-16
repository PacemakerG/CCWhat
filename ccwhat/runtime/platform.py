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


def process_is_alive(pid: int) -> bool:
    """Probe a process without sending Windows' terminating signal zero."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # Access denied still indicates a process.
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
