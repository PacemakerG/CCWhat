# 基于证据的反向归因诊断：长期改进参考

## 1. 文档定位

本文记录 CCWhat 当前图诊断 MVP 之后的长期演进方向，仅作为未来方案参考，不代表当前实现范围。

当前 MVP 已打通：

```text
Marker + 原始 Session
  -> Action Graph（粗图）+ Event Graph（细图）
  -> 用户反馈
  -> 一次 LLM 诊断
  -> suspicious_actions / suspicious_events
  -> 粗图高亮并下钻细图
```

当前方案适合快速定位候选阶段和步骤，但 LLM 输出仍属于“可疑假设”，不能证明真实因果。

## 2. 分阶段路线

### P0：显性预检与本地诊断 Agent

- 实现产物缺失和基础验证两个确定性 Precheck。
- `precheck_findings` 只记录程序规则确认的显性异常事实，不增加分数或置信度。
- 本地诊断 Agent 按路径读取 Action/Event Graph 和 OpenSpec 产物。
- Prompt 只传路径、用户反馈、`precheck_findings` 和输出契约，不再拼接裁剪后的图正文。
- 不读取或生成 Diff、Git Snapshot 和原始 Session 上下文。

详细方案见 [P0 实施计划](./P0_IMPLEMENTATION_PLAN.md)。

### P1：诊断证据引用与可追溯展示

- 让诊断 Agent 引用真实的 Action、Event、OpenSpec 文档和 `precheck_finding`。
- 后端只校验引用是否存在，不使用规则替代模型做隐性诊断。
- 前端展示“诊断结论 -> 证据 -> 图节点”的可追溯关系。
- 保持现有 Action/Event Graph，不新增 Artifact、Claim、Outcome 节点。

详细方案见 [P1 实施计划](./P1_IMPLEMENTATION_PLAN.md)。

### P2：评测与校准

- 建立带 critical failure step 的真实失败样本。
- 通过删除测试、漏写状态、错误需求理解等方式构造扰动轨迹。
- 评估 Top-K Action/Event 命中率、证据正确率和误报率。

### P3：反事实验证

- 对候选步骤做成功/失败轨迹对比。
- 支持局部 Replay 或受控干预。
- 只有 Outcome flip 后才将结论标记为 `intervention_verified`。

## 3. 可借鉴研究

| 研究 | 主要借鉴点 |
|---|---|
| AgentRx | 约束合成、逐步验证、定位首次关键违反 |
| ErrorProbe | Symptom 驱动的上下文裁剪、假设验证和已验证经验记忆 |
| PROTEA | 从最终目标反推中间节点期望 |
| False Success | Claim 与真实环境状态、Diff、测试证据对齐 |
| AgentTrace | 显性错误场景下的图反向追踪 |
| ECHO | 分层上下文与多验证器共识 |
| TrajAD | 轨迹异常检测和扰动数据集 |
| REFLECT | 局部干预、受控 Replay 和 Outcome flip 验证 |

## 4. 最终方向

CCWhat 的长期定位不是“让 LLM 看图猜错误”，而是：

> 以图组织证据，以约束发现违反，以多验证器形成归因假设，再用反事实干预逐步确认因果。

相关现有设计：

- [OpenSpec 归因诊断 MVP](../../Graph%20Attribution%20Refactor/基于CC原始Session的OpenSpec归因诊断MVP计划.md)
- [反向归因打分问题分析](../../Graph%20Attribution%20Refactor/反向归因打分机制问题分析与建议.md)
