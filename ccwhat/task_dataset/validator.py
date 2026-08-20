"""Validator for Task Dataset v1 directories and tar archives."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path
from typing import Any

from .models import (
    CHANGE_CONFIDENCES,
    CHANGE_KINDS,
    DATASET_JSONL_PATH,
    DATASET_SCHEMA_VERSION,
    DIFFS_DIR,
    MANIFEST_PATH,
    PATCH_CONFIDENCES,
    PATCH_FORMATS,
    SCORES_JSONL_PATH,
    TRACES_DIR,
    ValidationIssue,
    ValidationResult,
)


def validate_dataset_path(path: str | Path) -> ValidationResult:
    """Validate a Dataset v1 directory or existing tar/tar.gz archive."""
    source = Path(path)
    if source.is_dir():
        return validate_dataset(*_read_directory(source))
    if source.is_file() and tarfile.is_tarfile(source):
        return validate_dataset(*_read_tar(source))
    return ValidationResult(
        ok=False,
        errors=[ValidationIssue(str(source), "Path is not a Dataset directory or tar archive.")],
    )


def validate_dataset(
    files: dict[str, bytes],
    directories: set[str] | None = None,
) -> ValidationResult:
    """Validate normalized Dataset files loaded from any storage backend."""
    dirs = directories or set()
    errors: list[ValidationIssue] = []

    _check_required_paths(files, dirs, errors)

    manifest = _parse_json(files, MANIFEST_PATH, errors)
    dataset_rows = _parse_jsonl(files, DATASET_JSONL_PATH, errors)
    score_rows = _parse_jsonl(files, SCORES_JSONL_PATH, errors)

    trace_paths = sorted(
        path for path in files
        if path.startswith(f"{TRACES_DIR}/") and path.endswith(".json")
    )
    traces: dict[str, Any] = {}
    for trace_path in trace_paths:
        traces[trace_path] = _parse_json(files, trace_path, errors)

    counts = {
        "dataset_items": len(dataset_rows),
        "traces": len(trace_paths),
        "scores": len(score_rows),
    }

    if isinstance(manifest, dict):
        _validate_manifest(manifest, counts, errors)

    _validate_all_traces(traces, files, errors)

    for row in dataset_rows:
        _validate_dataset_row_trace(row, traces, errors)

    return ValidationResult(
        ok=not errors,
        errors=errors,
        counts=counts,
    )


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
            name = _clean_member_name(member.name)
            if not name:
                continue
            if member.isdir():
                raw_dirs.add(name.rstrip("/") + "/")
            elif member.isfile():
                extracted = tar.extractfile(member)
                if extracted is not None:
                    raw_files[name] = extracted.read()
    return _strip_common_tar_root(raw_files, raw_dirs)


def _clean_member_name(name: str) -> str:
    return name.lstrip("./").rstrip("/")


def _strip_common_tar_root(
    files: dict[str, bytes],
    directories: set[str],
) -> tuple[dict[str, bytes], set[str]]:
    if MANIFEST_PATH in files:
        return files, directories
    required_names = {MANIFEST_PATH, DATASET_JSONL_PATH, SCORES_JSONL_PATH}
    roots = {path.split("/", 1)[0] for path in files if "/" in path}
    for root in sorted(roots):
        prefix = f"{root}/"
        stripped_files = {
            path.removeprefix(prefix): data
            for path, data in files.items()
            if path.startswith(prefix)
        }
        if required_names.issubset(stripped_files):
            stripped_dirs = {
                directory.removeprefix(prefix)
                for directory in directories
                if directory.startswith(prefix)
            }
            return stripped_files, stripped_dirs
    return files, directories


def _check_required_paths(
    files: dict[str, bytes],
    directories: set[str],
    errors: list[ValidationIssue],
) -> None:
    for required in (MANIFEST_PATH, DATASET_JSONL_PATH, SCORES_JSONL_PATH):
        if required not in files:
            errors.append(ValidationIssue(required, f"Missing required path: {required}"))
    has_traces = any(path.startswith(f"{TRACES_DIR}/") for path in files) or f"{TRACES_DIR}/" in directories
    if not has_traces:
        errors.append(ValidationIssue(f"{TRACES_DIR}/", "Missing required path: traces/"))


def _parse_json(
    files: dict[str, bytes],
    path: str,
    errors: list[ValidationIssue],
) -> Any:
    if path not in files:
        return None
    try:
        return json.loads(files[path].decode("utf-8"))
    except UnicodeDecodeError as exc:
        errors.append(ValidationIssue(path, f"File is not valid UTF-8: {exc}"))
    except json.JSONDecodeError as exc:
        errors.append(ValidationIssue(path, f"Invalid JSON: {exc.msg}", line=exc.lineno))
    return None


def _parse_jsonl(
    files: dict[str, bytes],
    path: str,
    errors: list[ValidationIssue],
) -> list[Any]:
    if path not in files:
        return []
    try:
        text = files[path].decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.append(ValidationIssue(path, f"File is not valid UTF-8: {exc}"))
        return []

    rows: list[Any] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            errors.append(
                ValidationIssue(path, f"Invalid JSONL: {exc.msg}", line=line_number)
            )
    return rows


def _validate_manifest(
    manifest: dict[str, Any],
    counts: dict[str, int],
    errors: list[ValidationIssue],
) -> None:
    _require_field(manifest, MANIFEST_PATH, "created_at", errors)
    has_tool = _require_field(manifest, MANIFEST_PATH, "tool", errors)

    if manifest.get("schema_version") != DATASET_SCHEMA_VERSION:
        errors.append(
            ValidationIssue(
                MANIFEST_PATH,
                f"manifest.schema_version must be {DATASET_SCHEMA_VERSION!r}.",
                field="schema_version",
            )
        )
    if has_tool and manifest.get("tool") != "ccwhat":
        errors.append(
            ValidationIssue(
                MANIFEST_PATH,
                "manifest.tool must be 'ccwhat'.",
                field="tool",
            )
        )
    session = _require_object(manifest, MANIFEST_PATH, "session", errors)
    if session is not None:
        for field in ("session_id", "agent", "project_dir"):
            _require_field(session, MANIFEST_PATH, f"session.{field}", errors, key=field)

    manifest_counts = _require_object(manifest, MANIFEST_PATH, "counts", errors)
    if manifest_counts is None:
        return
    for key in counts:
        if not _require_field(
            manifest_counts,
            MANIFEST_PATH,
            f"counts.{key}",
            errors,
            key=key,
        ):
            continue
    for key, actual in counts.items():
        if key not in manifest_counts:
            continue
        expected = manifest_counts.get(key)
        if expected != actual:
            errors.append(
                ValidationIssue(
                    MANIFEST_PATH,
                    f"Count mismatch for counts.{key}: manifest has {expected!r}, actual is {actual}.",
                    field=f"counts.{key}",
                )
            )


def _validate_dataset_row_trace(
    row: Any,
    traces: dict[str, Any],
    errors: list[ValidationIssue],
) -> None:
    if not isinstance(row, dict):
        errors.append(ValidationIssue(DATASET_JSONL_PATH, "Dataset row must be an object."))
        return
    _validate_dataset_row_schema(row, errors)
    item_id = row.get("id")
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        return
    trace_path = metadata.get("trace_path")
    if not isinstance(trace_path, str) or not trace_path:
        errors.append(
            ValidationIssue(
                DATASET_JSONL_PATH,
                f"Dataset item {item_id!r} metadata.trace_path is required.",
                field="metadata.trace_path",
            )
        )
        return
    trace_id = metadata.get("trace_id")
    if trace_id and trace_path:
        expected_path = f"{TRACES_DIR}/{trace_id}.json"
        if trace_path != expected_path:
            errors.append(
                ValidationIssue(
                    DATASET_JSONL_PATH,
                    f"Dataset item {item_id!r} trace_path {trace_path!r} does not match trace_id {trace_id!r}.",
                    field="metadata.trace_path",
                )
            )
    trace = traces.get(trace_path)
    if trace is None:
        errors.append(
            ValidationIssue(
                trace_path,
                f"Dataset item {item_id!r} references missing trace path {trace_path!r}.",
                field="metadata.trace_path",
            )
        )
        return
    if not isinstance(trace, dict):
        return
    if trace.get("task_id") != item_id:
        errors.append(
            ValidationIssue(
                trace_path,
                f"Dataset item id {item_id!r} does not match trace.task_id {trace.get('task_id')!r}.",
                field="task_id",
            )
        )


def _validate_all_traces(
    traces: dict[str, Any],
    files: dict[str, bytes],
    errors: list[ValidationIssue],
) -> None:
    for trace_path, trace in traces.items():
        if isinstance(trace, dict):
            _validate_trace_schema(trace, trace_path, files, errors)
        elif trace is not None:
            errors.append(ValidationIssue(trace_path, "Trace JSON must be an object."))


def _validate_dataset_row_schema(
    row: dict[str, Any],
    errors: list[ValidationIssue],
) -> None:
    _require_field(row, DATASET_JSONL_PATH, "id", errors)
    input_obj = _require_object(row, DATASET_JSONL_PATH, "input", errors)
    if input_obj is not None:
        for field in ("instruction", "repo", "base_commit"):
            _require_field(input_obj, DATASET_JSONL_PATH, f"input.{field}", errors, key=field)

    expected = _require_object(row, DATASET_JSONL_PATH, "expected", errors)
    if expected is not None:
        _require_field(expected, DATASET_JSONL_PATH, "expected.success_criteria", errors, key="success_criteria")
        _require_array(expected, DATASET_JSONL_PATH, "expected.tests", errors, key="tests")

    metadata = _require_object(row, DATASET_JSONL_PATH, "metadata", errors)
    if metadata is not None:
        for field in (
            "agent",
            "session_id",
            "task_source",
            "trace_id",
            "trace_path",
            "start_event_id",
            "end_event_id",
        ):
            _require_field(metadata, DATASET_JSONL_PATH, f"metadata.{field}", errors, key=field)


def _validate_trace_schema(
    trace: dict[str, Any],
    trace_path: str,
    dataset_files: dict[str, bytes],
    errors: list[ValidationIssue],
) -> None:
    for field in (
        "trace_id",
        "task_id",
        "session_id",
        "agent",
        "boundary",
        "events",
        "commands",
        "test_commands",
        "files",
        "changes",
        "patches",
        "errors",
        "final_claim",
        "repo_state",
    ):
        _require_field(trace, trace_path, field, errors)

    boundary = _require_object(trace, trace_path, "boundary", errors)
    if boundary is not None:
        for field in ("start_event_id", "end_event_id", "start_turn", "end_turn"):
            _require_field(boundary, trace_path, f"boundary.{field}", errors, key=field)

    for field in ("events", "commands", "test_commands", "changes", "patches", "errors"):
        _require_array(trace, trace_path, field, errors)

    files = _require_object(trace, trace_path, "files", errors)
    if files is not None:
        _require_array(files, trace_path, "files.read", errors, key="read")
        _require_array(files, trace_path, "files.changed", errors, key="changed")

    repo_state = _require_object(trace, trace_path, "repo_state", errors)
    if repo_state is not None:
        for field in ("cwd", "base_commit", "head_commit", "git_dirty_at_export"):
            _require_field(repo_state, trace_path, f"repo_state.{field}", errors, key=field)

    changes = trace.get("changes") if isinstance(trace.get("changes"), list) else []
    patches = trace.get("patches") if isinstance(trace.get("patches"), list) else []
    _validate_patch_entries(patches, trace_path, errors)
    _validate_change_entries(changes, patches, trace_path, errors)
    if "task_diff" in trace:
        _validate_task_diff(trace, trace_path, dataset_files, errors)


def _validate_task_diff(
    trace: dict[str, Any],
    trace_path: str,
    dataset_files: dict[str, bytes],
    errors: list[ValidationIssue],
) -> None:
    task_diff = _require_object(trace, trace_path, "task_diff", errors)
    if task_diff is None:
        return
    for field in ("available", "source", "confidence", "path"):
        _require_field(task_diff, trace_path, f"task_diff.{field}", errors, key=field)

    available = task_diff.get("available")
    if not isinstance(available, bool):
        errors.append(
            ValidationIssue(
                trace_path,
                "task_diff.available must be a boolean.",
                field="task_diff.available",
            )
        )
        return

    source = task_diff.get("source")
    confidence = task_diff.get("confidence")
    diff_path = task_diff.get("path")
    if not available:
        if any(value is not None for value in (source, confidence, diff_path)):
            errors.append(
                ValidationIssue(
                    trace_path,
                    "Unavailable task_diff must use null source, confidence, and path.",
                    field="task_diff",
                )
            )
        return

    if source != "isolated_git_index":
        errors.append(
            ValidationIssue(
                trace_path,
                "Available task_diff.source must be 'isolated_git_index'.",
                field="task_diff.source",
            )
        )
    if confidence != "high":
        errors.append(
            ValidationIssue(
                trace_path,
                "Available task_diff.confidence must be 'high'.",
                field="task_diff.confidence",
            )
        )
    if not isinstance(diff_path, str) or not diff_path.startswith(f"{DIFFS_DIR}/") or not diff_path.endswith(".diff"):
        errors.append(
            ValidationIssue(
                trace_path,
                "Available task_diff.path must reference diffs/*.diff.",
                field="task_diff.path",
            )
        )
    elif diff_path not in dataset_files:
        errors.append(
            ValidationIssue(
                diff_path,
                f"Trace references missing task diff path {diff_path!r}.",
                field="task_diff.path",
            )
        )


def _validate_change_entries(
    changes: list[Any],
    patches: list[Any],
    trace_path: str,
    errors: list[ValidationIssue],
) -> None:
    patch_ids = {
        patch.get("patch_id")
        for patch in patches
        if isinstance(patch, dict) and isinstance(patch.get("patch_id"), str)
    }
    for index, change in enumerate(changes):
        prefix = f"changes[{index}]"
        if not isinstance(change, dict):
            errors.append(ValidationIssue(trace_path, "Change entry must be an object.", field=prefix))
            continue
        for field in (
            "change_id",
            "event_id",
            "file",
            "kind",
            "source",
            "old_string",
            "new_string",
            "content",
            "patch_id",
            "confidence",
        ):
            _require_field(change, trace_path, f"{prefix}.{field}", errors, key=field)
        kind = change.get("kind")
        if kind is not None and kind not in CHANGE_KINDS:
            errors.append(
                ValidationIssue(
                    trace_path,
                    f"Unknown change kind: {kind!r}",
                    field=f"{prefix}.kind",
                )
            )
        confidence = change.get("confidence")
        if confidence is not None and confidence not in CHANGE_CONFIDENCES:
            errors.append(
                ValidationIssue(
                    trace_path,
                    f"Unknown change confidence: {confidence!r}",
                    field=f"{prefix}.confidence",
                )
            )
        patch_id = change.get("patch_id")
        if patch_id is not None and patch_id not in patch_ids:
            errors.append(
                ValidationIssue(
                    trace_path,
                    f"Change references missing patch_id: {patch_id!r}",
                    field=f"{prefix}.patch_id",
                )
            )


def _validate_patch_entries(
    patches: list[Any],
    trace_path: str,
    errors: list[ValidationIssue],
) -> None:
    for index, patch in enumerate(patches):
        prefix = f"patches[{index}]"
        if not isinstance(patch, dict):
            errors.append(ValidationIssue(trace_path, "Patch entry must be an object.", field=prefix))
            continue
        for field in ("patch_id", "scope", "file", "source", "format", "confidence", "patch"):
            _require_field(patch, trace_path, f"{prefix}.{field}", errors, key=field)
        patch_format = patch.get("format")
        if patch_format is not None and patch_format not in PATCH_FORMATS:
            errors.append(
                ValidationIssue(
                    trace_path,
                    f"Unknown patch format: {patch_format!r}",
                    field=f"{prefix}.format",
                )
            )
        confidence = patch.get("confidence")
        if confidence is not None and confidence not in PATCH_CONFIDENCES:
            errors.append(
                ValidationIssue(
                    trace_path,
                    f"Unknown patch confidence: {confidence!r}",
                    field=f"{prefix}.confidence",
                )
            )


def _require_field(
    obj: dict[str, Any],
    path: str,
    field: str,
    errors: list[ValidationIssue],
    *,
    key: str | None = None,
) -> bool:
    lookup = key or field
    if lookup not in obj:
        errors.append(
            ValidationIssue(
                path,
                f"Missing required field: {field}",
                field=field,
            )
        )
        return False
    return True


def _require_object(
    obj: dict[str, Any],
    path: str,
    field: str,
    errors: list[ValidationIssue],
    *,
    key: str | None = None,
) -> dict[str, Any] | None:
    lookup = key or field
    if not _require_field(obj, path, field, errors, key=lookup):
        return None
    value = obj.get(lookup)
    if not isinstance(value, dict):
        errors.append(
            ValidationIssue(
                path,
                f"Required field must be an object: {field}",
                field=field,
            )
        )
        return None
    return value


def _require_array(
    obj: dict[str, Any],
    path: str,
    field: str,
    errors: list[ValidationIssue],
    *,
    key: str | None = None,
) -> list[Any] | None:
    lookup = key or field
    if not _require_field(obj, path, field, errors, key=lookup):
        return None
    value = obj.get(lookup)
    if not isinstance(value, list):
        errors.append(
            ValidationIssue(
                path,
                f"Required field must be an array: {field}",
                field=field,
            )
        )
        return None
    return value
