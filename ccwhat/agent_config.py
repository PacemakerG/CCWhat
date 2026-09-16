"""Auto-detect recording domains from coding agent config files.

Reads each agent's own config to find API provider base URLs,
so users don't need to run `ccwhat setup` before recording.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# JSONC comment stripping
# ---------------------------------------------------------------------------

def _strip_jsonc_comments(text: str) -> str:
    """Remove // line comments and /* */ block comments, skipping string literals."""
    result: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    while i < n:
        c = text[i]
        if in_string:
            if c == "\\":
                result.append(c)
                if i + 1 < n:
                    result.append(text[i + 1])
                    i += 2
                else:
                    i += 1
                continue
            elif c == '"':
                in_string = False
            result.append(c)
            i += 1
        else:
            if c == '"':
                in_string = True
                result.append(c)
                i += 1
            elif c == "/" and i + 1 < n and text[i + 1] == "/":
                while i < n and text[i] != "\n":
                    i += 1
            elif c == "/" and i + 1 < n and text[i + 1] == "*":
                i += 2
                while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                i += 2
            else:
                result.append(c)
                i += 1
    return "".join(result)


# ---------------------------------------------------------------------------
# Host extraction helper
# ---------------------------------------------------------------------------

def _host_from_url(url: str) -> str | None:
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    try:
        parsed = urlparse(url)
        return parsed.hostname or None
    except Exception:
        return None


def _add_host(hosts: list[str], url: str | None) -> None:
    host = _host_from_url(url or "")
    if host and host not in hosts:
        hosts.append(host)


def _json_objects_from_text(text: str) -> list[dict]:
    """Extract top-level JSON objects from mixed CLI output."""
    objects: list[dict] = []
    start: int | None = None
    depth = 0
    in_string = False
    escape = False

    for i, char in enumerate(text):
        if start is None:
            if char == "{":
                start = i
                depth = 1
                in_string = False
                escape = False
            continue

        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    pass
                else:
                    if isinstance(parsed, dict):
                        objects.append(parsed)
                start = None

    return objects


def _opencode_hosts_from_models_output(text: str) -> list[str]:
    hosts: list[str] = []
    for obj in _json_objects_from_text(text):
        api = obj.get("api")
        if not isinstance(api, dict):
            continue
        url = api.get("url")
        if isinstance(url, str) and "://" in url:
            _add_host(hosts, url)
    return hosts


def _detect_opencode_catalog_domains() -> list[str]:
    try:
        result = subprocess.run(
            ["opencode", "models", "--verbose"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return _opencode_hosts_from_models_output(result.stdout)


# ---------------------------------------------------------------------------
# Per-agent detectors
# ---------------------------------------------------------------------------

def _detect_opencode_domains(home: Path | None = None) -> list[str]:
    config_path = (home or Path.home()) / ".config" / "opencode" / "opencode.jsonc"
    hosts: list[str] = []
    try:
        raw = config_path.read_text(encoding="utf-8")
        data = json.loads(_strip_jsonc_comments(raw))
        providers = data.get("provider", {})
        if isinstance(providers, dict):
            for provider_cfg in providers.values():
                if not isinstance(provider_cfg, dict):
                    continue
                options = provider_cfg.get("options", {})
                if isinstance(options, dict):
                    _add_host(hosts, options.get("baseURL"))
                    _add_host(hosts, options.get("baseUrl"))
                    _add_host(hosts, options.get("base_url"))
    except Exception:
        pass

    # OpenCode built-in providers are not stored in opencode.jsonc. The CLI
    # exposes their model catalog, including provider API URLs.
    if home is None:
        for host in _detect_opencode_catalog_domains():
            if host not in hosts:
                hosts.append(host)

    return hosts if hosts else ["opencode.ai"]


def _detect_claude_domains(home: Path | None = None) -> list[str]:
    config_path = (home or Path.home()) / ".claude" / "settings.json"
    hosts: list[str] = []
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        env = data.get("env", {})
        if isinstance(env, dict):
            for key in (
                "ANTHROPIC_BASE_URL",
                "ANTHROPIC_VERTEX_BASE_URL",
                "ANTHROPIC_BEDROCK_BASE_URL",
                "ANTHROPIC_AWS_BASE_URL",
            ):
                value = env.get(key)
                if isinstance(value, str):
                    _add_host(hosts, value)
    except Exception:
        pass

    for key in (
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_VERTEX_BASE_URL",
        "ANTHROPIC_BEDROCK_BASE_URL",
        "ANTHROPIC_AWS_BASE_URL",
    ):
        _add_host(hosts, os.environ.get(key))

    return hosts if hosts else ["api.anthropic.com"]


def _detect_codex_domains(home: Path | None = None) -> list[str]:
    if tomllib is None:
        return ["api.openai.com", "chatgpt.com"]
    config_path = (home or Path.home()) / ".codex" / "config.toml"
    hosts: list[str] = []
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        _add_host(hosts, data.get("openai_base_url"))
        _add_host(hosts, data.get("chatgpt_base_url"))

        providers = data.get("model_providers", {})
        if isinstance(providers, dict):
            for provider_cfg in providers.values():
                if isinstance(provider_cfg, dict):
                    _add_host(hosts, provider_cfg.get("base_url"))
                    _add_host(hosts, provider_cfg.get("baseURL"))
                    _add_host(hosts, provider_cfg.get("baseUrl"))

        env_set = data.get("shell_environment_policy", {}).get("set", {})
        if isinstance(env_set, dict):
            for key, value in env_set.items():
                if (
                    isinstance(key, str)
                    and (key.endswith("_BASE_URL") or key.endswith("_API_BASE"))
                    and isinstance(value, str)
                ):
                    _add_host(hosts, value)
    except Exception:
        pass

    _add_host(hosts, os.environ.get("OPENAI_BASE_URL"))
    _add_host(hosts, os.environ.get("CHATGPT_BASE_URL"))

    return hosts if hosts else ["api.openai.com", "chatgpt.com"]


_AGENT_DETECTORS = {
    "opencode": _detect_opencode_domains,
    "claude": _detect_claude_domains,
    "codex": _detect_codex_domains,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_domains(agent_name: str, _home: Path | None = None) -> list[str]:
    """Return deduplicated recording domains inferred from agent config.

    Returns [] for unknown agents. Never raises.
    _home is an optional override for the user home directory (used in tests).
    """
    detector = _AGENT_DETECTORS.get(agent_name.lower())
    if detector is None:
        return []
    try:
        hosts = detector(_home)
    except Exception:
        return []
    seen: list[str] = []
    for h in hosts:
        if h not in seen:
            seen.append(h)
    return seen


def detect_default_paths(agent_name: str) -> list[str]:
    """No implicit filters: agent names do not determine provider URL paths."""
    return []
