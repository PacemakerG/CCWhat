from __future__ import annotations

from pathlib import Path

from ccwhat.adapters.base import AdapterNotImplementedError, AgentAdapter
from ccwhat.adapters.claude import ClaudeAdapter
from ccwhat.adapters.codex import CodexAdapter
from ccwhat.adapters.opencode import OpenCodeAdapter


_AGENT_ALIASES: dict[str, str] = {
    "claude": "claude",
    "claude-code": "claude",
    "claude_code": "claude",
    "claude-code-cli": "claude",
    "codex": "codex",
    "codex-cli": "codex",
    "opencode": "opencode",
    "open-code": "opencode",
    "open_code": "opencode",
    "open-code-cli": "opencode",
}


_IMPLEMENTED_AGENTS = frozenset({"claude", "codex", "opencode"})


def normalize_agent_name(name: str) -> str:
    lowered = name.strip().lower()
    return _AGENT_ALIASES.get(lowered, lowered)


def is_implemented(agent: str) -> bool:
    return agent in _IMPLEMENTED_AGENTS


def get_adapter_class(agent: str) -> type[AgentAdapter]:
    normalized = normalize_agent_name(agent)
    if normalized == "claude":
        return ClaudeAdapter
    if normalized == "codex":
        return CodexAdapter
    if normalized == "opencode":
        return OpenCodeAdapter
    raise AdapterNotImplementedError(agent)


def create_adapter(agent: str, projects_dir: Path | None = None) -> AgentAdapter:
    normalized = normalize_agent_name(agent)
    cls = get_adapter_class(normalized)
    return cls(projects_dir)


def infer_agent_from_target(target_args: tuple[str, ...]) -> str:
    if not target_args:
        return "claude"
    target = target_args[0].lower()
    return normalize_agent_name(target)
