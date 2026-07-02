## Why

`claude-log.html` 的 Timeline 页当前只是一个扁平日志列表（`renderTimelinePage()`，最多 200 条 entry，每条一行），无法呈现 Claude Code session 的执行树层级（需求 → 任务 → 步骤 → 轮次 → 工具）和工具调用的并发结构，也无法在时间轴上定位耗时瓶颈。

`deep-ai-analysis-session-report-clean/viewer/session-gantt.html` 已经实现了完整的层级树 + 右侧甘特时间轴 + 点击时间条弹出详情的视图，但它是独立项目，未集成进 `deep-ai-analysis-copy` 的主 viewer。用户希望在看 session 时直接在 Timeline 页获得甘特视图，而不是跳到另一个项目。

## What Changes

- 新增 `viewer/session-gantt.html`：从 `deep-ai-analysis-session-report-clean/viewer/session-gantt.html` 复制，保留其层级树导航、甘特时间轴、详情面板和点击联动逻辑。
- 新增后端 API `GET /api/session-gantt/<sessionId>`：返回甘特视图所需的树形数据。该接口在 `session-report-clean` 中依赖 `claude_code_log` 库，但 `deep-ai-analysis-copy` 没有该依赖，需基于 copy 现有的 `ClaudeAdapter` 重新实现等价的数据组装逻辑。
- 修改 `viewer/claude-log.html` 的 Timeline 页：删除现有扁平列表（`renderTimelinePage()` 的列表渲染部分），改为通过 `<iframe>` 嵌入 `session-gantt.html?sessionId=<当前sid>`。父页面 session 切换时同步更新 iframe 的 `sessionId` 参数。
- 新增后端静态文件路由 `GET /session-gantt.html`：serve `viewer/session-gantt.html`。

## Capabilities

### New Capabilities
- `session-gantt-view`: 在 viewer 中提供 session 执行树甘特视图，包含后端树形数据 API、独立 HTML 页面、以及通过 iframe 嵌入 Timeline 页的集成方式。

### Modified Capabilities
<!-- 无。现有 `session-viewer` spec 的"非核心页面降级" requirement 允许 Timeline 显示占位或最小入口，新增甘特视图不改变该 requirement 的语义，仅是升级实现。 -->

## Impact

- **代码**：
  - `viewer/claude-log.html`：`renderTimelinePage()` 改为渲染 iframe；新增 session 切换时同步 iframe src 的逻辑。
  - `viewer/server.py`：新增 `/api/session-gantt/<sessionId>` 路由和 `/session-gantt.html` 静态路由。
  - `viewer/session-gantt.html`：新增文件（从外部项目复制）。
- **依赖**：不引入 `claude_code_log` 依赖（copy 项目未使用），后端 API 基于 copy 现有的 `ClaudeAdapter` 和 `get_session()` 重新实现数据组装。
- **现有功能**：Timeline 页原有扁平列表将被移除（用户已确认替换而非并存）。其他页面（Session、Tasks、Overview 等）不受影响。
- **主题**：`session-gantt.html` 自带深色主题，与父页面 `claude-log.html` 的明暗主题系统独立。本期不做主题统一，iframe 内保持 gantt 自身样式。
