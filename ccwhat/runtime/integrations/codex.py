"""Codex slash command integration for CCWhat runtime recording."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from ccwhat.runtime.platform import quote_command


INTEGRATION_VERSION = "1"
MANAGED_MARKER = "CCWHAT MANAGED CODEX RUNTIME TASK COMMAND"
COMMANDS = {
    "start": ("CCWhat Task start", ""),
    "finish": ("CCWhat Task finish", ""),
}
OBSOLETE_COMMANDS = {"abort", "status", "note"}


class CodexIntegrationConflict(RuntimeError):
    pass


def codex_home() -> Path:
    configured = os.environ.get("CCWHAT_CODEX_HOME") or os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def install_codex_integration(workspace: Path, home: Path | None = None) -> list[Path]:
    home = home or codex_home()
    prompts_dir = home / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for name, (description, argument_hint) in COMMANDS.items():
        path = prompts_dir / f"ccwhat-{name}.md"
        _write_managed(path, _prompt_content(name, description, argument_hint), "Codex prompt")
        written.append(path)
    for name in OBSOLETE_COMMANDS:
        _remove_managed(prompts_dir / f"ccwhat-{name}.md")

    source_command_dir = workspace / ".agents" / "skills"
    source_command_dir.mkdir(parents=True, exist_ok=True)
    for name, (description, argument_hint) in COMMANDS.items():
        path = source_command_dir / f"source-command-ccwhat-{name}" / "SKILL.md"
        _write_managed(path, _source_command_content(name, description, argument_hint), "Codex source command")
        written.append(path)
    for name in OBSOLETE_COMMANDS:
        _remove_managed(source_command_dir / f"source-command-ccwhat-{name}" / "SKILL.md", remove_empty_parent=True)

    codex_dir = workspace / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    hooks_path = codex_dir / "hooks.json"
    _install_hook_settings(hooks_path)
    written.append(hooks_path)
    return written


def _prompt_content(name: str, description: str, argument_hint: str) -> str:
    hint_line = f"argument-hint: {argument_hint}\n" if argument_hint else ""
    return (
        "---\n"
        f"description: {description}\n"
        f"{hint_line}"
        "---\n\n"
        f"<!-- {MANAGED_MARKER} v{INTEGRATION_VERSION} -->\n"
        f"# CCWhat: {name}\n\n"
        f"CCWHAT_COMMAND={name}\n"
        "CCWHAT_ARGS=$ARGUMENTS\n"
    )


def _source_command_content(name: str, description: str, argument_hint: str) -> str:
    input_line = f" Optional input: {argument_hint}." if argument_hint else ""
    return (
        "---\n"
        f'name: "source-command-ccwhat-{name}"\n'
        f'description: "{description}"\n'
        "---\n\n"
        f"# source-command-ccwhat-{name}\n\n"
        f"<!-- {MANAGED_MARKER} v{INTEGRATION_VERSION} -->\n\n"
        f"Use this skill when the user invokes `/ccwhat:{name}` to record a CCWhat runtime task command."
        f"{input_line}\n\n"
        "## Command Template\n\n"
        f"CCWHAT_COMMAND={name}\n"
        "CCWHAT_ARGS=$ARGUMENTS\n"
    )


def _write_managed(path: Path, content: str, kind: str) -> None:
    if path.exists():
        existing = path.read_text(encoding="utf-8", errors="replace")
        if MANAGED_MARKER not in existing:
            raise CodexIntegrationConflict(f"refusing to overwrite non-CCWhat {kind}: {path}")
        if existing == content:
            return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _remove_managed(path: Path, *, remove_empty_parent: bool = False) -> None:
    if not path.exists():
        return
    existing = path.read_text(encoding="utf-8", errors="replace")
    if MANAGED_MARKER not in existing:
        return
    path.unlink()
    if remove_empty_parent:
        try:
            path.parent.rmdir()
        except OSError:
            return


def _install_hook_settings(hooks_path: Path) -> None:
    if hooks_path.exists():
        data = json.loads(hooks_path.read_text(encoding="utf-8") or "{}")
        if not isinstance(data, dict):
            raise CodexIntegrationConflict(f"Codex hooks config is not an object: {hooks_path}")
    else:
        data = {}

    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise CodexIntegrationConflict(f"Codex hooks config hooks is not an object: {hooks_path}")

    entries = hooks.setdefault("UserPromptSubmit", [])
    if not isinstance(entries, list):
        raise CodexIntegrationConflict("Codex UserPromptSubmit hooks is not a list")

    managed_entry = {
        "ccwhat_managed": MANAGED_MARKER,
        "hooks": [
            {
                "type": "command",
                "command": _hook_command(),
                "timeout": 10,
            }
        ],
    }

    replaced = False
    for idx, entry in enumerate(entries):
        if isinstance(entry, dict) and (
            entry.get("ccwhat_managed") == MANAGED_MARKER
            or "ccwhat.runtime.codex_hook" in json.dumps(entry)
        ):
            entries[idx] = managed_entry
            replaced = True
            break
    if not replaced:
        entries.append(managed_entry)

    hooks_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _hook_command() -> str:
    return quote_command([sys.executable, "-m", "ccwhat.runtime.codex_hook"])
