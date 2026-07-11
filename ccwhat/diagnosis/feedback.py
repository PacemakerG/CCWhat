"""User-feedback diagnosis over one Session-bound OpenSpec graph."""

from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path
from typing import Any

from ccwhat.analyzer import AnalysisError, run_mc_analysis
from ccwhat.diagnosis.precheck import run_prechecks


MAX_TEXT_PREVIEW = 700
MAX_SUSPICIOUS_ACTIONS = 5
MAX_SUSPICIOUS_EVENTS = 15
_MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
_TASK_CHECKLIST = re.compile(r"^-\s*\[[ xX]\]\s+\S")


def analyze_graph_feedback(
    *,
    feedback: str,
    action_graph: dict[str, Any],
    event_graph: dict[str, Any],
    action_graph_path: str | Path,
    event_graph_path: str | Path,
    change_root: str | Path,
    analyzer_cmd: list[str] | tuple[str, ...] | None = None,
    analyzer_agent: str | None = None,
    analyzer_timeout: int | float | None = None,
    runner: Any | None = None,
) -> dict[str, Any]:
    """Run one local Analyzer CLI session and return validated graph references.

    If the first Analyzer output is not valid JSON (e.g. unescaped quotes in
    string values), one automatic format-fix attempt is made.  If that also
    fails the diagnosis gracefully degrades to ``_unavailable_result``.
    """
    precheck_findings = run_prechecks(change_root, action_graph, event_graph)
    try:
        prompt = build_graph_attribution_prompt(
            feedback,
            action_graph_path=action_graph_path,
            event_graph_path=event_graph_path,
            change_root=change_root,
            precheck_findings=precheck_findings,
        )
    except ValueError as exc:
        return _unavailable_result("diagnosis_input_unavailable", str(exc))
    try:
        raw, elapsed_ms = run_mc_analysis(
            prompt,
            cmd=analyzer_cmd,
            agent=analyzer_agent,
            timeout=analyzer_timeout,
            runner=runner,
        )
    except AnalysisError as exc:
        return _unavailable_result(exc.code, exc.message)

    try:
        parsed = parse_graph_attribution_output(raw)
    except ValueError as exc:
        # One allowed format-fix attempt — only fix JSON syntax, no new facts.
        fix_prompt = build_graph_attribution_fix_prompt(raw, exc)
        try:
            fixed_raw, fix_elapsed = run_mc_analysis(
                fix_prompt,
                cmd=analyzer_cmd,
                agent=analyzer_agent,
                timeout=analyzer_timeout,
                runner=runner,
            )
        except AnalysisError as fix_exc:
            return _unavailable_result(fix_exc.code, fix_exc.message)
        try:
            parsed = parse_graph_attribution_output(fixed_raw)
        except ValueError as exc2:
            return _unavailable_result("invalid_analyzer_json", str(exc2))
        elapsed_ms += fix_elapsed

    result = validate_graph_attribution_result(
        parsed,
        action_graph,
        event_graph,
        precheck_findings=precheck_findings,
        change_root=change_root,
    )
    result["elapsed_ms"] = elapsed_ms
    result["analyzer_agent"] = analyzer_agent or "claude"
    return result


def build_graph_attribution_fix_prompt(raw: str, error: ValueError) -> str:
    """Build a prompt asking the model to only fix JSON syntax in *raw*."""
    template = (
        resources.files("ccwhat")
        .joinpath("assets/graph_attribution_fix_prompt.md")
        .read_text(encoding="utf-8")
    )
    return (
        template.replace("{{original_output}}", raw.strip())
        .replace("{{parse_error}}", str(error))
    )


def build_graph_attribution_prompt(
    feedback: str,
    *,
    action_graph_path: str | Path,
    event_graph_path: str | Path,
    change_root: str | Path,
    precheck_findings: list[dict[str, Any]],
) -> str:
    template = resources.files("ccwhat").joinpath("assets/graph_attribution_prompt.md").read_text(encoding="utf-8")
    inputs = {
        "action_graph_path": str(_require_path(action_graph_path, kind="file")),
        "event_graph_path": str(_require_path(event_graph_path, kind="file")),
        "change_root": str(_require_path(change_root, kind="directory")),
        "precheck_findings": precheck_findings,
    }
    return template.replace("{{feedback}}", feedback.strip()).replace(
        "{{diagnosis_inputs}}",
        json.dumps(inputs, ensure_ascii=False, indent=2),
    )


def _require_path(value: str | Path, *, kind: str) -> Path:
    path = Path(value).expanduser().resolve()
    valid = path.is_file() if kind == "file" else path.is_dir()
    if not valid:
        raise ValueError(f"Diagnosis {kind} is unavailable: {path}")
    return path


def parse_graph_attribution_output(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("Analyzer returned empty diagnosis output.")

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        if start < 0:
            raise ValueError("Analyzer output does not contain a JSON object.") from None
        try:
            value, _ = json.JSONDecoder().raw_decode(candidate[start:])
        except json.JSONDecodeError as exc:
            raise ValueError(f"Analyzer output is not valid diagnosis JSON: {exc.msg}.") from exc
    if not isinstance(value, dict):
        raise ValueError("Analyzer diagnosis JSON must be an object.")
    return value


def validate_graph_attribution_result(
    value: dict[str, Any],
    action_graph: dict[str, Any],
    event_graph: dict[str, Any],
    *,
    precheck_findings: list[dict[str, Any]] | None = None,
    change_root: str | Path | None = None,
) -> dict[str, Any]:
    precheck_findings = list(precheck_findings or [])
    precheck_by_id = {
        str(item.get("precheck_finding_id")): item
        for item in precheck_findings
        if isinstance(item, dict) and item.get("precheck_finding_id")
    }
    resolved_change_root = Path(change_root).expanduser().resolve() if change_root is not None else None
    actions = {
        str(item.get("action_id")): item
        for item in action_graph.get("actions", [])
        if isinstance(item, dict) and item.get("action_id")
    }
    events = {
        str(item.get("node_id")): item
        for item in event_graph.get("nodes", [])
        if isinstance(item, dict) and item.get("node_id")
    }
    event_actions: dict[str, list[str]] = {}
    for action_id, action in actions.items():
        for event_id in action.get("event_ids", []):
            event_actions.setdefault(str(event_id), []).append(action_id)

    missing = _string_list(value.get("missing_evidence"))
    suspicious_actions = []
    seen_actions: set[str] = set()
    for item in _dict_list(value.get("suspicious_actions")):
        if len(suspicious_actions) >= MAX_SUSPICIOUS_ACTIONS:
            break
        action_id = str(item.get("action_id") or "")
        if action_id not in actions:
            if action_id:
                missing.append(f"Analyzer referenced unknown Action ID: {action_id}")
            continue
        if action_id in seen_actions:
            continue
        seen_actions.add(action_id)
        row = {
            "action_id": action_id,
            "reason": _clip(item.get("reason"), MAX_TEXT_PREVIEW),
        }
        precheck_finding_ids = []
        for precheck_finding_id in _dedupe(_string_list(item.get("precheck_finding_ids"))):
            if precheck_finding_id not in precheck_by_id:
                missing.append(f"Analyzer referenced unknown precheck_finding_id: {precheck_finding_id}")
                continue
            precheck_finding_ids.append(precheck_finding_id)
        if precheck_finding_ids:
            row["precheck_finding_ids"] = precheck_finding_ids

        document_refs = []
        seen_document_refs: set[tuple[str, str, str | None]] = set()
        for document_ref in _dict_list(item.get("document_refs")):
            normalized, error = _validate_document_ref(document_ref, resolved_change_root)
            if normalized is None:
                missing.append(error)
                continue
            key = (normalized["path"], normalized["kind"], normalized["anchor"])
            if key in seen_document_refs:
                continue
            seen_document_refs.add(key)
            document_refs.append(normalized)
        if document_refs:
            row["document_refs"] = document_refs
        suspicious_actions.append(row)

    suspicious_events = []
    seen_events: set[str] = set()
    selected_action_ids = set(seen_actions)
    for item in _dict_list(value.get("suspicious_events")):
        if len(suspicious_events) >= MAX_SUSPICIOUS_EVENTS:
            break
        event_id = str(item.get("event_id") or "")
        if event_id not in events:
            if event_id:
                missing.append(f"Analyzer referenced unknown Event ID: {event_id}")
            continue
        if event_id in seen_events:
            continue
        seen_events.add(event_id)
        requested_action = str(item.get("action_id") or "")
        actual_actions = event_actions.get(event_id, [])
        if not actual_actions:
            missing.append(f"Analyzer referenced Event ID without an Action mapping: {event_id}")
            continue
        adjusted = False
        if requested_action not in actual_actions:
            requested_action = next(
                (action_id for action_id in actual_actions if action_id in selected_action_ids),
                actual_actions[0],
            )
            adjusted = True
        if requested_action not in selected_action_ids:
            missing.append(
                f"Analyzer referenced Event ID outside selected suspicious Actions: {event_id} -> {requested_action}"
            )
            continue
        row = {
            "event_id": event_id,
            "action_id": requested_action or None,
            "reason": _clip(item.get("reason"), MAX_TEXT_PREVIEW),
        }
        if adjusted:
            row["mapping_adjusted"] = True
        suspicious_events.append(row)

    symptoms = []
    for item in _dict_list(value.get("symptoms"))[:6]:
        symptoms.append({
            "type": _clip(item.get("type"), 80) or "unknown",
            "summary": _clip(item.get("summary"), MAX_TEXT_PREVIEW),
        })

    status = "complete" if suspicious_actions or suspicious_events else "insufficient_evidence"
    if status == "insufficient_evidence":
        missing.append("Analyzer did not return any valid Action or Event references.")
    return {
        "available": True,
        "status": status,
        "symptoms": symptoms,
        "suspicious_actions": suspicious_actions,
        "suspicious_events": suspicious_events,
        "precheck_findings": precheck_findings,
        "missing_evidence": _dedupe(missing),
        "summary": _clip(value.get("summary"), 2000) or "No diagnosis summary was returned.",
    }


def _unavailable_result(code: str, message: str) -> dict[str, Any]:
    return {
        "available": False,
        "status": "unavailable",
        "code": code,
        "symptoms": [],
        "suspicious_actions": [],
        "suspicious_events": [],
        "missing_evidence": [message],
        "summary": "Feedback diagnosis is unavailable.",
    }


def _dict_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value if item] if isinstance(value, list) else []


def _validate_document_ref(
    value: dict[str, Any],
    change_root: Path | None,
) -> tuple[dict[str, Any] | None, str]:
    path_text = str(value.get("path") or "").strip()
    kind = str(value.get("kind") or "").strip()
    anchor_value = value.get("anchor")
    anchor = str(anchor_value).strip() if anchor_value is not None else None
    label = f"path={path_text or '<empty>'}, kind={kind or '<empty>'}, anchor={anchor!r}"

    if change_root is None:
        return None, f"Analyzer document_ref cannot be validated without change root: {label}"
    if not path_text or "\\" in path_text:
        return None, f"Analyzer referenced invalid document_ref path: {label}"

    relative_path = Path(path_text)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        return None, f"Analyzer referenced out-of-scope document_ref path: {label}"

    try:
        document_path = (change_root / relative_path).resolve()
        normalized_path = document_path.relative_to(change_root).as_posix()
    except (OSError, ValueError):
        return None, f"Analyzer referenced out-of-scope document_ref path: {label}"
    if not document_path.is_file():
        return None, f"Analyzer referenced missing document_ref file: {label}"

    parts = Path(normalized_path).parts
    try:
        text = document_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None, f"Analyzer could not read document_ref file: {label}"
    headings = _markdown_headings(text)
    if normalized_path in {"proposal.md", "design.md"}:
        if kind == "document" and anchor is None:
            return {"path": normalized_path, "kind": kind, "anchor": None}, ""
        if kind == "section" and anchor and anchor in headings:
            return {"path": normalized_path, "kind": kind, "anchor": anchor}, ""
    elif normalized_path == "tasks.md":
        tasks = {line.strip() for line in text.splitlines() if _TASK_CHECKLIST.match(line.strip())}
        if kind == "task" and anchor and anchor in tasks:
            return {"path": normalized_path, "kind": kind, "anchor": anchor}, ""
    elif len(parts) == 3 and parts[0] == "specs" and parts[2] == "spec.md":
        if kind == "requirement" and anchor and anchor.startswith("Requirement:") and anchor in headings:
            return {"path": normalized_path, "kind": kind, "anchor": anchor}, ""

    return None, f"Analyzer referenced invalid document_ref kind or anchor: {label}"


def _markdown_headings(text: str) -> set[str]:
    result = set()
    for line in text.splitlines():
        match = _MARKDOWN_HEADING.match(line)
        if not match:
            continue
        result.add(re.sub(r"\s+#+\s*$", "", match.group(1)).strip())
    return result


def _clip(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
