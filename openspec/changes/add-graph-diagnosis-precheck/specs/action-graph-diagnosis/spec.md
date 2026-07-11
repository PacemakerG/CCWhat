## ADDED Requirements

### Requirement: 路径驱动的本地图诊断

用户反馈诊断 SHALL 将受控文件路径传给本地诊断 Agent，由 Agent 按需只读 Graph 和 OpenSpec 产物，而不是由后端内嵌裁剪后的 Graph 正文。

#### Scenario: 启动路径驱动诊断
- **WHEN** 用户对一个 Session-bound OpenSpec Graph 提交反馈
- **THEN** Prompt SHALL 包含 Action Graph 绝对路径、Event Graph 绝对路径、change root、用户反馈、`precheck_findings` 和诊断输出契约
- **AND** Prompt SHALL NOT 包含 Action Graph 或 Event Graph 正文

#### Scenario: Agent 按需读取证据
- **WHEN** 本地诊断 Agent 开始分析
- **THEN** Agent SHALL 先读取 Action Graph
- **AND** Agent SHALL 根据用户反馈和 `precheck_findings` 引用按 Event ID 查询 Event Graph
- **AND** Agent SHALL 在需要理解需求时读取 change root 中的 proposal、specs、design 或 tasks

#### Scenario: 只读范围受控
- **WHEN** 后端构建诊断请求
- **THEN** 所有文件路径 SHALL 由已校验的 change 名称派生
- **AND** Agent SHALL 只读指定 Graph 和 OpenSpec 产物
- **AND** Agent SHALL NOT 修改文件或执行项目命令

#### Scenario: Analyzer 无法读取文件
- **WHEN** 本地 Analyzer 不支持读取指定文件或文件不可访问
- **THEN** 系统 SHALL 返回明确的不可用或证据不足结果
- **AND** 系统 SHALL NOT 回退到粘贴完整原始 Session

### Requirement: 路径诊断的数据边界

路径驱动诊断 SHALL 保持 Session 行为归因边界，不将图证据解释为最终仓库状态证明。

#### Scenario: 不传原始 Session 和变更 Diff
- **WHEN** 后端启动本地诊断 Agent
- **THEN** 后端 SHALL NOT 传入原始 Session 路径或正文
- **AND** 后端 SHALL NOT 传入 Runtime Task、Dataset Diff、Git Diff、Git Tree 或 Snapshot

#### Scenario: 图证据不足
- **WHEN** Graph 和 OpenSpec 产物不足以判断用户反馈对应问题
- **THEN** Agent SHALL 在 `missing_evidence` 中说明限制
- **AND** Agent SHALL NOT 声称已验证最终代码状态

### Requirement: 保持诊断结果兼容

路径驱动诊断 SHALL 保持现有结构化输出和 ID 校验行为。

#### Scenario: 输出兼容 JSON
- **WHEN** Agent 完成分析
- **THEN** 输出 SHALL 包含 `symptoms`、`suspicious_actions`、`suspicious_events`、`missing_evidence` 和 `summary`
- **AND** 系统 SHALL 校验所有 Action ID 和 Event ID 是否存在于对应 Graph

#### Scenario: 模型引用未知 ID
- **WHEN** Agent 输出不存在的 Action ID 或 Event ID
- **THEN** 后端 SHALL 删除未知引用并记录缺失证据
