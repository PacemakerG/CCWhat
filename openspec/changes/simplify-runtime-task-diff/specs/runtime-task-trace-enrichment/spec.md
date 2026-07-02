## REMOVED Requirements

### Requirement: finish 时从 session 日志提取 Agent 行为轨迹
系统 SHALL 在 `finish_task()` 执行时，从 proxy session JSONL 日志中按任务时间窗口提取 Agent 行为字段，写入 `task_trace.json`。

#### Scenario: 正常提取并写入 task_trace.json
- **WHEN** controller 成功执行 `finish` 且 session JSONL 日志存在
- **THEN** 系统 SHALL 按 start/finish 时间戳切出任务时间窗口内的事件
- **AND** 系统 SHALL 从切出的事件中提取 commands、test_commands、files.read、files.changed、changes、patches、errors、final_claim
- **AND** 系统 SHALL 将提取结果写入 `tasks/<task-id>/task_trace.json`
- **AND** `task.json` 中 `evidence_availability.task_trace` SHALL 为 true

#### Scenario: session 日志不存在时降级
- **WHEN** controller 成功执行 `finish` 但 session JSONL 日志不存在
- **THEN** 系统 SHALL NOT 中断 finish 流程
- **AND** 系统 SHALL 将 `evidence_availability.task_trace` 置为 false
- **AND** 系统 SHALL NOT 创建 `task_trace.json`

#### Scenario: 提取结果为空时仍写入
- **WHEN** 时间窗口内的事件不含任何 commands 或 changes
- **THEN** 系统 SHALL 仍然写入 `task_trace.json`，对应字段为空列表
- **AND** `evidence_availability.task_trace` SHALL 为 true

### Requirement: task_trace.json 结构与 Dataset v1 trace 对齐
`task_trace.json` 的字段结构 SHALL 与 Dataset v1 的 `traces/<trace_id>.json` 保持一致，使诊断引擎可以统一消费两种数据来源。

#### Scenario: task_trace.json 包含必要字段
- **WHEN** `task_trace.json` 被写入
- **THEN** 文件 SHALL 包含以下顶层字段：task_id、run_id、agent、time_window、events、commands、test_commands、files、changes、patches、errors、final_claim、repo_state
- **AND** `files` SHALL 包含 `read` 和 `changed` 两个子字段
- **AND** `time_window` SHALL 包含 `started_at` 和 `finished_at`

#### Scenario: repo_state 与 task.json git 字段一致
- **WHEN** `task_trace.json` 被写入
- **THEN** `repo_state.base_commit` SHALL 等于 `task.json` 中的 `git.before_commit`
- **AND** `repo_state.head_commit` SHALL 等于 `task.json` 中的 `git.after_commit`

### Requirement: 复用已有 evidence 提取逻辑
系统 SHALL 复用 `ccwhat.task_segments.evidence.extract_evidence` 和 `ccwhat.task_dataset.change_evidence.extract_change_evidence`，不重新实现提取逻辑。

#### Scenario: 提取逻辑路径不重复
- **WHEN** `trace_extractor` 从事件列表提取字段
- **THEN** 系统 SHALL 调用 `extract_evidence(events)` 获取 commands、files、errors、final_claim
- **AND** 系统 SHALL 调用 `extract_change_evidence(events, agent=agent)` 获取 changes 和 patches

**Rationale:** runtime 路径抽取 Agent 行为轨迹与离线 `task_dataset` builder 同源重复，且会把 `task.json.instruction` 污染成 boundary marker。Agent 行为轨迹改由事后 dataset 导出时从原始日志（cc jsonl / opencode sqlite / 抓包 jsonl）抽取，可重放可校验。runtime 只保留 git diff ground truth。
