## Why

当前 runtime task recording 试图同时抓三件事：task 边界 git diff、step-by-step 增量 diff、Agent 行为轨迹（`task_trace.json`）。实际验证下来：

- **step-by-step diff 不可靠**：依赖 PostToolUse hook（Claude）/ `tool.execute.after` plugin（OpenCode）实时触发，但 plugin 偶发不加载、fetch 异步无确认、fire-and-forget curl 易丢，导致 Write/Edit 步骤整段丢失。靠 `finish_task` 的 unattributed fallback 兜底能保完整，但丢 step 级归因。
- **`task_trace.json` 是事后抽取的重复产物**：`trace_extractor` 从事后日志抽取的事件流和离线 `task_dataset` builder 同源，runtime 路径里再抽一次既无额外价值，又把 instruction 字段污染成 boundary marker。
- **`diff_total.patch` 不是真正的 task 边界 diff**：当前实现是 `working tree vs before_commit`（before_commit = start 时 HEAD），混入了 task 开始前的 dirty 改动。

runtime dataset 唯一不可替代的价值是 **git diff ground truth**，其余事件流/instruction/changes 都从事后日志抽取更靠谱。这个 change 把 runtime 产物砍到只剩 task 边界 diff + 边界元数据。

## What Changes

- `task.json` 精简为边界元数据：`task_id`、`run_id`、`agent`、`workspace`、`started_at`、`finished_at`、`start_tree`、`end_tree`。删掉 `instruction`、`success_criteria`、`expected_tests`、`paths`、`evidence_availability`、`git`、`schema`、`title`、`status`。
- `diff_total.patch` 改名为 `task.diff`，语义改为 **start 时工作树快照 → finish 时工作树快照** 的 diff（基于 isolated git index 的 `write-tree` 对比），不再混入 start 前 dirty 改动。
- 删掉 `diff.patch`（step-by-step 增量 diff）及其全部机制：`StepDiffBuffer`、`StepDiff`、`record_step`、`sync_step`、`remove_step`、`/step` controller endpoint、unattributed fallback。
- 删掉 `task_trace.json` 及 `trace_extractor` 整个模块：runtime 不再抽 Agent 行为轨迹，改由事后 dataset 导出时从原始日志抽取。
- 删掉 Claude `PostToolUse` hook 安装（`_install_posttooluse_hook`）和 `ccwhat-diff-hook.sh` 文件。
- 删掉 OpenCode plugin 的 `tool.execute.after` 整段，只保留 `command.execute.before` 用于 start/finish boundary。
- `CCWhatIndex` 精简：只保留 `init`（read-tree HEAD + sync 工作树）、`sync_workspace`、`write_tree`、`diff_cached(tree)`；删掉 `add`、`remove`、`reconcile_deletions`、`diff_working`、`diff_step`、`get_tree_hash` 等增量方法。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `runtime-task-recording`：task staging 产物从「repo 快照 + step diff + total diff + trace」简化为「task 边界 diff + 边界元数据」；task.json schema 精简；step-by-step 机制整体移除。

### Removed Capabilities

- `runtime-task-trace-enrichment`：runtime 不再在 finish 时抽取 Agent 行为轨迹，该职责移交事后 dataset 导出路径。

## Impact

- `ccwhat/runtime/core/staging.py`：`start_task` / `finish_task` / `abort_task` 重写，删 `record_step` / `sync_step` / `remove_step`。
- `ccwhat/runtime/core/models.py`：删 `StepDiff`、`StepDiffBuffer`，文件可能整个移除。
- `ccwhat/runtime/core/index.py`：精简 `CCWhatIndex` 到只支持 task 边界 diff 的方法集。
- `ccwhat/runtime/core/trace_extractor.py`：整个文件删除。
- `ccwhat/runtime/http/controller.py`：删 `/step` endpoint，`do_POST` action 白名单移除 `step`。
- `ccwhat/runtime/integrations/claude.py`：删 `_install_posttooluse_hook`，`install_claude_integration` 不再生成 PostToolUse 配置。
- `ccwhat/runtime/integrations/opencode.py`：plugin 内容删掉 `tool.execute.after` 整段。
- `.claude/hooks/ccwhat-diff-hook.sh`：不再由 integration 生成；已存在的文件需在升级时清理。
- `.claude/settings.local.json`：PostToolUse hook 条目需在升级时移除。
- `tests/test_runtime_recording.py`：移除 step-by-step / trace / diff.patch 相关断言，新增 task 边界 diff 断言。
- 既有 runtime run 目录（含 `diff.patch` / `task_trace.json`）不迁移，新代码只保证新 run 产出新 schema。
