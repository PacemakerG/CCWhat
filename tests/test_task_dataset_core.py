"""Tests for Task Dataset v1 builder and validator."""

from __future__ import annotations

import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from ccwhat.task_dataset import (
    DATASET_SCHEMA_VERSION,
    DatasetBuildError,
    TaskDiffEvidence,
    build_dataset_bundle,
    validate_dataset,
    validate_dataset_path,
)
from ccwhat.task_segments.models import (
    EvidenceBundle,
    NormalizedEvent,
    TaskSegment,
    TaskSegmentationResult,
)


def _event(
    event_id: str,
    event_type: str,
    text: str = "",
    tool_name: str | None = None,
    command: str | None = None,
    files: list[str] | None = None,
    turn_index: int = 1,
    raw_ref: dict | None = None,
    metadata: dict | None = None,
) -> NormalizedEvent:
    return NormalizedEvent(
        event_id=event_id,
        source="main",
        agent_id="main",
        turn_index=turn_index,
        event_type=event_type,
        text=text,
        tool_name=tool_name,
        command=command,
        files=files or [],
        timestamp=f"2026-01-01T00:00:{turn_index:02d}Z",
        raw_ref=raw_ref or {},
        metadata=metadata or {},
    )


def _fixture(agent: str) -> tuple[dict, list[NormalizedEvent], TaskSegmentationResult]:
    events = [
        _event("main:1", "user_message", f"Implement one {agent} task", turn_index=1),
        _event("main:2", "tool_call", "src/app.py", tool_name="Read", files=["/repo/src/app.py"], turn_index=1),
        _event("main:3", "tool_call", "edit", tool_name="Edit", files=["/repo/src/app.py"], turn_index=1),
        _event("main:4", "tool_call", command="pytest tests/test_app.py", tool_name="Bash", turn_index=1),
        _event("main:5", "assistant_text", "Implementation complete and all tests pass.", turn_index=1),
        _event("main:6", "user_message", "A later task outside the first trace", turn_index=2),
    ]
    task = TaskSegment(
        task_id="task-001",
        title="任务 1",
        task_type="feature",
        status="unevaluated",
        start_event_id="main:1",
        end_event_id="main:5",
        evidence=EvidenceBundle(
            files_read=["src/app.py"],
            files_changed=["src/app.py"],
            commands=["pytest tests/test_app.py"],
            test_commands=["pytest tests/test_app.py"],
            final_claims=["Implementation complete and all tests pass."],
        ),
        final_claim="Implementation complete and all tests pass.",
    )
    segmentation = TaskSegmentationResult(session_id=f"{agent}-session", tasks=[task])
    metadata = {
        "agent": agent,
        "project_dir": "/repo",
        "repo": "CCWhat",
        "base_commit": None,
        "head_commit": None,
        "git_dirty_at_export": None,
    }
    return metadata, events, segmentation


def _bundle(agent: str = "codex"):
    metadata, events, segmentation = _fixture(agent)
    return build_dataset_bundle(
        session_metadata=metadata,
        events=events,
        segmentation=segmentation,
        created_at="2026-06-14T00:00:00Z",
    )


class TestTaskDatasetBuilder(unittest.TestCase):
    def test_builds_dataset_item_trace_and_serialized_files(self) -> None:
        bundle = _bundle("codex")

        self.assertEqual(bundle.manifest["schema_version"], DATASET_SCHEMA_VERSION)
        self.assertEqual(bundle.manifest["counts"], {"dataset_items": 1, "traces": 1, "scores": 0})
        self.assertEqual(len(bundle.dataset_rows), 1)

        row = bundle.dataset_rows[0]
        self.assertEqual(row["id"], "task-001")
        self.assertEqual(row["input"]["instruction"], "Implement one codex task")
        self.assertIsNone(row["input"]["base_commit"])
        self.assertIsNone(row["expected"]["success_criteria"])
        self.assertEqual(row["expected"]["tests"], ["pytest tests/test_app.py"])
        self.assertEqual(row["metadata"]["trace_id"], "trace-task-001")
        self.assertEqual(row["metadata"]["trace_path"], "traces/trace-task-001.json")
        self.assertEqual(row["metadata"]["start_event_id"], "main:1")
        self.assertEqual(row["metadata"]["end_event_id"], "main:5")

        trace = bundle.traces["trace-task-001"]
        self.assertEqual(trace["task_id"], row["id"])
        self.assertEqual([event["event_id"] for event in trace["events"]], ["main:1", "main:2", "main:3", "main:4", "main:5"])
        self.assertEqual(trace["commands"], ["pytest tests/test_app.py"])
        self.assertEqual(trace["test_commands"], ["pytest tests/test_app.py"])
        self.assertEqual(trace["files"]["read"], ["src/app.py"])
        self.assertEqual(trace["files"]["changed"], ["src/app.py"])
        self.assertEqual(len(trace["changes"]), 1)
        self.assertEqual(trace["changes"][0]["kind"], "command")
        self.assertEqual(trace["changes"][0]["source"], "bash_command")
        self.assertEqual(trace["changes"][0]["patch_id"], None)
        self.assertEqual(trace["patches"], [])
        self.assertEqual(trace["repo_state"]["base_commit"], None)
        self.assertEqual(trace["repo_state"]["head_commit"], None)
        self.assertEqual(trace["task_diff"], {
            "available": False,
            "source": None,
            "confidence": None,
            "path": None,
        })

        text_files = bundle.to_text_files()
        self.assertIn("manifest.json", text_files)
        self.assertIn("dataset.jsonl", text_files)
        self.assertIn("scores.jsonl", text_files)
        self.assertIn("traces/trace-task-001.json", text_files)
        self.assertEqual(text_files["scores.jsonl"], "")

    def test_runtime_diff_uses_same_schema_and_adds_diff_file(self) -> None:
        metadata, events, segmentation = _fixture("codex")
        diff = "diff --git a/src/app.py b/src/app.py\n-old\n+new\n"

        bundle = build_dataset_bundle(
            session_metadata=metadata,
            events=events,
            segmentation=segmentation,
            task_source="runtimeTasks",
            task_diffs={"task-001": TaskDiffEvidence(content=diff)},
            created_at="2026-06-14T00:00:00Z",
        )

        trace = bundle.traces["trace-task-001"]
        self.assertEqual(trace["task_diff"], {
            "available": True,
            "source": "isolated_git_index",
            "confidence": "high",
            "path": "diffs/trace-task-001.diff",
        })
        self.assertEqual(bundle.to_text_files()["diffs/trace-task-001.diff"], diff)
        self.assertTrue(validate_dataset(bundle.to_bytes_files()).ok)

    def test_end_event_none_extends_to_session_end(self) -> None:
        metadata, events, segmentation = _fixture("claude")
        segmentation.tasks[0].end_event_id = None

        bundle = build_dataset_bundle(
            session_metadata=metadata,
            events=events,
            segmentation=segmentation,
            created_at="2026-06-14T00:00:00Z",
        )

        row = bundle.dataset_rows[0]
        trace = bundle.traces[row["metadata"]["trace_id"]]
        self.assertIsNone(row["metadata"]["end_event_id"])
        self.assertEqual(trace["events"][-1]["event_id"], "main:6")

    def test_clear_errors_for_invalid_boundaries_and_empty_tasks(self) -> None:
        metadata, events, segmentation = _fixture("opencode")

        empty = TaskSegmentationResult(session_id="empty", tasks=[])
        with self.assertRaisesRegex(DatasetBuildError, "task list is empty"):
            build_dataset_bundle(session_metadata=metadata, events=events, segmentation=empty)

        segmentation.tasks[0].start_event_id = "missing"
        with self.assertRaisesRegex(DatasetBuildError, "start_event_id"):
            build_dataset_bundle(session_metadata=metadata, events=events, segmentation=segmentation)


class TestTaskDatasetFixtures(unittest.TestCase):
    def test_claude_fixture_validates(self) -> None:
        result = validate_dataset(_bundle("claude").to_bytes_files())
        self.assertTrue(result.ok, result.errors)

    def test_codex_fixture_validates(self) -> None:
        result = validate_dataset(_bundle("codex").to_bytes_files())
        self.assertTrue(result.ok, result.errors)

    def test_opencode_fixture_validates(self) -> None:
        result = validate_dataset(_bundle("opencode").to_bytes_files())
        self.assertTrue(result.ok, result.errors)


class TestTaskDatasetValidator(unittest.TestCase):
    def test_valid_directory_and_tar_package(self) -> None:
        bundle = _bundle()

        with tempfile.TemporaryDirectory() as tmp:
            dataset_dir = Path(tmp) / "ccwhat-dataset"
            bundle.write_to_directory(dataset_dir)
            dir_result = validate_dataset_path(dataset_dir)
            self.assertTrue(dir_result.ok, dir_result.errors)
            self.assertEqual(dir_result.counts, {"dataset_items": 1, "traces": 1, "scores": 0})

            tar_path = Path(tmp) / "dataset.tar.gz"
            with tarfile.open(tar_path, "w:gz") as tar:
                tar.add(dataset_dir, arcname="ccwhat-dataset")
            tar_result = validate_dataset_path(tar_path)
            self.assertTrue(tar_result.ok, tar_result.errors)
            self.assertEqual(tar_result.counts, {"dataset_items": 1, "traces": 1, "scores": 0})

    def test_missing_required_file(self) -> None:
        files = _bundle().to_bytes_files()
        files.pop("scores.jsonl")
        result = validate_dataset(files)
        self.assertFalse(result.ok)
        self.assertTrue(any(issue.path == "scores.jsonl" for issue in result.errors))

    def test_bad_jsonl_reports_path_and_line(self) -> None:
        files = _bundle().to_bytes_files()
        files["dataset.jsonl"] = b'{"ok": true}\nnot-json\n'
        result = validate_dataset(files)
        self.assertFalse(result.ok)
        self.assertTrue(any(issue.path == "dataset.jsonl" and issue.line == 2 for issue in result.errors))

    def test_trace_reference_missing(self) -> None:
        files = _bundle().to_bytes_files()
        files.pop("traces/trace-task-001.json")
        result = validate_dataset(files, directories={"traces/"})
        self.assertFalse(result.ok)
        self.assertTrue(any("missing trace path" in issue.message for issue in result.errors))

    def test_runtime_diff_reference_missing(self) -> None:
        metadata, events, segmentation = _fixture("codex")
        bundle = build_dataset_bundle(
            session_metadata=metadata,
            events=events,
            segmentation=segmentation,
            task_diffs={"task-001": TaskDiffEvidence(content="")},
        )
        files = bundle.to_bytes_files()
        files.pop("diffs/trace-task-001.diff")

        result = validate_dataset(files)

        self.assertFalse(result.ok)
        self.assertTrue(any("missing task diff path" in issue.message for issue in result.errors))

    def test_task_id_mismatch(self) -> None:
        files = _bundle().to_bytes_files()
        trace = json.loads(files["traces/trace-task-001.json"])
        trace["task_id"] = "other-task"
        files["traces/trace-task-001.json"] = json.dumps(trace).encode("utf-8")

        result = validate_dataset(files)
        self.assertFalse(result.ok)
        self.assertTrue(any("does not match" in issue.message for issue in result.errors))

    def test_counts_mismatch(self) -> None:
        files = _bundle().to_bytes_files()
        manifest = json.loads(files["manifest.json"])
        manifest["counts"]["dataset_items"] = 2
        files["manifest.json"] = json.dumps(manifest).encode("utf-8")

        result = validate_dataset(files)
        self.assertFalse(result.ok)
        self.assertTrue(any(issue.field == "counts.dataset_items" for issue in result.errors))

    def test_manifest_missing_required_field_fails_even_when_counts_match(self) -> None:
        files = _bundle().to_bytes_files()
        manifest = json.loads(files["manifest.json"])
        manifest.pop("created_at")
        files["manifest.json"] = json.dumps(manifest).encode("utf-8")

        result = validate_dataset(files)
        self.assertFalse(result.ok)
        self.assertTrue(
            any(issue.path == "manifest.json" and issue.field == "created_at" for issue in result.errors),
            result.errors,
        )

    def test_dataset_row_missing_required_field_fails_even_when_trace_matches(self) -> None:
        files = _bundle().to_bytes_files()
        row = json.loads(files["dataset.jsonl"])
        row["expected"].pop("success_criteria")
        files["dataset.jsonl"] = (json.dumps(row) + "\n").encode("utf-8")

        result = validate_dataset(files)
        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                issue.path == "dataset.jsonl"
                and issue.field == "expected.success_criteria"
                for issue in result.errors
            ),
            result.errors,
        )

    def test_trace_missing_required_field_fails_even_when_reference_matches(self) -> None:
        files = _bundle().to_bytes_files()
        trace = json.loads(files["traces/trace-task-001.json"])
        trace["files"].pop("changed")
        files["traces/trace-task-001.json"] = json.dumps(trace).encode("utf-8")

        result = validate_dataset(files)
        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                issue.path == "traces/trace-task-001.json"
                and issue.field == "files.changed"
                for issue in result.errors
            ),
            result.errors,
        )

    def test_change_missing_required_field(self) -> None:
        files = _bundle().to_bytes_files()
        trace = json.loads(files["traces/trace-task-001.json"])
        trace["changes"][0].pop("change_id")
        files["traces/trace-task-001.json"] = json.dumps(trace).encode("utf-8")

        result = validate_dataset(files)
        self.assertFalse(result.ok)
        self.assertTrue(any(issue.field == "changes[0].change_id" for issue in result.errors), result.errors)

    def test_change_invalid_enum(self) -> None:
        files = _bundle().to_bytes_files()
        trace = json.loads(files["traces/trace-task-001.json"])
        trace["changes"][0]["kind"] = "magic"
        files["traces/trace-task-001.json"] = json.dumps(trace).encode("utf-8")

        result = validate_dataset(files)
        self.assertFalse(result.ok)
        self.assertTrue(any(issue.field == "changes[0].kind" for issue in result.errors), result.errors)

    def test_patch_missing_required_field(self) -> None:
        files = _bundle().to_bytes_files()
        trace = json.loads(files["traces/trace-task-001.json"])
        trace["patches"] = [{
            "patch_id": "patch-001",
            "scope": "step",
            "file": "src/app.py",
            "source": "codex_patch_apply_end",
            "format": "unified_diff",
            "confidence": "high",
        }]
        trace["changes"][0]["patch_id"] = "patch-001"
        files["traces/trace-task-001.json"] = json.dumps(trace).encode("utf-8")

        result = validate_dataset(files)
        self.assertFalse(result.ok)
        self.assertTrue(any(issue.field == "patches[0].patch" for issue in result.errors), result.errors)

    def test_patch_invalid_enum(self) -> None:
        files = _bundle().to_bytes_files()
        trace = json.loads(files["traces/trace-task-001.json"])
        trace["patches"] = [{
            "patch_id": "patch-001",
            "scope": "step",
            "file": "src/app.py",
            "source": "codex_patch_apply_end",
            "format": "invented",
            "confidence": "high",
            "patch": "@@\n-old\n+new\n",
        }]
        trace["changes"][0]["patch_id"] = "patch-001"
        files["traces/trace-task-001.json"] = json.dumps(trace).encode("utf-8")

        result = validate_dataset(files)
        self.assertFalse(result.ok)
        self.assertTrue(any(issue.field == "patches[0].format" for issue in result.errors), result.errors)

    def test_patch_id_reference_missing(self) -> None:
        files = _bundle().to_bytes_files()
        trace = json.loads(files["traces/trace-task-001.json"])
        trace["changes"][0]["patch_id"] = "missing-patch"
        files["traces/trace-task-001.json"] = json.dumps(trace).encode("utf-8")

        result = validate_dataset(files)
        self.assertFalse(result.ok)
        self.assertTrue(any(issue.field == "changes[0].patch_id" for issue in result.errors), result.errors)

    def test_extra_unreferenced_trace_missing_required_field_fails_when_counts_match(self) -> None:
        files = _bundle().to_bytes_files()
        manifest = json.loads(files["manifest.json"])
        manifest["counts"]["traces"] = 2
        files["manifest.json"] = json.dumps(manifest).encode("utf-8")

        extra_trace = json.loads(files["traces/trace-task-001.json"])
        extra_trace["trace_id"] = "extra"
        extra_trace["task_id"] = "extra-task"
        extra_trace.pop("repo_state")
        files["traces/extra.json"] = json.dumps(extra_trace).encode("utf-8")

        result = validate_dataset(files)
        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                issue.path == "traces/extra.json"
                and issue.field == "repo_state"
                for issue in result.errors
            ),
            result.errors,
        )


class TestTaskDatasetScopeGuard(unittest.TestCase):
    def test_no_evaluator_or_cli_save_behavior_added(self) -> None:
        root = Path(__file__).resolve().parents[1]
        searched_files = [
            *Path(root, "ccwhat").rglob("*.py"),
        ]
        haystack = "\n".join(path.read_text(encoding="utf-8") for path in searched_files)
        self.assertNotIn("def save_dataset", haystack)
        self.assertNotIn("evaluate_dataset", haystack)

        bundle = _bundle()
        self.assertEqual(bundle.scores_rows, [])
        self.assertEqual(bundle.to_text_files()["scores.jsonl"], "")


class TestTaskDatasetValidatorInternalAPI(unittest.TestCase):
    def test_validate_dataset_accepts_tar_like_file_map(self) -> None:
        bundle = _bundle()
        result = validate_dataset(bundle.to_bytes_files())
        self.assertTrue(result.ok, result.errors)

    def test_tar_with_root_prefix_validates(self) -> None:
        bundle = _bundle()
        with tempfile.TemporaryDirectory() as tmp:
            tar_path = Path(tmp) / "prefixed.tar"
            with tarfile.open(tar_path, "w") as tar:
                for rel_path, content in bundle.to_bytes_files().items():
                    info = tarfile.TarInfo(f"ccwhat-dataset/{rel_path}")
                    info.size = len(content)
                    tar.addfile(info, io.BytesIO(content))
            result = validate_dataset_path(tar_path)
            self.assertTrue(result.ok, result.errors)
