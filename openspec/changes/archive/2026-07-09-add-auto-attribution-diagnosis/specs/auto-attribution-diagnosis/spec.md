## ADDED Requirements

### Requirement: 规则层诊断覆盖确定性失败模式

规则层 SHALL 对以下确定性问题生成诊断：
- diff 为空但 final_claim 声称任务完成
- 测试命令存在但未运行或运行失败
- 关键命令（如 build、test）未在 trace 中出现
- final_claim 与 diff 内容矛盾（如声称"修复 bug"但 diff 是文档修改）

#### Scenario: diff 为空但 final_claim 声称完成
- **WHEN** diff.patch 为空字符串且 final_claim 包含"完成"、"修复"、"已解决"等关键词
- **THEN** 规则层 SHALL 生成 root_cause: "代码未实际修改"
- **AND** confidence SHALL 为 "high"
- **AND** source SHALL 为 "rule"

#### Scenario: 测试命令运行失败
- **WHEN** trace.test_commands 非空且 trace.errors 包含测试失败信息
- **THEN** 规则层 SHALL 生成 root_cause: "测试未通过"
- **AND** evidence SHALL 包含具体失败的测试命令和错误信息

#### Scenario: 关键命令缺失
- **WHEN** task.expected_tests 非空但 trace.test_commands 为空
- **THEN** 规则层 SHALL 生成 root_cause: "未运行预期测试"
- **AND** missing_evidence SHALL 包含 "test_commands"

### Requirement: LLM 层诊断覆盖语义分析

LLM 层 SHALL 使用 LLM 分析以下语义问题：
- instruction 与 files.changed 的相关性
- success_criteria 达成度评估
- Agent 行为模式分析（如频繁重试、死循环迹象）

#### Scenario: instruction 与改动不相关
- **WHEN** instruction 要求"修复登录 bug"但 files.changed 只有文档文件
- **THEN** LLM 层 SHALL 生成 root_cause: "改动与任务描述不相关"
- **AND** confidence 可能为 "medium" 或 "high"
- **AND** source SHALL 为 "llm"

#### Scenario: success_criteria 未达成
- **WHEN** task.success_criteria 存在但评估认为未达成
- **THEN** LLM 层 SHALL 说明未达成的具体 criteria
- **AND** recommended_next_steps SHALL 包含改进步骤

### Requirement: diagnosis.json 结构规范

diagnosis.json SHALL 包含以下字段：
- task_id: string（任务标识）
- diagnosed_at: ISO8601 时间戳
- summary: string（人类可读的问题摘要）
- likely_root_causes: array（可能的根因列表，按可能性排序）
- missing_evidence: array（缺失的证据列表）
- confidence: "high" | "medium" | "low"（整体置信度）
- recommended_next_steps: array（建议的下一步操作）

#### Scenario: diagnosis.json 字段完整性
- **WHEN** 诊断引擎生成 diagnosis.json
- **THEN** 文件 SHALL 包含所有必需字段
- **AND** likely_root_causes 每个条目 SHALL 包含 cause、evidence、confidence、source

### Requirement: 诊断置信度分级

诊断结果 SHALL 按以下规则标记 confidence：
- high: 规则层发现明确问题，或 LLM 层有强证据支持
- medium: LLM 层发现可能问题，但需人工确认
- low: 证据不足，无法做出可靠判断

#### Scenario: 规则层问题标记为 high confidence
- **WHEN** 规则层发现 diff 为空但 final_claim 声称完成
- **THEN** confidence SHALL 为 "high"
- **AND** source SHALL 为 "rule"

#### Scenario: 证据不足标记为 low confidence
- **WHEN** task_trace.extraction_status 不为 "ok" 且 diff.patch 缺失
- **THEN** confidence SHALL 为 "low"
- **AND** missing_evidence SHALL 列出缺失的证据
