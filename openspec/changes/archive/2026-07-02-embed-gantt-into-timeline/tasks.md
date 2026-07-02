# Implementation Tasks

## 1. 后端依赖与文件准备

- [x] 1.1 在 `pyproject.toml` 的 `[project].dependencies` 中添加 `claude-code-log>=1.4.0`
- [x] 1.2 运行 `pip install -e .`（或 `uv sync`）安装新依赖，验证 `python -c "from claude_code_log.converter import load_transcript; from claude_code_log.json.renderer import JsonRenderer; from claude_code_log.models import AssistantTranscriptEntry, TextContent, ThinkingContent, ToolUseContent, ToolResultContent, UserTranscriptEntry"` 无报错
- [x] 1.3 将 `deep-ai-analysis-session-report-clean/viewer/session-gantt.html` 复制到 `deep-ai-analysis-copy/viewer/session-gantt.html`

## 2. 后端 API 实现

- [x] 2.1 在 `viewer/server.py` 中移植 `_iso_to_ms()`、`_GANTT_BARRIER_TYPES`、`_flatten_gantt_nodes()`、`_find_session_jsonl()` 四个辅助函数（来自 session-report-clean `server.py` line 333-488）
- [x] 2.2 在 `viewer/server.py` 中移植 `get_session_gantt(session_id, projects_dir)` 函数，依赖 `claude_code_log.converter.load_transcript`、`_integrate_agent_entries`、`deduplicate_messages` 和 `claude_code_log.json.renderer.JsonRenderer`
- [x] 2.3 在 `viewer/server.py` 中移植 `get_session_entry_detail(session_id, node_id, projects_dir)` 函数，依赖 `claude_code_log.models` 下的 typed models
- [x] 2.4 在 `viewer/server.py` 中新增 FastAPI 路由 `GET /api/session-gantt/<sessionId>`，调用 `get_session_gantt()`，session 不存在时返回 404 `{"error": "session not found"}`；响应附带 `Access-Control-Allow-Origin: *`
- [x] 2.5 在 `viewer/server.py` 中新增 FastAPI 路由 `GET /api/session-entry/<sessionId>/<nodeId>`，调用 `get_session_entry_detail()`，节点不存在时返回 404 `{"error": "entry not found"}`
- [x] 2.6 在 `viewer/server.py` 中新增静态路由 `GET /session-gantt.html`，仿照现有 `/claude-log.html` 路由用 `FileResponse(backend.viewer_dir / "session-gantt.html", media_type="text/html")`
- [x] 2.7 启动 server，用 curl 验证三个新路由：`curl -s http://127.0.0.1:<port>/api/session-gantt/<real-sid> | python -m json.tool`、`curl -s http://127.0.0.1:<port>/api/session-entry/<real-sid>/assistant-<msgId>`、`curl -sI http://127.0.0.1:<port>/session-gantt.html`

## 3. 前端 session-gantt.html 改造

- [x] 3.1 在复制的 `viewer/session-gantt.html` 中新增 URL 参数解析逻辑：读取 `embedded` 参数值
- [x] 3.2 当 `embedded=1` 时，通过内联 CSS 或 JS 给 `.topbar` 元素设置 `display: none`（优先在 `<head>` 内联一段 `<style>body.embedded .topbar { display: none }</style>`，并在 JS 解析到 `embedded=1` 时给 `body` 加 `embedded` class）
- [x] 3.3 直接访问 `session-gantt.html`（不带 `embedded=1`）时验证 `.topbar` 仍正常显示

## 4. 前端 claude-log.html Timeline 页改造

- [x] 4.1 在 `claude-log.html` 的 Timeline 页 `#timelineContent` 容器中，将原占位 div 改为同时容纳占位文案和 iframe 的结构（例如保留 `#timelineContent`，由 JS 决定渲染占位还是 iframe）
- [x] 4.2 新增函数 `updateTimelineIframe(sid)`：sid 为空时显示占位文案"选择一个 session 加载后查看时间线"；sid 非空且与 iframe 当前 `data-sid` 不同时，设置 `#timelineContent` 内的 iframe `src = "session-gantt.html?sessionId=" + encodeURIComponent(sid) + "&embedded=1"`，并记录 `data-sid`；sid 相同时跳过
- [x] 4.3 iframe 样式设为 `width:100%; height:100%; border:0; display:block;`，`#timelineContent` 设为 `flex:1; overflow:hidden;` 以撑满 Timeline 页剩余空间
- [x] 4.4 删除 `renderTimelinePage()` 中原有扁平列表渲染逻辑（line ~3420-3441 的 `for (const e of allEntries.slice(0, 200))` 循环和拼接 html 的部分），改为调用 `updateTimelineIframe(currentSid)`
- [x] 4.5 在 `loadSession()` 流程末尾（或 `navigateToPage('timeline')` 触发时）调用 `updateTimelineIframe(sid)`，确保 session 切换后 Timeline 页 iframe 同步
- [x] 4.6 处理 Timeline 页未激活时的延迟同步：若用户在 Timeline 页未激活时切换 session，iframe 应在 Timeline 页下次激活时刷新（即在 `navigateToPage('timeline')` 路径内也调用一次 `updateTimelineIframe`）

## 5. 集成验证

- [x] 5.1 启动 `ccwhat web-server`（或等价命令），浏览器打开 `claude-log.html`
- [x] 5.2 选择一个真实 session，切换到 Timeline 页，验证 iframe 加载 `session-gantt.html?sessionId=<sid>&embedded=1`，gantt 顶栏隐藏，树面板 + 时间轴 + 详情面板正常显示
- [x] 5.3 在 gantt 视图中点击树节点和时间条，验证右侧详情面板正确弹出对应内容（assistant / tool_use / tool_result）
- [x] 5.4 切换到另一个 session，验证 iframe `src` 更新，gantt 视图加载新 session 数据
- [x] 5.5 切换到其他页面（Session / Tasks 等）再切回 Timeline，验证 iframe 仍显示当前 session（无重复加载闪烁）
- [x] 5.6 不选中任何 session 时切到 Timeline 页，验证显示占位文案而非空白 iframe
- [x] 5.7 直接访问 `http://127.0.0.1:<port>/session-gantt.html?sessionId=<sid>`（不带 `embedded=1`），验证顶栏正常显示，session 选择器可用
