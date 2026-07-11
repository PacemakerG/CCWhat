## Why

当前图诊断已经能返回并校验可疑 Action/Event，但诊断结论尚未稳定引用对应的 P0 显性异常和 OpenSpec 文档依据，用户难以核查模型为什么得出该结论。P1 需要在不扩建图和不新增规则的前提下，让现有诊断结果具备可验证、可展示的证据引用。

## What Changes

- 为 `suspicious_actions` 增加可选的 `precheck_finding_ids` 和 `document_refs`。
- 将 P0 显性异常标识统一为 `precheck_finding_id: precheck-finding-NNN`。
- 后端校验 Action、Event、`precheck_finding` 和 OpenSpec 文档引用，删除无效引用并记录 `missing_evidence`。
- 前端在现有诊断详情中简单展示被引用的 `precheck_finding` 和文档依据，保持粗图到细图的核心交互。
- 候选输出改为按可疑程度排序的动态最小集合：0～5 个 Action、最多 15 个 Event，不引入数值打分。
- 不新增诊断规则，不修改 Action Graph/Event Graph，不增加 LLM 调用次数。

## Capabilities

### New Capabilities
- `diagnosis-evidence-references`: 定义图诊断结论对 `precheck_findings` 和 OpenSpec 文档的引用契约、后端校验及前端最小展示。

### Modified Capabilities

- 无。

## Impact

- 后端：`ccwhat/diagnosis/precheck.py`、`ccwhat/diagnosis/feedback.py`。
- Prompt：`ccwhat/assets/graph_attribution_prompt.md`。
- 前端：Graph Diagnosis Viewer 的类型、诊断详情和少量样式。
- 测试：Precheck 字段迁移、引用校验、兼容输出和前端构建验证。
- 不影响图构建、Marker、Session、Diff、Git Snapshot 或旧打分链路。
