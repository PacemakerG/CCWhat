## Why

当前 `ccwhat` 已能抽取 Dataset trace、工具调用、文件改动、命令和 final claim，但诊断仍缺少一层可以解释“流程哪里偏了”的结构。OpenSpec 本身是固定开发流程，适合作为第一版粗粒度 Action Graph 的 workflow 模板。

## What Changes

- 新增 OpenSpec Action Graph 归因 MVP。
- 从 Dataset trace 构建细粒度 Event Graph。
- 从固定 OpenSpec 流程构建粗粒度 Action Graph：proposal、specs、design、tasks、apply、verify、archive。
- 将细粒度事件映射到粗粒度 Action 节点。
- 从症状节点反向传播并输出可疑 causal chains。
- 新增 `ccwhat diagnose` CLI，输出 `event_graph.json`、`action_graph.json` 和 `diagnosis.json`。
- 新增 `ccwhat openspec-graph sync`，让 OpenSpec change 在流程执行时无感生成 `graph/` 产物。
- 改造 OpenSpec skill / slash command 文档，在 propose、apply、archive 关键节点同步 graph。

## Non-Goals

- 不接入 Viewer 或 Session Report。
- 不做通用 workflow schema 编辑器。
- 不调用 LLM。
- 不支持 runtime task 目录作为第一版主入口。
- 不实现前端图谱展示。
