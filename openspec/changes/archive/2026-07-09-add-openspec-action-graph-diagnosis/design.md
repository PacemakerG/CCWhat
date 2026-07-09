## Context

本 change 以 Dataset v1 为输入。Dataset trace 已包含 task 范围内的 events、commands、test_commands、files、changes、patches、errors 和 final_claim。OpenSpec 流程固定，因此粗图不需要从日志中猜测，而应从 OpenSpec workflow 模板实例化。

## Decisions

### Decision: 两层图

- Event Graph 表示事实证据，节点来自 trace events，边来自时间顺序、工具调用结果、文件读写、命令错误和 final claim。
- Action Graph 表示 OpenSpec 流程，节点固定为 proposal、specs、design、tasks、apply、verify、archive。
- Action 节点通过 `event_ids` 绑定 Event Graph。缺失 Action 节点没有事件，但必须说明 `expected_because`。

### Decision: 第一版只输出 JSON

CLI 写入：

- `event_graph.json`
- `action_graph.json`
- `diagnosis.json`

Viewer、HTML 报告和图形可视化后续另开 change。

### Decision: 不调用 LLM

第一版只做规则可解释归因，避免把不稳定语义判断混入图构建 MVP。CLI 接受 `--no-llm`，默认即为 no-LLM；如果用户显式启用 LLM，应返回清晰错误。

## Data Flow

### Dataset diagnosis path

```text
Dataset v1 directory/tar
  -> select dataset row by task_id
  -> load trace
  -> build Event Graph
  -> instantiate OpenSpec Action Graph
  -> map events to actions
  -> detect symptoms
  -> backward attribution scoring
  -> write JSON outputs
```

### OpenSpec workflow path

```text
OpenSpec skill / slash command
  -> write proposal/spec/design/tasks or complete task
  -> append graph/events.jsonl milestone
  -> ccwhat openspec-graph sync --change <name>
  -> write graph/event_graph.json, graph/action_graph.json, graph/diagnosis.json
```

OpenSpec workflow path is the preferred manual acceptance path because graph generation is bound to the OpenSpec process itself instead of CCWhat runtime start/finish.

## Scoring

每个候选 Action 的分数由确定性规则组成：

- 确定性缺失证据：+40
- 距离症状 1 跳：+25，每远一跳递减 5
- 证据强度 high/medium/low：+20/+12/+5
- 时间顺序合理：+10
- 下游影响节点数：最多 +5

总分裁剪到 `0..100`。`>=80` 为 high，`50..79` 为 medium，否则 low。

## Risks

- Dataset trace 中可能没有足够原始事件。此时诊断必须把缺失证据写入 `missing_evidence`，不能编造。
- OpenSpec action mapping 可能不完整。未识别事件会进入 `ad_hoc_turn`，保留证据而不是丢弃。
