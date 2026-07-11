## ADDED Requirements

### Requirement: precheck_finding 标识契约

系统 SHALL 为本次 P0 程序规则确认的每条显性异常生成稳定格式的 `precheck_finding_id`，并将异常集合表示为 `precheck_findings`。

#### Scenario: 生成显性异常标识
- **WHEN** P0 Precheck 发现一个显性异常
- **THEN** 该记录 SHALL 包含 `precheck_finding_id`
- **AND** ID SHALL 使用 `precheck-finding-NNN` 格式
- **AND** 该记录 SHALL 继续包含 `type`、`action_id`、`event_ids`、`target`、`expected` 和 `observed`

### Requirement: 可疑 Action 的证据引用

诊断 Agent SHALL 继续以 `suspicious_actions` 和 `suspicious_events` 作为主要诊断结果，并可为可疑 Action 输出 `precheck_finding_ids` 和 `document_refs` 作为诊断依据。

#### Scenario: 引用 precheck_finding
- **WHEN** 一个可疑 Action 的结论依据包含 P0 显性异常
- **THEN** Agent SHALL 在该 Action 的 `precheck_finding_ids` 中引用输入已有的 `precheck_finding_id`
- **AND** Agent SHALL NOT 把 `precheck_finding` 输出为新的可疑节点

#### Scenario: 引用 OpenSpec 文档
- **WHEN** 一个可疑 Action 的结论依据包含 OpenSpec 文档
- **THEN** Agent SHALL 在 `document_refs` 中输出相对 change root 的 `path`、`kind` 和稳定 `anchor`
- **AND** Agent SHALL NOT 使用行号作为引用位置

### Requirement: OpenSpec 文档引用类型

系统 SHALL 根据 OpenSpec 文档类型校验 `document_refs` 的 `kind` 和 `anchor`。

#### Scenario: 引用 spec Requirement
- **WHEN** `path` 指向 `specs/*/spec.md`
- **THEN** `kind` SHALL 为 `requirement`
- **AND** `anchor` SHALL 为文件中真实存在的 Requirement 标题

#### Scenario: 引用 proposal 或 design 章节
- **WHEN** `path` 指向 `proposal.md` 或 `design.md` 且引用具体章节
- **THEN** `kind` SHALL 为 `section`
- **AND** `anchor` SHALL 为文件中真实存在的章节标题

#### Scenario: 引用 proposal 或 design 整体
- **WHEN** `path` 指向 `proposal.md` 或 `design.md` 且没有合适章节
- **THEN** `kind` SHALL 为 `document`
- **AND** `anchor` SHALL 为 `null`

#### Scenario: 引用 checklist 任务
- **WHEN** `path` 指向 `tasks.md`
- **THEN** `kind` SHALL 为 `task`
- **AND** `anchor` SHALL 为文件中真实存在的完整 checklist 任务文本

### Requirement: 后端引用真实性校验

后端 SHALL 只保留本次诊断输入范围内真实存在且归属正确的引用，不判断引用是否足以证明模型结论。

#### Scenario: 校验有效引用
- **WHEN** Agent 引用真实 Action、Event、`precheck_finding` 或允许的 OpenSpec 文档锚点
- **THEN** 后端 SHALL 保留该引用
- **AND** 诊断响应 SHALL 附带本次 `precheck_findings` 供前端按 ID 展示

#### Scenario: 删除无效引用
- **WHEN** Agent 引用不存在的 ID、文件、`kind` 或 `anchor`
- **THEN** 后端 SHALL 删除无效引用
- **AND** 后端 SHALL 在 `missing_evidence` 中记录该问题
- **AND** 其他有效引用 SHALL 保留

#### Scenario: 拒绝越界文档路径
- **WHEN** 文档引用使用绝对路径、包含 `..` 或解析后离开当前 change root
- **THEN** 后端 SHALL 删除该引用
- **AND** 后端 SHALL 在 `missing_evidence` 中记录该问题

### Requirement: 前端最小证据展示

Graph Diagnosis Viewer SHALL 在保持现有粗图到细图交互和主要布局的前提下，在当前诊断详情中展示有效诊断依据。

#### Scenario: 展示诊断依据
- **WHEN** 可疑 Action 包含有效 `precheck_finding_ids` 或 `document_refs`
- **THEN** 前端 SHALL 在该 Action 的诊断详情中展示被引用的 `precheck_finding` 和文档信息
- **AND** `precheck_finding` SHALL 展示 `type`、`expected` 和 `observed`
- **AND** 文档引用 SHALL 展示 `path`、`kind` 和 `anchor`

#### Scenario: 保持图诊断交互
- **WHEN** 用户查看包含证据引用的诊断结果
- **THEN** 前端 SHALL 继续高亮可疑 Action
- **AND** 用户 SHALL 能点击 Action 下钻到 Event Graph
- **AND** 前端 SHALL 高亮该 Action 下的可疑 Event
- **AND** 前端 SHALL NOT 将文档或 `precheck_finding` 创建为图节点或同级诊断对象

