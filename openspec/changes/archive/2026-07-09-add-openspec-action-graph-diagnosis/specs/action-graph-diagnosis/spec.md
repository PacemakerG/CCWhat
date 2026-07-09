## ADDED Requirements

### Requirement: 构建 Event Graph

系统 SHALL 从 Dataset trace events 构建细粒度 Event Graph。

#### Scenario: Event Graph 包含事件节点和事实边
- **WHEN** trace 中包含 tool call、file edit、command、error 和 final claim 事件
- **THEN** Event Graph SHALL 为这些事件生成节点
- **AND** Event Graph SHALL 生成 temporal 边
- **AND** Event Graph SHALL 在可证明时生成 tool_result_of、reads_before_edit、edit_before_command、command_produces_error 和 claim_after_action 边

### Requirement: 构建 OpenSpec Action Graph

系统 SHALL 从固定 OpenSpec workflow 模板构建粗粒度 Action Graph。

#### Scenario: OpenSpec 模板节点
- **WHEN** 诊断引擎构建 Action Graph
- **THEN** Action Graph SHALL 包含 proposal、specs、design、tasks、apply、verify、archive 七个 required action
- **AND** Action Graph SHALL 包含按 OpenSpec 流程顺序连接的 workflow_expected 边

### Requirement: 事件映射到 Action

系统 SHALL 将 Event Graph 中的事件映射到 Action Graph 节点。

#### Scenario: OpenSpec 文件路径映射
- **WHEN** 事件或 change evidence 引用 `openspec/changes/*/proposal.md`
- **THEN** 系统 SHALL 将该事件映射到 proposal action
- **WHEN** 引用 `design.md`
- **THEN** 系统 SHALL 映射到 design action
- **WHEN** 引用 `specs/**/spec.md`
- **THEN** 系统 SHALL 映射到 specs action
- **WHEN** 引用 `tasks.md`
- **THEN** 系统 SHALL 映射到 tasks action

#### Scenario: 未识别事件保留为 ad hoc action
- **WHEN** 事件无法映射到固定 OpenSpec action
- **THEN** 系统 SHALL 按 turn 生成 ad_hoc_turn action
- **AND** 该 action SHALL 保留对应 event_ids

### Requirement: 症状检测和反向归因

系统 SHALL 基于 Action Graph 检测症状，并从症状节点反向传播生成 causal chains。

#### Scenario: 缺失 verify
- **WHEN** Action Graph 中 verify action 没有事件证据
- **THEN** 系统 SHALL 生成 missing_required_action symptom
- **AND** diagnosis SHALL 包含指向上游 action 的 causal chain

#### Scenario: unsupported final claim
- **WHEN** trace 中存在 final_claim
- **AND** tasks action 缺失、tasks 仍有未完成 checkbox、或 verify action 缺失/失败
- **THEN** 系统 SHALL 生成 unsupported_final_claim symptom

### Requirement: CLI 输出诊断文件

系统 SHALL 提供 `ccwhat diagnose` CLI。

#### Scenario: 对 Dataset task 生成 JSON
- **WHEN** 用户运行 `ccwhat diagnose --dataset <path> --task-id <id> --output <dir> --no-llm`
- **THEN** 系统 SHALL 写入 `event_graph.json`
- **AND** 系统 SHALL 写入 `action_graph.json`
- **AND** 系统 SHALL 写入 `diagnosis.json`

#### Scenario: 不支持 LLM
- **WHEN** 用户显式请求启用 LLM
- **THEN** CLI SHALL 返回明确错误
- **AND** 系统 SHALL NOT 尝试调用 analyzer 或 API key

### Requirement: OpenSpec workflow 同步图产物

系统 SHALL 提供 `ccwhat openspec-graph sync`，为一个 OpenSpec change 生成流程内 graph 产物。

#### Scenario: 同步 OpenSpec change graph
- **WHEN** 用户运行 `ccwhat openspec-graph sync --change <name>`
- **THEN** 系统 SHALL 在 `openspec/changes/<name>/graph/` 下写入 `event_graph.json`
- **AND** 系统 SHALL 写入 `action_graph.json`
- **AND** 系统 SHALL 写入 `diagnosis.json`

#### Scenario: 记录 workflow event 后同步
- **WHEN** 用户运行 `ccwhat openspec-graph sync --change <name> --event validate_ran --success`
- **THEN** 系统 SHALL 追加 `graph/events.jsonl`
- **AND** 系统 SHALL 重新生成 graph JSON
- **AND** verify action SHALL 具有 observed 状态

### Requirement: OpenSpec skill 自动同步 graph

OpenSpec skill 和 slash command 文档 SHALL 在 propose、apply 和 archive 流程的关键节点调用 graph sync。

#### Scenario: propose 生成 artifact 后同步
- **WHEN** OpenSpec propose workflow 创建或更新 artifact
- **THEN** workflow instruction SHALL 要求调用 `ccwhat openspec-graph sync --change <name> --event artifact_created --artifact <artifact-id>`

#### Scenario: apply 完成 task 后同步
- **WHEN** OpenSpec apply workflow 将一个 task checkbox 标记为完成
- **THEN** workflow instruction SHALL 要求调用 `ccwhat openspec-graph sync --change <name> --event task_completed --task <task description>`

#### Scenario: archive 前同步
- **WHEN** OpenSpec archive workflow 移动 change 目录前
- **THEN** workflow instruction SHALL 要求调用 `ccwhat openspec-graph sync --change <name> --event archive_ran --success`
