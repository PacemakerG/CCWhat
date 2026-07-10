## Context

`openspecGraphDiagnoseBtn` 目前使用通用 `btn` 外观。这个 Mock 需要一个用户可直接观察、但不改变诊断功能或数据模型的真实 UI 改动，并同时提供完整的 Marker 图证据。

## Goals / Non-Goals

**Goals:**

- 只改变图诊断生成按钮的视觉形状。
- 用语义化专用 class 避免影响其他通用按钮。
- 保持现有 `onclick`、id、文案与禁用逻辑。

**Non-Goals:**

- 不改变诊断 API、Session、Graph JSON 或 Analyzer 行为。
- 不调整其他按钮的形状或全局设计系统。

## Decisions

### Decision: 添加局部 CSS class

在现有按钮上添加 `ops-diagnosis-generate-btn`，并用该 class 设置 `border-radius: 999px`。相比修改 `.btn`，局部 class 不会改变其他页面的既有控件。

### Decision: 用静态测试保护 DOM 契约

测试断言按钮 id、专用 class 和圆角样式同时存在；既有前端测试继续覆盖诊断函数与 API 路径。

## Risks / Trade-offs

- [视觉变化不足够明显] → 使用完全圆角而不是轻微增大现有圆角。
- [误伤通用按钮] → 只针对专用 class 写样式。
