## Context

MVP 明确假设一个 Claude Code Session 只执行一个 OpenSpec change。唯一执行证据来自 Claude Code 原始 Session 日志，经现有 Adapter 和 normalized event 链路提取。

可复用能力：

- `ccwhat.diagnosis.action_graph` 的固定 OpenSpec 七节点图。
- `ccwhat.diagnosis.event_graph` 和 `mapping` 的基本构图/映射路径。
- `ccwhat.openspec_graph` 的 Session source binding 和 graph JSON 输出。
- `ccwhat.analyzer.run_mc_analysis()`、Analyzer Registry、timeout、输出解析和 fallback 错误模型。
- Viewer 现有 OpenSpec Graph 展示和 Action -> Event 高亮能力。

不复用旧 `attribute_symptoms()` 的 Action 反向分数作为新诊断主路径。

## Decisions

### Decision: MVP 只使用 CC 原始 Session

输入为：

```json
{
  "session_id": "...",
  "change": "...",
  "feedback": "实现完成了，但是按钮点击后仍跳转到错误页面"
}
```

不读取 Runtime Task、Dataset 或 task diff。报告明确标注为“基于 Session 行为证据的诊断”，不声称验证最终仓库状态。

### Decision: 固定粗图只作为阶段索引

保留：

```text
proposal -> specs -> design -> tasks -> apply -> verify -> archive
```

Action 状态只使用：

```text
observed | not_observed | failed
```

固定流程边只用于展示和上下文，不做反向根因传播。可疑 Action 只在收到用户反馈并完成 Analyzer 诊断后产生。

### Decision: 细图优先保证证据完整

Event Graph 只建最小节点和边：

- 节点：user/assistant/tool call/tool result/file read/file edit/command/error/final claim。
- 边：`next`、`tool_result_of`。
- Action 映射保存在节点 data 和 Action `event_ids/evidence` 中。

节点必须保留唯一 ID、Tool Call ID、files、command、result summary、error flag 和 raw reference。无法映射到 Action 的 Event 仍保留。

### Decision: 复用 Analyzer Adapter，不新增模型 API

反馈诊断流程：

```text
feedback + compact Action/Event context
  -> graph attribution prompt
  -> run_mc_analysis(...)
  -> local AI CLI subprocess
  -> output text
  -> JSON parse
  -> Action/Event reference validation
  -> Diagnosis Result
```

默认 Analyzer 选择沿用 Viewer 逻辑：显式 analyzer -> 当前 Adapter/Session agent -> Claude fallback。用户不在本项目中配置 API Key，但对应 AI CLI 必须已安装并完成自身登录。

MVP 只调用一次 Analyzer。Analyzer 负责理解 symptom、选择 Top-K Action/Event 和生成解释，不能创建不存在的证据。

### Decision: 严格输出校验

Analyzer 输出：

```json
{
  "symptoms": [{"type": "wrong_output", "summary": "..."}],
  "suspicious_actions": [{"action_id": "A5", "reason": "..."}],
  "suspicious_events": [{"event_id": "E40", "action_id": "A5", "reason": "..."}],
  "missing_evidence": [],
  "summary": "..."
}
```

程序必须验证：

- Action ID 属于固定七节点。
- Event ID 存在于本次 Event Graph。
- Event/Action 映射一致；冲突时标记或使用真实映射。
- JSON 无法解析、Analyzer timeout/失败或有效引用为空时，返回明确状态和 `missing_evidence`，不伪造诊断。

### Decision: Viewer 提供最小闭环

OpenSpec Graph 区域增加：

- feedback 文本框。
- “生成诊断”按钮和运行状态。
- 结构化报告：问题理解、可疑阶段、可疑 Event、缺失证据、总结。
- 点击 Action/Event 结果高亮对应图节点。

### Decision: Mock 使用真实 Claude 日志结构

Mock Session 使用 Claude Code JSONL 结构，包含：

- OpenSpec proposal/spec/design/tasks 写入。
- 源码 Read/Edit。
- Bash 验证和 Tool Result。
- 一个隐藏的错误实现或验证缺口。
- final claim。

它绑定一个 mock OpenSpec change，能够从 Viewer 加载双图，并通过手动 feedback 触发诊断。

## Risks

- 原始 Session 不提供最终仓库真相；报告必须保留该限制。
- 一次 Analyzer 调用可能受上下文长度影响；compact context 优先保留 edit、command、error、result 和 final claim。
- 本地 AI CLI 可能未安装、未登录或 timeout；接口应返回可读错误，Viewer 不得空白。
- Analyzer 输出可能带 Markdown code fence 或无效 JSON；parser 必须兼容 code fence 并严格校验 schema/引用。
