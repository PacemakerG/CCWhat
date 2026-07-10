# 基于 CC 原始 Session 的 OpenSpec 归因诊断 MVP 计划

## 1. MVP 目标

用最短路径验证一个核心产品假设：

> 在一个 Claude Code Session 只运行一个 OpenSpec 流程的前提下，系统能否根据用户反馈，先定位可疑的 OpenSpec Action，再从该 Action 关联的具体 Tool/Event 中指出可疑步骤，并生成一份用户认为有帮助的诊断报告。

本 MVP 保留现有“粗图 + 细图”结构，不重做整套归因基础设施：

```text
Claude Code 原始 Session 日志
  -> Normalized Events
  -> 固定 OpenSpec 七节点粗图
  -> Event 细图与 Event->Action 映射

用户问题反馈
  + 粗图摘要
  + 细图事件摘要
  -> 一次受约束的 LLM 诊断
  -> 可疑 Action + 可疑 Event + 诊断报告
```

MVP 成功的标准不是“证明真实根因”，而是跑通并验证下面的闭环：

```text
用户反馈
  -> 粗粒度流程定位
  -> 细粒度日志定位
  -> 可回到原始证据的解释
```

## 2. 已确认的 MVP 前提

### 2.1 一个 Session 只运行一个 OpenSpec 流程

MVP 明确假设：

- 一个 Claude Code Session 只处理一个 OpenSpec change。
- Session 中的代码修改、验证命令和最终回复均属于该 change。
- 不处理一个 Session 混合多个 change 或多个独立任务的情况。
- 不引入 Task Segmentation 或 Runtime Task 来解决边界问题。

因此 MVP 输入只需要：

```json
{
  "session_id": "claude-session-id",
  "change": "add-symptom-routed-graph-attribution"
}
```

如果以后实际数据证明“一 Session 一 change”经常不成立，再单独讨论任务边界，不在 MVP 中提前解决。

### 2.2 唯一事实源是 CC 原始日志

MVP 的执行证据只来自 Claude Code 原始 Session 日志，经现有 Claude Adapter 和 normalized event 链路抽取。

暂不联动：

- Runtime Task。
- `/ccwhat:start`、`/ccwhat:finish`。
- Task Dataset。
- Dataset export。
- `task.diff`。
- Runtime staging 中的 task metadata。
- 逐步 Git diff 或 Hook 回传。

原始 CC 日志负责提供：

- 用户消息。
- Assistant 文本。
- Tool Call。
- Tool Result。
- 文件路径。
- Edit/Write 输入摘要。
- Bash command。
- 命令输出和错误信息。
- final claim。
- 时间、turn 和 agent 信息。

MVP 接受以下限制：

- 无法用最终 diff 判断某次 Edit 是否后来被撤回。
- 无法证明日志中的修改就是最终仓库状态。
- 无法识别 Session 外部的并发修改。
- ignored file、二进制产物和非日志操作可能不可见。

报告中应把结果称为“基于 Session 行为证据的诊断”，不能声称已验证最终仓库真相。

## 3. 奥卡姆剃刀原则

MVP 采用以下判断标准：

```text
现有模型能表达 -> 不新增实体
现有字段小改能解决 -> 不新建抽象
没有真实失败案例 -> 不提前设计扩展
不是闭环必需 -> 不进入 MVP
```

当前只保留四个核心实体：

```text
Action
Event
User Feedback
Diagnosis Result
```

明确不新增：

- Action Contract。
- Action Run。
- Workflow Template Adapter。
- Artifact/Artifact Version 节点。
- Requirement 节点。
- Outcome 节点。
- Signal Registry。
- 多信号投票框架。
- 反事实执行框架。
- Reference Trace 系统。

这些设计保留在远期文档中，只有出现明确需求时才讨论。

## 4. MVP 总体架构

```text
+-------------------------+
| Claude Code raw session |
+------------+------------+
             |
             v
+-------------------------+
| Normalize session events|
+------------+------------+
             |
             +--------------------------+
             |                          |
             v                          v
+-------------------------+   +-------------------------+
| Fixed OpenSpec Actions  |   | Event Graph             |
| A1..A7                  |   | Tool/Event nodes        |
+------------+------------+   +------------+------------+
             |                             |
             +---------- mapping ----------+
                           |
                           v
                 +-------------------+
                 | User Feedback     |
                 +---------+---------+
                           |
                           v
                 +-------------------+
                 | One LLM Call      |
                 | structured output |
                 +---------+---------+
                           |
                           v
                 +-------------------+
                 | Diagnosis Result  |
                 | Action/Event refs |
                 +-------------------+
```

## 5. 粗图 MVP

### 5.1 保留当前七节点

直接复用：

```text
A1 Proposal
A2 Specs
A3 Design
A4 Tasks
A5 Apply
A6 Verify
A7 Archive
```

MVP 不增加 contract，不区分多个 Apply/Verify 实例，不抽象多模板。

每个 Action 继续作为：

- OpenSpec 流程阶段的展示节点。
- 对应 Event 的聚合容器。
- 用户反馈诊断时的候选搜索范围。

### 5.2 只做必要状态简化

Action 状态只保留：

```text
observed      有 Event 映射到该 Action
not_observed  没有观察到相关 Event
failed        该 Action 内存在明确失败证据
```

MVP 不输出 `skipped`。没有 Event 只能说明 `not_observed`，不能证明 Agent 跳过了该阶段。

Archive 尚未发生也不自动产生高严重度问题。

### 5.3 粗图边的职责

保留固定流程边用于展示：

```text
proposal -> specs -> design -> tasks -> apply -> verify -> archive
```

这些边只表示 OpenSpec 预期顺序，不用于：

- 计算根因距离。
- 沿上游自动传播 suspicion score。
- 把所有前置 Action 都变成可疑节点。
- 声称实际因果关系。

### 5.4 粗图输出

```json
{
  "workflow": "openspec",
  "actions": [
    {
      "action_id": "A5",
      "type": "apply",
      "label": "Apply",
      "status": "observed",
      "event_ids": ["E31", "E32", "E40"],
      "evidence": [
        {
          "reason": "source file edit",
          "event_ids": ["E31", "E40"]
        }
      ]
    }
  ],
  "edges": [
    {
      "from": "A4",
      "to": "A5",
      "type": "workflow_expected"
    }
  ]
}
```

MVP 删除对外 `suspicion_score`，可疑程度只出现在用户反馈后的 Diagnosis Result 中。

## 6. 细图 MVP

### 6.1 节点范围

只使用 normalized session event，不增加 Artifact 或 Outcome 节点。

节点类型：

```text
user_message
assistant_text
tool_call
tool_result
file_read
file_edit
command
error
final_claim
```

### 6.2 节点最小字段

```json
{
  "event_id": "E40",
  "type": "file_edit",
  "timestamp": "...",
  "turn_index": 8,
  "agent_id": "main",
  "tool_name": "Edit",
  "tool_call_id": "toolu_123",
  "files": ["ccwhat/diagnosis/attribution.py"],
  "command": null,
  "text": "Edit attribution scoring",
  "result_summary": "updated successfully",
  "is_error": false,
  "raw_ref": {
    "session_id": "...",
    "line": 142
  }
}
```

必须修正或保证：

1. 每个 Event ID 在图中唯一；一条原始日志里有多个 Tool Use 时不能复用同一个节点 ID。
2. Tool Call 和 Tool Result 能通过 `tool_call_id` 配对。
3. Edit/Write 保留文件路径和修改摘要。
4. Bash 保留 command，Result 保留成功/失败和错误摘要。
5. `raw_ref` 能定位回原始 Session 日志。
6. 不因构图而丢掉 Tool input/result 中对诊断有价值的字段。

### 6.3 MVP 边类型

只保留确定或低争议关系：

```text
next             同一 Session 中的事件顺序
tool_result_of   Tool Call 与 Tool Result 的精确关系
mapped_to        Event 到 Action 的映射关系
```

第一版不实现：

- 通用因果边。
- Artifact dependency。
- command validates artifact。
- claim supports/contradicts outcome。
- 自动 `edit -> failed command` 因果关系。

如果实现成本很低，可以保留 `same_file_context` 作为辅助检索关系，但必须明确它只是同文件关联，不是因果边。

### 6.4 Event 到 Action 的映射

沿用现有 path/command/tool 规则，做小范围修正：

| Event 证据 | Action |
|---|---|
| 编辑当前 change 的 `proposal.md` | Proposal |
| 编辑当前 change 的 `specs/**/spec.md` | Specs |
| 编辑当前 change 的 `design.md` | Design |
| 编辑当前 change 的 `tasks.md` | Tasks |
| 编辑非 OpenSpec 源码文件 | Apply |
| 测试、build、lint、`openspec validate` 命令 | Verify |
| `openspec archive` 命令 | Archive |

需要避免：

- 只读取 `proposal.md` 就把 Proposal 判定为已完成。
- Assistant 文本中提到 `openspec validate` 就映射为 Verify。
- 无法映射的 Event 被丢弃。

映射结果保存原因：

```json
{
  "event_id": "E40",
  "action_id": "A5",
  "reason": "edited non-OpenSpec source file",
  "confidence": "high"
}
```

无法映射的 Event 保留在细图中，`action_id` 为 `null`。

## 7. 用户反馈 MVP

### 7.1 反馈输入

第一版只要求一个文本框：

```json
{
  "session_id": "...",
  "change": "...",
  "feedback": "实现完成了，但是点击按钮后仍然跳转到错误页面"
}
```

暂不增加 expected/observed、附件、artifact hint 等独立字段。LLM 可以从反馈中尝试提取；提取不到就在结果中说明信息不足。

### 7.2 一次 LLM 调用

MVP 不拆分“反馈路由模型”和“证据审阅模型”。一次调用同时完成：

1. 理解用户描述的 symptom。
2. 选择 Top-K 可疑 Action。
3. 从已有 Event 中选择可疑细节点。
4. 生成基于证据的解释和缺失信息。

程序提供给 LLM：

- 用户反馈。
- OpenSpec 七节点摘要。
- 每个 Action 的状态和映射 Event。
- Event 的 ID、type、tool、files、command、文本/结果摘要和错误标记。
- 未映射但可能相关的 Event。

不向 LLM 提供未经裁剪的完整原始日志。构建 compact context 时：

- 始终保留 user message、file edit、command、error、final claim。
- Tool Result 保留结果摘要和错误信息。
- Read 事件只保留路径和短摘要。
- 普通 Assistant 文本可截断。
- 超过上下文预算时，优先删除低信息量的重复 Read/Assistant 事件。

### 7.3 LLM 输出契约

要求严格 JSON：

```json
{
  "symptoms": [
    {
      "type": "wrong_output",
      "summary": "点击跳转行为不符合用户预期"
    }
  ],
  "suspicious_actions": [
    {
      "action_id": "A5",
      "reason": "Apply 阶段修改了相关路由文件"
    },
    {
      "action_id": "A6",
      "reason": "Verify 阶段没有覆盖点击跳转行为"
    }
  ],
  "suspicious_events": [
    {
      "event_id": "E40",
      "action_id": "A5",
      "reason": "该 Edit 修改了按钮目标路由"
    }
  ],
  "missing_evidence": [
    "Session 中没有发现点击行为验证"
  ],
  "summary": "最可疑的是 Apply 中的路由修改，同时 Verify 没有覆盖该行为。"
}
```

### 7.4 LLM 输出校验

程序必须：

1. 校验所有 `action_id` 存在于固定七节点中。
2. 校验所有 `event_id` 存在于当前 Event Graph 中。
3. 校验 `event_id` 的实际映射与返回的 `action_id` 一致；不一致时保留 Event，但修正或标记冲突。
4. 删除 LLM 编造的 ID。
5. 如果删除后没有可疑 Event，输出 `insufficient_evidence`，不能伪造替代证据。

MVP 不要求 LLM 给出数值分数。

## 8. 诊断报告 MVP

报告只包含五部分：

```text
1. 用户问题理解
2. 最可疑的 OpenSpec 阶段
3. 可疑的具体 Event
4. 证据不足与替代解释
5. 建议下一步检查
```

Viewer 最小交互：

- 用户选择或输入 change/session。
- 展示粗图和细图。
- 用户输入问题反馈。
- 点击“生成诊断”。
- 报告中的 Action 可高亮粗图节点。
- 报告中的 Event 可高亮细图节点或跳转原始日志。

不做：

- 诊断历史管理。
- 用户反馈训练闭环。
- 可视化调参。
- 自动修改代码。
- 自动反事实复跑。

## 9. 实现阶段

### Phase 1：加固 CC Event Graph

1. 以 Claude Code 原始 Session 为唯一输入。
2. 修复 Event ID 唯一性。
3. 补齐 Tool input/result、文件、command、error、raw reference。
4. 保留 `next` 和 `tool_result_of`。
5. 添加针对真实 Claude Session fixture 的图结构测试。

完成条件：细图能稳定还原一次 Session 中的主要 Tool/Event，并可回到原始日志。

### Phase 2：微调现有粗图与映射

1. 保留固定 OpenSpec 七节点。
2. Action 状态简化为 `observed/not_observed/failed`。
3. 删除或停止使用 Action 反向归因分数。
4. 修复 read/edit、Assistant 文本/command 的映射误判。
5. 无法映射的 Event 继续保留。

完成条件：粗图能合理聚合 Proposal/Specs/Design/Tasks/Apply/Verify/Archive Event，不再把流程缺证据直接包装成根因。

### Phase 3：搭建用户反馈与 LLM 诊断

1. 增加 feedback 输入。
2. 构建 compact diagnosis context。
3. 调用一次 LLM，要求严格 JSON。
4. 校验 Action/Event 引用。
5. 输出结构化 Diagnosis Result。

完成条件：给定一个已知问题的 Session 和用户反馈，返回至少一个真实 Action/Event 引用，或者诚实返回证据不足。

### Phase 4：Viewer 与端到端验收

1. 展示诊断报告。
2. Action/Event 引用可定位到对应图节点。
3. 准备 5-8 个真实或高度接近真实的 Session fixture。
4. 人工判断报告是否帮助定位问题。

完成条件：完整跑通“加载 Session -> 查看双图 -> 输入反馈 -> 获取可定位报告”的产品闭环。

## 10. 测试与验收

### 10.1 图数据测试

- Event ID 唯一。
- Tool Call/Result 正确配对。
- file/edit/command/error 字段未丢失。
- raw reference 有效。
- Event 到 Action 映射理由正确。
- 未映射 Event 不丢失。

### 10.2 反馈诊断场景

至少准备：

1. 明确测试失败。
2. Tool error 被忽略后 claim 完成。
3. 用户报告 wrong output，相关 Edit 可在日志中找到。
4. 用户报告 wrong output，但 Verify 没有对应覆盖。
5. 用户反馈过于模糊，应返回证据不足。
6. LLM 返回不存在的 Event ID，应被校验层删除。
7. Session 中没有 final claim 或没有 Verify。
8. Apply 中存在多次修改，报告应能引用具体 Event。

### 10.3 MVP 验收标准

MVP 完成必须同时满足：

- 只依赖 CC 原始 Session 日志即可运行。
- 固定七节点粗图可用。
- 细图可显示具体 Tool/Event 和结果。
- 用户可以输入自然语言反馈。
- LLM 输出至少能定位真实 Action/Event，或明确拒绝判断。
- 报告中的所有 ID 都能回到图节点和原始日志。
- 不依赖 Runtime Task、Dataset 或 `task.diff`。

MVP 不以自动诊断准确率达到某个数值为完成条件。第一阶段先验证用户是否认为这种“粗到细、可回看证据”的报告有价值。

## 11. 明确非目标

本 MVP 不做：

- 重构固定七节点为 Action Contract。
- 多轮 Action Run 实例化。
- Superpowers 或其他模板。
- 多 Session/多 change 边界。
- Runtime Task 联动。
- Dataset 读写与导出。
- `task.diff` 联动。
- Artifact/Requirement/Outcome 图。
- 复杂因果边。
- 规则投票与权重调参。
- 数值 root-cause score。
- 两阶段或多 Agent 诊断。
- 反事实执行和成功/失败 trace 对齐。
- 自动修复。

## 12. MVP 后的决策门槛

后续是否增加实体，必须由 MVP 暴露出的真实问题驱动。

### 12.1 是否改造粗图

只有出现以下问题才考虑 Action Contract 或 Action Run：

- 多轮 Apply/Verify 聚合后无法定位具体阶段。
- `not_observed` 无法表达真实流程状态，持续产生用户误解。
- 需要判断条件性 required、输入输出或阶段完成质量。
- 第二种模板接入证明固定七节点已成为阻塞。

否则继续保留当前粗图。

### 12.2 是否联动 Runtime Task

只有出现以下问题才考虑：

- 一 Session 一 change 假设在真实使用中频繁失败。
- 原始日志无法稳定确定诊断范围。
- 必须关联明确的 start/finish 边界。

如果 Session 本身足够确定范围，就不引入 Runtime Task。

### 12.3 是否联动 Dataset

只有出现以下需求才考虑：

- 需要保存、共享或离线复现诊断样本。
- 需要批量评测诊断准确率。
- 需要长期积累标注数据。
- 需要跨版本比较同一批 Session。

在线单 Session 诊断不以 Dataset 为前置条件。

### 12.4 是否联动 `task.diff`

只有出现以下问题才考虑：

- 日志中的 Edit 无法代表最终仓库状态。
- 用户明确需要判断某次修改最终是否保留。
- 需要把 final claim 与最终代码变化交叉验证。

在 Runtime Task 的 diff 能力稳定前，不把它引入 MVP 主链路。

### 12.5 是否升级细图

只有在用户反馈无法稳定关联到具体 Event 时，才考虑增加：

- Artifact 节点。
- Requirement 节点。
- Outcome 节点。
- 更复杂的 dependency/causal edge。

优先先验证“Event 字段完整 + LLM 语义分析”是否已经足够。

## 13. 最终执行原则

```text
先跑通 CC 原始日志 -> 双图 -> 用户反馈 -> 报告。
粗图能用就不重构。
细图先保证信息完整，不追求完整因果图。
一次 LLM 调用能解决就不拆两次。
Session 能提供边界就不接 Runtime Task。
在线诊断不需要 Dataset 就不接 Dataset。
没有真实问题证明必要，就不新增实体。
```

这个 MVP 的价值是尽快验证用户是否需要、是否信任、是否愿意使用“模板粗图定位 + 原始日志细图定位 + 用户反馈语义诊断”这条链路。验证成立后，再基于真实失败案例决定下一步，而不是从远期架构倒推当前实现。
