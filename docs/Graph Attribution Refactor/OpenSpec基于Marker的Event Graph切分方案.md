# OpenSpec 基于 Marker 的 Event Graph 切分方案

## 1. 结论

OpenSpec 归因诊断采用以下关系：

```text
OpenSpec change
├── 固定 Action Graph
└── Marker 定义的事件范围
      ↓
指定 Session 原始日志
      ↓
按 Marker 截取 Event
      ↓
生成该 change 独立的 Event Graph
```

核心原则：

1. Action Graph 使用 OpenSpec 固定流程节点，不依赖完整 Session。
2. 原始 Claude Code Session 日志不修改、不复制。
3. 一个 Session 可以执行多个 OpenSpec change。
4. 每个 change 通过独立 Marker 标记各 Action 的执行边界。
5. Event Graph 只包含 Marker 范围内的事件，不包含 Session 中无关对话和操作。
6. Session 只是原始日志来源，不再等同于一次 OpenSpec 执行。

---

## 2. 为什么不用 Hook

OpenSpec 当前通过 Skill / slash command 流程驱动 Agent：

- 显式输入 `/opsx:propose`、`/opsx:apply`、`/opsx:archive` 时，Claude Code 会加载对应 Skill/command 文档正文。
- 使用自然语言并成功触发对应 Skill 时，Agent 执行的也是同一套流程指令。

因此，Marker 命令直接写入 OpenSpec Skill / slash command 文档即可，不需要额外使用 Hook。

这种方式的取舍是：Marker 命令由 Agent 按 Skill 指令执行，而不是由 Hook 在系统层自动触发。当前 Agent 能力足以稳定执行固定流程命令，因此第一版采用 Skill 驱动方案。

---

## 3. Marker 标记什么

Marker 标记的不是日志文件行号，而是 OpenSpec 某个 Action 在 Session 事件流中的开始和结束位置。

例如进入 Apply：

```bash
ccwhat openspec-mark \
  --change add-auth \
  --action apply \
  --phase start \
  --marker-id 7f22c8d4
```

Apply 完成：

```bash
ccwhat openspec-mark \
  --change add-auth \
  --action apply \
  --phase end \
  --marker-id b83a0fa1
```

这两条命令本身会作为 Bash Tool Call 出现在 Claude Code 原始 Session 日志中，因此可以作为稳定的事件边界。

不要使用日志行号，原因是：

- 日志格式可能变化；
- 同一条逻辑事件可能展开为多条原始记录；
- 子 Agent、Tool Result 和重复事件会使文件行号不稳定；
- Event ID、Tool Call ID 和 Marker ID 更适合跨解析流程关联。

---

## 4. Marker 如何存储

Marker 元数据写入独立文件：

```text
openspec/changes/<change>/graph/markers.jsonl
```

示例：

```json
{"marker_id":"7f22c8d4","change":"add-auth","action":"apply","phase":"start","timestamp":"2026-07-10T10:00:00Z"}
{"marker_id":"b83a0fa1","change":"add-auth","action":"apply","phase":"end","timestamp":"2026-07-10T10:18:00Z"}
```

第一版至少包含：

```text
marker_id
change
 action
phase
 timestamp
```

其中真正用于回溯 Session 的关键字段是 `marker_id`。`timestamp` 只用于展示和辅助排查，不作为唯一定位依据。

---

## 5. Marker 如何和 Session 日志对应

执行 `ccwhat openspec-mark` 时，同时发生两件事：

1. CCWhat 将 Marker 元数据追加到 `markers.jsonl`。
2. Agent 执行的 Bash 命令被 Claude Code 正常记录到原始 Session 日志中。

生成 Event Graph 时：

1. 用户或程序提供 `session_id` 和 `change`。
2. 读取 `openspec/changes/<change>/graph/markers.jsonl`。
3. 读取该 `session_id` 对应的原始 Claude Code 日志。
4. 在 Bash Tool Call 事件中搜索 `marker_id`。
5. 获取 Marker 对应的标准化 `event_id`、事件序号或 `tool_call_id`。
6. 按 start/end Marker 截取事件范围。
7. 将截取出的事件挂到对应 Action 节点。
8. 生成该 change 的 `event_graph.json`。

示意：

```text
Session Event Stream

E100  普通对话，与 OpenSpec 无关
E101  marker: change=add-auth action=apply phase=start
E102  Read spec
E103  Edit src/auth.py
E104  Run pytest
E105  Tool result: failed
E106  Edit src/auth.py
E107  Run pytest
E108  Tool result: passed
E109  marker: change=add-auth action=apply phase=end
E110  讨论另一个 change

Event Graph 只提取 E102-E108。
```

Marker 自身可以保留为边界事件，也可以在最终 Event Graph 中隐藏；第一版建议保留，但标记为 `marker` 类型，方便调试。

---

## 6. Action Graph 和 Event Graph 的关系

### 6.1 Action Graph

Action Graph 使用固定 OpenSpec 流程：

```text
Proposal → Specs → Design → Tasks → Apply → Verify → Archive
```

每个 Action 节点表示流程阶段，不表示整个 Session。

### 6.2 Event Graph

Event Graph 表示本次 change 在真实 Session 中发生的具体操作：

```text
Action: Apply
├── Read tasks.md
├── Read source file
├── Edit source file
├── Run tests
├── Observe failure
├── Edit source file
└── Run tests successfully
```

Action 与 Event 的绑定主要依赖 Marker 范围，不再依赖“整个 Session 都属于一个 OpenSpec”这一假设。

---

## 7. Skill 文档中的集成方式

需要在 OpenSpec 对应流程文档的固定位置加入 Marker 命令。

例如 `/opsx:apply`：

```text
选择 change
  ↓
openspec-mark apply start
  ↓
读取上下文、实现任务、运行验证
  ↓
openspec-mark apply end
```

建议覆盖：

```text
propose
specs
 design
 tasks
apply
verify
archive
```

对于一次 Skill 内包含多个 Action 的流程，应分别写各自的 start/end Marker，而不是只给整个 Skill 写一对 Marker。

例如 `/opsx:propose` 可能连续创建 Proposal、Specs、Design 和 Tasks，则每个产物阶段单独打标。

---

## 8. 一个 Session 执行多个 Change

同一个 Session 可以出现：

```text
change-a / apply
change-b / propose
change-a / verify
change-c / apply
```

每条 Marker 都携带 `change + action + phase + marker_id`，因此生成图时可以精确筛选：

```text
change-a
├── apply 范围
└── verify 范围

change-b
└── propose 范围

change-c
└── apply 范围
```

这解决了当前 MVP 将整个 Session 全部转换为 Event Graph，导致无关对话和多个 change 混入同一张图的问题。

---

## 9. 诊断阶段

Event Graph 生成完成后，诊断阶段只使用：

```text
action_graph.json
event_graph.json
用户反馈
```

诊断接口不需要再次扫描整个 Session。

但 Event Graph 重新生成、补充或修复时，仍需要：

```text
session_id
markers.jsonl
原始 Session 日志
```

因此，Session 是 Event Graph 的原始数据来源，但不是 OpenSpec 归因诊断的业务主体。

---

## 10. 当前 MVP 的改造顺序

1. 新增 `ccwhat openspec-mark` CLI。
2. Marker 同时写入 `markers.jsonl`，并通过 Bash Tool Call 留在原始 Session 日志。
3. 在 OpenSpec Skill / slash command 文档中加入 Marker 命令。
4. 修改 Event Graph 生成逻辑：不再默认使用完整 Session。
5. 根据 Marker ID 定位 start/end 事件。
6. 按 Action 分段提取 Session Event。
7. 未命中 Marker 时明确报错，不静默退回整个 Session。
8. 保留现有完整 Session 生成方式作为临时兼容入口，后续删除。

---

## 11. 最终定义

> Action Graph 描述 OpenSpec 应执行哪些固定阶段；Skill 在每个阶段边界执行 Marker 命令；CCWhat 通过 Marker 从指定 Session 的原始日志中提取属于该 change 的事件，并生成独立 Event Graph。原始 Session 不修改、不复制，一个 Session 可以同时承载多个 OpenSpec change。