"""Deterministic prechecks for Session-bound OpenSpec graph diagnosis."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


FINDING_FIELDS = {
    "finding_id",
    "type",
    "action_id",
    "event_ids",
    "target",
    "expected",
    "observed",
}

_EDIT_TOOLS = {"edit", "write", "multiedit", "patch", "apply_patch", "str_replace_editor"}
_VERIFY_COMMAND = re.compile(
    r"(?:"
    r"\bpytest\b|\bpython\s+-m\s+unittest\b|\bopenspec\s+validate\b|"
    r"\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:test|build|lint|check)\b|"
    r"\bcargo\s+(?:test|check)\b|\bgo\s+test\b|\bmvn\s+test\b|"
    r"\bgradle\w*\s+test\b|\bruff\s+check\b|\bmypy\b|\btsc\b"
    r")",
    re.IGNORECASE,
)
_FAILURE_TEXT = re.compile(
    r"(?:\b[1-9]\d*\s+failed\b|\bfailed\b|\bfailure\b|\berror\b|traceback|失败|报错)",
    re.IGNORECASE,
)
_TASK_ITEM = re.compile(r"^\s*-\s*\[[ xX]\]\s+\S", re.MULTILINE)
_SPEC_REQUIREMENT = re.compile(r"^###\s+Requirement:\s*\S", re.MULTILINE)


def run_prechecks(
    change_root: str | Path,
    action_graph: dict[str, Any],
    event_graph: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return only deterministic anomaly findings, numbered once."""
    findings = [
        *check_artifacts(change_root, action_graph),
        *check_basic_verify(action_graph, event_graph),
    ]
    for index, finding in enumerate(findings, 1):
        finding["finding_id"] = f"PF-{index:03d}"
    return findings


def check_artifacts(
    change_root: str | Path,
    action_graph: dict[str, Any],
) -> list[dict[str, Any]]:
    """Check minimal filesystem artifacts for Action types actually observed."""
    root = Path(change_root)
    findings: list[dict[str, Any]] = []
    for action in _actions(action_graph):
        action_type = str(action.get("type") or "").lower()
        if action_type not in {"proposal", "specs", "design", "tasks"} or not _action_observed(action):
            continue

        target, observed = _artifact_problem(root, action_type)
        if observed is None:
            continue
        findings.append(_finding(
            type="artifact_missing",
            action_id=str(action.get("action_id") or ""),
            event_ids=[],
            target=target,
            expected=_artifact_expectation(action_type),
            observed=observed,
        ))
    return findings


def check_basic_verify(
    action_graph: dict[str, Any],
    event_graph: dict[str, Any],
) -> list[dict[str, Any]]:
    """Check validation presence and ordering using Event Graph order only."""
    nodes = [item for item in event_graph.get("nodes", []) if isinstance(item, dict)]
    event_actions = _event_actions(action_graph)
    edits = [(index, node) for index, node in enumerate(nodes) if _is_edit(node)]
    verifications = [(index, node) for index, node in enumerate(nodes) if _is_verification(node)]
    if not edits:
        return []

    last_edit_index, last_edit = edits[-1]
    later_verifications = [item for item in verifications if item[0] > last_edit_index]
    findings: list[dict[str, Any]] = []

    if not later_verifications:
        last_verification = verifications[-1][1] if verifications else None
        finding_type = "verification_stale" if last_verification else "verification_missing"
        event_ids = [str(last_edit.get("node_id") or "")]
        if last_verification:
            event_ids.insert(0, str(last_verification.get("node_id") or ""))
        findings.append(_finding(
            type=finding_type,
            action_id=event_actions.get(str(last_edit.get("node_id") or ""), ""),
            event_ids=[value for value in event_ids if value],
            target=_edit_target(last_edit),
            expected="最后一次修改后存在验证命令及结果",
            observed=(
                "验证后又发生修改，之后没有重新验证"
                if last_verification
                else "修改之后没有发现验证命令"
            ),
        ))
        return findings

    results_by_call = _results_by_call(nodes)
    _, command_node = later_verifications[-1]
    command_id = str(command_node.get("node_id") or "")
    call_id = _tool_call_id(command_node)
    result = results_by_call.get(call_id) if call_id else None
    action_id = event_actions.get(command_id, "")
    command = _command(command_node)
    if result is None:
        findings.append(_finding(
            type="verification_result_missing",
            action_id=action_id,
            event_ids=[command_id] if command_id else [],
            target=command,
            expected="最后一次验证命令具有对应 Tool Result",
            observed="没有发现与最后一次验证命令配对的 Tool Result",
        ))
    elif _result_failed(result):
        result_id = str(result.get("node_id") or "")
        findings.append(_finding(
            type="verification_failed",
            action_id=action_id,
            event_ids=[value for value in (command_id, result_id) if value],
            target=command,
            expected="最后一次验证命令执行成功",
            observed="最后一次验证的 Tool Result 明确包含失败或错误证据",
        ))
    return findings


def _finding(
    *,
    type: str,
    action_id: str,
    event_ids: list[str],
    target: str,
    expected: str,
    observed: str,
) -> dict[str, Any]:
    return {
        "finding_id": "",
        "type": type,
        "action_id": action_id,
        "event_ids": event_ids,
        "target": target,
        "expected": expected,
        "observed": observed,
    }


def _actions(action_graph: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in action_graph.get("actions", []) if isinstance(item, dict)]


def _action_observed(action: dict[str, Any]) -> bool:
    return bool(action.get("event_ids")) or str(action.get("status") or "") in {"observed", "failed"}


def _artifact_problem(root: Path, action_type: str) -> tuple[str, str | None]:
    if action_type == "specs":
        target = "specs/*/spec.md"
        files = sorted((root / "specs").rglob("spec.md")) if (root / "specs").is_dir() else []
        if not files:
            return target, "没有找到任何 spec.md"
        if not any(_valid_text(path, _SPEC_REQUIREMENT) for path in files):
            return target, "spec.md 为空或缺少 Requirement"
        return target, None

    filename = {"proposal": "proposal.md", "design": "design.md", "tasks": "tasks.md"}[action_type]
    path = root / filename
    if not path.is_file():
        return filename, f"{filename} 不存在"
    text = _read_text(path)
    if not text.strip():
        return filename, f"{filename} 为空"
    if action_type == "tasks" and not _TASK_ITEM.search(text):
        return filename, "tasks.md 不包含可解析 checklist"
    return filename, None


def _artifact_expectation(action_type: str) -> str:
    return {
        "proposal": "Proposal 阶段生成非空 proposal.md",
        "specs": "Specs 阶段生成至少一个包含 Requirement 的非空 spec.md",
        "design": "Design 阶段生成非空 design.md",
        "tasks": "Tasks 阶段生成包含可解析 checklist 的非空 tasks.md",
    }[action_type]


def _valid_text(path: Path, pattern: re.Pattern[str]) -> bool:
    text = _read_text(path)
    return bool(text.strip() and pattern.search(text))


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _event_actions(action_graph: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for action in _actions(action_graph):
        action_id = str(action.get("action_id") or "")
        for event_id in action.get("event_ids", []):
            result.setdefault(str(event_id), action_id)
    return result


def _data(node: dict[str, Any]) -> dict[str, Any]:
    return node.get("data") if isinstance(node.get("data"), dict) else {}


def _is_edit(node: dict[str, Any]) -> bool:
    data = _data(node)
    return str(node.get("type") or "") == "file_edit" or str(data.get("tool_name") or "").lower() in _EDIT_TOOLS


def _is_verification(node: dict[str, Any]) -> bool:
    return bool(_VERIFY_COMMAND.search(_command(node)))


def _command(node: dict[str, Any]) -> str:
    data = _data(node)
    return str(data.get("command") or node.get("label") or "").strip()


def _edit_target(node: dict[str, Any]) -> str:
    files = [str(value) for value in _data(node).get("files", []) if value]
    return ", ".join(files) if files else "latest code changes"


def _tool_call_id(node: dict[str, Any]) -> str:
    data = _data(node)
    return str(data.get("tool_call_id") or data.get("tool_use_id") or "")


def _results_by_call(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if str(node.get("type") or "") != "tool_result":
            continue
        call_id = _tool_call_id(node)
        if call_id:
            result.setdefault(call_id, node)
    return result


def _result_failed(node: dict[str, Any]) -> bool:
    data = _data(node)
    if bool(data.get("is_error")):
        return True
    text = " ".join(str(value or "") for value in (data.get("result_summary"), data.get("text"), node.get("label")))
    text = re.sub(r"\b0\s+(?:failed|errors?)\b", "", text, flags=re.IGNORECASE)
    return bool(_FAILURE_TEXT.search(text))
