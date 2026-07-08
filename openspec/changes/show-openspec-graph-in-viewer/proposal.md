## Why

OpenSpec workflow graph 已经能生成 JSON 产物，但用户仍需要手动打开文件查看。为了验证图结构的产品方向，Viewer 需要先提供一个最小可用的点线图展示。

## What Changes

- 在 Diagnostics 页面新增 OpenSpec Graph 面板。
- 后端提供读取 active change graph JSON 的 API。
- 前端用点和线展示 Action Graph 和 Event Graph 两张图。

## Non-Goals

- 不做复杂图布局引擎。
- 不支持编辑图节点。
- 不展示 archived change。
