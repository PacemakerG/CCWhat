from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class AdapterNotImplementedError(NotImplementedError):
    """Raised when a requested agent does not have a log adapter yet."""

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name
        super().__init__(
            f"No log adapter available for agent '{agent_name}'. "
            f"Supported log adapters: claude, codex, opencode. "
            f"Use --agent to choose one; HTTP recording can still use configured domains."
        )


class SessionRenameError(Exception):
    """Raised when a session rename operation fails."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class AgentAdapter(ABC):
    """Unified interface for reading coding agent session logs."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def default_projects_dir(self) -> Path:
        ...

    @abstractmethod
    def list_projects(self) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def list_sessions(self) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def load_session(self, session_id: str) -> dict[str, Any] | None:
        ...

    @abstractmethod
    def raw_to_normalized_events(
        self, raw_entry: dict[str, Any], session_id: str
    ) -> list[dict[str, Any]]:
        ...

    @property
    def can_rename_session(self) -> bool:
        """Whether this adapter supports native session title rename."""
        return False

    def rename_session(self, session_id: str, title: str) -> dict[str, Any]:
        """Rename a session's native title. Returns updated metadata dict with
        keys: title, displayName, canRenameSession.
        Raises SessionRenameError on failure."""
        raise SessionRenameError(
            "rename_not_supported",
            f"Agent '{self.name}' does not support native session rename.",
        )

    def session_title_metadata(self, session_id: str, title: str = "") -> dict[str, Any]:
        """Build unified title metadata for a session entry.
        Returns dict with: title, displayName, canRenameSession."""
        display = title.strip() if title else session_id[:8]
        return {
            "title": title or "",
            "displayName": display,
            "canRenameSession": self.can_rename_session,
        }
