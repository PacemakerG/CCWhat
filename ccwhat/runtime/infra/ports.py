"""Port allocation helpers for runtime runs."""

from __future__ import annotations

import socket


LOCALHOST = "127.0.0.1"


def port_bind_error(port: int) -> OSError | None:
    """Return the bind error for localhost:port, or None if it is bindable."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((LOCALHOST, port))
        except OSError as exc:
            return exc
    return None


def format_port_bind_error(port: int, exc: OSError, suggestion: str) -> str:
    lines = [
        f"Error: port {port} cannot be bound on {LOCALHOST}: {exc}.",
    ]
    if getattr(exc, "winerror", None) == 10013:
        lines.extend(
            [
                "Detected Windows WinError 10013.",
                "On Windows, this often means the port is reserved in the TCP excluded port range.",
                "Check with: netsh interface ipv4 show excludedportrange protocol=tcp",
            ]
        )
    lines.append(suggestion)
    return "\n".join(lines)


def allocate_port(exclude: set[int] | None = None) -> int:
    exclude = exclude or set()
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((LOCALHOST, 0))
            port = int(sock.getsockname()[1])
        if port not in exclude:
            return port


def resolve_runtime_ports(
    *,
    proxy_port: int | None,
    viewer_port: int | None,
    need_viewer: bool,
) -> tuple[int, int | None, int]:
    used: set[int] = set()
    final_proxy = proxy_port or allocate_port(used)
    used.add(final_proxy)
    final_viewer = None
    if need_viewer:
        final_viewer = viewer_port or allocate_port(used)
        used.add(final_viewer)
    final_control = allocate_port(used)
    return final_proxy, final_viewer, final_control
