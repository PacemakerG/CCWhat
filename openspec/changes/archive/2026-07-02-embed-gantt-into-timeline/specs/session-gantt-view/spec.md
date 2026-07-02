## ADDED Requirements

### Requirement: 后端 API — 甘特树数据
`viewer/server.py` SHALL 提供 `GET /api/session-gantt/<sessionId>` 接口，基于 `claude_code_log` 解析指定 session 的 JSONL，返回扁平化执行树节点数组，供前端甘特视图渲染。返回结构 SHALL 为 `{"sessionId": str, "nodes": list[dict], "sessionStartMs": int, "sessionMaxMs": int}`，每个 node SHALL 包含 `type`、`timestamp`、`content`、`depth`、`parentIdx`、`childIdxs`、`durationMs`、`tags`、`startMs`、`endMs` 字段；`tool_use` 类型节点 SHALL 额外包含 `index` 和 `pair_last` 字段以支持配对计时。

#### Scenario: session 存在
- **WHEN** 前端调用 `GET /api/session-gantt/<sessionId>`，且该 sessionId 在 `~/.claude/projects/`（或 `--projects-dir` 指定目录）下存在对应 JSONL 文件
- **THEN** 返回 HTTP 200 和 JSON `{"sessionId", "nodes", "sessionStartMs", "sessionMaxMs"}`，`nodes` 为扁平化树节点数组，按树前序遍历顺序排列

#### Scenario: session 不存在
- **WHEN** 指定 sessionId 在所有项目目录中均不存在
- **THEN** 返回 HTTP 404 和 `{"error": "session not found"}`

#### Scenario: CORS 头
- **WHEN** 任意 `GET /api/session-gantt/<sessionId>` 请求到达
- **THEN** 响应 SHALL 包含 `Access-Control-Allow-Origin: *`

### Requirement: 后端 API — 甘特节点详情
`viewer/server.py` SHALL 提供 `GET /api/session-entry/<sessionId>/<nodeId>` 接口，返回指定节点的详情。`nodeId` 前缀决定解析方式：`assistant-<msgId>`、`tool_use-<tuid>`、`tool_result-<tuid>`、`user_input-<uuid>`、`compact-<uuid>`。

#### Scenario: assistant 节点详情
- **WHEN** 调用 `GET /api/session-entry/<sessionId>/assistant-<msgId>`
- **THEN** 返回 `{"nodeId", "type": "assistant", "timestamp", "items": [...]}`，`items` 数组每项为 `{"kind": "text"|"thinking"|"tool_use", ...}`，且若存在 message.id 则返回 `messageId` 字段

#### Scenario: tool_use 节点详情
- **WHEN** 调用 `GET /api/session-entry/<sessionId>/tool_use-<tuid>`
- **THEN** 返回 `{"nodeId", "type": "tool_use", "timestamp", "toolName", "input"}`

#### Scenario: tool_result 节点详情
- **WHEN** 调用 `GET /api/session-entry/<sessionId>/tool_result-<tuid>`
- **THEN** 返回 `{"nodeId", "type": "tool_result", "timestamp", "toolName", "toolInput", "isError", "content"}`，`content` 为字符串

#### Scenario: user_input 节点详情
- **WHEN** 调用 `GET /api/session-entry/<sessionId>/user_input-<uuid>`
- **THEN** 返回 `{"nodeId", "type": "user_input", "timestamp", "text"}`

#### Scenario: compact 节点详情
- **WHEN** 调用 `GET /api/session-entry/<sessionId>/compact-<uuid>`
- **THEN** 返回 `{"nodeId", "type": "compact", "timestamp", "text"}`

#### Scenario: 节点不存在
- **WHEN** 指定 nodeId 在 session 中无法匹配任何条目
- **THEN** 返回 HTTP 404 和 `{"error": "entry not found"}`

### Requirement: 后端 — 静态文件 session-gantt.html
`viewer/server.py` SHALL 提供 `GET /session-gantt.html` 路由，以 `text/html` 类型返回 `viewer/session-gantt.html` 文件内容。

#### Scenario: 访问甘特页
- **WHEN** 浏览器请求 `GET /session-gantt.html`
- **THEN** 返回 HTTP 200 和 `viewer/session-gantt.html` 文件内容，`Content-Type` 为 `text/html`

### Requirement: 前端 — Timeline 页嵌入甘特 iframe
`claude-log.html` 的 Timeline 页 SHALL 通过 `<iframe>` 嵌入 `session-gantt.html`，替换原有 `renderTimelinePage()` 的扁平列表实现。iframe SHALL 占满 Timeline 页 `#timelineContent` 容器。

#### Scenario: 无 session 选中
- **WHEN** Timeline 页可见且当前未选中任何 session（`sessionSel` 的 value 为空）
- **THEN** `#timelineContent` 显示占位文案"选择一个 session 加载后查看时间线"，不加载 iframe

#### Scenario: 已选中 session
- **WHEN** Timeline 页可见且已选中某个 sessionId
- **THEN** `#timelineContent` 内渲染 `<iframe src="session-gantt.html?sessionId=<sid>&embedded=1">`，iframe 高度撑满容器

### Requirement: 前端 — session 切换同步 iframe
父页面 session 切换时 SHALL 同步更新 Timeline 页 iframe 的 `sessionId` 参数，避免iframe 内显示与父页面不一致的 session。

#### Scenario: 切换 session
- **WHEN** 用户在父页面切换 session 选择器，新 sessionId 与 iframe 当前 `data-sid` 不同
- **THEN** iframe 的 `src` 更新为 `session-gantt.html?sessionId=<新sid>&embedded=1`，并记录新的 `data-sid`

#### Scenario: session 未变化
- **WHEN** 触发同步逻辑但当前 sessionId 与 iframe `data-sid` 相同
- **THEN** 不修改 iframe `src`，避免重复加载

### Requirement: 前端 — embedded 模式隐藏顶栏
`session-gantt.html` SHALL 支持 `?embedded=1` URL 参数。在该模式下，gantt 页面自带的 `.topbar` 元素（含 session 选择器和跳转链接）SHALL 被隐藏，仅显示树面板、甘特时间轴和详情面板。

#### Scenario: embedded 模式
- **WHEN** `session-gantt.html` 的 URL 含 `embedded=1` 参数
- **THEN** `.topbar` 元素 `display: none`，不占用布局空间

#### Scenario: 非 embedded 模式
- **WHEN** `session-gantt.html` 的 URL 不含 `embedded=1` 参数（如直接访问该页面）
- **THEN** `.topbar` 正常显示，保留 session 选择器和跳转链接
