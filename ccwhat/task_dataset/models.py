"""Data structures for Task Dataset v1."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypedDict


DATASET_SCHEMA_VERSION = "ccwhat-dataset-v1"
MANIFEST_PATH = "manifest.json"
DATASET_JSONL_PATH = "dataset.jsonl"
SCORES_JSONL_PATH = "scores.jsonl"
TRACES_DIR = "traces"
DIFFS_DIR = "diffs"
CHANGE_KINDS = {"edit", "write", "patch", "command", "git_diff"}
CHANGE_CONFIDENCES = {"high", "medium", "low"}
PATCH_FORMATS = {"unified_diff", "apply_patch", "git_diff", "opencode_diff"}
PATCH_CONFIDENCES = {"high", "medium"}


class DatasetManifest(TypedDict):
    schema_version: str
    created_at: str
    tool: str
    session: dict[str, Any]
    counts: dict[str, int]


class DatasetItemInput(TypedDict):
    instruction: str | None
    repo: str | None
    base_commit: str | None


class DatasetItemExpected(TypedDict):
    success_criteria: str | None
    tests: list[str]


class DatasetItemMetadata(TypedDict):
    agent: str | None
    session_id: str
    task_source: str
    trace_id: str
    trace_path: str
    start_event_id: str
    end_event_id: str | None
    task_type: str
    status: str


class DatasetItemRow(TypedDict):
    id: str
    input: DatasetItemInput
    expected: DatasetItemExpected
    metadata: DatasetItemMetadata


class DatasetTraceBoundary(TypedDict):
    start_event_id: str
    end_event_id: str | None
    start_turn: int | None
    end_turn: int | None


class DatasetTraceFiles(TypedDict):
    read: list[str]
    changed: list[str]


class DatasetTraceRepoState(TypedDict):
    cwd: str | None
    base_commit: str | None
    head_commit: str | None
    git_dirty_at_export: bool | None


class DatasetTraceTaskDiff(TypedDict):
    available: bool
    source: str | None
    confidence: str | None
    path: str | None


class DatasetChangeEvidence(TypedDict):
    change_id: str
    event_id: str
    file: str | None
    kind: str
    source: str
    old_string: str | None
    new_string: str | None
    content: str | None
    patch_id: str | None
    confidence: str


class DatasetPatchEvidence(TypedDict):
    patch_id: str
    scope: str
    file: str | None
    source: str
    format: str
    confidence: str
    patch: str


class DatasetTrace(TypedDict):
    trace_id: str
    task_id: str
    session_id: str
    agent: str | None
    boundary: DatasetTraceBoundary
    events: list[dict[str, Any]]
    commands: list[str]
    test_commands: list[str]
    files: DatasetTraceFiles
    changes: list[DatasetChangeEvidence]
    patches: list[DatasetPatchEvidence]
    errors: list[str]
    final_claim: str | None
    repo_state: DatasetTraceRepoState
    task_diff: DatasetTraceTaskDiff


class DatasetScoreRow(TypedDict, total=False):
    id: str
    dataset_item_id: str
    trace_id: str
    name: str
    value: Any
    data_type: str
    source: str
    comment: str | None


@dataclass
class DatasetBundle:
    """In-memory representation of a Dataset v1 file collection."""

    manifest: DatasetManifest
    dataset_rows: list[DatasetItemRow]
    traces: dict[str, DatasetTrace]
    scores_rows: list[DatasetScoreRow] = field(default_factory=list)
    diffs: dict[str, str] = field(default_factory=dict)

    def to_text_files(self) -> dict[str, str]:
        """Return normalized relative paths mapped to text content."""
        files: dict[str, str] = {
            MANIFEST_PATH: _json_dump(self.manifest),
            DATASET_JSONL_PATH: _jsonl_dump(self.dataset_rows),
            SCORES_JSONL_PATH: _jsonl_dump(self.scores_rows),
        }
        for trace_id in sorted(self.traces):
            files[f"{TRACES_DIR}/{trace_id}.json"] = _json_dump(self.traces[trace_id])
        for diff_path in sorted(self.diffs):
            files[diff_path] = self.diffs[diff_path]
        return files

    def to_bytes_files(self) -> dict[str, bytes]:
        """Return normalized relative paths mapped to UTF-8 bytes."""
        return {path: text.encode("utf-8") for path, text in self.to_text_files().items()}

    def write_to_directory(self, directory: str | Path) -> None:
        """Write the bundle to *directory* using Dataset v1 paths."""
        root = Path(directory)
        (root / TRACES_DIR).mkdir(parents=True, exist_ok=True)
        for rel_path, content in self.to_text_files().items():
            target = root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")


@dataclass
class ValidationIssue:
    path: str
    message: str
    line: int | None = None
    field: str | None = None


@dataclass
class ValidationResult:
    ok: bool
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    counts: dict[str, int] = field(
        default_factory=lambda: {"dataset_items": 0, "traces": 0, "scores": 0}
    )


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _jsonl_dump(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    return "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n"


@dataclass(frozen=True)
class TaskDiffEvidence:
    """High-confidence repository diff captured at an explicit runtime boundary."""

    content: str
    source: str = "isolated_git_index"
    confidence: str = "high"


DatasetInputSource = Literal["runtime", "auto", "manual", "edited"]
