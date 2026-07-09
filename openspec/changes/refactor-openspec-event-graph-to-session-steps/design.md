## Context

现有系统已经有三块底座：

- `ccwhat.task_segments.events` 能把 session 日志 normalize 成 step 级事件。
- `ccwhat.diagnosis.*` 已有 Event Graph、Action Graph、mapping、symptoms 和 attribution。
- `ccwhat openspec-graph sync` 已能在 `openspec/changes/<change>/graph/` 下写 graph JSON。

问题在于 OpenSpec graph sync 当前主要读取 `graph/events.jsonl` milestone，导致 Viewer 里的 Event Graph 不是 step 级细图。

## Decisions

### Decision: 两层图职责不变

- Action Graph 表示 OpenSpec 流程责任区，仍固定为七个 required action。
- Event Graph 表示事实证据，节点来自 session normalized steps 或 Dataset trace events。
- 本 change 只保证 Action 和 Event 之间有可解释映射，不重新设计 attribution scoring。

### Decision: source binding 是必需元数据

OpenSpec change 本身不能唯一确定 session 或 task，因此 graph 需要绑定来源：

```json
{
  "change": "some-change",
  "session_id": "session-uuid",
  "task_id": "task-001",
  "dataset_id": "dataset-id",
  "source_kind": "dataset_task|session_task|session_full|milestone_fallback"
}
```

优先级：

1. Dataset task trace。
2. Session normalized events + task boundary。
3. Session normalized events 全量。
4. milestone/artifact fallback。

### Decision: 旧 milestone 图降级为 fallback

`graph/events.jsonl` 仍保留为 OpenSpec workflow 审计日志，但它不能再作为 Event Graph 主干。只有无法拿到 session step evidence 时，才使用 milestone/artifact fallback，并在输出里明确说明。

## Data Flow

```text
OpenSpec change name
  -> resolve graph source binding
  -> load Dataset trace or session normalized steps
  -> build step-level Event Graph
  -> instantiate fixed OpenSpec Action Graph
  -> map Events to Actions with reasons
  -> write event_graph.json and action_graph.json
  -> write metadata/missing_evidence for graph completeness
```

## Risks

- change 与 session/task 绑定缺失时不能生成可信 step 级细图，必须在 `missing_evidence` 中说明。
- session 全量图可能很大，Viewer 第一版需要限制渲染数量或提供过滤。
- 旧 `ccwhat/diagnosis` 中已有 attribution MVP，后续 change 会单独决定保留、重写或删除哪些部分，避免本 change 继续扩大诊断逻辑。
