## Why

真实用户复现反馈：ccwhat/diagnosis/feedback.py 中 `analyze_graph_feedback` 第一次调用 Analyzer 后，模型可能返回近似 JSON，但字符串内复制了未转义的双引号，导致 `parse_graph_attribution_output` 抛出 `Expecting comma delimiter` 错误，Viewer 无法生成诊断。当前代码仅做一次解析尝试，失败即降级为 `unavailable`，浪费了可用但不合规的模型输出。需要在不增加 Analyzer 调用次数约束的前提下，允许一次可逆的格式修复调用，提升调试可用性。

## What Changes

- `analyze_graph_feedback` 调整设计约束：从一次主分析调用调整为**一次主分析 + 最多一次格式修复调用**（即主分析输出非法 JSON 时，调用一次专用修复提示）。
- 新增一次专用格式修复子调用逻辑：仅在首次 `parse_graph_attribution_output` 抛出 `ValueError` 时允许触发；修复提示要求只修正 JSON 语法错误（不增加新事实、不改变语义），并携带原始输出和解析异常信息。
- 第二次解析仍非法则复用现有 `_unavailable_result` 降级通道。
- 首次解析合法不产生第二次调用。
- 所有 Action/Event 引用校验仍必须通过现有的 `validate_graph_attribution_result`。
- 新增三人测试组：未转义引号导致首次失败后修复成功、首次合法只调用一次、第二次仍失败时降级。
- 更新当前 change 的 design.md 设计约束："一次主分析调用" → "一次主分析加最多一次格式修复调用"。

## Capabilities

### New Capabilities
- `graph-feedback-json-fix`: 允许一次 JSON 格式修复子调用，在模型输出近似 JSON 时挽救诊断结果。

### Modified Capabilities
- 无

## Impact

- **代码**: `ccwhat/diagnosis/feedback.py` 的 `analyze_graph_feedback` 函数逻辑调整，新增修复调用的工厂函数或内联逻辑。
- **测试**: `tests/test_graph_feedback.py` 新增三个测试用例。
- **设计文档**: `openspec/changes/harden-graph-feedback-json-retry/design.md` 更新调用次数约束。
