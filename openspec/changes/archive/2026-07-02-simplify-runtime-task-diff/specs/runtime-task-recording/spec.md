## MODIFIED Requirements

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

## REMOVED Requirements

### Requirement: task.json 记录任务语义字段
`task.json` SHALL 在创建时写入任务语义字段，供诊断引擎理解任务意图。

#### Scenario: instruction 字段从 control event 提取
- **WHEN** `start` 命令包含非空 title
- **THEN** `task.json.instruction` SHALL 记录该 title 作为任务描述
- **AND** `task.json.expected_tests` SHALL 初始化为空列表
- **AND** `task.json.success_criteria` SHALL 初始化为 null

#### Scenario: instruction 字段在 finish 时可从 trace 补充
- **WHEN** `task_trace.json` 提取成功且 session 首条 user_message 不为空
- **THEN** 系统 SHALL 用 session 首条 user_message 更新 `task.json.instruction`（若比 title 更详细）
- **AND** 系统 SHALL 用 `task_trace.test_commands` 更新 `task.json.expected_tests`

**Rationale:** 任务语义字段（instruction / success_criteria / expected_tests）从事后原始日志抽取更可靠，runtime 路径不再记录。`task.json` 精简为边界元数据 + git tree 锚点，供事后抽取关联。
