## ADDED Requirements

### Requirement: 图诊断生成按钮形状

Diagnostics 页面 SHALL 将 OpenSpec 图诊断的“生成诊断”入口渲染为胶囊形主操作按钮，且不改变既有诊断请求行为。

#### Scenario: 加载图诊断区域

- **WHEN** 用户打开 Diagnostics 页面
- **THEN** `openspecGraphDiagnoseBtn` SHALL 具有专用胶囊形样式类
- **AND** 该样式 SHALL 使用完全圆角

#### Scenario: 提交诊断

- **WHEN** 用户点击胶囊形生成按钮
- **THEN** 页面 SHALL 继续向 `/api/openspec-graph-diagnose` 提交既有请求
- **AND** 按钮禁用与状态提示行为 SHALL 保持不变
