## Context

当前 graph 产物位于 `openspec/changes/<name>/graph/`，包含 `action_graph.json`、`event_graph.json` 和 `diagnosis.json`。Viewer 目前已有 Diagnostics 页面，适合作为第一版展示入口。

## Design

- 新增 `GET /api/openspec-graph/<change>`，只读取 repo 当前 active change 的 `graph/` JSON。
- Diagnostics 页面增加 change name 输入框和加载按钮。
- Action Graph 使用横向流程布局，展示 OpenSpec 粗节点状态。
- Event Graph 使用紧凑网格布局，展示细粒度 artifact/event 节点和边。
- 图渲染使用内联 SVG，不引入第三方依赖。

## Risks

- 图数据可能不存在；UI 显示空态和错误态。
- 节点数量可能较多；第一版限制 SVG 高度并允许横向滚动。
