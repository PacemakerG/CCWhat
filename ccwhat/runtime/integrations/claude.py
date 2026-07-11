"""Claude Code slash command integration for CCWhat runtime recording."""

from __future__ import annotations

import json
import os
from pathlib import Path


INTEGRATION_VERSION = "1"
MANAGED_MARKER = "CCWHAT MANAGED RUNTIME TASK COMMAND"
COMMANDS = {
    "start": ("CCWhat Task start", ""),
    "finish": ("CCWhat Task finish", ""),
    "abort": ("CCWhat Task abort", ""),
    "status": ("CCWhat Task status", ""),
}


class ClaudeIntegrationConflict(RuntimeError):
    pass


def install_claude_integration(workspace: Path) -> list[Path]:
    claude_dir = workspace / ".claude"
    command_dir = claude_dir / "commands" / "ccwhat"
    hook_dir = claude_dir / "hooks"
    written: list[Path] = []
    for directory in (command_dir, hook_dir):
        directory.mkdir(parents=True, exist_ok=True)

    for name, (description, argument_hint) in COMMANDS.items():
        path = command_dir / f"{name}.md"
        _write_managed(path, _command_content(name, description, argument_hint))
        written.append(path)

    hook_path = hook_dir / "ccwhat-runtime-hook.sh"
    _write_managed(hook_path, _hook_content())
    hook_path.chmod(hook_path.stat().st_mode | 0o111)
    written.append(hook_path)

    settings_path = claude_dir / "settings.local.json"
    _install_hook_settings(settings_path, hook_path, claude_dir)
    written.append(settings_path)

    _cleanup_legacy_diff_hook(claude_dir, settings_path)
    return written


def _command_content(name: str, description: str, argument_hint: str) -> str:
    hint_line = f"argument-hint: {argument_hint}\n" if argument_hint else ""
    return (
        f"<!-- {MANAGED_MARKER} v{INTEGRATION_VERSION} -->\n"
        "---\n"
        f"name: \"CCWhat: {name}\"\n"
        f"description: {description}\n"
        "category: Workflow\n"
        "tags: [ccwhat, runtime, task]\n"
        f"{hint_line}"
        "---\n\n"
        f"CCWHAT_COMMAND={name}\n"
        "CCWHAT_ARGS=$ARGUMENTS\n"
    )


def _hook_content() -> str:
    return (
        f"#!/bin/sh\n"
        f"# {MANAGED_MARKER} v{INTEGRATION_VERSION}\n"
        "exec \"${CCWHAT_PYTHON:-python3}\" -m ccwhat.runtime.claude_hook\n"
    )


def _write_managed(path: Path, content: str) -> None:
    if path.exists():
        existing = path.read_text(encoding="utf-8", errors="replace")
        if MANAGED_MARKER not in existing:
            raise ClaudeIntegrationConflict(f"refusing to overwrite non-CCWhat file: {path}")
        if existing == content:
            return
    path.write_text(content, encoding="utf-8")


def _install_hook_settings(settings_path: Path, hook_path: Path, claude_dir: Path) -> None:
    if settings_path.exists():
        data = json.loads(settings_path.read_text(encoding="utf-8") or "{}")
        if not isinstance(data, dict):
            raise ClaudeIntegrationConflict(f"Claude settings is not an object: {settings_path}")
    else:
        data = {}

    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ClaudeIntegrationConflict(f"Claude settings hooks is not an object: {settings_path}")

    entries = hooks.setdefault("UserPromptSubmit", [])
    if not isinstance(entries, list):
        raise ClaudeIntegrationConflict("Claude UserPromptSubmit hooks is not a list")

    command = _portable_hook_command(hook_path)
    managed_entry = {
        "matcher": r"ccwhat:(start|finish|abort|status)|ccwhat-(start|finish|abort|status)",
        "hooks": [{"type": "command", "command": command, "timeout": 10}],
    }

    replaced = False
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        entry_hooks = entry.get("hooks")
        if not isinstance(entry_hooks, list):
            continue
        for hook in entry_hooks:
            if isinstance(hook, dict) and "ccwhat-runtime-hook.sh" in str(hook.get("command", "")):
                entries[idx] = managed_entry
                replaced = True
                break
        if replaced:
            break
    if not replaced:
        entries.append(managed_entry)

    settings_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _cleanup_legacy_diff_hook(claude_dir: Path, settings_path: Path) -> None:
    """Remove leftover ccwhat-diff-hook.sh and its PostToolUse entry from prior versions."""
    legacy_hook = claude_dir / "hooks" / "ccwhat-diff-hook.sh"
    if legacy_hook.exists():
        try:
            legacy_hook.unlink()
        except OSError:
            pass

    if not settings_path.exists():
        return
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return

    post = hooks.get("PostToolUse")
    if not isinstance(post, list):
        return

    filtered = [
        entry for entry in post
        if not _entry_references_diff_hook(entry)
    ]
    if filtered:
        hooks["PostToolUse"] = filtered
    else:
        hooks.pop("PostToolUse", None)

    settings_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _entry_references_diff_hook(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    inner = entry.get("hooks")
    if not isinstance(inner, list):
        return False
    for hook in inner:
        if isinstance(hook, dict) and "ccwhat-diff-hook.sh" in str(hook.get("command", "")):
            return True
    return False


def _portable_hook_command(hook_path: Path) -> str:
    try:
        rel = hook_path.relative_to(Path.cwd())
        return os.fspath(Path("$CLAUDE_PROJECT_DIR") / rel)
    except ValueError:
        return str(hook_path)
