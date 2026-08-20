# Task Dataset Core

This document records the implementation handoff for `add-task-dataset-core`.

## Dataset v1 Files

`ccwhat.task_dataset` defines `ccwhat-dataset-v1` as an in-memory bundle with stable serialized paths:

- `manifest.json`: schema version, creation time, tool name, session metadata, and counts.
- `dataset.jsonl`: one task row per line with `input`, `expected`, and `metadata`.
- `traces/<trace-id>.json`: one execution trace per task.
- `scores.jsonl`: present but empty in Dataset v1 core.
- `diffs/<trace-id>.diff`: optional task-level repository diff captured at runtime boundaries.

Fields that may not be available in local sessions are intentionally stable and nullable, including `input.base_commit`, `expected.success_criteria`, `repo_state.base_commit`, and `repo_state.head_commit`.

## Builder

Use `build_dataset_bundle(session_metadata=..., events=..., segmentation=...)` with normalized `NormalizedEvent` values and a `TaskSegmentationResult`.

The builder returns a `DatasetBundle`:

- `bundle.manifest`
- `bundle.dataset_rows`
- `bundle.traces`
- `bundle.scores_rows`
- `bundle.diffs`

Serialization helpers:

- `bundle.to_text_files()`
- `bundle.to_bytes_files()`
- `bundle.write_to_directory(path)`

The builder slices trace events by `start_event_id` and `end_event_id` as a closed interval. If `end_event_id` is `None`, the trace extends to the end of the session. It also extracts event-backed `changes` and `patches`.

## Boundary Sources

Runtime and offline segmentation share one Dataset schema and builder:

- `runtimeTasks`: `/ccwhat:start` and `/ccwhat:finish` provide explicit time boundaries; the isolated Git index adds the task-level repository diff.
- `taskSegments`: rules, BM25, and file relatedness infer boundaries from a historical Session.
- `activeOverlay`: a user-confirmed correction of offline boundaries.

Every trace has the same `task_diff` descriptor. Runtime tasks set `available: true` and reference `diffs/*.diff`; offline tasks set `available: false` with nullable evidence fields. Runtime `task.json` and `task.diff` are staging evidence, not a second Dataset format.

## Validator

Use `validate_dataset_path(path)` for a Dataset directory or an existing tar/tar.gz package. Use `validate_dataset(files, directories=None)` when a caller already has a relative-path-to-bytes map.

The validator checks required files, JSON/JSONL parsing, `manifest.schema_version`, manifest counts, dataset row to trace references, change/patch semantics, and available `task_diff` file references. It does not score tasks or run tests.

## Change Evidence

`extract_change_evidence(events, agent)` reads only task-scoped normalized events and returns Dataset trace `changes` and `patches`.

Agent mappings:

- Claude Code `Edit` / `MultiEdit`: `source=claude_edit`, `kind=edit`, `confidence=medium`, stores `old_string` / `new_string`, no patch.
- Claude Code `Write`: `source=claude_write`, `kind=write`, `confidence=medium`, stores `content`, no patch.
- Claude Code or generic `Bash.command`: `source=bash_command`, `kind=command`, `confidence=low`, no patch.
- OpenCode `oldString` / `newString`: `source=opencode_edit`, `kind=edit`, `confidence=medium`, no patch unless a real diff is present.
- OpenCode `metadata.diff` / `metadata.filediff`: patch `format=opencode_diff`, `confidence=high`, plus a referencing change.
- OpenCode `apply_patch.patchText`: patch `format=apply_patch`, `source=opencode_patch`, `confidence=high`, plus a referencing change.
- Codex `patch_apply_end.changes[path].unified_diff`: patch `format=unified_diff`, `source=codex_patch_apply_end`, `confidence=high`, plus a referencing change.
- Codex new file `content`: change evidence with `source=codex_patch_apply_end`; a patch is only emitted when `unified_diff` exists.

No evidence extractor reads the current repo, runs `git diff`, or guesses missing patch text. The Dataset builder calls this extractor after slicing events to a single task boundary, so evidence cannot cross task boundaries.

The validator now checks change and patch entry schemas, allowed `kind` / `format` / `confidence` values, and non-null `patch_id` references within the same trace.

## Follow-Up Integration Points

- `extract-dataset-change-evidence` populates trace `changes` and `patches` from task-scoped evidence.
- `save-and-export-task-dataset-from-viewer` can call the builder, write a Dataset directory, and run the validator before exposing save/download UI.
