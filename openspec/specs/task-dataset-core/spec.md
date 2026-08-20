## Purpose

定义 Task Dataset v1 的后端核心数据契约、构建器和校验器，使 CCWhat 可以从运行时或离线切分的 coding task 生成稳定、可保存、可导出、可复用的数据资产。
## Requirements
### Requirement: Dataset v1 文件契约
Task Dataset Core SHALL 定义 `ccwhat-dataset-v1` 文件集合，包含 `manifest.json`、`dataset.jsonl`、`traces/*.json` 和 `scores.jsonl`，并允许运行时任务附带 `diffs/*.diff`。

#### Scenario: 生成必需文件集合
- **WHEN** 系统从已切分 Task 构建 Dataset
- **THEN** 输出 SHALL 包含 `manifest.json`
- **AND** 输出 SHALL 包含 `dataset.jsonl`
- **AND** 输出 SHALL 包含 `scores.jsonl`
- **AND** 输出 SHALL 包含 `traces/` 目录下每个 task 对应的 trace JSON

#### Scenario: manifest 描述数据包
- **WHEN** Dataset 包含 N 个 task
- **THEN** `manifest.json` SHALL 包含 `schema_version` 且值为 `ccwhat-dataset-v1`
- **AND** `manifest.json` SHALL 包含 `created_at`
- **AND** `manifest.json` SHALL 包含 `tool` 且值为 `ccwhat`
- **AND** `manifest.json` SHALL 包含 session 信息
- **AND** `manifest.json` SHALL 记录 `counts.dataset_items`
- **AND** `manifest.json` SHALL 记录 `counts.traces`
- **AND** `manifest.json` SHALL 记录 `counts.scores`

#### Scenario: dataset.jsonl 一行对应一个 task
- **WHEN** Dataset 包含一个 task
- **THEN** `dataset.jsonl` SHALL 为该 task 写入一行 JSON
- **AND** 该 JSON SHALL 包含 `id`
- **AND** 该 JSON SHALL 包含 `input.instruction`
- **AND** 该 JSON SHALL 包含 `input.repo`
- **AND** 该 JSON SHALL 包含 `input.base_commit`
- **AND** 该 JSON SHALL 包含 `expected.success_criteria`
- **AND** 该 JSON SHALL 包含 `expected.tests`
- **AND** 该 JSON SHALL 包含 `metadata.agent`
- **AND** 该 JSON SHALL 包含 `metadata.session_id`
- **AND** 该 JSON SHALL 包含 `metadata.task_source`
- **AND** 该 JSON SHALL 包含 `metadata.trace_id`
- **AND** 该 JSON SHALL 包含 `metadata.trace_path`
- **AND** 该 JSON SHALL 包含 task 边界 event id

#### Scenario: scores.jsonl 第一版为空
- **WHEN** Dataset v1 初次生成
- **THEN** `scores.jsonl` SHALL 存在
- **AND** `scores.jsonl` SHALL 允许为空文件
- **AND** 系统 SHALL NOT 自动写入 evaluator score

### Requirement: Dataset builder 构建核心内容
Task Dataset Core SHALL 提供 builder，从 normalized session events 与已切分 task 边界构建 Dataset v1 内容，并从 task 边界内的可证明 event evidence 抽取 `changes` 和 `patches`。

#### Scenario: 从 TaskSegmentationResult 构建 Dataset
- **WHEN** builder 接收 session metadata、normalized events 和 `TaskSegmentationResult`
- **THEN** builder SHALL 为每个 `TaskSegment` 生成一个 dataset item
- **AND** builder SHALL 为每个 `TaskSegment` 生成一个 trace JSON
- **AND** 每个 dataset item SHALL 通过 `metadata.trace_id` 和 `metadata.trace_path` 引用对应 trace
- **AND** 每个 trace SHALL 通过 `task_id` 引用对应 dataset item

#### Scenario: 按 task 边界裁剪 events
- **WHEN** task 指定 `start_event_id` 和 `end_event_id`
- **THEN** builder SHALL 将 trace `events` 限制在该闭区间内
- **AND** builder SHALL 保持 events 的原始输入顺序
- **AND** builder SHALL NOT 将其他 task 范围内的 events 写入该 trace

#### Scenario: task 没有 end_event_id
- **WHEN** task 的 `end_event_id` 为空
- **THEN** builder SHALL 将 trace `events` 从 `start_event_id` 开始延伸到 session events 末尾
- **AND** dataset item SHALL 保留 `metadata.end_event_id` 为 `null`

#### Scenario: 提取基础执行 evidence
- **WHEN** builder 生成 trace JSON
- **THEN** trace SHALL 包含 `events`
- **AND** trace SHALL 包含 `commands`
- **AND** trace SHALL 包含 `test_commands`
- **AND** trace SHALL 包含 `files.read`
- **AND** trace SHALL 包含 `files.changed`
- **AND** trace SHALL 包含 `errors`
- **AND** trace SHALL 包含 `final_claim`
- **AND** trace SHALL 包含 `repo_state`

#### Scenario: 抽取 changes 和 patches evidence
- **WHEN** builder 生成 trace JSON
- **THEN** trace SHALL 包含 `changes` 数组
- **AND** trace SHALL 包含 `patches` 数组
- **AND** builder SHALL 从该 task 边界内的 events 抽取可证明的 change evidence
- **AND** builder SHALL 从该 task 边界内的 events 抽取可证明的 patch evidence
- **AND** builder SHALL NOT 通过 LLM 猜测 patch 或 diff
- **AND** builder SHALL NOT 通过当前 repo 现场 `git diff` 生成 patch 或 diff

#### Scenario: 无可证明 patch 时保持 patches 为空
- **WHEN** task 边界内只有 command 或 edit evidence 但没有原生 patch / diff 字段
- **THEN** builder SHALL 可以生成 `changes` entry
- **AND** builder SHALL NOT 生成 `patches` entry

### Requirement: 运行时和离线切分使用统一 Dataset Schema
Task Dataset Core SHALL 将运行时显式切分和历史 Session 离线切分视为 Task 边界的不同来源，并通过同一个 builder 生成 Dataset。

#### Scenario: 运行时任务附带仓库 Diff
- **WHEN** Task 由 `/ccwhat:start` 和 `/ccwhat:finish` 显式记录
- **AND** 隔离 Git Index 已生成该 Task 的 `task.diff`
- **THEN** trace 的 `task_diff.available` SHALL 为 `true`
- **AND** `task_diff.source` SHALL 为 `isolated_git_index`
- **AND** `task_diff.confidence` SHALL 为 `high`
- **AND** `task_diff.path` SHALL 引用 Dataset 内对应的 `diffs/*.diff`

#### Scenario: 离线任务不伪造仓库 Diff
- **WHEN** Task 由自动切分或人工修正的历史 Session 边界生成
- **THEN** trace SHALL 保留相同的 `task_diff` 对象
- **AND** `task_diff.available` SHALL 为 `false`
- **AND** `source`、`confidence` 和 `path` SHALL 为 `null`
- **AND** 系统 SHALL NOT 把日志中的 Edit、Write 或 Patch 证据冒充为任务级仓库 Diff

### Requirement: Dataset validator 校验结构和引用
Task Dataset Core SHALL 提供 validator，校验 Dataset v1 目录或 tar 包的结构、格式和引用一致性。

#### Scenario: 校验合法目录
- **WHEN** validator 接收一个合法 Dataset v1 目录
- **THEN** validator SHALL 返回通过结果
- **AND** validator SHALL 报告 dataset item 数量、trace 数量和 score 数量

#### Scenario: 校验合法 tar 包
- **WHEN** validator 接收一个包含 Dataset v1 文件集合的 tar 包
- **THEN** validator SHALL 返回通过结果
- **AND** validator SHALL 使用与目录校验相同的结构和 schema 规则

#### Scenario: 缺少必需文件时报错
- **WHEN** Dataset 缺少 `manifest.json`、`dataset.jsonl`、`scores.jsonl` 或 `traces/`
- **THEN** validator SHALL 返回失败结果
- **AND** validator SHALL 报告缺失的路径

#### Scenario: JSON 或 JSONL 格式错误时报错
- **WHEN** Dataset 文件包含非法 JSON 或非法 JSONL 行
- **THEN** validator SHALL 返回失败结果
- **AND** validator SHALL 报告文件路径和行号或字段位置

#### Scenario: trace 引用不存在时报错
- **WHEN** `dataset.jsonl` 中的 `metadata.trace_path` 指向不存在的 trace
- **THEN** validator SHALL 返回失败结果
- **AND** validator SHALL 报告对应 dataset item id 和 trace path

#### Scenario: task 与 trace id 不一致时报错
- **WHEN** dataset item 的 `id` 与对应 trace 的 `task_id` 不一致
- **THEN** validator SHALL 返回失败结果
- **AND** validator SHALL 报告不一致的 dataset item id 和 trace path

#### Scenario: manifest counts 不一致时报错
- **WHEN** `manifest.json` 中的 `counts.dataset_items`、`counts.traces` 或 `counts.scores` 与实际文件内容不一致
- **THEN** validator SHALL 返回失败结果
- **AND** validator SHALL 报告不一致的 count 字段

### Requirement: 三类 agent fixture 覆盖
Task Dataset Core SHALL 提供最小 fixture 和测试，证明 Claude Code、Codex、OpenCode session 都可以生成 Dataset v1。

#### Scenario: Claude Code fixture 可生成 Dataset
- **WHEN** 测试使用 Claude Code fixture 构建 Dataset
- **THEN** builder SHALL 生成合法 Dataset v1
- **AND** validator SHALL 校验通过

#### Scenario: Codex fixture 可生成 Dataset
- **WHEN** 测试使用 Codex fixture 构建 Dataset
- **THEN** builder SHALL 生成合法 Dataset v1
- **AND** validator SHALL 校验通过

#### Scenario: OpenCode fixture 可生成 Dataset
- **WHEN** 测试使用 OpenCode fixture 构建 Dataset
- **THEN** builder SHALL 生成合法 Dataset v1
- **AND** validator SHALL 校验通过

### Requirement: Dataset core 不引入产品流程
Task Dataset Core SHALL 保持为后端核心能力，不直接引入 viewer 保存入口、registry 写入、下载流程或 evaluator。

#### Scenario: 不新增 viewer 保存入口
- **WHEN** 本 change 完成
- **THEN** 系统 SHALL NOT 新增 Tasks 页面“保存为 Dataset”按钮
- **AND** 系统 SHALL NOT 新增保存确认 modal

#### Scenario: 不新增保存和下载 API
- **WHEN** 本 change 完成
- **THEN** 系统 SHALL NOT 新增 `POST /api/save-task-dataset`
- **AND** 系统 SHALL NOT 写入 `~/.agentlens/datasets/`
- **AND** 系统 SHALL NOT 生成 `dataset-*.tar.gz`

#### Scenario: 不做 evaluator
- **WHEN** Dataset v1 生成
- **THEN** 系统 SHALL NOT 自动评分
- **AND** 系统 SHALL NOT 写入非空 evaluator score
### Requirement: Dataset change evidence schema
Task Dataset Core SHALL 使用稳定 schema 表达 trace 中的 `changes` 和 `patches` evidence。

#### Scenario: change entry 字段
- **WHEN** trace 中存在一条 change evidence
- **THEN** change entry SHALL 包含 `change_id`
- **AND** change entry SHALL 包含 `event_id`
- **AND** change entry SHALL 包含 `file`
- **AND** change entry SHALL 包含 `kind`
- **AND** change entry SHALL 包含 `source`
- **AND** change entry SHALL 包含 `old_string`
- **AND** change entry SHALL 包含 `new_string`
- **AND** change entry SHALL 包含 `content`
- **AND** change entry SHALL 包含 `patch_id`
- **AND** change entry SHALL 包含 `confidence`

#### Scenario: change kind 和 confidence 枚举
- **WHEN** trace 中存在 change evidence
- **THEN** `kind` SHALL 是 `edit`、`write`、`patch`、`command` 或 `git_diff`
- **AND** `confidence` SHALL 是 `high`、`medium` 或 `low`

#### Scenario: patch entry 字段
- **WHEN** trace 中存在一条 patch evidence
- **THEN** patch entry SHALL 包含 `patch_id`
- **AND** patch entry SHALL 包含 `scope`
- **AND** patch entry SHALL 包含 `file`
- **AND** patch entry SHALL 包含 `source`
- **AND** patch entry SHALL 包含 `format`
- **AND** patch entry SHALL 包含 `confidence`
- **AND** patch entry SHALL 包含 `patch`

#### Scenario: patch format 和 confidence 枚举
- **WHEN** trace 中存在 patch evidence
- **THEN** `format` SHALL 是 `unified_diff`、`apply_patch`、`git_diff` 或 `opencode_diff`
- **AND** `confidence` SHALL 是 `high` 或 `medium`

#### Scenario: change 引用 patch
- **WHEN** change entry 的 `patch_id` 非空
- **THEN** 同一个 trace 的 `patches` 数组 SHALL 包含相同 `patch_id` 的 patch entry

### Requirement: Claude Code change evidence 抽取
Task Dataset Core SHALL 从 Claude Code session events 中抽取可证明的 edit、write 和 command evidence。

#### Scenario: 抽取 Claude Edit evidence
- **WHEN** task 边界内存在 Claude Code `Edit` tool event
- **AND** event 中包含 file path、`old_string` 和 `new_string`
- **THEN** builder SHALL 生成 `kind = "edit"` 的 change entry
- **AND** `source` SHALL 为 `claude_edit`
- **AND** change entry SHALL 保留 file、`old_string` 和 `new_string`
- **AND** `confidence` SHALL 为 `medium`
- **AND** builder SHALL NOT 因该 Edit event 自动生成 patch entry

#### Scenario: 抽取 Claude Write evidence
- **WHEN** task 边界内存在 Claude Code `Write` tool event
- **AND** event 中包含 file path 和 `content`
- **THEN** builder SHALL 生成 `kind = "write"` 的 change entry
- **AND** `source` SHALL 为 `claude_write`
- **AND** change entry SHALL 保留 file 和 `content`
- **AND** builder SHALL NOT 因该 Write event 自动生成 patch entry

#### Scenario: 抽取 Claude Bash command evidence
- **WHEN** task 边界内存在 Claude Code `Bash` tool event
- **AND** event 中包含 command
- **THEN** builder SHALL 生成 `kind = "command"` 的 change entry
- **AND** `source` SHALL 为 `bash_command`
- **AND** change entry SHALL 保留 command 内容
- **AND** builder SHALL NOT 因 Bash command 自动生成 patch entry

### Requirement: OpenCode change evidence 抽取
Task Dataset Core SHALL 从 OpenCode session events 中抽取可证明的 edit 和 patch evidence。

#### Scenario: 抽取 OpenCode edit evidence
- **WHEN** task 边界内存在 OpenCode edit event
- **AND** event 中包含 file path、`oldString` 和 `newString`
- **THEN** builder SHALL 生成 `kind = "edit"` 的 change entry
- **AND** `source` SHALL 为 `opencode_edit`
- **AND** change entry SHALL 保留 file、`old_string` 和 `new_string`
- **AND** `confidence` SHALL 为 `medium`

#### Scenario: 抽取 OpenCode metadata diff evidence
- **WHEN** task 边界内存在 OpenCode event
- **AND** event 中包含 `metadata.diff` 或 `metadata.filediff`
- **THEN** builder SHALL 生成 patch entry
- **AND** patch entry `source` SHALL 为 `opencode_edit`
- **AND** patch entry `format` SHALL 为 `opencode_diff`
- **AND** patch entry `confidence` SHALL 为 `high`
- **AND** builder SHALL 生成引用该 `patch_id` 的 change entry

#### Scenario: 抽取 OpenCode apply_patch evidence
- **WHEN** task 边界内存在 OpenCode apply_patch event
- **AND** event 中包含 `patchText`
- **THEN** builder SHALL 生成 patch entry
- **AND** patch entry `source` SHALL 为 `opencode_patch`
- **AND** patch entry `format` SHALL 为 `apply_patch`
- **AND** patch entry `confidence` SHALL 为 `high`
- **AND** builder SHALL 生成引用该 `patch_id` 的 change entry

### Requirement: Codex change evidence 抽取
Task Dataset Core SHALL 从 Codex session events 中抽取 `patch_apply_end` 相关 change 和 patch evidence。

#### Scenario: 抽取 Codex unified_diff evidence
- **WHEN** task 边界内存在 Codex `patch_apply_end` event
- **AND** event payload 中某个 file change 包含 `unified_diff`
- **THEN** builder SHALL 生成 patch entry
- **AND** patch entry `source` SHALL 为 `codex_patch_apply_end`
- **AND** patch entry `format` SHALL 为 `unified_diff`
- **AND** patch entry `confidence` SHALL 为 `high`
- **AND** builder SHALL 生成引用该 `patch_id` 的 `kind = "patch"` change entry

#### Scenario: 抽取 Codex 新增文件 content evidence
- **WHEN** task 边界内存在 Codex `patch_apply_end` event
- **AND** event payload 中某个 file change 包含新增文件 `content`
- **THEN** builder SHALL 生成 `kind = "write"` 或 `kind = "patch"` 的 change entry
- **AND** `source` SHALL 为 `codex_patch_apply_end`
- **AND** change entry SHALL 保留 file 和可证明的 content
- **AND** builder SHALL 只在存在 `unified_diff` 时生成 patch entry

#### Scenario: Codex patch 不跨 task 泄漏
- **WHEN** session 中存在两个 task
- **AND** 第二个 task 内存在 Codex `patch_apply_end` event
- **THEN** 第一个 task trace SHALL NOT 包含第二个 task 的 change 或 patch evidence

### Requirement: Dataset validator 校验 change evidence
Task Dataset Core SHALL 校验 trace 中 `changes` 和 `patches` 的基础 schema 与引用一致性。

#### Scenario: 校验 change entry 缺少必填字段
- **WHEN** trace 中的 change entry 缺少 `change_id`、`event_id`、`kind`、`source` 或 `confidence`
- **THEN** validator SHALL 返回失败结果
- **AND** validator SHALL 报告对应 trace path 和字段

#### Scenario: 校验 change 枚举
- **WHEN** trace 中的 change entry 使用未知 `kind` 或未知 `confidence`
- **THEN** validator SHALL 返回失败结果
- **AND** validator SHALL 报告对应字段

#### Scenario: 校验 patch entry 缺少必填字段
- **WHEN** trace 中的 patch entry 缺少 `patch_id`、`source`、`format`、`confidence` 或 `patch`
- **THEN** validator SHALL 返回失败结果
- **AND** validator SHALL 报告对应 trace path 和字段

#### Scenario: 校验 patch 枚举
- **WHEN** trace 中的 patch entry 使用未知 `format` 或未知 `confidence`
- **THEN** validator SHALL 返回失败结果
- **AND** validator SHALL 报告对应字段

#### Scenario: 校验 patch_id 引用
- **WHEN** trace 中的 change entry 引用了不存在的 `patch_id`
- **THEN** validator SHALL 返回失败结果
- **AND** validator SHALL 报告对应 trace path 和 `patch_id`

### Requirement: Dataset core 仍不引入产品流程
Task Dataset Core SHALL 在抽取 change evidence 后仍保持为后端核心能力，不直接引入 viewer 保存入口、registry 写入、下载流程或 evaluator。

#### Scenario: 不新增 viewer 保存入口
- **WHEN** 本 change 完成
- **THEN** 系统 SHALL NOT 新增 Tasks 页面“保存为 Dataset”按钮
- **AND** 系统 SHALL NOT 新增保存确认 modal

#### Scenario: 不新增保存和下载 API
- **WHEN** 本 change 完成
- **THEN** 系统 SHALL NOT 新增 `POST /api/save-task-dataset`
- **AND** 系统 SHALL NOT 写入 `~/.agentlens/datasets/`
- **AND** 系统 SHALL NOT 生成 `dataset-*.tar.gz`

#### Scenario: 不做 evaluator
- **WHEN** Dataset v1 生成
- **THEN** 系统 SHALL NOT 自动评分
- **AND** 系统 SHALL NOT 写入非空 evaluator score
