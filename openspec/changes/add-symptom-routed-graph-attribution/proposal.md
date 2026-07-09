## Why

上一版 `ccwhat/diagnosis` 已经有 Action 级反向遍历和通用打分 MVP，但它不是产品级归因机制：

- 没有用户问题分类路由。
- 没有每类 symptom 的独立反推策略。
- 没有 Event 级可疑节点排序。
- 代码里同时混着 graph 构建、症状检测、粗糙打分和 OpenSpec milestone fallback，继续堆会变成死代码/野代码。

本 change 专门处理“用户反馈问题后，系统如何分类、反推、打分、解释”的机制。它依赖前一个 change 提供的 step-level Event Graph 和 fixed OpenSpec Action Graph。

## What Changes

- 整理 `ccwhat/diagnosis/`，保留稳定数据模型和固定 Action DAG 骨架，删除或清空不再适合作为主路径的粗糙 attribution 代码。
- 新增 symptom router：把用户反馈或系统检测结果归类为明确 symptom。
- 新增 Action-first attribution：先沿 OpenSpec Action DAG 反向找可疑 Action。
- 新增 Event-level scoring：在可疑 Action 内排序具体 tool call、file edit、command、tool result、final claim 等 Event。
- 新增 symptom-specific scorer：不同 symptom 使用不同加权规则。
- 输出可解释 causal chains，包含 suspicious actions、suspicious events、分数、证据和缺失证据。

## Non-Goals

- 不重新构建 step-level Event Graph；那属于 `refactor-openspec-event-graph-to-session-steps`。
- 不改变 OpenSpec 七节点粗图模板。
- 不让 LLM 直接替代图归因。
- 不在第一版实现可视化调参 UI。
