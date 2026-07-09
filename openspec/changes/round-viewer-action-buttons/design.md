## Context

本 change 是 graph 语义验收样本：它模拟一次线性的 OpenSpec 工作流，并从原始 Claude session 日志构建细图。

## Decision

Event Graph v1 只保留两类边：

- `timeline`：事件发生顺序。
- `tool_result_of`：工具调用和工具结果的确定绑定。

不生成 `reads_before_edit`、`edit_before_command`、`command_produces_error`、`claim_after_action` 这类弱推断边。

## UI Change

只修改 `viewer/claude-log.html` 中 `.btn` 的 `border-radius`：

- 原来：`var(--radius-sm)`
- 现在：`var(--radius-md)`
