"""Runtime task staging with task boundary diff."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

from ccwhat.runtime.core.index import CCWhatIndex
from ccwhat.runtime.infra.registry import RunRegistry, RuntimeRun, utc_now


class RuntimeTaskError(RuntimeError):
    pass


class TaskStaging:
    def __init__(self, registry: RunRegistry) -> None:
        self.registry = registry

    def start_task(self, run: RuntimeRun, title: str) -> dict[str, Any]:
        if run.active_task_id:
            raise RuntimeTaskError(f"task already recording: {run.active_task_id}")
        workspace = Path(run.workspace)
        self._ensure_git_workspace(workspace)
        task_id = self._next_task_id(run.run_id)
        task_dir = self._task_dir(run.run_id, task_id)
        task_dir.mkdir(parents=True, exist_ok=False)

        index = CCWhatIndex(workspace)
        index.init()
        start_tree = index.write_tree()

        task = {
            "schema": "ccwhat-runtime-task-v1",
            "task_id": task_id,
            "run_id": run.run_id,
            "agent": run.agent,
            "workspace": run.workspace,
            "title": title,
            "status": "recording",
            "started_at": utc_now(),
            "finished_at": None,
            "start_tree": start_tree,
            "end_tree": None,
            "paths": {"task_diff": "task.diff"},
        }
        self._write_json(task_dir / "task.json", task)
        self.registry.set_active_task(run.run_id, task_id)
        return task

    def finish_task(self, run: RuntimeRun) -> dict[str, Any]:
        if not run.active_task_id:
            raise RuntimeTaskError("no active task to finish")
        workspace = Path(run.workspace)
        self._ensure_git_workspace(workspace)
        task_dir = self._task_dir(run.run_id, run.active_task_id)
        task = self._read_json(task_dir / "task.json")

        index = CCWhatIndex(workspace)
        index.init()
        index.sync_workspace()
        end_tree = index.write_tree()

        diff = index.diff_cached(task["start_tree"])
        (task_dir / "task.diff").write_text(diff, encoding="utf-8")

        task["finished_at"] = utc_now()
        task["end_tree"] = end_tree
        task["status"] = "finalized"
        self._write_json(task_dir / "task.json", task)
        self.registry.set_active_task(run.run_id, None)
        return task

    def abort_task(self, run: RuntimeRun) -> dict[str, Any]:
        if not run.active_task_id:
            raise RuntimeTaskError("no active task to abort")
        task_dir = self._task_dir(run.run_id, run.active_task_id)
        task = self._read_json(task_dir / "task.json")
        task["finished_at"] = utc_now()
        task["status"] = "aborted"
        self._write_json(task_dir / "task.json", task)
        self.registry.set_active_task(run.run_id, None)
        return task

    def status(self, run: RuntimeRun) -> dict[str, Any]:
        return {
            "run_id": run.run_id,
            "status": "recording" if run.active_task_id else "idle",
            "active_task_id": run.active_task_id,
        }

    def _next_task_id(self, run_id: str) -> str:
        tasks_dir = self.registry.run_dir(run_id) / "tasks"
        existing = sorted(tasks_dir.glob("task-*")) if tasks_dir.exists() else []
        return f"task-{len(existing) + 1:03d}"

    def _task_dir(self, run_id: str, task_id: str) -> Path:
        return self.registry.run_dir(run_id) / "tasks" / task_id

    def _ensure_git_workspace(self, workspace: Path) -> None:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=workspace,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0 or result.stdout.strip() != "true":
            raise RuntimeTaskError(f"workspace is not a git repository: {workspace}")

    def _read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
