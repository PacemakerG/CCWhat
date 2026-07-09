## Why

Runtime Dataset V2 已具备归因诊断所需的全部数据（git diff、Agent 行为轨迹、任务边界），但缺乏自动化分析能力。当前需要人工审阅 task_trace.json 和 diff.patch 来判断任务失败原因。为了提升诊断效率和标准化分析流程，需要引入自动归因诊断引擎，从 Task 现场包直接生成结构化诊断报告。

## What Changes

- 新增 `ccwhat/diagnosis/` 模块，实现两层诊断架构：
  - **规则层**：确定性检查（命令未运行、测试失败、diff 为空但声称完成、final_claim 矛盾）
  - **LLM 层**：语义分析（instruction 与改动相关性、成功标准达成度）
- 新增 `ccwhat diagnose` CLI 命令：对指定 task 或 run 生成 `diagnosis.json`
- 新增 `DiagnosisEngine` 类：消费 task.json + task_trace.json + diff.patch，输出结构化诊断
- `diagnosis.json` 结构：包含 summary、likely_root_causes、missing_evidence、confidence、recommended_next_steps
- 集成到 `/ccwhat:finish` 流程：可选自动生成诊断报告

## Capabilities

### New Capabilities
- `auto-attribution-diagnosis`: 自动归因诊断引擎，从 Task 现场包生成诊断报告
- `diagnosis-cli`: CLI 命令支持对历史 task 进行诊断分析

### Modified Capabilities
- 无（此 change 为纯新增能力，不修改现有 capability 需求）

## Impact

- 新增目录 `ccwhat/diagnosis/`：包含 engine.py、rules.py、llm_layer.py、models.py
- 新增 CLI 命令：`ccwhat/cli.py` 注册 `diagnose` 子命令
- 可选集成点：`ccwhat/runtime/staging.py` finish_task 流程（标志位控制）
- 新增依赖：可能需 LLM client（复用现有 proxy 配置）
- 受影响测试：`tests/test_runtime_recording.py`（如开启自动诊断）
