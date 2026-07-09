# Graph 归因图改造计划

## 背景

本次讨论围绕 CCWhat 当前的因果图、因果链和 DAG 诊断能力展开。项目已经有两层图：

- 细图：Event Graph
- 粗图：Action Graph

用户的预期是：细图应从 Cloud/Claude session 原始日志中抽取每一个 step，例如用户消息、assistant 文本、tool call、tool result、命令、文件读写、错误和 final claim；粗图则应固定为 OpenSpec 工作流 Action，用于承载反向诊断和因果归因。

当前实现与预期存在偏差：OpenSpec viewer 中展示的 Event Graph 不是 session 原始 step 级别，而是 artifact/milestone 级别，因此细图粒度过粗。

## 本轮需求理解

目标不是重新设计 OpenSpec Action Graph，而是增强 Event Graph 的数据来源和绑定方式。

期望的数据流应为：

```text
Cloud/Claude session 原始日志
  -> normalize 成 step 级事件
  -> 构建细粒度 Event Graph
  -> 映射到固定 OpenSpec Action Graph
  -> 基于 Action DAG 做 symptoms 检测和反向 causal attribution
```

其中粗图固定为 OpenSpec Action：

```text
proposal -> specs -> design -> tasks -> apply -> verify -> archive
```

细图需要覆盖每个 session step，而不是只覆盖人工记录的 workflow milestone。

## 当前实现观察

### OpenSpec graph sync 路径

`ccwhat/openspec_graph.py` 当前的同步路径为：

```text
openspec/changes/<change>/graph/events.jsonl
  -> _build_event_graph()
  -> _build_action_graph()
  -> diagnosis.json
```

`_build_event_graph()` 目前生成的节点主要包括：

- `artifact_present`
- `change_created`
- `artifact_created`
- `code_changed`
- `task_completed`
- `validate_ran`

这条路径不读取 Cloud/Claude session 原始日志，所以它生成的 Event Graph 天然不是 step 级细图。

### Dataset diagnosis 路径

`ccwhat/diagnosis/event_graph.py` 已经能从 Dataset trace events 构建更细粒度的 Event Graph，包括：

- temporal
- tool_result_of
- reads_before_edit
- edit_before_command
- command_produces_error
- claim_after_action

`ccwhat/diagnosis/mapping.py` 已经能把细事件映射到 OpenSpec Action，包括：

- OpenSpec artifact path 映射到 proposal/specs/design/tasks
- code edit 映射到 apply
- openspec validate 或测试命令映射到 verify
- openspec archive 映射到 archive
- 无法识别的事件保留为 `ad_hoc_turn`

这条路径更接近目标，但它目前依赖 Dataset trace，而不是 OpenSpec viewer graph sync 直接消费 session。

### Session normalization 能力

`ccwhat/task_segments/events.py` 已经具备把 session 日志 normalize 成 `NormalizedEvent` 的能力：

- Claude main entries
- subagent entries
- Codex/OpenCode adapter-normalized events
- assistant tool_use 拆成 tool_call
- user tool_result 拆成 tool_result
- 保留 `raw_ref` 作为原始证据引用

这说明“step 级 Event Graph”的原料已经存在，主要缺的是与 OpenSpec graph 展示和归因链路的绑定。

## 问题定义

当前的问题可以拆成三层：

1. Event Graph 粒度错误
   - 当前 OpenSpec viewer 细图是 artifact/milestone 粒度。
   - 目标细图应是 session step 粒度。

2. 数据源路径分裂
   - OpenSpec graph sync 读 `graph/events.jsonl`。
   - Dataset diagnosis 读 Dataset trace events。
   - Session viewer 读 Cloud/Claude session。
   - 三者没有统一到同一条诊断图生成链路。

3. OpenSpec change 与 session/task 的绑定缺失
   - OpenSpec change name 本身无法唯一定位对应 session 或 task segment。
   - 需要明确绑定来源：`sessionId`、`taskId`、Dataset registry，或 graph sync 显式参数。

## 改造目标

### 目标 1：细图使用 session step

Event Graph SHALL 优先使用 session 原始 step 归一化后的事件作为节点来源。

节点应至少保留：

- event id
- event type
- timestamp
- agent id
- turn index
- tool name
- tool call id
- command
- files
- text/summary
- raw evidence reference

### 目标 2：粗图仍然固定 OpenSpec Action

Action Graph SHALL 继续使用固定 OpenSpec workflow 模板：

```text
A1 proposal
A2 specs
A3 design
A4 tasks
A5 apply
A6 verify
A7 archive
```

Action Graph 不应从日志中自由生成，避免把粗图变成不可控的语义分类结果。

### 目标 3：细图到粗图建立可解释映射

每个 Action 节点应通过 `event_ids` 绑定细图节点，并记录映射原因：

- `path: openspec/changes/*/proposal.md`
- `path: openspec/changes/*/specs/**/spec.md`
- `path: openspec/changes/*/design.md`
- `path: openspec/changes/*/tasks.md`
- `command: openspec_validate`
- `command: test`
- `command: openspec_archive`
- `event: file_change`
- `unmapped_turn`

### 目标 4：反向诊断基于 Action DAG

症状检测和 causal attribution 仍然基于 Action Graph，而不是直接在大量 step 节点上打分。

Event Graph 负责提供事实证据；Action Graph 负责表达 OpenSpec 流程预期和归因路径。

## 建议改造方案

### 阶段 1：明确绑定模型

新增 OpenSpec graph 与 session/task 的绑定元数据，例如：

```json
{
  "change": "some-openspec-change",
  "sessionId": "xxx",
  "taskId": "task-001",
  "datasetId": "dataset-..."
}
```

优先级建议：

1. 如果已有 Dataset task，直接使用 Dataset trace。
2. 如果只有 sessionId 和 task boundary，则从 session normalize events 后切片。
3. 如果只有 sessionId，则允许生成 session 全量 Event Graph，但诊断可信度标记为较低。

### 阶段 2：复用现有诊断构建器

OpenSpec graph sync 不应再单独维护一套 artifact/milestone Event Graph 逻辑。建议复用：

- `ccwhat.task_segments.events.normalize_session_events`
- `ccwhat.diagnosis.event_graph.build_event_graph`
- `ccwhat.diagnosis.action_graph.build_openspec_action_graph`
- `ccwhat.diagnosis.mapping.map_events_to_actions`
- `ccwhat.diagnosis.symptoms.detect_symptoms`
- `ccwhat.diagnosis.attribution.attribute_symptoms`

这样可以减少两套图语义漂移。

### 阶段 3：保留 artifact/milestone 作为补充证据

现有 `artifact_present` 和 `graph/events.jsonl` milestone 不需要立即删除，但它们不应作为细图主干。

建议把它们作为：

- Action evidence
- graph metadata
- fallback evidence

当没有 session trace 时，才退回到 artifact/milestone 图，并在 `missing_evidence` 中明确说明缺少 session step evidence。

### 阶段 4：Viewer 展示调整

Diagnostics 页面中的 Event Graph 应展示 step 级节点：

- 按时间或 turn 排列
- 区分 message/tool_call/tool_result/command/file_edit/error/final_claim
- 点击 Action 节点时高亮映射的 Event 节点
- 点击 Event 节点时显示 raw_ref 摘要和映射原因

Action Graph 保持横向 OpenSpec 流程图，但节点状态来自 step evidence，而不是 artifact 文件存在。

## 验收标准

1. 对一个真实 Cloud/Claude session，Event Graph 节点数量应接近 normalized session events 数量，而不是只有 artifact/milestone 数量。
2. OpenSpec Action Graph 仍然只包含固定七个 required action。
3. proposal/specs/design/tasks/apply/verify/archive 能通过 session step evidence 映射为 observed/missing/failed。
4. 没有对应 session 或 task trace 时，diagnosis 必须在 `missing_evidence` 中明确说明，而不是假装细图完整。
5. Viewer 中加载 OpenSpec graph 时，用户能看到 step 级细图和 Action 粗图之间的绑定关系。

## 需要进一步确认的问题

1. 细图范围是整个 session，还是只取某个 task segment？
2. OpenSpec change 与 session/task 的绑定由谁提供？
3. 现有 `graph/events.jsonl` 是否继续作为 milestone 审计日志保留？
4. 如果一个 session 中包含多个 OpenSpec change，如何区分事件归属？
5. 是否需要支持手动修正 event-to-action mapping？

## 初步实施建议

建议新开一个 OpenSpec change，例如：

```text
refactor-graph-attribution-to-session-step-events
```

任务切分建议：

1. 设计 graph source binding schema。
2. 为 OpenSpec graph sync 增加 session/task trace 输入能力。
3. 将 OpenSpec graph sync 的 Event Graph 构建切到 diagnosis event graph builder。
4. 复用现有 event-to-action mapping 和 symptoms/attribution。
5. 更新 Viewer，展示 step 级 Event Graph 与 Action 映射。
6. 添加真实 session fixture 或最小 mock session 测试。

## 结论

当前系统已经有大部分底座，但 OpenSpec viewer graph path 走的是 milestone 级证据，因此细图不符合预期。改造方向应是统一到 session step evidence：细图从 Cloud/Claude session normalized events 来，粗图保持固定 OpenSpec Action DAG，归因仍从症状节点沿 Action DAG 反向传播。
