## Context

当前反馈诊断由后端读取 Action/Event Graph、裁剪并内嵌到 Prompt，再启动一次本地 Analyzer。图已经是 Marker 范围内原始 Claude Code Session 的结构化投影，因此 P0 不需要再次传入原始 Session，也不需要引入不稳定的 Diff 或 Snapshot 链路。

## Goals / Non-Goals

**Goals:**

- 用程序稳定识别产物缺失和基础验证问题。
- 让本地诊断 Agent 按绝对路径只读图和 OpenSpec 产物。
- 保留一次 Analyzer 调用、现有诊断 JSON、ID 校验和前端交互。
- 将 Finding 契约压缩到必要字段，正常检查不进入上下文。

**Non-Goals:**

- 不验证最终仓库状态或代码语义正确性。
- 不读取原始 Session、Runtime Task、Dataset Diff、Git Diff 或 Snapshot。
- 不新增分数、置信度、步骤级 Diff 或自动根因证明。
- 不修改 Marker、图结构或 React Viewer。

## Decisions

### Decision: 显性错误与隐性错误分层

程序只输出确定性的 `precheck_findings`；需求理解、修改方向、声明与行为是否一致由诊断 Agent 判断。相比继续增加启发式规则，该方案更小且不把语义推断伪装成程序事实。

### Decision: Prompt 传路径而不是 Graph 正文

后端传入 `action_graph_path`、`event_graph_path`、`change_root`、用户反馈、Findings 和输出契约。Agent 先读 Action Graph，再按 Event ID 查询 Event Graph，并按需读取 OpenSpec 产物。

不再调用 `build_compact_graph_context()`。Event Graph 已被 Marker 限定到当前 change，P0 不做可能丢失隐性错误的二次语义裁剪。

### Decision: Finding 使用七个固定字段

每条 Finding 只包含：

```text
finding_id, type, action_id, event_ids, target, expected, observed
```

数组只包含异常，不包含正常检查。Finding 不携带 `status`、`confidence`、`score`、重复 Evidence 或自然语言 summary。

### Decision: 只实现两个 Precheck

`ArtifactMissingVerifier` 检查已执行 proposal/specs/design/tasks Action 的明确产物。`BasicVerifyChecker` 检查修改后的验证缺失、明确失败、Result 缺失和验证过期。

没有明确 Contract 的“本应调用工具”、修改是否正确、是否真正落盘等问题不由程序判断。

### Decision: 保持现有输出与后端校验

Agent 继续输出 `symptoms`、`suspicious_actions`、`suspicious_events`、`missing_evidence` 和 `summary`。后端继续过滤未知 ID，并在 Agent 无法读取文件或没有有效引用时降级为不可用或证据不足。

### Decision: 文件访问只读且路径受控

所有路径由后端基于已校验 change 名称生成并使用绝对路径。Agent 只允许读取指定 Graph 和 OpenSpec 产物，不允许修改文件或执行项目命令。若 Analyzer 不支持只读文件访问，不回退到粘贴完整 Session。

## Risks / Trade-offs

- [Analyzer 的文件工具行为因 CLI 而异] → 使用绝对路径、明确只读约束，并为不可读情况提供稳定降级。
- [Event Graph 可能较大] → P0 依赖 Agent 按 Action/Event ID 查询；未来需要时按 Action 拆文件，不做语义裁剪。
- [没有 Diff 无法证明修改最终存在] → 将产品结论限定为 Session 行为归因，并要求在 `missing_evidence` 中说明边界。
- [OpenSpec 产物可能在 Session 后变化] → Precheck 只报告诊断时可观察的文件事实，不声称其为历史快照。
