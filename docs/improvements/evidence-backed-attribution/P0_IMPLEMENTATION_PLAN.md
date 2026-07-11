# P0：显性预检与路径驱动诊断 Agent

> 状态：待评审。目标是在当前图诊断 MVP 上做最小增强，不引入 Diff、Git Snapshot 或复杂规则。

## 1. 核心方案

```text
后端生成 Action Graph + Event Graph
  -> 程序生成极简 precheck_findings
  -> 启动本地诊断 Agent
  -> 传入图文件路径、OpenSpec change 路径、用户反馈和 precheck_findings
  -> Agent 按需读取文件并判断隐性错误
  -> 输出并校验诊断 JSON
  -> 现有前端高亮粗图并下钻细图
```

分工：

- 程序只判断确定性的显性错误。
- 诊断 Agent 判断需求理解、修改方向、声明与行为不一致等隐性错误。

## 2. 数据边界

P0 使用：

- `action_graph.json`。
- `event_graph.json`；其数据来自 Marker 范围内的原始 Claude Code Session。
- OpenSpec change 目录中的 proposal、specs、design 和 tasks。
- 用户反馈。

P0 不使用：

- 原始 Session 文件路径。
- Runtime Task、`task.diff` 或 Dataset `diff.patch`。
- `git diff`、Git Tree、仓库快照或 Action 级 Diff。
- 其他模块生成的变更证据。

诊断范围是“Session 行为归因”，不承诺验证仓库最终代码状态。

## 3. 图的使用方式

### 3.1 不再拼接图内容

后端不再运行 `build_compact_graph_context()`，也不把裁剪后的 Graph JSON 塞入 Prompt。

Prompt 只传绝对路径。诊断 Agent 应：

1. 先读取 Action Graph，确定 Action 和 Event 范围。
2. 根据用户反馈和 `precheck_findings`，按 Event ID 查询 Event Graph。
3. 必要时读取 OpenSpec proposal/specs/design/tasks。

### 3.2 不做语义裁剪

Event Graph 已按当前 OpenSpec change 的 Marker 范围切分。P0 不再进行可能丢失隐性错误的二次语义裁剪。

如果未来单个 Event Graph 过大，优先按 Action 拆分文件；不在 P0 中实现。

### 3.3 只读约束

- 路径由后端根据已校验的 change 名称生成，不能由用户自由指定。
- 诊断 Agent 只允许读取指定图文件和 OpenSpec 产物。
- 不允许修改文件或执行项目命令。
- Analyzer 不支持只读文件访问时，返回不可用，不回退到粘贴完整 Session。

## 4. 程序化显性诊断

P0 只实现两个检查器。

### 4.1 ArtifactMissingVerifier

只检查真实执行过的 Action：

| Action | 显性检查 |
|---|---|
| `proposal` | `proposal.md` 存在且非空 |
| `specs` | 至少一个 `specs/*/spec.md` 存在且非空 |
| `design` | `design.md` 存在且非空 |
| `tasks` | `tasks.md` 存在、非空且 checklist 可解析 |

边界：

- 未执行对应 Action 时不检查。
- 只检查存在性和最小结构，不判断内容是否正确。
- 不根据 Apply 反推全部上游产物必须存在。

### 4.2 BasicVerifyChecker

从 Event Graph 时间线识别：

- 修改事件：Edit、Write、MultiEdit、Patch、apply_patch。
- 验证命令：常见 test、build、lint、check 和 `openspec validate`。
- Tool Call 与 Tool Result：通过 `tool_call_id/tool_use_id` 配对。

只输出以下显性错误：

| precheck_finding 类型 | 条件 |
|---|---|
| `verification_missing` | 存在修改事件，但其后没有验证命令 |
| `verification_failed` | 验证 Result 明确失败 |
| `verification_result_missing` | 有验证命令，但没有对应 Result |
| `verification_stale` | 验证后再次修改，且没有重新验证 |

无法明确判断时不生成 `precheck_finding`，由诊断 Agent 处理或写入 `missing_evidence`。

### 4.3 不做的程序判断

P0 不程序化判断：

- 修改是否符合用户需求。
- 文件是否选错、修改是否真正生效或被覆盖。
- Agent 是否理解错需求、目标漂移或过早结束。
- Tool 成功是否等于最终代码正确。
- 根因、概率、分数或置信度。
- 未被明确 Contract 要求的“应该调用某工具但没有调用”。

## 5. precheck_finding 最小字段

`precheck_findings` 只包含发现的异常；正常检查不输出记录。

```json
{
  "precheck_finding_id": "precheck-finding-001",
  "type": "verification_stale",
  "action_id": "apply-1",
  "event_ids": ["E50", "E55"],
  "target": "latest code changes",
  "expected": "最后一次修改后存在验证",
  "observed": "E50 验证后又发生 E55 修改，之后没有验证"
}
```

固定字段只有：

- `precheck_finding_id`
- `type`
- `action_id`
- `event_ids`
- `target`
- `expected`
- `observed`

不增加 `status`、`confidence`、`score`、`summary` 或重复的 Evidence 对象。`precheck_finding` 本身就是程序确认的异常事实。

## 6. 传给诊断 Agent 的内容

Prompt 只包含：

```text
action_graph_path: <absolute path>
event_graph_path: <absolute path>
change_root: <absolute path>
feedback: <user feedback>
precheck_findings: <small JSON array>
diagnosis_output_contract: <required JSON schema>
```

不包含 Graph 正文、原始 Session 正文和 Diff。

诊断 Agent 负责：

- 阅读 OpenSpec 产物，理解本应实现的需求。
- 阅读 Action/Event Graph，理解实际执行行为。
- 优先审阅 Precheck 指向的 Action/Event。
- 在 Precheck 为空时，根据用户反馈独立查找隐性错误。
- 说明替代解释和缺失证据。

## 7. 输出与校验

沿用当前输出：

```json
{
  "symptoms": [],
  "suspicious_actions": [],
  "suspicious_events": [],
  "missing_evidence": [],
  "summary": ""
}
```

规则：

- Precheck 事实和 Agent 推断不再通过 `status` 字段混在一起。
- `precheck_findings` 表示程序确认的显性异常事实。
- `suspicious_actions/events` 表示 Agent 的归因假设。
- 后端继续校验所有 Action ID 和 Event ID，删除模型编造的 ID。
- 图证据不足时必须写入 `missing_evidence`，不能读取原始 Session 补猜。

## 8. 最小代码改动

新增：

- `ccwhat/diagnosis/precheck.py`
  - `check_artifacts(change_root, action_graph)`
  - `check_basic_verify(action_graph, event_graph)`

修改：

- `viewer/server.py`
  - 生成并校验绝对图路径和 change root。
  - 将路径传入反馈诊断。
- `ccwhat/diagnosis/feedback.py`
  - 执行两个 Precheck。
  - 停止构建 compact graph context。
  - 构建路径驱动的诊断 Prompt。
- `ccwhat/assets/graph_attribution_prompt.md`
  - 允许只读文件访问。
  - 规定读取顺序、数据边界和 JSON 输出。
- `tests/test_graph_feedback.py`
  - 覆盖路径 Prompt、Agent 输出和 ID 校验。
- 新增 `tests/test_diagnosis_precheck.py`
  - 覆盖两个 Precheck。

不修改：

- Marker 和图构建方式。
- Runtime Task、Dataset 和 Git 相关模块。
- React 图展示和下钻交互。
- LLM 调用次数。

## 9. 验收场景

1. 执行 Tasks Action，但 `tasks.md` 缺失：生成 `artifact_missing`。
2. 未执行 Design Action，且 `design.md` 缺失：不生成 `precheck_finding`。
3. 最后修改后没有验证：生成 `verification_missing`。
4. 验证 Result 明确失败：生成 `verification_failed` 并引用真实 Event ID。
5. 验证后再次修改且未重新验证：生成 `verification_stale`。
6. Precheck 为空，但用户反馈功能错误：Agent 能读取 spec 和图并输出可疑 Action/Event。
7. Prompt 只包含路径、反馈、`precheck_findings` 和输出契约，不包含 Graph 正文。
8. 全链路不读取原始 Session，不调用或读取任何 Diff/Snapshot。
9. Analyzer 无法读取指定文件时，返回明确不可用或证据不足。

## 10. 完成标准

- 程序化诊断只覆盖确定性显性错误。
- `precheck_finding` 使用七个固定字段且只输出异常。
- 诊断 Agent 能按路径读取图和 OpenSpec 产物。
- 当前诊断 JSON、ID 校验和前端交互保持兼容。
- 图不足以证明最终代码状态时，报告边界而不是扩大结论。
