## Context

当前 runtime task recording 的产物链路：

```
start_task
  └─ read-tree HEAD → isolated index baseline
  └─ write-tree → _prev_tree (baseline tree)
finish_task
  ├─ reconcile_deletions + sync_workspace → isolated index 同步当前工作树
  ├─ diff_working(_prev_tree) → trailing unattributed step (fallback)
  ├─ format_patch() → diff.patch (step-by-step, 含每步 tool_name)
  ├─ diff_working(before_commit) → diff_total.patch (working tree vs HEAD)
  └─ extract_task_trace() → task_trace.json (events/changes/patches)
```

实测痛点：

1. **step-by-step 靠 hook 实时触发，不可靠**：OpenCode plugin `tool.execute.after` 偶发不加载，Claude `ccwhat-diff-hook.sh` 是 fire-and-forget curl，丢步常态。fallback 能保 diff 完整但归因全丢。
2. **`task_trace.json` 与离线 dataset 同源重复**：`trace_extractor` 调的就是 `extract_evidence` + `extract_change_evidence`，离线 builder 也调这俩。runtime 抽一次没有额外信息量，反而把 `task.json.instruction` 污染成 boundary marker。
3. **`diff_total.patch` 语义错位**：`git diff HEAD`（working tree vs HEAD commit）混入了 task 开始前就存在的 dirty 改动，不是纯 task 边界 diff。
4. **step 与 trace events 无关联键**：diff.patch 的 step 只有 `timestamp`/`tool_name`/`file_path`，trace events 有 `event_id`/`tool_use_id`，两者只能靠 timestamp 模糊匹配，plugin 触发延迟导致错位。

核心判断：**runtime 唯一不可替代的价值是 git diff ground truth**。事件流、instruction、changes 从事后日志（cc jsonl / opencode sqlite / 抓包 jsonl）抽取更完整、可重放、可校验。runtime 不该再背这些。

## Goals / Non-Goals

**Goals：**

- runtime 产物只剩 2 个文件：`task.json`（边界元数据）+ `task.diff`（task 边界 git diff）。
- `task.diff` 语义精确为「start 时工作树状态 → finish 时工作树状态」，不含 task 开始前的 dirty 改动。
- git index 隔离：全程使用 `.git/index.ccwhat`，零污染用户 `.git/index` 和工作树。
- 砍掉所有 step-by-step 机制、trace 抽取、PostToolUse / `tool.execute.after` hook，降低 runtime 路径复杂度和故障面。
- task.json 提供事后抽取所需的关联键（`started_at` / `finished_at` / `workspace` / `agent`）。

**Non-Goals：**

- 不实现事后 dataset 导出路径（从原始日志 + 抓包文件抽取 trace）。那是后续 change。
- 不修改离线 `task_dataset` builder。
- 不修改 viewer / diagnosis 引擎。
- 不迁移既有 runtime run 目录的旧产物。
- 不改 runtime run registry / port allocation / controller 的 start/finish/abort/status 机制。

## Decisions

### Decision: task 边界 diff 用 isolated index 的 write-tree 对比

start 时：
1. `git read-tree HEAD`（isolated index 从 HEAD 初始化）
2. `git add -A`（把 start 时工作树含 dirty 全部同步进 isolated index）
3. `git write-tree` → `start_tree`（存入 task.json）

finish 时：
1. `git add -A`（isolated index 同步 finish 时工作树）
2. `git write-tree` → `end_tree`（存入 task.json）
3. `git diff --cached --binary <start_tree>` → `task.diff`

这样 `task.diff` 是纯 task 边界内改动，与 task 前 dirty 状态、task 中是否 commit 无关。

### Decision: 工作树共享、index 文件隔离

不复制工作树到独立目录（成本高、易漂移），而是共享用户工作树但隔离 index 文件：

- 所有 git 命令带 `GIT_INDEX_FILE=.git/index.ccwhat` 环境变量
- `git add -A` 只写 `.git/index.ccwhat`，不碰用户 `.git/index`
- 用户的 `git status` / `git add` / `git commit` 完全不受影响
- untracked 文件会被 add 进 isolated index（用于 diff），但用户 `git status` 看不到我们 add 过
- `.git/index.ccwhat` 在用户 `.git/` 下但 git 不认识，删掉对用户仓库零影响

工作树只读不改：我们只 `git add`（读文件内容写进 index），从不写磁盘文件。

### Decision: task.json 精简到边界元数据

只留事后抽取必需的关联键：

```json
{
  "task_id": "task-001",
  "run_id": "run-...",
  "agent": "opencode",
  "workspace": "/path/to/repo",
  "started_at": "2026-07-01T03:00:20.781884Z",
  "finished_at": "2026-07-01T03:02:25.614476Z",
  "start_tree": "abc123...",
  "end_tree": "def456..."
}
```

删掉的字段及理由：
- `schema` / `title` / `status`：内部状态，事后抽取不需要
- `git.before_commit` / `git.after_commit` / `git.before_status` / `git.after_status`：被 `start_tree` / `end_tree` 取代
- `instruction` / `success_criteria` / `expected_tests`：从事后日志抽取，不在 runtime 记
- `paths` / `evidence_availability`：产物固定为 `task.diff`，不需要 availability 标记

### Decision: 砍掉 trace_extractor，runtime 不抽 Agent 轨迹

`trace_extractor.extract_task_trace` 从事后日志抽 events/changes/patches，和离线 `task_dataset` builder 同源。runtime 路径不再调它，`task_trace.json` 不再产出。事后 dataset 导出时自行从原始日志抽取，可重放可校验。

### Decision: 砍掉 step-by-step 机制

`record_step` / `sync_step` / `remove_step` / `StepDiffBuffer` / `StepDiff` / `/step` endpoint / PostToolUse hook / `tool.execute.after` plugin 整体移除。step 级归因本就不可靠（hook 触发依赖 + 并发 race + fetch 延迟），砍掉后 runtime 只保 task 边界完整 diff，归因交给事后从日志反推。

### Decision: 升级时清理旧 hook 产物

`install_claude_integration` 升级时检测并移除既有 `ccwhat-diff-hook.sh` 文件和 `settings.local.json` 里的 PostToolUse 条目，避免残留 hook 调用已删除的 `/step` endpoint 报错。OpenCode plugin 文件由 `_write_managed` 覆盖更新，新版不含 `tool.execute.after`。

## Risks

- **失去 step 级归因**：用户不能再从 diff.patch 看每个 step 对应哪个 tool call。缓解：本就不可靠，且事后可从日志反推。
- **既有 runtime run 目录产物不一致**：旧 run 有 `diff.patch` / `task_trace.json` / `diff_total.patch`，新 run 只有 `task.diff` + `task.json`。缓解：不迁移，文档说明 schema 版本差异；viewer / diagnosis 如需兼容旧格式另行处理。
- **task 期间用户 git commit 的影响**：用户在 task 中途 `git commit`，commit 不改变工作树内容，所以 `task.diff`（基于 write-tree 对比工作树）不受影响。但如果用户 `git checkout` 切换分支会改变工作树，`task.diff` 会包含切换带来的改动——这是预期行为，task 边界内的工作树状态变化都算 task 改动。
- **untracked 文件被 add 进 isolated index 后，用户后续 `git add` 同名文件**：用户 add 写入 `.git/index`，我们 add 写入 `.git/index.ccwhat`，互不干扰。
