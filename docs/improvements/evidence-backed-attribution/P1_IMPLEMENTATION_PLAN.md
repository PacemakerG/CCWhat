# P1：诊断证据引用与可追溯展示

> 状态：待评审。P1 只增强诊断结论与证据的引用关系，不新增诊断规则，不修改 Action Graph/Event Graph。

## 1. 目标与边界

主要诊断结果保持不变：

- `suspicious_actions`：可疑粗图节点。
- `suspicious_events`：可疑细图事件。

`precheck_findings` 是 P0 程序规则确认的显性异常事实，例如产物缺失、验证失败、验证过期。OpenSpec 文档和 `precheck_findings` 只作为诊断依据，不成为新的可疑节点。

```text
Agent 输出 suspicious_actions / suspicious_events 和证据引用
  -> 后端校验引用是否存在
  -> 删除无效引用并写入 missing_evidence
  -> 前端继续高亮可疑 Action，并下钻到可疑 Event
```

后端只验证引用真实性，不判断模型诊断是否正确。

## 2. JSON 字段

保留现有输出结构，只给 `suspicious_actions` 增加两个可选字段：

```json
{
  "suspicious_actions": [
    {
      "action_id": "apply-1",
      "reason": "实现方向与需求不一致",
      "precheck_finding_ids": [
        "precheck-finding-001"
      ],
      "document_refs": [
        {
          "path": "specs/button-shape/spec.md",
          "kind": "requirement",
          "anchor": "Requirement: Button shape"
        }
      ]
    }
  ],
  "suspicious_events": [
    {
      "event_id": "main:40",
      "action_id": "apply-1",
      "reason": "该步骤采用了错误实现方式"
    }
  ]
}
```

P0 的 `precheck_findings` 字段统一为：

```json
{
  "precheck_finding_id": "precheck-finding-001",
  "type": "verification_stale",
  "action_id": "apply-1",
  "event_ids": ["E50", "E55"],
  "target": "latest code changes",
  "expected": "最后一次修改后存在验证",
  "observed": "验证后又发生修改，之后没有重新验证"
}
```

P1 实施时同步把当前 P0 实现迁移到上述字段名和 ID 格式。

Agent 只返回引用 ID。后端诊断响应附带本次程序生成的 `precheck_findings`，前端再按 `precheck_finding_ids` 查找并展示；不要求 Agent 重复输出显性异常内容。

## 3. `document_refs` 规则

统一字段为 `path / kind / anchor`，路径均相对于当前 OpenSpec change 目录：

| 文档 | `kind` | `anchor` |
|---|---|---|
| `specs/*/spec.md` | `requirement` | 具体 Requirement 标题 |
| `proposal.md` | `section` | 具体章节标题 |
| `proposal.md` 整体 | `document` | `null` |
| `design.md` | `section` | 具体章节标题 |
| `design.md` 整体 | `document` | `null` |
| `tasks.md` | `task` | 完整 checklist 任务文本 |

示例：

```json
{
  "path": "tasks.md",
  "kind": "task",
  "anchor": "- [x] 修改按钮样式"
}
```

不使用行号。`proposal.md` 和 `design.md` 没有合适章节时允许引用整个文件；其他类型必须提供 `anchor`。

## 4. 后端校验

修改 `ccwhat/diagnosis/feedback.py`：

1. P0 的 `precheck_findings` 只生成一次，同时传给 Prompt 和结果校验器。
2. 保留现有 Action/Event 校验：
   - `action_id` 必须存在于 Action Graph；
   - `event_id` 必须存在于 Event Graph；
   - Event 与 Action 归属不一致时沿用现有修正逻辑。
3. `precheck_finding_ids`：每个 ID 必须存在于本次 P0 输出。
4. `document_refs`：
   - 禁止绝对路径和 `..`；
   - 路径解析后必须位于当前 change 目录；
   - 只允许 `proposal.md`、`design.md`、`tasks.md`、`specs/**/spec.md`；
   - `kind` 必须与文档类型匹配；
   - Requirement 标题、章节标题或 checklist 文本必须真实存在；
   - `kind=document` 只允许 `proposal.md` 或 `design.md`，且 `anchor=null`。
5. 引用去重。无效引用删除，并写入 `missing_evidence`。
6. 校验完成后，将本次 `precheck_findings` 作为诊断响应的辅助数据返回；前端只展示被 `precheck_finding_ids` 引用的记录。

校验只检查存在性和归属关系，不检查引用是否足以支持模型结论。

## 5. Prompt 调整

修改 `ccwhat/assets/graph_attribution_prompt.md`：

- 继续输出 `suspicious_actions / suspicious_events` 作为诊断结果。
- 允许可疑 Action 引用相关的 `precheck_finding_ids / document_refs`。
- `precheck_finding_ids` 只能来自输入的 `precheck_findings`。
- 文档引用必须按文档类型原样提取稳定的 `anchor`，不得使用行号。
- 没有证据时留空并写入 `missing_evidence`，不得编造。

不增加 LLM 调用次数、分数或置信度。

## 6. 前端最小改动

保持现有核心交互：

```text
高亮可疑 Action 粗节点
  -> 点击 Action
  -> 下钻到 Event Graph
  -> 高亮具体可疑 Event
```

仅在当前诊断详情中增加“诊断依据”：

- `precheck_finding`：展示 `type / expected / observed`。
- OpenSpec 文档：展示 `path / kind / anchor`。

不新增证据页面，不改变粗图/细图布局，不把文档或 `precheck_finding` 变成图节点或同级诊断对象。

## 7. 修改文件

后端与 Prompt：

- `ccwhat/diagnosis/precheck.py`：迁移 `precheck_finding_id` 字段和 ID 格式。
- `ccwhat/diagnosis/feedback.py`：校验并保留有效证据引用。
- `ccwhat/assets/graph_attribution_prompt.md`：更新输出契约与引用规则。

前端：

- `viewer/graph-diagnosis/src/types.ts`：增加两个可选字段、`precheck_findings` 辅助数据及引用类型。
- `viewer/graph-diagnosis/src/GraphDiagnosisApp.tsx`：在现有诊断详情中展示依据。
- `viewer/graph-diagnosis/src/graph-diagnosis.css`：仅补充诊断依据样式。

测试与文档：

- `tests/test_diagnosis_precheck.py`
- `tests/test_graph_feedback.py`
- `docs/improvements/evidence-backed-attribution/P0_IMPLEMENTATION_PLAN.md`
- `docs/improvements/evidence-backed-attribution/P1_IMPLEMENTATION_PLAN.md`
- `docs/improvements/diagnosis-improvement/graph-attribution-diagnosis-flow.md`

不修改 Action/Event Graph 构建、P0 规则判断、Marker、Session、Diff、Git Snapshot 或旧打分链路。

## 8. 验收标准

1. `precheck_findings` 使用 `precheck_finding_id: precheck-finding-NNN`。
2. 真实 Action/Event、`precheck_finding` 和文档引用被保留并展示。
3. 编造的 ID、路径、`kind` 或 `anchor` 被删除并写入 `missing_evidence`。
4. 绝对路径和路径逃逸被拒绝。
5. 旧结果缺少新增可选字段时，前端仍正常展示。
6. 粗图高亮、点击下钻和细图高亮交互保持不变。
7. 后端单测通过，前端 `typecheck` 和 `build` 通过。
