## 1. task.json schema 精简

- [ ] 1.1 重写 `start_task`：task.json 只写 `task_id`、`run_id`、`agent`、`workspace`、`started_at`、`start_tree`；不再写 `schema`、`title`、`status`、`git`、`instruction`、`success_criteria`、`expected_tests`、`paths`、`evidence_availability`。
- [ ] 1.2 重写 `finish_task`：补写 `finished_at`、`end_tree`；不再写 `git.after_commit`、`paths`、`evidence_availability`、`instruction`、`expected_tests`。
- [ ] 1.3 `abort_task` 同步精简：只补 `finished_at`，不再写 `status` / `git`。
- [ ] 1.4 删除 `staging._task_title` 等仅服务旧 schema 的辅助方法。

## 2. task 边界 diff 实现

- [ ] 2.1 `CCWhatIndex.init`：保留 `read-tree HEAD` + `sync_workspace`，作为 start 时 baseline。
- [ ] 2.2 `start_task` 调 `index.write_tree()` 得到 `start_tree`，存入 task.json。
- [ ] 2.3 `finish_task` 调 `index.sync_workspace()` 同步当前工作树，再 `write_tree()` 得到 `end_tree`，存入 task.json。
- [ ] 2.4 `finish_task` 调 `index.diff_cached(start_tree)` 生成 `task.diff`，写入 `tasks/<task-id>/task.diff`。
- [ ] 2.5 `task.diff` 为空时仍写入空文件（保持产物固定），或跳过写入并在 task.json 留 `task.diff` 字段为 null——选其一并写测试覆盖。

## 3. CCWhatIndex 精简

- [ ] 3.1 删除 `add`、`remove`、`reconcile_deletions`、`diff_working`、`diff_step`、`get_tree_hash` 方法。
- [ ] 3.2 保留 `init`、`sync_workspace`、`write_tree`、`diff_cached`；新增 `diff_cached(tree)` 方法（对比 isolated index 与指定 tree）。
- [ ] 3.3 移除 `_git_cmd` 中仅服务已删方法使用的分支（如有）。
- [ ] 3.4 确保所有保留方法仍带 `GIT_INDEX_FILE` 环境变量，零污染用户 index。

## 4. 删除 step-by-step 机制

- [ ] 4.1 删除 `staging.record_step`、`staging.sync_step`、`staging.remove_step` 方法。
- [ ] 4.2 删除 `staging._diff_buffer`、`staging._prev_tree` 实例字段。
- [ ] 4.3 删除 `staging._current_task_dir` 字段（如不再需要）。
- [ ] 4.4 删除 `finish_task` 中的 unattributed fallback 逻辑。
- [ ] 4.5 删除 `ccwhat/runtime/core/models.py` 的 `StepDiff`、`StepDiffBuffer`；若文件无其他内容则整个删除。

## 5. 删除 trace_extractor

- [ ] 5.1 删除 `ccwhat/runtime/core/trace_extractor.py` 整个文件。
- [ ] 5.2 移除 `staging.py` 顶部对 `extract_task_trace` 的 import。
- [ ] 5.3 移除 `finish_task` 中调用 `extract_task_trace` 及写 `task_trace.json` 的整段逻辑。
- [ ] 5.4 移除 `finish_task` 中从 trace 补充 `instruction` / `expected_tests` 的逻辑。

## 6. Controller 精简

- [ ] 6.1 `do_POST` action 白名单移除 `step`。
- [ ] 6.2 删除 `_handle` 中 `action == "step"` 分支及 `staging.sync_step` / `remove_step` / `record_step` 调用。
- [ ] 6.3 保留 `start` / `finish` / `abort` / `status` 四个 action。

## 7. Claude integration 精简

- [ ] 7.1 删除 `integrations/claude.py` 的 `_install_posttooluse_hook` 函数。
- [ ] 7.2 `install_claude_integration` 不再调用 `_install_posttooluse_hook`。
- [ ] 7.3 升级逻辑：检测并删除既有 `.claude/hooks/ccwhat-diff-hook.sh` 文件。
- [ ] 7.4 升级逻辑：从 `.claude/settings.local.json` 的 `hooks.PostToolUse` 移除 `ccwhat-diff-hook.sh` 条目；若 PostToolUse 列表为空则移除整个 key。
- [ ] 7.5 不再生成 `ccwhat-diff-hook.sh` 文件。

## 8. OpenCode integration 精简

- [ ] 8.1 删除 `_plugin_content()` 中 `tool.execute.after` 整段。
- [ ] 8.2 删除 `detectFileOperation` 函数。
- [ ] 8.3 plugin 只保留 `command.execute.before` 用于 start/finish boundary。
- [ ] 8.4 `_plugin_content` 不再引用 `CCWHAT_ENABLED` 环境变量（如仅 `tool.execute.after` 使用）。

## 9. 测试更新

- [ ] 9.1 移除 `tests/test_runtime_recording.py` 中 step-by-step / `/step` endpoint 相关测试。
- [ ] 9.2 移除 `task_trace.json` 存在性断言。
- [ ] 9.3 移除 `diff.patch` 存在性断言。
- [ ] 9.4 移除 `instruction` / `expected_tests` / `evidence_availability` 字段断言。
- [ ] 9.5 新增测试：start 后 task.json 含 `start_tree`，无 `end_tree`。
- [ ] 9.6 新增测试：finish 后 task.json 含 `finished_at` 和 `end_tree`，`task.diff` 文件存在。
- [ ] 9.7 新增测试：task 期间 Write 文件，`task.diff` 包含该文件改动，且 diff 只含 task 边界内改动（不混 start 前 dirty）。
- [ ] 9.8 新增测试：task 期间 Bash 改文件（mv/sed/echo >），`task.diff` 包含这些改动。
- [ ] 9.9 新增测试：untracked 文件被纳入 `task.diff`。
- [ ] 9.10 新增测试：用户 `.git/index` 在 task 前后保持不变（隔离验证）。
- [ ] 9.11 新增测试：Claude integration install 后 `settings.local.json` 不含 PostToolUse hook。
- [ ] 9.12 新增测试：升级场景下，既有 `ccwhat-diff-hook.sh` 和 PostToolUse 条目被清理。

## 10. 文档与验收

- [ ] 10.1 更新 `README.md` / `docs/` 中 runtime dataset 产物说明（如涉及）。
- [ ] 10.2 手工验收：`ccwhat -- opencode` 起一个 task，确认产物只有 `task.json` + `task.diff`。
- [ ] 10.3 手工验收：`ccwhat -- claude` 起一个 task，确认 `.claude/settings.local.json` 无 PostToolUse hook。
- [ ] 10.4 手工验收：task 期间改文件后 `git status` 不受 runtime 影响（隔离验证）。
