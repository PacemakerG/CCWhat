# runtime-task-recording Specification

## Purpose
TBD - created by archiving change add-runtime-task-recording-mvp. Update Purpose after archive.

## Requirements
### Requirement: Runtime run registry
系统 SHALL 在每次 `ccwhat -- claude` 启动时创建独立 runtime run，并将 run metadata 写入 `~/.ccwhat/runtime-runs/<run-id>/run.json`。

#### Scenario: 创建独立 run
- **WHEN** 用户执行 `ccwhat -- claude`
- **THEN** 系统 SHALL 创建唯一 `run_id`
- **AND** 系统 SHALL 写入 `run.json`
- **AND** `run.json` SHALL 记录 agent、workspace、started_at、status、agent_process、proxy、viewer、control 和 active_task_id

#### Scenario: 多个 run 并发
- **WHEN** 用户在两个终端分别执行 `ccwhat -- claude`
- **THEN** 系统 SHALL 为两个进程创建不同 `run_id`
- **AND** 两个 run SHALL 写入不同 runtime run 目录
- **AND** 两个 run SHALL 不共享 active_task_id

### Requirement: Runtime ports are allocated per run
系统 SHALL 在未显式指定端口时为每个 runtime run 自动分配可用 proxy、viewer 和 control 端口。

#### Scenario: 自动分配端口
- **WHEN** 用户执行 `ccwhat -- claude` 且未传入 `--port` 或 `--web-port`
- **THEN** 系统 SHALL 自动选择可用 proxy 端口
- **AND** 系统 SHALL 自动选择可用 viewer 端口
- **AND** 系统 SHALL 自动选择可用 control 端口
- **AND** 最终端口 SHALL 写入 `run.json`

#### Scenario: 保留显式端口
- **WHEN** 用户执行 `ccwhat --port 7790 --web-port 7791 -- claude`
- **THEN** 系统 SHALL 使用用户指定的 proxy 和 viewer 端口
- **AND** 系统 SHALL 在端口不可用时报错

### Requirement: Runtime controller supports task commands
系统 SHALL 为每个 runtime run 启动本地 controller，支持 Task start、finish、status 和 abort。

#### Scenario: Start task through controller
- **WHEN** controller 收到 `start` 命令和 task title
- **THEN** 系统 SHALL 创建新的 task_id
- **AND** 系统 SHALL 将 `run.json.active_task_id` 更新为该 task_id
- **AND** 系统 SHALL 在该 run 的 `tasks/<task-id>/` 下创建 task staging

#### Scenario: Finish task through controller
- **WHEN** controller 收到 `finish` 命令且存在 active task
- **THEN** 系统 SHALL finalize active task
- **AND** 系统 SHALL 将 `run.json.active_task_id` 置为 null

#### Scenario: Reject finish without active task
- **WHEN** controller 收到 `finish` 命令但不存在 active task
- **THEN** 系统 SHALL 返回明确错误
- **AND** 系统 SHALL NOT 创建新的 task staging

### Requirement: Runtime task staging 捕获 task 边界 diff
系统 SHALL 在 Task start 时记录工作树快照（`start_tree`），在 Task finish 时记录当前工作树快照（`end_tree`），并将两者 diff 写入 `tasks/<task-id>/task.diff`。系统 SHALL NOT 保存 repo before/after tarball、step-by-step `diff.patch`、或 `task_trace.json`。

#### Scenario: Start 记录 start_tree
- **WHEN** controller 成功执行 `start`
- **THEN** 系统 SHALL 创建 `tasks/<task-id>/task.json`
- **AND** `task.json` SHALL 包含 `task_id`、`run_id`、`agent`、`workspace`、`started_at`、`start_tree`
- **AND** `start_tree` SHALL 为 isolated git index（`.git/index.ccwhat`）在 read-tree HEAD + sync 工作树后的 `write-tree` 结果
- **AND** `task.json` SHALL NOT 包含 `instruction`、`success_criteria`、`expected_tests`、`paths`、`evidence_availability`、`git`、`schema`、`title`、`status` 字段

#### Scenario: Finish 写入 task.diff 和 end_tree
- **WHEN** controller 成功执行 `finish`
- **THEN** 系统 SHALL 将 isolated index 同步为当前工作树状态
- **AND** 系统 SHALL 调 `write-tree` 得到 `end_tree`，写入 `task.json`
- **AND** 系统 SHALL 调 `git diff --cached --binary <start_tree>` 生成 `task.diff`，写入 `tasks/<task-id>/task.diff`
- **AND** `task.json` SHALL 补写 `finished_at` 和 `end_tree`
- **AND** 系统 SHALL NOT 创建 `diff.patch`、`diff_total.patch`、`task_trace.json`、`repo_before.tar.gz`、`repo_after.tar.gz`

#### Scenario: task.diff 只含 task 边界内改动
- **WHEN** task 开始前工作树存在 dirty 改动（如 `uv.lock` 已修改）
- **AND** task 期间未触碰该文件
- **THEN** `task.diff` SHALL NOT 包含该 dirty 文件的改动
- **AND** `task.diff` SHALL 只包含 start 命令到 finish 命令之间工作树发生的变化

#### Scenario: task 期间 git commit 不影响 task.diff
- **WHEN** 用户在 task 中途执行 `git commit`
- **AND** commit 未改变工作树文件内容
- **THEN** `task.diff` SHALL NOT 因 commit 而新增改动
- **AND** `task.diff` 仍只反映工作树实际文件内容的变化

#### Scenario: untracked 文件被纳入 task.diff
- **WHEN** task 期间新建一个 untracked 文件
- **THEN** `task.diff` SHALL 包含该新文件的 diff
- **AND** 用户的 `git status` SHALL 不受 runtime add 影响

#### Scenario: Non-git workspace is rejected
- **WHEN** 用户在非 git workspace 中通过 controller 执行 `start`
- **THEN** 系统 SHALL 返回明确错误
- **AND** 系统 SHALL NOT 创建 task staging

### Requirement: Runtime git index 隔离
系统 SHALL 使用 isolated git index 文件（`.git/index.ccwhat`）进行所有 task diff 相关的 git 操作，SHALL NOT 读写用户的 `.git/index` 或修改工作树文件。

#### Scenario: 用户 git index 零污染
- **WHEN** runtime 执行 start / finish / abort
- **THEN** 所有 git 命令 SHALL 通过 `GIT_INDEX_FILE=.git/index.ccwhat` 环境变量操作 isolated index
- **AND** 用户的 `git status` 输出 SHALL 与 runtime 未运行时一致
- **AND** 用户的 `git add` / `git commit` 暂存区 SHALL 不受 runtime 影响

#### Scenario: 工作树只读
- **WHEN** runtime 执行 start / finish
- **THEN** 系统 SHALL NOT 写入、删除、移动工作树中的任何文件
- **AND** 系统 SHALL 只通过 `git add`（读文件内容写入 isolated index）读取工作树状态

### Requirement: Runtime control evidence is recorded
系统 SHALL 为每次 CCWhat Task 控制命令写入 control event，并记录该命令是否对模型可见。

#### Scenario: Local command records high confidence evidence
- **WHEN** Claude Code slash command 被本地拦截并成功调用 controller
- **THEN** 系统 SHALL 在 `control_events.jsonl` 写入 command、raw_args、agent、integration、model_visible、agent_log_visible 和 confidence
- **AND** model_visible SHALL 为 false
- **AND** confidence SHALL 为 high
