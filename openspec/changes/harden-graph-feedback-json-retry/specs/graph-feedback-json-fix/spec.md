## ADDED Requirements

### Requirement: 最多一次格式修复调用

当 `analyze_graph_feedback` 调用 Analyzer 主分析输出后 `parse_graph_attribution_output` 抛出 `ValueError` 时，系统 SHALL 允许且仅允许一次自动格式修复子调用。首次解析合法时系统 SHALL NOT 产生第二次调用。

#### Scenario: 首次解析失败触发格式修复
- **WHEN** `run_mc_analysis` 主调用返回的原始输出中字符串包含未转义双引号
- **AND** `parse_graph_attribution_output` 抛出 `ValueError`
- **THEN** 系统 SHALL 自动构造一次格式修复 prompt
- **AND** 系统 SHALL 调用 `run_mc_analysis` 完成一次格式修复子调用
- **AND** 系统 SHALL 使用 `parse_graph_attribution_output` 解析修复后的输出

#### Scenario: 首次解析合法不触发额外调用
- **WHEN** 首次 `parse_graph_attribution_output` 成功解析为合法 JSON 对象
- **THEN** 系统 SHALL NOT 产生格式修复子调用
- **AND** 系统 SHALL 直接使用首次解析结果进入 `validate_graph_attribution_result`

#### Scenario: 第二次解析仍失败则降级
- **WHEN** 格式修复子调用的输出再次被 `parse_graph_attribution_output` 抛出 `ValueError`
- **THEN** 系统 SHALL 返回与原始 `_unavailable_result` 一致的降级结果
- **AND** 系统 SHALL NOT 进行第三次尝试

### Requirement: 格式修复提示限定范围

格式修复提示 SHALL 要求模型仅修正 JSON 语法错误，不新增字段、不改变语义、不修改数据值。

#### Scenario: 修复提示约束
- **WHEN** 系统构造格式修复 prompt
- **THEN** prompt SHALL 包含原始 Analyzer 输出
- **AND** prompt SHALL 包含前一次解析错误的具体信息
- **AND** prompt SHALL 明确要求只修正 JSON 语法
- **AND** prompt SHALL 明确要求不增加新事实或不改变语义

### Requirement: Action/Event 引用校验不变

格式修复调用之后的解析结果 SHALL 仍然通过 `validate_graph_attribution_result` 校验所有 Action/Event 引用。

#### Scenario: 修复后仍过校验
- **WHEN** 格式修复调用成功返回合法 JSON
- **THEN** 系统 SHALL 使用 `validate_graph_attribution_result` 校验该 JSON 中的 Action/Event 引用
- **AND** 校验行为与主分析输出完全一致
