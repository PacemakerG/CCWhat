"""Diagnosis engine for OpenSpec action graph attribution."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path
from typing import Any

from ccwhat.task_dataset import validate_dataset
from ccwhat.task_dataset.models import DATASET_JSONL_PATH, MANIFEST_PATH, SCORES_JSONL_PATH, TRACES_DIR

from .action_graph import build_openspec_action_graph
from .attribution import attribute_symptoms
from .event_graph import build_event_graph
from .mapping import map_events_to_actions
from .models import DiagnosisResult
from .symptoms import detect_symptoms


class DiagnosisInputError(ValueError):
    """Raised when diagnosis input cannot be loaded or selected."""


class DiagnosisEngine:
    def diagnose_dataset_task(self, dataset_path: str | Path, task_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        files, directories = _read_dataset_files(Path(dataset_path))
        validation = validate_dataset(files, directories)
        if not validation.ok:
            messages = "; ".join(f"{issue.path}: {issue.message}" for issue in validation.errors[:5])
            raise DiagnosisInputError(f"Dataset validation failed: {messages}")

        row, trace = _select_task(files, task_id)
        event_graph = build_event_graph(trace)
        action_graph = build_openspec_action_graph()
        map_events_to_actions(action_graph, trace)
        symptoms = detect_symptoms(action_graph, trace)
        causal_chains = attribute_symptoms(action_graph, symptoms)
        missing_evidence = _missing_evidence(row, trace)
        diagnosis = DiagnosisResult(
            task_id=task_id,
            workflow="openspec",
            summary=_summary(symptoms, causal_chains),
            symptoms=symptoms,
            causal_chains=causal_chains,
            missing_evidence=missing_evidence,
        )
        return event_graph.to_dict(), action_graph.to_dict(), diagnosis.to_dict()


def write_diagnosis_outputs(
    *,
    output_dir: str | Path,
    event_graph: dict[str, Any],
    action_graph: dict[str, Any],
    diagnosis: dict[str, Any],
) -> None:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    _write_json(root / "event_graph.json", event_graph)
    _write_json(root / "action_graph.json", action_graph)
    _write_json(root / "diagnosis.json", diagnosis)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_dataset_files(path: Path) -> tuple[dict[str, bytes], set[str]]:
    if path.is_dir():
        return _read_directory(path)
    if path.is_file() and tarfile.is_tarfile(path):
        return _read_tar(path)
    raise DiagnosisInputError(f"{path} is not a Dataset directory or tar archive.")


def _read_directory(root: Path) -> tuple[dict[str, bytes], set[str]]:
    files: dict[str, bytes] = {}
    directories: set[str] = set()
    for child in root.rglob("*"):
        rel_path = child.relative_to(root).as_posix()
        if child.is_dir():
            directories.add(rel_path.rstrip("/") + "/")
        elif child.is_file():
            files[rel_path] = child.read_bytes()
    return files, directories


def _read_tar(path: Path) -> tuple[dict[str, bytes], set[str]]:
    raw_files: dict[str, bytes] = {}
    raw_dirs: set[str] = set()
    with tarfile.open(path, "r:*") as tar:
        for member in tar.getmembers():
            name = member.name.lstrip("./").rstrip("/")
            if not name or member.issym() or member.islnk():
                continue
            if member.isdir():
                raw_dirs.add(name.rstrip("/") + "/")
            elif member.isfile():
                extracted = tar.extractfile(member)
                if extracted is not None:
                    raw_files[name] = extracted.read()
    return _strip_common_root(raw_files, raw_dirs)


def _strip_common_root(files: dict[str, bytes], directories: set[str]) -> tuple[dict[str, bytes], set[str]]:
    if MANIFEST_PATH in files:
        return files, directories
    required = {MANIFEST_PATH, DATASET_JSONL_PATH, SCORES_JSONL_PATH}
    roots = {path.split("/", 1)[0] for path in files if "/" in path}
    for root in sorted(roots):
        prefix = f"{root}/"
        stripped = {path.removeprefix(prefix): data for path, data in files.items() if path.startswith(prefix)}
        if required.issubset(stripped):
            stripped_dirs = {item.removeprefix(prefix) for item in directories if item.startswith(prefix)}
            return stripped, stripped_dirs
    return files, directories


def _select_task(files: dict[str, bytes], task_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in files[DATASET_JSONL_PATH].decode("utf-8").splitlines()
        if line.strip()
    ]
    for row in rows:
        if row.get("id") != task_id:
            continue
        trace_path = row.get("metadata", {}).get("trace_path")
        if not trace_path or trace_path not in files:
            raise DiagnosisInputError(f"Trace for task {task_id!r} was not found.")
        return row, json.loads(files[trace_path].decode("utf-8"))
    raise DiagnosisInputError(f"Task id {task_id!r} was not found in dataset.jsonl.")


def _missing_evidence(row: dict[str, Any], trace: dict[str, Any]) -> list[str]:
    missing = []
    if not trace.get("events"):
        missing.append("trace.events is empty")
    if row.get("expected", {}).get("tests") and not trace.get("test_commands"):
        missing.append("expected.tests present but trace.test_commands is empty")
    if trace.get("final_claim") and not trace.get("changes"):
        missing.append("final_claim present but trace.changes is empty")
    return missing


def _summary(symptoms, causal_chains) -> str:
    if not symptoms:
        return "No OpenSpec action graph symptoms detected."
    top = causal_chains[0] if causal_chains else None
    if top:
        return f"Detected {len(symptoms)} symptom(s); top suspected action is {top.root_action_id} with score {top.score}."
    return f"Detected {len(symptoms)} symptom(s), but no causal chain was generated."
