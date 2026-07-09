## Context

Runtime Dataset V2 已完成所有基础设施建设：
- `task.json`: 任务元数据、git 状态、证据可用性标记
- `task_trace.json`: Agent 行为轨迹（events、commands、files、changes、errors、final_claim）
- `diff.patch`: 代码变更的统一 diff 格式

当前缺失最后一环：自动消费这些数据并生成诊断报告的能力。当任务失败时，开发者需要手动查看多个文件才能定位原因，效率低下且缺乏标准化。

## Goals / Non-Goals

**Goals:**
- 实现两层诊断架构（规则层 + LLM 层），覆盖常见失败模式
- 生成结构化 `diagnosis.json`，包含明确的 root cause 和证据链
- 提供 `ccwhat diagnose` CLI 命令，支持对历史 task 进行诊断
- 规则层诊断达到 100% 准确率（确定性检查）

**Non-Goals:**
- 不实现完整的 evaluator 平台（只做单机诊断）
- 不做批量 benchmark 或统计报表
- 不做诊断 UI（只输出 JSON，viewer 展示后续再补）
- 不训练模型（只使用 LLM 做推理，不做微调）

## Decisions

### Decision: 两层诊断架构

**规则层（Rule Layer）**
- 处理确定性问题：命令未运行、测试失败、diff 为空但 final_claim 声称完成
- 优点：零成本、速度快、100% 准确
- 实现：`diagnosis/rules.py`，纯本地逻辑

**LLM 层（LLM Layer）**
- 处理语义问题：instruction 与改动相关性、成功标准达成度
- 优点：覆盖规则层无法判断的复杂场景
- 实现：`diagnosis/llm_layer.py`，调用 LLM API

**执行顺序**: 规则层先执行，LLM 层补充规则层未覆盖的维度。

### Decision: diagnosis.json 作为唯一输出格式

**Rationale:**
- 下游工具（viewer、benchmark、训练数据转换）统一消费 JSON
- 避免多格式维护成本

**结构:**
```json
{
  "task_id": "task-001",
  "diagnosed_at": "2026-06-28T10:00:00Z",
  "summary": "Agent 声称完成任务但 diff 为空，且测试未运行",
  "likely_root_causes": [
    {
      "cause": "代码未实际修改",
      "evidence": ["diff.patch 为空", "final_claim: '已完成'"],
      "confidence": "high",
      "source": "rule"
    }
  ],
  "missing_evidence": ["success_criteria 未填写"],
  "confidence": "high",
  "recommended_next_steps": ["检查 Agent 是否正确调用了文件修改工具"]
}
```

### Decision: 复用现有 LLM 配置

**Rationale:**
- 复用 `ccwhat` 已有的 proxy 配置（Claude/Codex/OpenCode 的 API key）
- 避免引入新的配置复杂度

**Implementation:**
- 从 `~/.ccwhat/config.toml` 读取代理配置
- LLM 层使用与 proxy 相同的 API endpoint 和 key

### Decision: 可选集成到 finish 流程

**Rationale:**
- 自动生成诊断报告方便，但增加 finish 时间（LLM 调用延迟）
- 用户可能不需要每次都有诊断报告

**Implementation:**
- staging.py 添加 `auto_diagnose: bool = False` 参数
- `/ccwhat:finish` 默认不生成诊断，可通过配置开启

## Risks / Trade-offs

**Risk: LLM 调用成本** → Mitigation: 规则层优先，LLM 层只在需要时调用；支持配置关闭 LLM 层。

**Risk: LLM 输出不稳定** → Mitigation: 使用结构化输出（response_format JSON），设置 temperature=0，失败时降级到规则层结果。

**Risk: 诊断准确率不达标** → Mitigation: 规则层保持 100% 准确；LLM 层标注 confidence，low confidence 时不作为决定性证据。

## Migration Plan

无需数据迁移：
- 新模块纯新增，不影响已有 task 数据
- 历史 task 可通过 `ccwhat diagnose --task-id <id>` 重新诊断

代码迁移：
1. 新增 `ccwhat/diagnosis/` 目录
2. 新增 `ccwhat/commands/diagnose.py`
3. 可选修改 `ccwhat/runtime/staging.py`（添加 auto_diagnose 标志）

## Open Questions

1. **LLM 模型选择**: 是否强制使用 Claude 3.5 Sonnet 或允许配置？
2. **诊断缓存**: 相同 task 是否缓存诊断结果？
3. **多语言支持**: diagnosis.json 的 summary 是否跟随 viewer locale？
