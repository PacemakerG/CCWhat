## Why

图诊断页面的“生成诊断”按钮与普通操作按钮外观相同，难以在验收时确认诊断入口。用一个范围极小的真实 change 验证 OpenSpec Marker、Session 图和 Viewer 的完整链路。

## What Changes

- 将图诊断区域的“生成诊断”按钮改为胶囊形主操作按钮。
- 保持按钮行为、文案、禁用状态和 API 调用不变。
- 为该视觉契约补静态前端测试。

## Capabilities

### New Capabilities

- `diagnosis-button-shape`: 图诊断页面生成按钮的可识别胶囊形视觉样式。

### Modified Capabilities

- 无。

## Impact

- `viewer/claude-log.html` 的诊断按钮标记与样式。
- `tests/test_openspec_graph_viewer.py` 的静态断言。
