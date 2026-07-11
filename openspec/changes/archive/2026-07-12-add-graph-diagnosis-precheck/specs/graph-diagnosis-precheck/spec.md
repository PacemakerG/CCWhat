## ADDED Requirements

### Requirement: 极简显性错误 Precheck

系统 SHALL 在启动本地诊断 Agent 前执行产物缺失和基础验证两个确定性 Precheck，并且只输出已发现的异常。

#### Scenario: 已执行阶段缺少明确产物
- **WHEN** proposal、specs、design 或 tasks Action 已执行
- **AND** 对应 OpenSpec 产物不存在、为空或不满足最小可解析结构
- **THEN** 系统 SHALL 生成 `artifact_missing` `precheck_finding`

#### Scenario: 未执行阶段缺少产物
- **WHEN** 某个 OpenSpec Action 未执行
- **AND** 对应产物不存在
- **THEN** 系统 SHALL NOT 因该缺失生成 `precheck_finding`

#### Scenario: 修改后没有验证
- **WHEN** Event Graph 包含修改事件
- **AND** 修改事件之后没有验证命令
- **THEN** 系统 SHALL 生成 `verification_missing` `precheck_finding`

#### Scenario: 验证明确失败
- **WHEN** 验证命令具有配对 Tool Result
- **AND** Tool Result 明确标记错误或失败
- **THEN** 系统 SHALL 生成 `verification_failed` `precheck_finding`
- **AND** `precheck_finding` SHALL 引用真实命令和 Result Event ID

#### Scenario: 验证结果缺失
- **WHEN** Event Graph 包含验证命令
- **AND** 没有对应 Tool Result
- **THEN** 系统 SHALL 生成 `verification_result_missing` `precheck_finding`

#### Scenario: 验证后再次修改
- **WHEN** 验证命令之后又出现修改事件
- **AND** 后续没有再次验证
- **THEN** 系统 SHALL 生成 `verification_stale` `precheck_finding`

### Requirement: precheck_finding 最小契约

每条 `precheck_finding` SHALL 只包含定位和描述显性异常所需的固定字段。

#### Scenario: precheck_finding 字段输出
- **WHEN** Precheck 发现异常
- **THEN** `precheck_finding` SHALL 包含 `precheck_finding_id`、`type`、`action_id`、`event_ids`、`target`、`expected` 和 `observed`
- **AND** `precheck_finding` SHALL NOT 包含 `status`、`confidence`、`score`、重复 Evidence 对象或额外 summary

#### Scenario: 正常检查不输出
- **WHEN** 一个产物或验证检查正常
- **THEN** 系统 SHALL NOT 为该正常检查生成 `precheck_finding`

### Requirement: Precheck 数据边界

Precheck SHALL 只使用当前 Graph 和 OpenSpec change 产物，不依赖其他变更证据模块。

#### Scenario: 禁止 Diff 和 Snapshot
- **WHEN** 系统执行 Precheck
- **THEN** 系统 SHALL NOT 读取或生成 Runtime Task、Dataset Diff、Git Diff、Git Tree、仓库 Snapshot 或 Action 级 Diff

#### Scenario: 不确定语义不程序化判断
- **WHEN** 问题需要判断需求理解、文件相关性、修改是否真正生效或代码语义正确性
- **THEN** Precheck SHALL NOT 生成确定性 `precheck_finding`
- **AND** 该问题 SHALL 留给本地诊断 Agent 或记录为缺失证据
