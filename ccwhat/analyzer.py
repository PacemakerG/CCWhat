"""Current-session analysis helpers for the viewer API."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


ANALYZE_TIMEOUT_SECONDS = 120


class AnalysisError(Exception):
    """User-facing analysis failure."""

    def __init__(self, message: str, code: str = "analysis_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


import os as _os

from ccwhat.analyzers.registry import get as _get_analyzer_spec, list_names as _list_analyzer_names

_KNOWN_BINARY_PATHS = {
    "codex": "/Applications/Codex.app/Contents/Resources/codex",
    "opencode": "/Applications/OpenCode.app/Contents/MacOS/opencode",
}


def _resolve_binary(cmd: list[str]) -> list[str]:
    if not cmd:
        return cmd
    binary = cmd[0]
    if Path(binary).is_file():
        return cmd
    resolved = shutil.which(binary)
    if resolved:
        updated = list(cmd)
        updated[0] = resolved
        return updated
    known = _KNOWN_BINARY_PATHS.get(binary)
    if known and Path(known).is_file():
        updated = list(cmd)
        updated[0] = known
        return updated
    return cmd


def _normalize_analyzer_agent(agent: str | None) -> str:
    from ccwhat.analyzers.registry import _normalize
    return _normalize(agent or "claude")


def _default_analyze_cmd(agent: str | None = None) -> list[str]:
    normalized = _normalize_analyzer_agent(agent)
    spec = _get_analyzer_spec(normalized)
    if spec is None:
        raise AnalysisError(
            f"Analyzer protocol is not supported for agent '{normalized}'. "
            f"Supported agents: {', '.join(_list_analyzer_names())}",
            "analyzer_not_supported",
        )
    return list(spec.default_command)


def _analyze_cmd(
    cmd: list[str] | tuple[str, ...] | None = None,
    agent: str | None = None,
) -> list[str]:
    if cmd:
        return _resolve_binary(list(cmd))
    raw = _os.environ.get("CCWHAT_ANALYZE_CMD", "").strip()
    if raw:
        import shlex
        return _resolve_binary(shlex.split(raw))
    return _resolve_binary(_default_analyze_cmd(agent))


def _analyze_spec(
    cmd: list[str] | tuple[str, ...] | None = None,
    agent: str | None = None,
) -> tuple[Any, list[str]]:
    """Return (spec_or_None, resolved_command) for the given config."""
    normalized = _normalize_analyzer_agent(agent)
    env_cmd = _os.environ.get("CCWHAT_ANALYZE_CMD", "").strip()
    # Only use the analyzer spec when neither explicit cmd nor env override is provided
    spec = _get_analyzer_spec(normalized) if (not cmd and not env_cmd) else None
    resolved_cmd = _analyze_cmd(cmd, agent=agent)
    return spec, resolved_cmd


def _resolve_analyzer_agent(
    agent: str | None = None,
    *,
    default_agent: str | None = None,
) -> str:
    """Resolve the analyzer agent name.

    Priority:
    1. Explicit ``agent`` parameter
    2. CCWHAT_ANALYZE_AGENT env var
    3. ``default_agent`` (adapter name / session agent)
    4. ``"claude"`` fallback
    """
    if agent:
        return _normalize_analyzer_agent(agent)
    env_agent = _os.environ.get("CCWHAT_ANALYZE_AGENT", "").strip()
    if env_agent:
        return _normalize_analyzer_agent(env_agent)
    if default_agent:
        return _normalize_analyzer_agent(default_agent)
    return "claude"


def _resolve_analyzer_timeout(timeout: int | None = None, spec: Any = None) -> int:
    """Resolve timeout from explicit param, env var, spec default, or global default.

    Priority:
    1. Explicit ``timeout`` parameter
    2. CCWHAT_ANALYZE_TIMEOUT env var
    3. ``spec.timeout_seconds``
    4. ``ANALYZE_TIMEOUT_SECONDS`` (120)
    """
    if timeout is not None and timeout > 0:
        return timeout
    env_timeout = _os.environ.get("CCWHAT_ANALYZE_TIMEOUT", "").strip()
    if env_timeout:
        try:
            parsed = int(env_timeout)
            if parsed > 0:
                return parsed
        except ValueError:
            pass
    if spec is not None and getattr(spec, "timeout_seconds", None) and spec.timeout_seconds > 0:
        return spec.timeout_seconds
    return ANALYZE_TIMEOUT_SECONDS


def _run_one_try(
    prompt: str,
    cmd_list: list[str],
    timeout_sec: int,
    spec: Any,
    runner: Any,
    extra_files: dict[str, str] | None = None,
) -> tuple[str, int]:
    """Run a single analyzer attempt and return (report, elapsed_ms) or raise AnalysisError."""
    started = time.monotonic()
    resolved = _resolve_binary(cmd_list)
    try:
        result = runner(
            resolved,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except FileNotFoundError as exc:
        raise AnalysisError(
            f"Analyzer command not found: {resolved[0]!r}.\n"
            "Set CCWHAT_ANALYZE_CMD to your AI CLI command, e.g.:\n"
            "  export CCWHAT_ANALYZE_CMD='claude -p -'",
            "analyzer_not_found",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise AnalysisError(f"Analysis timed out after {timeout_sec} seconds.", "analyzer_timeout") from exc

    elapsed_ms = int((time.monotonic() - started) * 1000)
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    if result.returncode != 0:
        detail = stderr or stdout or f"exit code {result.returncode}"
        raise AnalysisError(f"Analysis failed: {detail}", "analyzer_failed")

    if not stdout and spec and spec.output_mode == "stdout":
        detail = stderr or f"{resolved[0]} returned empty output"
        raise AnalysisError(f"Analysis produced no report: {detail}", "empty_report")

    if spec and spec.output_mode != "stdout" and spec.parse_output:
        try:
            parsed = spec.parse_output(stdout, stderr, extra_files or {})
            if not parsed.strip():
                if not stdout.strip():
                    detail = stderr or f"{resolved[0]} returned empty output"
                    raise AnalysisError(
                        f"Analysis produced no report: {detail}",
                        "empty_report",
                    )
                raise AnalysisError(
                    "Analyzer output parser produced empty report. "
                    "The command may have returned an unexpected format.",
                    "analyzer_output_parse_error",
                )
            return parsed, elapsed_ms
        except AnalysisError:
            raise
        except Exception as exc:
            raise AnalysisError(
                f"Failed to parse analyzer output: {exc}",
                "analyzer_output_parse_error",
            ) from exc

    return stdout, elapsed_ms


def run_mc_analysis(
    prompt: str,
    timeout: int | None = None,
    runner: Any | None = None,
    cmd: list[str] | tuple[str, ...] | None = None,
    agent: str | None = None,
    default_agent: str | None = None,
) -> tuple[str, int]:
    normalized_agent = _resolve_analyzer_agent(agent, default_agent=default_agent)
    spec, resolved_cmd = _analyze_spec(cmd, agent=normalized_agent)
    effective_timeout = _resolve_analyzer_timeout(timeout, spec=spec)
    return _run_one_try(
        prompt,
        resolved_cmd,
        effective_timeout,
        spec,
        runner or subprocess.run,
    )
