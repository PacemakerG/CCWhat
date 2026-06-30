"""OpenCode command/plugin integration for CCWhat runtime recording."""

from __future__ import annotations

import os
from pathlib import Path


INTEGRATION_VERSION = "1"
MANAGED_MARKER = "CCWHAT MANAGED OPENCODE RUNTIME TASK COMMAND"
COMMANDS = {
    "start": "CCWhat Task start",
    "finish": "CCWhat Task finish",
}
LEGACY_COLON_COMMAND_NAMES = ("ccwhat:start", "ccwhat:finish")


class OpenCodeIntegrationConflict(RuntimeError):
    pass


def install_opencode_integration(workspace: Path) -> list[Path]:
    opencode_dir = workspace / ".opencode"
    command_dir = opencode_dir / "command"
    plugin_dir = opencode_dir / "plugin"
    written: list[Path] = []

    for directory in (command_dir, plugin_dir):
        directory.mkdir(parents=True, exist_ok=True)

    if os.name != "nt":
        for legacy_name in LEGACY_COLON_COMMAND_NAMES:
            _remove_managed(command_dir / f"{legacy_name}.md")

    for name, description in COMMANDS.items():
        path = command_dir / f"ccwhat-{name}.md"
        _write_managed(path, _command_content(name, description), "OpenCode command")
        written.append(path)

    plugin_path = plugin_dir / "ccwhat-runtime.js"
    _write_managed(plugin_path, _plugin_content(), "OpenCode plugin")
    written.append(plugin_path)
    return written


def _command_content(name: str, description: str) -> str:
    boundary = "start" if name == "start" else "finish"
    return (
        "---\n"
        f"description: {description}\n"
        "---\n\n"
        f"<!-- {MANAGED_MARKER} v{INTEGRATION_VERSION} -->\n"
        f"CCWHAT_COMMAND={name}\n"
        "\n"
        "This is a CCWhat local task-boundary marker for OpenCode.\n"
        f"Boundary action: {boundary}.\n"
        "Do not inspect files, run tools, or explain CCWhat.\n"
        "Reply exactly with: 收到\n"
    )


def _plugin_content() -> str:
    return (
        f"// {MANAGED_MARKER} v{INTEGRATION_VERSION}\n"
        "async function callController(action, body = {}) {\n"
        "  const port = process.env.CCWHAT_RUNTIME_CONTROL_PORT\n"
        "  const token = process.env.CCWHAT_RUNTIME_TOKEN || \"\"\n"
        "  if (!port) return null\n"
        "  const response = await fetch(`http://127.0.0.1:${port}/${action}`, {\n"
        "    method: \"POST\",\n"
        "    headers: {\n"
        "      \"Content-Type\": \"application/json\",\n"
        "      \"X-CCWhat-Run-Token\": token,\n"
        "    },\n"
        "    body: JSON.stringify(body),\n"
        "  })\n"
        "  const payload = await response.json().catch(() => ({}))\n"
        "  if (!response.ok || payload.ok === false) {\n"
        "    console.error(`CCWhat ${action} failed:`, payload.error)\n"
        "    return null\n"
        "  }\n"
        "  return payload.data || {}\n"
        "}\n\n"
        "function detectFileOperation(toolName, toolInput) {\n"
        "  // OpenCode tool names are lowercase: write, edit, bash\n"
        "  if ([\"write\", \"edit\"].includes(toolName)) {\n"
        "    const filePath = toolInput?.filePath || toolInput?.file_path || toolInput?.path\n"
        "    if (filePath) return { tool: toolName, path: filePath, action: \"add\" }\n"
        "  }\n"
        "  // Any bash command may modify files (mv, sed, cp, echo >, rm, ...).\n"
        "  // Rather than parse the command, sync the whole workspace so the\n"
        "  // backend reconciles actual disk state into the isolated index.\n"
        "  if (toolName === \"bash\") {\n"
        "    return { tool: \"bash\", path: \"\", action: \"sync\" }\n"
        "  }\n"
        "  return null\n"
        "}\n\n"
        "export default async function ccwhatRuntimePlugin() {\n"
        "  return {\n"
        "    \"command.execute.before\": async (input, output) => {\n"
        "      const actions = {\n"
        "        \"ccwhat:start\": \"start\",\n"
        "        \"ccwhat:finish\": \"finish\",\n"
        "        \"ccwhat-start\": \"start\",\n"
        "        \"ccwhat-finish\": \"finish\",\n"
        "      }\n"
        "      const action = actions[input.command]\n"
        "      if (!action) return\n"
        "      const data = await callController(action, {\n"
        "        agent: \"opencode\",\n"
        "        integration: \"opencode_command_execute_before\",\n"
        "      })\n"
        "      if (data) {\n"
        "        console.error(`CCWhat ${action} recorded locally${data.task_id ? ` (${data.task_id})` : \"\"}.`)\n"
        "      }\n"
        "    },\n"
        "    \"tool.execute.after\": async (input, output) => {\n"
        "      // Skip if CCWhat is not enabled\n"
        "      if (!process.env.CCWHAT_ENABLED) return\n"
        "      const toolName = input?.tool\n"
        "      const toolInput = input?.args\n"
        "      const operations = detectFileOperation(toolName, toolInput)\n"
        "      if (!operations) return\n"
        "      const ops = Array.isArray(operations) ? operations : [operations]\n"
        "      for (const op of ops) {\n"
        "        await callController(\"step\", {\n"
        "          tool_name: op.tool,\n"
        "          file_path: op.path,\n"
        "          action: op.action,\n"
        "        })\n"
        "      }\n"
        "    },\n"
        "  }\n"
        "}\n"
    )


def _remove_managed(path: Path) -> None:
    if not path.exists():
        return
    existing = path.read_text(encoding="utf-8", errors="replace")
    if MANAGED_MARKER in existing:
        path.unlink()


def _write_managed(path: Path, content: str, kind: str) -> None:
    if path.exists():
        existing = path.read_text(encoding="utf-8", errors="replace")
        if MANAGED_MARKER not in existing:
            raise OpenCodeIntegrationConflict(f"refusing to overwrite non-CCWhat {kind}: {path}")
        if existing == content:
            return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
