## Context

现有可复用部分：

- `action_graph.py` 的 OpenSpec 七节点 DAG。
- `models.py` 的基础 graph/result dataclass。
- `attribution.py` 中沿 Action Graph 反向遍历的思路。
- `mapping.py` 中 path/command/tool 到 Action 的映射规则。

需要重做或清理部分：

- `symptoms.py` 当前只是系统规则检测少数 symptom，不是用户反馈分类路由。
- `attribution.py` 当前只有一套通用 `_score_candidate()`，没有 symptom-specific scorer。
- `CausalChain` 当前主要是 Action 级，没有 Event 级可疑节点。
- `openspec_graph.py` 中 milestone 级 graph 主路径不应再驱动归因。

## Decisions

### Decision: 先清理，再扩展

实现前先做 `ccwhat/diagnosis/` 代码审计：

- 保留能明确复用的 graph models、fixed Action DAG、mapping helpers。
- 删除或清空不再作为主路径的粗糙 symptom/scoring 实现。
- 新 attribution 以清晰模块边界重建，避免继续在旧 MVP 上叠规则。

建议模块边界：

- `symptom_router.py`：用户反馈/系统证据 -> symptom。
- `scoring.py`：通用分和 symptom-specific scorer。
- `event_scorer.py`：Event 级可疑分。
- `causal_chain.py`：Action/Event chain 组装。
- `explain.py`：把结构化结果转成人能读的摘要。

### Decision: 用户反馈先变成 symptom

用户说的问题不是 root cause，而是 symptom。第一版 symptom 类型：

- `workflow_skip`
- `validation_failed`
- `unsupported_final_claim`
- `missing_required_artifact`
- `wrong_or_incomplete_output`
- `tool_or_command_error_ignored`
- `bad_edit_or_regression`
- `insufficient_context`

router 输出应包含：

- `type`
- `anchor_action_ids`
- `query_terms`
- `confidence`
- `source`: `user_report|system_detected`

### Decision: Attribution 先粗后细

归因顺序：

```text
symptom
  -> anchor Action
  -> reverse walk Action DAG
  -> score suspicious Actions
  -> score Events inside those Actions
  -> causal chains with Action + Event evidence
```

不要直接在全部 Event 上打分，否则会丢掉 OpenSpec 流程约束。

### Decision: 打分是通用分 + symptom 加权

通用 Action 分：

- 距离 symptom 越近，分越高。
- Action 状态 missing/skipped/failed 加分。
- 有错误证据加分。
- 下游影响越大加分。
- 缺少 verify 或 evidence 加分。

通用 Event 分：

- Event 时间离 symptom 越近，分越高。
- Event 是 edit/command/tool_result/error/final_claim 时按类型加权。
- Event 文件/命令/文本命中用户问题关键词加分。
- Event 与失败命令、错误输出、final claim 有边连接加分。

symptom 专属加权：

- `validation_failed`：失败命令前最近 edit、相关文件 edit、失败后未修复、失败后 claim。
- `unsupported_final_claim`：缺 verify、verify failed、tasks 未完成、artifact missing、claim 前无证据。
- `workflow_skip`：required Action missing、下游继续执行、缺失后 final claim。
- `wrong_or_incomplete_output`：需求关键词未覆盖、相关文件未改、可见产物缺失、apply 证据弱。
- `tool_or_command_error_ignored`：error tool_result/command 后继续执行或 claim。
- `bad_edit_or_regression`：失败前相关 edit、删除/覆盖风险高的 edit、未读先改。
- `insufficient_context`：未读取 spec/task/相关文件就 edit。

## Output Shape

Diagnosis result 应至少包含：

```json
{
  "symptoms": [],
  "suspicious_actions": [],
  "suspicious_events": [],
  "causal_chains": [],
  "missing_evidence": []
}
```

Event 级结果应包含：

```json
{
  "event_id": "E42",
  "action_id": "A5",
  "score": 86,
  "reasons": ["edited related file before failed verify"],
  "evidence": []
}
```

## Risks

- 用户反馈分类可能不稳定，需要保留低置信度和 fallback。
- 不同 symptom 的权重一开始不可能完美，需要测试 fixture 和人工验收逐步调参。
- 如果 step-level Event Graph 不完整，Event-level attribution 必须降级并明确说明。
