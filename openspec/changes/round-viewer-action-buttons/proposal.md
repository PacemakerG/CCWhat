## Why

Claude Log Viewer 的普通操作按钮当前使用 `--radius-sm`，视觉上偏硬。这个 mock change 用来验收从原始 Claude session 日志生成 step-level Event Graph，并检查粗图和细图的映射关系。

## What Changes

- 将 Viewer 通用 `.btn` 按钮圆角从 `--radius-sm` 调整为 `--radius-md`。
- 不改变按钮尺寸、文案、行为和布局。
- 使用原始 Claude session JSONL 重新生成 graph。

## Non-Goals

- 不重做 Viewer 视觉系统。
- 不使用 Dataset trace。
- 不把弱规则边当作因果链。
