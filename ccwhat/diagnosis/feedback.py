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
    try:
        prompt = build_graph_attribution_prompt(
            feedback,
            action_graph_path=action_graph_path,
            event_graph_path=event_graph_path,
            change_root=change_root,
            precheck_findings=run_prechecks(change_root, action_graph, event_graph),
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

    result = validate_graph_attribution_result(parsed, action_graph, event_graph)
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
) -> dict[str, Any]:
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
        action_id = str(item.get("action_id") or "")
        if action_id not in actions:
            if action_id:
                missing.append(f"Analyzer referenced unknown Action ID: {action_id}")
            continue
        if action_id in seen_actions:
            continue
        seen_actions.add(action_id)
        suspicious_actions.append({
            "action_id": action_id,
            "reason": _clip(item.get("reason"), MAX_TEXT_PREVIEW),
        })

    suspicious_events = []
    seen_events: set[str] = set()
    for item in _dict_list(value.get("suspicious_events")):
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
        adjusted = False
        if actual_actions and requested_action not in actual_actions:
            requested_action = actual_actions[0]
            adjusted = True
        elif requested_action not in actions:
            requested_action = actual_actions[0] if actual_actions else ""
            adjusted = bool(actual_actions)
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
