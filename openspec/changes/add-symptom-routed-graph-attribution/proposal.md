## Why

现有 OpenSpec Graph 已能从 Claude Code Session 生成固定七节点 Action Graph 和 step-level Event Graph，但产品尚未形成“用户描述问题 -> 定位可疑 Action -> 定位具体 Event -> 输出可回看证据的报告”闭环。

原有 change 计划继续扩展 Action/Event 规则打分，但这会在 MVP 阶段引入大量无法校准的权重和因果假设。当前最需要验证的是：仅使用一个 OpenSpec change 对应的一份 Claude Code 原始 Session，复用项目现有 Analyzer Adapter 启动一次本地 AI CLI 非交互分析，是否已经能给用户提供有价值的粗到细诊断。

## What Changes

- 保留固定 OpenSpec 七节点 Action Graph，只把状态收敛为 `observed|not_observed|failed`，不再使用流程距离产生根因分数。
- 加固基于 Claude Code 原始 Session 的 Event Graph：唯一 Event ID、Tool Call/Result 配对、文件/命令/错误/result summary 和 raw reference。
- 修正 Event 到 Action 的最小映射规则，保留映射理由，未映射 Event 不丢失。
- 新增用户反馈归因入口：输入 `session_id`、`change` 和自然语言 feedback。
- 复用 `run_mc_analysis()` 和 Analyzer Registry，启动一次本地 Claude/Codex/OpenCode CLI 非交互会话；不新增模型 API Client 或 API Key 配置。
- Analyzer 输出严格结构化诊断，程序校验所有 Action/Event 引用并删除编造 ID。
- Viewer 增加反馈输入、诊断报告，以及从报告定位粗图 Action 和细图 Event 的交互。
- 提供一个真实结构的 OpenSpec 驱动 Claude Code Session mock，用于前端手动验收。

## Non-Goals

- 不接 Runtime Task、Task Dataset、Dataset export 或 `task.diff`。
- 不支持一个 Session 中包含多个 OpenSpec change。
- 不引入 Action Contract、Action Run、多模板适配器或 Artifact/Requirement/Outcome 图。
- 不实现复杂因果边、反事实执行、规则投票或数值 root-cause score。
- 不调用模型 HTTP API；本 change 只复用用户本机已安装并已登录的 AI CLI。
- 不让 Analyzer 修改代码或自动修复问题。
