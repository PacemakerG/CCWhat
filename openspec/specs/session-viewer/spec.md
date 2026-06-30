## Purpose
定义 AgentLens Web Viewer 读取、展示和分析本地 Coding Agent session 日志的核心能力，包括 session 加载、日志渲染、请求响应关联和任务切分视图。
## Requirements
### Requirement: Backend API — list projects and sessions
`server.py` SHALL 提供 `GET /api/projects` 接口，返回 `~/.claude/projects`（或 `--projects-dir` 指定目录）下所有项目及其会话 ID 列表。

#### Scenario: List projects
- **WHEN** 前端调用 `GET /api/projects`
- **THEN** 返回 JSON 数组，每项包含 `projectDir`（目录名）和 `sessions`（该项目下的 sessionId 列表）

### Requirement: Backend API — load session
`server.py` SHALL 提供 `GET /api/session/<sessionId>` 接口，在所有项目目录中查找对应的主会话 JSONL 文件和 subagent 目录，返回解析后的数据。返回的 user 条目 SHALL 包含 `uuid` 字段，供前端用于 message-http 查询。

#### Scenario: Session found
- **WHEN** 前端调用 `GET /api/session/<sessionId>`，对应 `.jsonl` 文件存在
- **THEN** 返回 `{"main": [...entries], "subagents": [{"agentId": "...", "meta": {...}, "entries": [...]}]}`，每个 user 条目保留原始 `uuid` 字段

#### Scenario: Session not found
- **WHEN** 指定 sessionId 在所有项目目录中均不存在
- **THEN** 返回 HTTP 404 和 `{"error": "session not found"}`

#### Scenario: CORS headers
- **WHEN** 任意 API 请求到达
- **THEN** 响应包含 `Access-Control-Allow-Origin: *`，允许前端从 file:// 或其他来源访问

### Requirement: Backend API — message HTTP lookup
`server.py` SHALL 提供 `GET /api/message-http/<sessionId>/<messageId>` 接口，根据 sessionId 和 messageId（assistant entry 的 message.id，格式为 msg_bdrk_xxx）在 logs 目录下的 `*_parsed.jsonl` 文件中查找对应的 HTTP 请求/响应记录，通过 response_json.message.id 精确匹配。

#### Scenario: Records found
- **WHEN** 调用 `GET /api/message-http/<sessionId>/<messageId>`，能在 parsed JSONL 中找到匹配记录
- **THEN** 返回 `{"records": [...]}` 数组，每条记录包含 `timestamp`、`url`、`request_json`、`response_json` 字段，按 timestamp 升序排列

#### Scenario: No records found
- **WHEN** logs 目录为空或无匹配记录
- **THEN** 返回 `{"records": []}` 和 HTTP 200

#### Scenario: messageId not found in session
- **WHEN** 指定 messageId 在会话 JSONL 中不存在
- **THEN** 返回 HTTP 404 和 `{"error": "message not found"}`

#### Scenario: Exact message.id matching
- **WHEN** 匹配 parsed 记录时
- **THEN** 筛选条件为 `claude_session_id == sessionId` 且 `response_json.message.id == messageId`

### Requirement: Frontend — session selector
前端 SHALL 在加载时调用 `/api/projects` 展示项目和会话选择器，用户选择后加载对应会话。

#### Scenario: Project and session selection
- **WHEN** 页面加载完成
- **THEN** 显示项目列表和每个项目下的会话 ID 下拉选择器；用户选择会话后渲染对话

#### Scenario: Load session
- **WHEN** 用户选择一个 sessionId 并点击加载
- **THEN** 前端调用 `/api/session/<sessionId>`，渲染主会话和 subagent 标签页

### Requirement: Render main session
前端 SHALL 渲染主会话中 `isSidechain: false` 的 `user` 和 `assistant` 条目。

#### Scenario: User message
- **WHEN** 条目 `type` 为 `user`，`isSidechain` 为 false，`message.content` 为字符串
- **THEN** 渲染为右侧用户气泡，显示文本和时间戳

#### Scenario: Assistant message with tool calls
- **WHEN** 条目 `type` 为 `assistant`，`message.content` 包含 `text` 和/或 `tool_use` 块
- **THEN** 渲染助手气泡：文本块直接显示，每个 tool_use 渲染为工具卡片（工具名 + 输入摘要 + 配对结果）

### Requirement: Render subagent sessions
前端 SHALL 为每个 subagent 渲染独立标签页，显示其完整对话（所有 user/assistant 条目）。

#### Scenario: Subagent tab
- **WHEN** 会话包含 subagents
- **THEN** 每个 subagent 显示为独立标签，标签名为 `meta.description`（截断至 20 字符）+ agentType

#### Scenario: Subagent conversation
- **WHEN** 用户切换到 subagent 标签
- **THEN** 渲染该 subagent 的所有 user/assistant 条目（同主会话渲染规则）

### Requirement: Tool call inline display
工具调用 SHALL 内联展示在对应 assistant 气泡内，与 tool_result 配对。

#### Scenario: Tool call card
- **WHEN** assistant 消息包含 `tool_use` 块
- **THEN** 显示工具名称和输入摘要（超 200 字符截断，提供展开按钮）

#### Scenario: Tool result paired
- **WHEN** 后续 user 消息包含匹配 `tool_use_id` 的 `tool_result`
- **THEN** 结果显示在工具卡片内，默认折叠（超 300 字符），点击展开

#### Scenario: Tool error
- **WHEN** `tool_result.is_error` 为 `true`
- **THEN** 工具卡片以红色背景标识错误

### Requirement: Session statistics
前端 SHALL 在每个标签顶部展示该会话/subagent 的统计信息。

#### Scenario: Stats display
- **WHEN** 会话加载完成
- **THEN** 显示：用户消息数、助手消息数、工具调用数、input_tokens、output_tokens、cache_read_input_tokens

### Requirement: CLI web-server subcommand
`deep-ai-analysis web-server` 子命令 SHALL 启动 viewer HTTP 服务，与直接运行 `viewer/server.py` 等效。

#### Scenario: Start with defaults
- **WHEN** 用户执行 `deep-ai-analysis web-server`
- **THEN** 在默认端口 7789 启动服务，打印监听地址和 viewer 访问 URL

#### Scenario: Custom port and projects dir
- **WHEN** 用户执行 `deep-ai-analysis web-server --port 8080 --projects-dir ~/my-projects`
- **THEN** 在指定端口和目录启动服务

### Requirement: CLI web-server req-resp-dir option
`deep-ai-analysis web-server` 子命令 SHALL 支持 `--req-resp-dir` 选项，指定 parsed JSONL 文件所在目录，默认为 `~/.deep-ai-analysis/raw-req-resp`。

#### Scenario: Custom req-resp dir
- **WHEN** 用户执行 `deep-ai-analysis web-server --req-resp-dir ~/ai-logs`
- **THEN** 服务启动后使用指定目录查找 parsed JSONL 文件

### Requirement: HTTP lookup button on messages
前端用户消息气泡和助手消息气泡 SHALL 在右上角显示「查看请求」按钮（主会话和 subagent 均支持）。

#### Scenario: Button visible on user and assistant messages
- **WHEN** 渲染 user 气泡（非纯 tool_result 消息）或 assistant 气泡
- **THEN** 气泡右上角显示「查看请求」按钮（user 传 assistantMsgId，assistant 传自身 message.id）

#### Scenario: Button click triggers lookup
- **WHEN** 用户点击「查看请求」按钮
- **THEN** 前端调用 `/api/message-http/<sessionId>/<messageId>`，显示加载弹窗

#### Scenario: Results displayed in modal
- **WHEN** 后端返回匹配记录
- **THEN** 弹窗展示：token 用量、助手回复内容、折叠的 request_json 摘要、完整 request_json、原始 response_json

#### Scenario: No results
- **WHEN** 后端返回空 records 数组
- **THEN** 弹窗显示"未找到对应的 HTTP 请求记录"

### Requirement: Backend API — list raw logs
`server.py` SHALL 提供 `GET /api/logs` 接口，扫描 logs_dir 下所有 `*_parsed.jsonl` 文件并返回记录列表。支持可选的 `session` query 参数过滤 claude_session_id。

#### Scenario: List all logs
- **WHEN** 调用 `GET /api/logs`
- **THEN** 返回 `{"records": [...], "sessions": [...]}` 按 timestamp 降序排列；`sessions` 为所有出现过的 session ID 列表

#### Scenario: Filter by session
- **WHEN** 调用 `GET /api/logs?session=<id>`
- **THEN** 仅返回 `claude_session_id` 等于指定值的记录

#### Scenario: Empty logs dir
- **WHEN** logs_dir 不存在或无 `*_parsed.jsonl` 文件
- **THEN** 返回 `{"records": [], "sessions": []}`

### Requirement: Raw log viewer page
`viewer/logs.html` SHALL 提供两栏布局的原始日志查看页面。

#### Scenario: Session filter
- **WHEN** 页面加载完成
- **THEN** 顶部显示 session 选择器，选项来自 `/api/logs` 返回的 sessions 列表；默认显示全部

#### Scenario: Log list
- **WHEN** 加载完成或 session 筛选变更
- **THEN** 左栏显示日志列表，每条展示：时间戳、model、stop_reason badge、input+output token 数、response 前 80 字

#### Scenario: Log detail
- **WHEN** 用户点击列表中某条记录
- **THEN** 右栏展示该记录的完整明细：基本信息（url、session_id）、response 内容（完整文本）、token usage、request 摘要（含 messages 数量，折叠展开）、完整 request_json（折叠展开）

### Requirement: Backend API — list req-resp sessions
`server.py` SHALL 提供 `GET /api/req-resp/sessions` 接口，扫描 logs_dir（即 req-resp-dir）下的子目录，返回所有 session 及其对应的日期文件列表。

#### Scenario: List sessions
- **WHEN** 调用 `GET /api/req-resp/sessions`
- **THEN** 返回 `{"sessions": [{"id": "<sessionId>", "dates": ["YYYY-MM-DD", ...]}]}`，按 session ID 排序

#### Scenario: Empty directory
- **WHEN** logs_dir 不存在或无子目录
- **THEN** 返回 `{"sessions": []}`

### Requirement: Backend API — list req-resp records
`server.py` SHALL 提供 `GET /api/req-resp/records?session=<id>&date=<YYYY-MM-DD>` 接口，读取对应 JSONL 文件并返回记录列表。对于 SSE 记录，SHALL 解析 `sse_events` 中的 `message_start` 事件，将 `message.id` 注入为顶层字段 `_message_id`；非 SSE 记录该字段为 `null`。

#### Scenario: Records found
- **WHEN** 调用 `GET /api/req-resp/records?session=<id>&date=<date>`，对应 JSONL 文件存在
- **THEN** 返回 `{"records": [...]}` 数组，每条保留原始字段，SSE 记录额外包含 `_message_id` 字段（格式 `msg_bdrk_xxx`）

#### Scenario: _message_id injected for SSE records
- **WHEN** 记录 `is_sse` 为 true 且 `sse_events` 包含 `message_start` 事件
- **THEN** 记录顶层包含 `_message_id` 字段，值等于 `message_start.message.id`

#### Scenario: _message_id null for non-SSE records
- **WHEN** 记录 `is_sse` 为 false
- **THEN** 记录顶层 `_message_id` 为 `null`

#### Scenario: File not found
- **WHEN** 指定 session/date 的 JSONL 文件不存在
- **THEN** 返回 `{"records": []}` 和 HTTP 200

### Requirement: Raw req-resp viewer search
`viewer/req-resp.html` SHALL 在顶部提供搜索框，支持按 `_message_id`（精确/前缀匹配）或 URL 路径（模糊匹配）实时过滤左侧记录列表。

#### Scenario: Search by message ID
- **WHEN** 用户在搜索框输入 `msg_bdrk_` 开头的字符串
- **THEN** 左侧列表仅显示 `_message_id` 包含该字符串的记录，计数实时更新

#### Scenario: Search by URL
- **WHEN** 用户在搜索框输入非 `msg_bdrk_` 开头的字符串
- **THEN** 左侧列表仅显示 URL 包含该字符串的记录

#### Scenario: Clear search
- **WHEN** 搜索框为空
- **THEN** 显示全部记录

### Requirement: Raw req-resp viewer page
`viewer/req-resp.html` SHALL 提供两栏布局的原始请求/响应日志查看页面。

#### Scenario: Session and date selection
- **WHEN** 页面加载完成
- **THEN** 顶部显示 session 选择器（来自 `/api/req-resp/sessions`）和日期选择器

#### Scenario: Record list
- **WHEN** 用户选择 session 和日期后
- **THEN** 左栏展示记录列表，每条显示：时间、URL path、is_sse badge、响应状态码

#### Scenario: Record detail
- **WHEN** 用户点击列表中某条记录
- **THEN** 右栏展示：基本信息、请求 headers（折叠）、请求 body（折叠）、响应 headers（折叠）、SSE events 列表或响应 body（展开）

### Requirement: Claude Log assistant entry link to req-resp viewer
`claude-log.html` 的 assistant 条目明细面板中，SHALL 在 `message.id` 旁展示「在请求日志中查看」链接，点击后在新 tab 打开 `req-resp.html?q=<message.id>`。

#### Scenario: Link visible for assistant entries with message.id
- **WHEN** 右侧明细展示 assistant 条目且 `message.id` 非空
- **THEN** `message.id` 值旁显示外链按钮，href 为 `req-resp.html?q=<message.id>`，target 为 `_blank`

#### Scenario: Link not shown without message.id
- **WHEN** assistant 条目的 `message.id` 为空
- **THEN** 不显示链接

### Requirement: Raw req-resp viewer URL search param
`viewer/req-resp.html` SHALL 在页面加载时读取 URL query 参数 `?q=`，若存在则自动填入搜索框，并在记录加载完成后触发过滤。

#### Scenario: URL param auto-fills search box
- **WHEN** 用户通过 `req-resp.html?q=msg_bdrk_xxx` 打开页面
- **THEN** 搜索框自动填入 `msg_bdrk_xxx`，记录加载完成后列表自动按该值过滤

### Requirement: Task segmentation entry point
Claude Log 页面 SHALL 为当前已加载 session 提供任务切分入口，用于展示 `/api/task-segments` 返回的结构化 Task Segment 结果。

#### Scenario: Button disabled before session selection
- **WHEN** 页面尚未选择或加载 session
- **THEN** 任务切分按钮 SHALL 处于 disabled 状态
- **AND** 按钮 SHALL 显示“任务切分”

#### Scenario: Button enabled after session load
- **WHEN** 用户成功加载一个 session
- **THEN** 页面 SHALL 启用任务切分按钮
- **AND** 若该 session 尚无缓存结果，按钮 SHALL 显示“任务切分”

#### Scenario: Restore cached task segmentation result
- **WHEN** 当前 session 已生成任务切分结果
- **AND** detail panel 当前显示原始日志详情或分析报告
- **THEN** 任务切分按钮 SHALL 显示“查看任务切分”
- **AND** 用户点击后 SHALL 恢复该 session 的缓存任务切分视图

### Requirement: Task segmentation API request
Claude Log 页面 SHALL 使用当前 session ID 调用 `POST /api/task-segments`，不上传完整 session 内容。

#### Scenario: Request current session only
- **WHEN** 用户点击任务切分按钮且当前 session 没有缓存结果
- **THEN** 前端 SHALL 向 `/api/task-segments` 发送 POST 请求
- **AND** 请求体 SHALL 为 `{"sessionId": "<current-session-id>"}`
- **AND** SHALL NOT 发送 turns、筛选结果、完整日志、跨 session 参数或多 session 参数

#### Scenario: Loading state
- **WHEN** `/api/task-segments` 请求进行中
- **THEN** 任务切分按钮 SHALL disabled
- **AND** 按钮 SHALL 显示“切分中…”
- **AND** detail panel SHALL 显示任务切分 loading 状态

#### Scenario: Failed request
- **WHEN** `/api/task-segments` 返回错误或网络失败
- **THEN** 前端 SHALL 恢复任务切分按钮可点击状态
- **AND** detail panel SHALL 显示可读错误信息
- **AND** 若该 session 已有旧缓存结果，旧结果 SHALL 保留

### Requirement: Task segmentation cache
Claude Log 页面 SHALL 按 `sessionId` 在页面内存中缓存任务切分结果。

#### Scenario: Cache successful result
- **WHEN** `/api/task-segments` 返回成功结果
- **THEN** 前端 SHALL 将结果保存到当前页面内存缓存
- **AND** 缓存 key SHALL 为当前 `sessionId`
- **AND** SHALL NOT 写入 localStorage、后端文件、session 日志或导出包

#### Scenario: Session switch updates button state
- **WHEN** 用户切换 session
- **THEN** 页面 SHALL 根据新 session 是否已有任务切分缓存更新按钮文案
- **AND** 新 session 没有缓存时 SHALL 显示“任务切分”
- **AND** 新 session 有缓存时 SHALL 显示“查看任务切分”

#### Scenario: Re-segment current session
- **WHEN** 当前 session 已有任务切分结果
- **AND** 用户在任务切分视图中点击“重新切分”
- **THEN** 前端 SHALL 重新调用 `/api/task-segments`
- **AND** 请求成功后 SHALL 用新结果覆盖当前 session 的旧缓存
- **AND** 请求失败时 SHALL 保留旧缓存并显示失败原因

### Requirement: Task segmentation overview
Claude Log 页面 SHALL 在 detail panel 中展示任务切分概览和 task card 列表。

#### Scenario: Render summary
- **WHEN** `/api/task-segments` 返回成功结果
- **THEN** detail panel SHALL 展示 summary 信息
- **AND** 至少包含任务数量、ambiguous 状态、topic flip 数量和生成耗时

#### Scenario: Render empty state
- **WHEN** `/api/task-segments` 返回 `tasks` 为空数组
- **THEN** detail panel SHALL 显示“未识别到任务片段”或等价空状态
- **AND** SHALL NOT 渲染空白页面

#### Scenario: Render task cards
- **WHEN** 返回结果包含一个或多个 tasks
- **THEN** detail panel SHALL 为每个 task 渲染一个 task card
- **AND** task card SHALL 展示 task id、title、task type、status、filesChanged 数量、commands 数量、errors 数量、subagent 数量和 ambiguous 标记

#### Scenario: Select a task
- **WHEN** 用户点击 task card
- **THEN** 页面 SHALL 将该 task 标记为选中
- **AND** 在同一 detail panel 中展示该 task 的详情区块

### Requirement: Task segmentation detail panel
Claude Log 页面 SHALL 展示所选 Task Segment 的 evidence、边界原因、文件权重和原始 JSON。

#### Scenario: Render task overview
- **WHEN** 用户选中一个 task
- **THEN** task 详情 SHALL 展示 title、task type、status、startEventId、endEventId 和 finalClaim

#### Scenario: Render evidence
- **WHEN** 用户选中一个 task
- **THEN** task 详情 SHALL 展示 filesRead、filesChanged、commands、testCommands、errors、subagentIds 和 todosUser
- **AND** 空 evidence 列表 SHALL 显示为空状态而不是 undefined/null

#### Scenario: Render boundary reasons
- **WHEN** task 包含 `boundaryReasons`
- **THEN** task 详情 SHALL 逐条展示 boundary reason
- **AND** SHALL 保留原始原因文本中的信号名称和分数信息

#### Scenario: Render file weights
- **WHEN** task 包含 `fileWeights`
- **THEN** task 详情 SHALL 按权重降序展示文件和权重

#### Scenario: Render raw task JSON
- **WHEN** 用户查看 task 详情
- **THEN** 页面 SHALL 提供折叠的 raw JSON 区块
- **AND** raw JSON 内容 SHALL 经过 HTML 转义，不执行其中的 HTML 或脚本

### Requirement: Task segmentation event navigation
Claude Log 页面 SHALL 支持从 Task Segment 定位到起止事件附近的原始日志条目。

#### Scenario: Locate start event
- **WHEN** task 包含可映射的 `startEventId`
- **AND** 用户点击“定位开始事件”
- **THEN** 页面 SHALL 选中并展开对应原始日志条目
- **AND** detail panel SHALL 显示该原始日志条目详情

#### Scenario: Locate end event
- **WHEN** task 包含可映射的 `endEventId`
- **AND** 用户点击“定位结束事件”
- **THEN** 页面 SHALL 选中并展开对应原始日志条目
- **AND** detail panel SHALL 显示该原始日志条目详情

#### Scenario: Event not found
- **WHEN** task 的 `startEventId` 或 `endEventId` 无法映射到当前前端日志条目
- **THEN** 对应定位入口 SHALL disabled 或显示不可定位提示
- **AND** 页面 SHALL NOT 抛出脚本错误

### Requirement: Task segmentation debug boundaries
Claude Log 页面 SHALL 展示或折叠展示 `/api/task-segments` 返回的 debug boundaries，用于人工校准规则。

#### Scenario: Render debug boundaries
- **WHEN** 返回结果包含 `debugBoundaries`
- **THEN** 任务切分视图 SHALL 提供 debug boundaries 区块
- **AND** 每条 boundary SHALL 展示 eventId、score、shouldSplit 和 reasons

#### Scenario: No debug boundaries
- **WHEN** 返回结果不包含 debug boundaries 或为空数组
- **THEN** 页面 SHALL 显示空状态
- **AND** SHALL NOT 影响 task cards 或 task detail 渲染

### Requirement: Session + Tasks 双模块工作台
Viewer SHALL prioritize two core modules: `Session` and `Tasks`.

#### Scenario: 左侧核心导航
- **WHEN** viewer 渲染完成
- **THEN** 左侧 SHALL 显示 `Session` 和 `Tasks` 两个核心导航项
- **AND** `Session` SHALL be the default active page
- **AND** 其他非核心页面 MAY be hidden or shown as explicit placeholders

#### Scenario: 选择 session 后不出现空白主工作区
- **WHEN** 用户选择 project 和 session
- **THEN** viewer SHALL load the session data
- **AND** the active page SHALL render visible content
- **AND** page content SHALL NOT remain blank

### Requirement: Session 页面承接旧版日志展示
`Session` page SHALL migrate and preserve the previous local log viewer capability.

#### Scenario: Session 页面展示日志树和详情区
- **WHEN** 用户进入 `Session` 页面并已选择 session
- **THEN** 页面 SHALL 显示 turn tree / entry list
- **AND** 页面 SHALL 显示 entry detail panel
- **AND** 用户 SHALL be able to click an entry and inspect its raw/detail content

#### Scenario: Session 页面保留筛选和搜索
- **WHEN** 用户在 Session 页面查看日志
- **THEN** 页面 SHALL retain type filters
- **AND** 页面 SHALL respect the global search query for entries

#### Scenario: Session 页面为空时显示明确状态
- **WHEN** session 已加载但没有 entries
- **THEN** 页面 SHALL show a clear empty state
- **AND** SHALL NOT show an empty blank panel

#### Scenario: raw-events alias 跳转到 Session
- **WHEN** internal code navigates to `raw-events`
- **THEN** viewer SHALL route it to `Session`
- **AND** SHALL preserve canonical event focusing behavior

### Requirement: Tasks 页面承接任务切分
`Tasks` page SHALL provide task segmentation and task detail browsing for the current session.

#### Scenario: Tasks 页面无切分结果时显示 CTA
- **WHEN** 用户进入 `Tasks` 页面且当前 session 尚未加载
- **THEN** 页面 SHALL display a clear disabled state
- **AND** SHALL explain that a session must be selected first

#### Scenario: 已加载 session 后进入 Tasks 自动切分
- **WHEN** 用户已经选择并成功加载一个 session
- **AND** 当前 session 没有 task segmentation result
- **WHEN** 用户点击左侧 `Tasks`
- **THEN** viewer SHALL automatically request task segmentation for the current session
- **AND** 页面 SHALL show loading, success, or error state
- **AND** 页面 SHALL NOT remain blank

#### Scenario: Tasks 页面复用当前 session 切分缓存
- **WHEN** 当前 session already has a task segmentation result
- **AND** 用户点击左侧 `Tasks`
- **THEN** 页面 SHALL render cached Task List and Task Detail immediately
- **AND** SHALL NOT send an unnecessary duplicate segmentation request

#### Scenario: Tasks 页面展示 Task List 和 Task Detail
- **WHEN** task segmentation returns tasks
- **THEN** 页面 SHALL render Task List and Task Detail panes
- **AND** selecting a task SHALL update Task Detail

#### Scenario: 报告分析不阻塞任务切分
- **WHEN** a long-running session report analysis request is in progress
- **AND** 用户在 `Tasks` 页面触发 task segmentation
- **THEN** viewer server SHALL be able to process the task segmentation request without waiting for the analysis request to finish
- **AND** task segmentation SHALL NOT be serialized behind report generation by the HTTP server

#### Scenario: Task 卡片名称稳定
- **WHEN** task segmentation returns multiple tasks
- **THEN** task card title SHALL use a stable ordinal label such as `任务 1`, `任务 2`
- **AND** SHALL NOT display raw noisy event text, encoded payload fragments, or adapter-specific internal strings as the card title

#### Scenario: Task Detail 保留核心 tabs
- **WHEN** 用户查看 task detail
- **THEN** 页面 SHALL provide Overview, Evidence, Turns, Files & Diff, Commands, and Raw task tabs or equivalent sections

#### Scenario: Task evidence 跳转回 Session 页面
- **WHEN** 用户点击 task start/end/evidence navigation
- **THEN** viewer SHALL navigate to `Session`
- **AND** SHALL focus the corresponding entry when the target can be resolved
- **AND** SHALL show clear debug information when the target cannot be resolved

#### Scenario: Session 和 Tasks 往返切换不丢失页面
- **WHEN** 用户已加载 session 并停留在 `Session`
- **AND** 用户点击 `Tasks`
- **AND** 用户再点击 `Session`
- **THEN** `Session` 页面 SHALL restore the current session log list and detail area
- **AND** viewer SHALL have an active page
- **AND** 主工作区 SHALL NOT be blank

### Requirement: Session 报告分析入口
`Session` page SHALL expose the existing session report analysis workflow.

#### Scenario: Session 页面展示报告分析按钮
- **WHEN** 用户进入 `Session` 页面
- **THEN** 页面 SHALL show a report analysis button in the Session toolbar
- **AND** the button SHALL be disabled until the current session is loaded

#### Scenario: 报告分析复用已有链路
- **WHEN** 用户点击 Session 页面报告分析按钮
- **THEN** viewer SHALL open the existing report mode modal
- **AND** confirming the modal SHALL call the existing `/api/analyze` workflow
- **AND** report output SHALL be shown in the Session detail area
- **AND** viewer SHALL NOT navigate to a missing `evidence` page

### Requirement: 非核心页面降级
Non-core workbench pages SHALL NOT block the Session and Tasks migration.

#### Scenario: 非核心入口不伪装为已完成
- **WHEN** Overview, Timeline, Req / Resp, Diff, Diagnostics, Export, or Settings is visible
- **THEN** it SHALL either show a clear placeholder or a minimal existing entry point
- **AND** it SHALL NOT be required for this change's manual acceptance

### Requirement: 回归测试
The change SHALL include regression tests for the two core modules and navigation aliases.

#### Scenario: 静态结构测试
- **WHEN** tests inspect `viewer/claude-log.html`
- **THEN** they SHALL verify default `Session` navigation, `Tasks` navigation, and Session log container presence

#### Scenario: Session load tests
- **WHEN** tests inspect frontend session loading behavior
- **THEN** they SHALL verify `loadSession()` does not auto-jump away because task segmentation is missing
- **AND** it renders the current active page after session data loads

#### Scenario: Task navigation tests
- **WHEN** tests inspect task evidence navigation
- **THEN** they SHALL verify task navigation targets route to Session/raw-events alias and keep event focusing behavior

#### Scenario: Tasks 自动切分与往返测试
- **WHEN** DOM tests simulate loading a session and clicking `Tasks`
- **THEN** tests SHALL verify task segmentation is requested for the current session
- **AND** tests SHALL verify switching back to `Session` restores visible log content

#### Scenario: 并发和标题回归测试
- **WHEN** tests inspect viewer server construction
- **THEN** they SHALL verify the viewer uses a threaded HTTP server
- **WHEN** tests inspect task segmentation output
- **THEN** they SHALL verify task titles are stable ordinal labels

#### Scenario: 报告分析入口测试
- **WHEN** tests inspect frontend analysis behavior
- **THEN** they SHALL verify a visible Session report analysis button exists
- **AND** analysis code SHALL route report rendering to `Session`, not a missing `evidence` page

### Requirement: Task Segment 任务卡片选择
Claude Log 页面 SHALL 支持用户点击任意 Task Segment card 后切换当前选中任务，并展示该任务对应的详情内容。

#### Scenario: 点击任务卡片切换详情
- **WHEN** Task Segment 面板已渲染多个 task cards
- **AND** 用户点击非当前选中的 task card
- **THEN** 页面 SHALL 将该 task 标记为唯一选中 task
- **AND** task detail SHALL 展示被点击 task 的 `taskId`、`title`、`taskType`、`startEventId`、`endEventId`、evidence、fileWeights 和 boundaryReasons
- **AND** 之前选中的 task card SHALL 不再显示 selected 状态

#### Scenario: 任务选择状态由数据驱动
- **WHEN** Task Segment 面板重渲染
- **THEN** selected 状态 SHALL 由 `selectedTaskSegmentId` 和 task data 决定
- **AND** SHALL NOT 依赖查询 inline `onclick` 字符串来查找当前 card

#### Scenario: 点击无效任务不会破坏当前视图
- **WHEN** 用户触发的 task id 不存在于当前 session 的缓存结果中
- **THEN** 页面 SHALL 保持当前选中 task 和当前 detail 内容
- **AND** SHALL NOT 抛出脚本错误

### Requirement: Task Segment Final Claim 展示
Claude Log 页面 SHALL 将 Task Segment 的 `finalClaim` 展示为 Agent 最终声明，并明确该内容是 agent 自述而非任务成功证据。

#### Scenario: 展示 final claim 摘要
- **WHEN** 当前 task 包含 `finalClaim`
- **THEN** task detail SHALL 显示“Agent 最终声明”区块
- **AND** 默认 SHALL 展示不超过 160 字符的摘要
- **AND** SHALL 显示该声明不代表任务成功的提示

#### Scenario: 展开 final claim 全文
- **WHEN** `finalClaim` 超过摘要长度
- **THEN** task detail SHALL 提供折叠的全文查看入口
- **AND** 全文内容 SHALL 经过 HTML 转义
- **AND** 展开全文 SHALL NOT 改变当前选中 task

#### Scenario: 无 final claim
- **WHEN** 当前 task 不包含 `finalClaim`
- **THEN** task detail SHALL 显示空状态或不渲染 Agent 最终声明正文
- **AND** SHALL NOT 显示 undefined/null

### Requirement: Task Segment 错误摘要展示
Claude Log 页面 SHALL 将 Task Segment 的 `errors` 默认展示为短摘要，并将长错误原文折叠，以便用户快速扫描负向证据。

#### Scenario: 展示错误摘要
- **WHEN** 当前 task 的 evidence 包含 `errors`
- **THEN** task detail SHALL 显示错误数量
- **AND** 每条错误默认 SHALL 展示短摘要
- **AND** 单条摘要 SHALL 截断到有限长度，避免撑开页面或遮挡其他 evidence

#### Scenario: 展开错误原文
- **WHEN** 某条 error 原文长于摘要
- **THEN** 页面 SHALL 提供折叠原文查看入口
- **AND** 原文 SHALL 经过 HTML 转义
- **AND** 折叠区 SHALL NOT 默认展开

#### Scenario: 无错误
- **WHEN** 当前 task 的 `errors` 为空或不存在
- **THEN** task detail SHALL 显示错误为空状态
- **AND** SHALL NOT 显示 undefined/null

### Requirement: 左侧稳定 Turn 索引
Claude Log 页面 SHALL 基于完整 session entries 构建稳定 turn 索引，使 Task Segment 的事件定位不受当前类型筛选或搜索筛选改变。

#### Scenario: 完整 entries 构建 turn 归属
- **WHEN** session 加载成功
- **THEN** 页面 SHALL 基于完整 group entries 构建 turn tree
- **AND** 每个可定位 entry SHALL 记录其所属 `_turnKey`
- **AND** 每个可定位 entry SHOULD 记录其 turn root index

#### Scenario: 筛选不改变 turn 归属
- **WHEN** 用户启用 type filter 或搜索 filter
- **THEN** entry 的 `_turnKey` SHALL 保持不变
- **AND** 定位事件 SHALL 使用既有 `_turnKey` 展开 turn
- **AND** SHALL NOT 从过滤后的 entries 重新推断目标事件所属 turn

#### Scenario: Subagent turn 归属
- **WHEN** 目标事件来自 subagent
- **THEN** 页面 SHALL 使用该 subagent group 内的 turn index 定位
- **AND** SHALL 展开对应 subagent group

### Requirement: Task Segment 事件定位到左侧导航
Claude Log 页面 SHALL 支持从 Task Segment 的 `startEventId` 和 `endEventId` 定位到左侧导航中的对应 group、turn 和 entry。

#### Scenario: 定位开始事件到左侧导航
- **WHEN** 当前 task 包含可映射的 `startEventId`
- **AND** 用户点击“定位开始事件”
- **THEN** 页面 SHALL 展开目标 entry 所属 group
- **AND** 页面 SHALL 展开目标 entry 所属 turn
- **AND** 左侧导航 SHALL 滚动到目标 entry 或其 turn header
- **AND** 目标 entry 或其 turn header SHALL 显示高亮状态

#### Scenario: 定位结束事件到左侧导航
- **WHEN** 当前 task 包含可映射的 `endEventId`
- **AND** 用户点击“定位结束事件”
- **THEN** 页面 SHALL 展开目标 entry 所属 group
- **AND** 页面 SHALL 展开目标 entry 所属 turn
- **AND** 左侧导航 SHALL 滚动到目标 entry 或其 turn header
- **AND** 目标 entry 或其 turn header SHALL 显示高亮状态

#### Scenario: 定位不默认替换 task detail
- **WHEN** 用户从 task detail 点击“定位开始事件”或“定位结束事件”
- **THEN** 页面 SHALL 保持当前 Task Segment detail 可见
- **AND** SHALL NOT 默认用原始日志 detail 替换 task detail

#### Scenario: 目标被筛选隐藏
- **WHEN** 目标 entry 存在但被当前 type filter 或搜索 filter 隐藏
- **THEN** 页面 SHALL 展开并滚动到目标 turn header
- **AND** 页面 SHALL 提示目标事件被当前筛选隐藏
- **AND** SHALL NOT 抛出脚本错误

#### Scenario: 事件无法映射
- **WHEN** `startEventId` 或 `endEventId` 无法映射到当前 session 的 entry
- **THEN** 对应定位按钮 SHALL disabled 或展示不可定位提示
- **AND** 页面 SHALL 保持当前 task detail 不变

### Requirement: Viewer 初始化入口唯一且非递归
`viewer/claude-log.html` SHALL 只有一个真实页面初始化入口，页面打开后 SHALL 自动加载项目列表并初始化 workbench 状态。初始化流程 MUST NOT 通过函数声明提升导致 `init()` 调用自身。

#### Scenario: 页面自动初始化
- **WHEN** 用户打开 viewer 页面
- **THEN** 前端调用项目列表加载逻辑
- **AND** 页面不会出现 `Maximum call stack size exceeded`

#### Scenario: 初始化函数非递归
- **WHEN** 前端测试执行 `init()`
- **THEN** `init()` 至多进入一次顶层初始化流程
- **AND** 不会通过 `_origInit` 或等价包装调用自身

### Requirement: Viewer 默认进入 Session 页面
Workbench SHALL 默认展示 `Session` 页面，`Session` 页面内部展示当前 session 的 turns/events 列表和详情。选择或加载 session 后，前端 SHALL 刷新当前页面，但 MUST NOT 自动跳转到 `Tasks` 页面。

#### Scenario: 首屏默认 Session
- **WHEN** viewer 初次加载完成
- **THEN** 左侧导航中 `Session` 处于 active 状态
- **AND** 主工作区展示 session/raw events 相关内容或选择 session 的提示

#### Scenario: 加载 session 不自动进入 Tasks
- **WHEN** 用户选择一个 session 并完成加载
- **THEN** 当前页面仍为 `Session`
- **AND** `Tasks` 页面不会自动运行任务切分

### Requirement: Tasks 页面由用户手动进入
`Tasks` 页面 SHALL 作为左侧一级导航入口存在。任务切分 SHALL 仅在用户点击 `Tasks` 页面或任务切分按钮后触发或展示缓存结果。

#### Scenario: 用户点击 Tasks
- **WHEN** 用户点击左侧 `Tasks`
- **THEN** 主工作区切换到 `Tasks` 页面
- **AND** 若当前 session 已加载，页面展示任务切分入口、加载状态、缓存结果或任务列表

#### Scenario: 未加载 session 时点击 Tasks
- **WHEN** 用户尚未选择 session 并点击 `Tasks`
- **THEN** 页面显示需要先选择 session 的提示
- **AND** 不发送 `/api/task-segments` 请求

### Requirement: 左侧导航作为一级功能入口
Viewer SHALL 使用左侧一级导航展示产品级功能入口，而不是把全局左栏固定为 turn 树。导航 SHALL 至少包含 `Session`、`Tasks`、`Overview`、`Timeline`、`Req / Resp`、`Diff`、`Diagnostics`、`Export`、`Settings`。

#### Scenario: 左侧导航入口齐全
- **WHEN** viewer 页面渲染完成
- **THEN** 左侧导航展示所有 required 功能入口
- **AND** turn/event 列表只在 `Session` 页面内部展示

#### Scenario: 未完成页面有占位
- **WHEN** 用户点击尚未完整实现的数据页面
- **THEN** 主工作区显示清晰的开发中、空状态或需要选择 session 的占位
- **AND** 页面不能空白

### Requirement: 本地 App Shell 视觉迁移
Viewer SHALL 采用本地 App Shell 的视觉方向：左侧导航分组、顶部上下文栏、紧凑按钮、开发者工具风格和高信息密度布局。该视觉迁移 MUST NOT 改变云端已有的数据加载、server、adapter 和 task segmentation API 行为。

#### Scenario: 顶部只承载全局上下文
- **WHEN** viewer 页面渲染完成
- **THEN** 顶部区域展示 Agent、Project、Session、Search、Refresh 等全局上下文控件
- **AND** 页面级操作放在对应页面内部

#### Scenario: 不直接复制设计稿
- **WHEN** 实现 App Shell 视觉迁移
- **THEN** 页面使用真实 API 和当前 viewer 状态
- **AND** 不以静态设计稿或 mock 数据替代真实 session 数据

### Requirement: Agent badge 使用真实 agent
Viewer 的 agent badge SHALL 从后端返回的真实 agent 信息设置。初始 DOM MAY 使用中性占位，但加载完成后 MUST NOT 硬编码为 `claude`，除非后端真实返回的 agent 就是 `claude`。

#### Scenario: 显示真实 agent
- **WHEN** `/api/projects` 或 `/api/viewer/status` 返回 `agent: "opencode"`
- **THEN** agent badge 显示 `opencode`
- **AND** 不显示硬编码的 `claude`

### Requirement: 任务证据定位保持稳定
Task 详情中的开始事件、结束事件、命令、错误和其他 evidence 跳转 SHALL 使用 canonical navigation target 定位到 `Session` 页面内部的对应 turn/event。视觉迁移 MUST NOT 破坏已有 `startEventId` / `endEventId` 定位能力。

#### Scenario: 定位开始事件
- **WHEN** 用户在 Task 详情点击定位开始事件
- **THEN** workbench 切换或保持在 `Session` 页面
- **AND** 左侧或页面内部的对应 turn/event 被滚动到可见位置并高亮

#### Scenario: 未知事件显示可解释状态
- **WHEN** Task evidence 的 event id 无法映射到当前 session entries
- **THEN** 定位按钮禁用或显示无法定位的提示
- **AND** 不抛出 JavaScript 异常

### Requirement: 前端派生会话层
Claude Log Viewer SHALL 在加载 session entries 后派生 Conversation 层，用于表示一次用户请求到 Agent 完成本次反馈之间的交互单元。

#### Scenario: 真实用户请求开始新会话
- **WHEN** session entries 中出现真实用户请求
- **THEN** viewer SHALL 创建一个新的 Conversation
- **AND** Conversation SHALL 拥有人类可读 label，例如 `会话 1`
- **AND** Conversation SHALL 记录 start anchor、end anchor、user message text 和所属 group

#### Scenario: 下一条真实用户请求结束上一会话
- **WHEN** 已存在当前 Conversation
- **AND** 后续 entries 中出现下一条真实用户请求
- **THEN** viewer SHALL 结束上一 Conversation
- **AND** viewer SHALL 创建新的 Conversation
- **AND** 两个 Conversation 的编号 SHALL 保持稳定且按原始执行顺序递增

#### Scenario: 非真实用户请求不开始新会话
- **WHEN** entry 是纯 tool_result、system-reminder、local-command、last-prompt、queue、permission 或重复镜像用户消息
- **THEN** viewer SHALL NOT 将该 entry 作为新 Conversation 的起点
- **AND** 该 entry SHALL 归入当前 Conversation、preamble 或 metadata

#### Scenario: 首个用户请求前的 entries
- **WHEN** 首个真实用户请求前存在 system/context/metadata entries
- **THEN** viewer SHALL NOT 因这些 entries 改变普通 Conversation 编号
- **AND** viewer MAY 将其归入 preamble 或 group metadata

### Requirement: 会话内派生最小 Turn
Claude Log Viewer SHALL 在每个 Conversation 内派生 minimal Turn，且每个 Turn 只表示一种执行片段。

#### Scenario: 用户消息 Turn
- **WHEN** Conversation 由真实用户请求开始
- **THEN** viewer SHALL 为该用户请求创建 `user_message` Turn
- **AND** 该 Turn SHALL 只包含当前用户请求对应的最小内容和原始 JSON 引用

#### Scenario: Thinking Turn
- **WHEN** assistant content 或 normalized event 表示 thinking/reasoning
- **THEN** viewer SHALL 创建 `thinking` Turn
- **AND** 该 Turn SHALL NOT 合并后续 tool_use 或 assistant text

#### Scenario: Assistant text Turn
- **WHEN** assistant content block 是普通 text
- **THEN** viewer SHALL 创建 `assistant_text` Turn
- **AND** 该 Turn SHALL NOT 合并同一 entry 中的 tool_use block

#### Scenario: Tool use Turn
- **WHEN** assistant content block 是 `tool_use`
- **THEN** viewer SHALL 为该 block 创建一个 `tool_use` Turn
- **AND** 该 Turn SHALL 记录 tool name、tool_use_id、input 摘要和 block anchor

#### Scenario: Tool result Turn
- **WHEN** user entry 或 normalized event 包含 `tool_result`
- **THEN** viewer SHALL 为该 tool_result 创建一个 `tool_result` Turn
- **AND** 该 Turn SHALL 记录 tool_use_id、结果摘要、错误状态和 block anchor

#### Scenario: 多 block assistant entry 拆分
- **WHEN** 一个 assistant entry 的 `message.content` 包含多个 block
- **THEN** viewer SHALL 按 block 顺序创建多个 Turn
- **AND** 每个 Turn SHALL 对应唯一 content block
- **AND** 一个 Turn SHALL NOT 包含多次 tool_use

#### Scenario: 一个 Turn 只表示一种片段
- **WHEN** viewer 完成 Turn 派生
- **THEN** 每个非 unknown Turn SHALL 只有一个 kind
- **AND** `tool_use` Turn SHALL NOT 同时包含 `tool_result`
- **AND** `assistant_text` Turn SHALL NOT 同时包含 `tool_use`

### Requirement: Conversation 和 Turn 稳定锚点
Claude Log Viewer SHALL 为 Conversation 和 minimal Turn 建立稳定锚点，使原始 entry、content block 和派生节点可互相定位。

#### Scenario: Conversation key 稳定
- **WHEN** viewer 派生 Conversation
- **THEN** 每个 Conversation SHALL 拥有稳定 `conversationKey`
- **AND** `conversationKey` SHALL 包含 group scope 和 conversation index

#### Scenario: Turn key 稳定
- **WHEN** viewer 派生 Turn
- **THEN** 每个 Turn SHALL 拥有稳定 `turnKey`
- **AND** `turnKey` SHALL 包含 group scope、conversation scope 和 turn index

#### Scenario: Entry anchor 映射到 Conversation 和 Turn
- **WHEN** 原始 entry 可通过 uuid、message id、event id 或 file anchor 定位
- **THEN** viewer SHALL 能将该 entry 映射到所属 Conversation
- **AND** viewer SHALL 能将该 entry 映射到该 entry 派生出的一个或多个 Turn

#### Scenario: Content block anchor 映射到 Turn
- **WHEN** Turn 来自 entry 内的某个 content block
- **THEN** viewer SHALL 为该 Turn 记录 block anchor
- **AND** block anchor SHALL 能映射回唯一 Turn

#### Scenario: 兼容旧 entry 级定位
- **WHEN** 旧逻辑提供 entry 级 `startEventId` 或 `endEventId`
- **THEN** viewer SHALL 能将该 anchor 映射到所属 Conversation
- **AND** viewer SHALL 能映射到该 entry 下第一个或最后一个相关 minimal Turn

### Requirement: Change 1 不改变 Task 树注入和 Tools Skills Snapshot
Conversation minimal Turn 数据层改造 SHALL NOT 在本 change 中实现 Task 注入或 Tools / Skills Snapshot UI。

#### Scenario: 不注入 Task 树
- **WHEN** task segmentation 返回任务结果
- **THEN** 本 change SHALL NOT 要求将 Task 作为左侧树顶层分组渲染
- **AND** Task 注入 SHALL 留给后续 change

#### Scenario: 不展示 Tools Skills Snapshot
- **WHEN** session 加载完成
- **THEN** 本 change SHALL NOT 要求在 Trace 顶部展示 Tools / Skills Snapshot 节点
- **AND** Tools / Skills Snapshot SHALL 留给后续 change

### Requirement: Session 页面显示 Trace 树
Claude Log Viewer 的 `Session` 页面 SHALL 基于已有 Conversation/minimal Turn 数据层，以树状结构展示当前 session 的执行 Trace，而不是继续使用平铺 Turn 卡片作为主浏览结构。

#### Scenario: 默认显示会话与 Turn 树
- **WHEN** 用户加载一个 session 并进入 `Session` 页面
- **THEN** 页面 SHALL 显示按 group 分段的 Trace 树
- **AND** 每个 group 下 SHALL 展示按顺序编号的会话节点，例如 `会话 1`、`会话 2`
- **AND** 每个会话节点下 SHALL 展示该会话包含的 minimal Turn 节点，例如 `Turn 1`、`Turn 2`

#### Scenario: 会话节点展示摘要
- **WHEN** Trace 树渲染会话节点
- **THEN** 会话节点 SHALL 展示会话 label、用户请求摘要和 Turn 数量
- **AND** 会话节点 SHALL NOT 使用 UUID、event id 或文件行号作为默认标题

#### Scenario: Turn 节点展示摘要
- **WHEN** Trace 树渲染 Turn 节点
- **THEN** Turn 节点 SHALL 展示稳定 Turn label、kind badge 和当前 Turn 的简短内容摘要
- **AND** Turn 节点 SHALL NOT 混入同一会话内其他 Turn 的摘要

### Requirement: Trace 树节点交互
Claude Log Viewer SHALL 支持在 Trace 树中展开/折叠会话、选择会话和选择 Turn，并用右侧详情区展示对应层级的内容。

#### Scenario: 展开和折叠会话
- **WHEN** 用户点击会话节点的展开/折叠控件
- **THEN** 页面 SHALL 切换该会话下 Turn 节点的可见状态
- **AND** 其他会话的展开状态 SHALL 保持不变

#### Scenario: 选择会话
- **WHEN** 用户点击会话节点主体
- **THEN** 页面 SHALL 将该会话标记为当前选中节点
- **AND** 右侧详情区 SHALL 展示会话级摘要

#### Scenario: 选择 Turn
- **WHEN** 用户点击某个 Turn 节点
- **THEN** 页面 SHALL 将该 Turn 标记为当前选中节点
- **AND** 右侧详情区 SHALL 展示该 Turn 的极简详情
- **AND** 当前选中状态 SHALL 只落在一个 Trace 节点上

#### Scenario: Task 定位跳转到 Trace Turn
- **WHEN** 用户从 `Tasks` 页面点击“定位开始 Turn”或“定位结束 Turn”
- **THEN** 页面 SHALL 切换到 `Session` 页面
- **AND** 页面 SHALL 展开目标 Turn 所属会话
- **AND** 页面 SHALL 选中、滚动并临时高亮目标 Turn 节点

### Requirement: 会话详情极简展示
Claude Log Viewer SHALL 在用户选中会话节点时展示轻量会话摘要，用于确认该会话对应的一次用户请求和 Agent 回复范围。

#### Scenario: 会话详情内容
- **WHEN** 用户选中会话节点
- **THEN** 右侧详情区 SHALL 展示会话 label、所属 group、用户请求内容或摘要、Agent 最终反馈摘要、Turn 数量和起止锚点
- **AND** 右侧详情区 SHALL NOT 展示 task evidence、diagnostics、diff、test result 或 req/resp 明细

#### Scenario: 会话详情中的 Turn 入口
- **WHEN** 会话详情展示该会话包含的 Turn
- **THEN** 每个 Turn 入口 SHALL 使用稳定 Turn label 和 kind
- **AND** 用户点击该入口后 SHALL 选中 Trace 树中对应 Turn 节点

### Requirement: Turn 详情只展示 Agent 响应和原始 JSON
Claude Log Viewer SHALL 在用户选中 Turn 节点时只展示两个主要区块：`Agent 响应` 和 `原始 JSON`。

#### Scenario: Turn detail 区块数量
- **WHEN** 用户选中任意 Turn 节点
- **THEN** 右侧详情区 SHALL 展示 `Agent 响应` 区块
- **AND** 右侧详情区 SHALL 展示折叠的 `原始 JSON` 区块
- **AND** 右侧详情区 SHALL NOT 展示 evidence、files、diff、commands、tests、diagnostics 或 task boundary 字段

#### Scenario: Agent 响应按 Turn kind 渲染
- **WHEN** 选中的 Turn kind 为 `user_message`、`thinking`、`assistant_text`、`tool_use`、`tool_result`、`system`、`context` 或 `unknown`
- **THEN** `Agent 响应` 区块 SHALL 展示当前 minimal Turn 对应的文本、工具名、工具输入、工具结果或摘要
- **AND** 该区块 SHALL NOT 展示同一会话内其他 Turn 的内容

#### Scenario: Raw JSON 只对应当前 Turn
- **WHEN** 用户展开 `原始 JSON`
- **THEN** 页面 SHALL 展示当前 Turn 对应的原始 entry 或 block anchor 数据
- **AND** Raw JSON SHALL NOT 默认展示整个会话、整个 session 或相邻 Turn 的 JSON

### Requirement: 筛选与搜索不改变 Trace 树编号
Claude Log Viewer SHALL 保持会话编号、Turn 编号和 Trace node key 的稳定性，不因搜索或类型筛选而重新切分或重新编号。

#### Scenario: 类型筛选保持编号稳定
- **WHEN** 用户切换 `user / assistant / system / attachment / perm / fhs / queue / other` 类型筛选
- **THEN** 会话 label 和 Turn label SHALL 保持不变
- **AND** 页面 SHALL NOT 基于筛选后的可见节点重新生成编号

#### Scenario: 搜索保持编号稳定
- **WHEN** 用户在 Session 页面搜索文本
- **THEN** Trace 树 MAY 隐藏或标记不匹配的 Turn 节点
- **AND** 匹配节点 SHALL 保留原始会话编号和 Turn 编号

#### Scenario: 选中节点被筛选隐藏
- **WHEN** 当前选中的 Turn 被搜索或类型筛选隐藏
- **THEN** 右侧详情区 SHALL 显示“当前筛选隐藏了该 Turn”或等价提示
- **AND** 页面 SHALL NOT 自动选择另一个 Turn 或静默清空详情区

### Requirement: 本 change 不实现 Task 与 Tools/Skills 树层
本 change SHALL 只实现 `Trace -> 会话 -> Turn` 的 Session 页面树状浏览和极简 Turn 详情，不引入后续 change 的树顶层能力。

#### Scenario: 不注入 Task 顶层
- **WHEN** 用户完成任务切分或进入 `Tasks` 页面
- **THEN** `Session` 页面的 Trace 树 SHALL NOT 在本 change 中新增 `Task -> 会话 -> Turn` 顶层结构
- **AND** Task 注入 SHALL 留给后续 change 实现

#### Scenario: 不展示 Tools/Skills Snapshot 节点
- **WHEN** 用户进入 `Session` 页面
- **THEN** Trace 树 SHALL NOT 在本 change 中新增 `Tools Snapshot`、`Skills Snapshot` 或等价顶层节点
- **AND** Tools/Skills Snapshot SHALL 留给后续 change 实现

### Requirement: Trace 树顶部显示 Tools Skills Snapshot
Claude Log Viewer 的 `Session` 页面 SHALL 在 Trace 树顶部显示唯一的 `Tools / Skills Snapshot` 节点，用于展示当前 Trace 初始可用工具和技能。

#### Scenario: 未切分时显示 Snapshot
- **WHEN** 用户加载 session 并进入 `Session` 页面
- **THEN** Trace 树 SHALL 在会话节点之前显示 `Tools / Skills Snapshot` 节点
- **AND** Snapshot 节点 SHALL 只显示一次
- **AND** 会话节点 SHALL 继续显示在 Snapshot 节点之后

#### Scenario: 切分确认后 Snapshot 仍在顶部
- **WHEN** 用户确认 Task 切分结果后进入 `Session` 页面
- **THEN** Trace 树 SHALL 在所有 Task 节点之前显示 `Tools / Skills Snapshot` 节点
- **AND** Snapshot 节点 SHALL NOT 出现在任何 Task 节点内部
- **AND** Snapshot 节点 SHALL NOT 因 Task 数量增加而重复
- **AND** Task 节点 SHALL 是 Snapshot 之后的一级可展开节点，而不是 Turn 上的 badge

#### Scenario: 点击 Snapshot 展示详情
- **WHEN** 用户点击 `Tools / Skills Snapshot` 节点
- **THEN** 右侧详情区 SHALL 展示当前 Trace 的 Tools 列表和 Skills 列表
- **AND** 右侧详情区 SHALL 展示 Snapshot 的来源说明或锚点信息
- **AND** 右侧详情区 SHALL NOT 展示某个 Task、会话或 Turn 的详情

### Requirement: Task 切分结果需要确认后注入 Trace 树
Claude Log Viewer SHALL 将自动切分得到的 Task Segment 先作为预览结果展示，只有用户确认后才将 Task 注入 `Session` 页面的 Trace 树。

#### Scenario: 切分完成但未确认
- **WHEN** 用户点击“切分 Task”并得到 Task Segment 结果
- **THEN** `Tasks` 页面 SHALL 展示切分预览
- **AND** `Session` 页面的 Trace 树 SHALL 仍保持 `Snapshot -> 会话 -> Turn` 结构
- **AND** 页面 SHALL 提供“确认切分”或等价操作

#### Scenario: 用户确认切分
- **WHEN** 用户在 `Tasks` 页面确认当前 Task Segment 结果
- **THEN** 当前 session SHALL 记录已确认的 Task Trace 状态
- **AND** `Session` 页面的 Trace 树 SHALL 切换为 `Snapshot -> Task -> 会话 -> Turn` 结构
- **AND** 已确认状态 SHALL 只作用于当前 session
- **AND** 页面 SHALL NOT 仅通过在 Turn 行内显示 `Task N` badge 来表示已确认 Task Trace

#### Scenario: 用户重新切分
- **WHEN** 用户在已有确认结果后再次触发重新切分
- **THEN** 页面 SHALL 取消当前 session 的已确认 Task Trace 状态
- **AND** 新结果 SHALL 先作为预览展示
- **AND** `Session` 页面的 Task 注入 SHALL 等待用户再次确认

### Requirement: Task 节点作为会话上层分组
Claude Log Viewer SHALL 在 Task Trace 确认后，将 Task 节点作为会话节点的上层分组展示。

#### Scenario: Task 是 Trace 一级结构
- **WHEN** Task Trace 已确认且存在至少一个 Task Segment
- **THEN** Trace 树 SHALL 在 `Tools / Skills Snapshot` 之后直接展示 Task 节点
- **AND** Source group，例如 `main`、`Claude Code` 或 subagent 名称，MAY 作为 Task 节点或会话节点的元信息展示
- **AND** Source group SHALL NOT 成为 Snapshot 和 Task 之间的树层级
- **AND** 被 Task 覆盖的会话 SHALL NOT 继续作为 Task 外的独立会话节点展示

#### Scenario: Task 节点展示基础信息
- **WHEN** Trace 树渲染 Task 节点
- **THEN** Task 节点 SHALL 展示人类可读 label，例如 `Task 1`
- **AND** Task 节点 SHALL 展示 title 或 user intent 摘要
- **AND** Task 节点 MAY 展示 task type、status、confidence、覆盖会话数、覆盖 Turn 数和 boundary reason 简短摘要
- **AND** Task 节点 SHALL NOT 使用长 UUID 或 event id 作为默认标题

#### Scenario: Task 下展示会话和 Turn
- **WHEN** Task 节点处于展开状态
- **THEN** Trace 树 SHALL 在该 Task 下展示被该 Task 覆盖的会话节点
- **AND** 每个会话节点下 SHALL 展示该 Task 覆盖范围内的 Turn 节点
- **AND** 会话和 Turn 的 label SHALL 保持原始 Trace 中的稳定编号
- **AND** Task 下的 Turn 节点 SHALL NOT 再通过 `Task N` badge 表示自己的所属 Task

#### Scenario: Task 锚点使用统一导航索引映射
- **WHEN** Task Segment 包含 `startEventId` 或 `endEventId`
- **THEN** Task-to-Trace 映射 SHALL 使用现有统一 Turn lookup 能力解析锚点
- **AND** 映射 SHALL 支持 event id、uuid、message id、block anchor 和 `main:<line>` / subagent file anchor
- **AND** 映射 SHALL NOT 只用 `_eventId` 或 `uuid` 自建索引

#### Scenario: Task 部分无法映射仍显示 Task 节点
- **WHEN** Task Trace 已确认但某个 Task 的起止锚点只能部分映射或无法映射
- **THEN** Trace 树 SHALL 仍显示该 Task 节点
- **AND** Task detail SHALL 显示该 Task 的映射降级状态
- **AND** 页面 SHALL NOT 因该 Task 映射失败而回退为 `会话 -> Turn + Task badge` 展示

#### Scenario: Task 展开折叠
- **WHEN** 用户点击 Task 节点的展开/折叠控件
- **THEN** 页面 SHALL 切换该 Task 下会话节点和 Turn 节点的可见状态
- **AND** 其他 Task 的展开状态 SHALL 保持不变

#### Scenario: 未确认状态才允许 Turn badge 作为预览辅助
- **WHEN** Task Segment 只处于预览状态且尚未确认
- **THEN** 页面 MAY 在 Turn 节点上展示 `Task N` badge 作为辅助跳转
- **AND** 一旦 Task Trace 被确认，Task 所属关系 SHALL 通过 `Task -> 会话 -> Turn` 树层级表达

### Requirement: Task 节点详情
Claude Log Viewer SHALL 在用户选中 Task 节点时展示 Task 基础摘要，帮助用户理解该 Task 覆盖的目标和执行范围。

#### Scenario: 点击 Task 节点
- **WHEN** 用户点击 Trace 树中的 Task 节点主体
- **THEN** 页面 SHALL 将该 Task 标记为当前选中节点
- **AND** 右侧详情区 SHALL 展示 Task 基础摘要

#### Scenario: Task detail 内容
- **WHEN** 右侧详情区展示 Task detail
- **THEN** 页面 SHALL 展示 Task label、title 或 user intent、task type、status、confidence、起止 Turn、覆盖会话列表和 boundary reason
- **AND** 页面 SHALL 提供跳转到该 Task 首个会话或首个 Turn 的入口
- **AND** 页面 SHALL NOT 在本 change 中展示复杂 diagnostics、diff、test result 或 req/resp 明细

#### Scenario: Task 范围无法完整映射
- **WHEN** Task 的起止锚点无法映射到 Conversation/minimal Turn
- **THEN** Task detail SHALL 显示明确的无法定位提示
- **AND** Task 节点 SHALL 仍可被选中
- **AND** 页面 SHALL NOT 抛出脚本错误或静默失败

### Requirement: Trace 节点选择支持 Snapshot Task Conversation Turn
Claude Log Viewer SHALL 使用统一节点选择机制支持 `snapshot`、`task`、`conversation` 和 `turn` 四类节点。

#### Scenario: 选择唯一节点
- **WHEN** 用户点击 Snapshot、Task、会话或 Turn 节点
- **THEN** 页面 SHALL 只将被点击节点标记为当前选中节点
- **AND** 其他节点 SHALL 取消选中状态
- **AND** 右侧详情 SHALL 匹配当前节点类型

#### Scenario: Task 下选择会话
- **WHEN** 用户点击某个 Task 下的会话节点
- **THEN** 页面 SHALL 复用已有会话详情展示该会话内容
- **AND** 页面 SHALL 保持该会话所属 Task 的上下文可见

#### Scenario: Task 下选择 Turn
- **WHEN** 用户点击某个 Task 下的 Turn 节点
- **THEN** 页面 SHALL 复用已有 Turn 极简详情展示 `Agent 响应` 和 `原始 JSON`
- **AND** 页面 SHALL 保持该 Turn 所属 Task 和会话的上下文可见

### Requirement: Task 定位使用注入后的 Trace 树
Claude Log Viewer SHALL 在 Task Trace 确认后，将 Task 相关定位操作导航到注入后的 Task 树节点，而不是只跳到未分组的会话或 Turn。

#### Scenario: 定位开始 Turn
- **WHEN** 用户在 Task detail 点击“定位开始 Turn”
- **THEN** 页面 SHALL 切换到 `Session` 页面
- **AND** 页面 SHALL 展开目标 Task 和目标会话
- **AND** 页面 SHALL 选中、滚动并临时高亮目标 Turn

#### Scenario: 定位结束 Turn
- **WHEN** 用户在 Task detail 点击“定位结束 Turn”
- **THEN** 页面 SHALL 切换到 `Session` 页面
- **AND** 页面 SHALL 展开目标 Task 和目标会话
- **AND** 页面 SHALL 选中、滚动并临时高亮目标 Turn

#### Scenario: 未确认 Task Trace 时定位
- **WHEN** 用户尚未确认 Task Trace 但点击 Task 预览中的定位入口
- **THEN** 页面 SHALL 按现有 `会话 -> Turn` Trace 树定位目标 Turn
- **AND** 页面 SHALL NOT 自动确认 Task Trace

### Requirement: 本 change 不修改切分算法和评测逻辑
本 change SHALL 只负责将已有 Task Segment 结果和 Tools / Skills Snapshot 展示到 Trace 树中，不改变 Task 切分算法和任务评测逻辑。

#### Scenario: 不改变 segment API
- **WHEN** 用户触发 Task 切分
- **THEN** 前端 SHALL 继续使用现有 `/api/task-segments` 返回结果
- **AND** 本 change SHALL NOT 要求后端返回新的切分字段

#### Scenario: 不重新判断任务成功率
- **WHEN** Trace 树渲染 Task 节点
- **THEN** 页面 SHALL 使用已有 Task Segment 中的 status、confidence 或 equivalent 字段
- **AND** 页面 SHALL NOT 在本 change 中新增任务成功率判断规则

#### Scenario: 不实现复杂 Tools Skills 变化检测
- **WHEN** session 中可能存在 Tools 或 Skills 变化
- **THEN** 本 change MAY 保留特殊 Turn 扩展点
- **AND** 本 change SHALL NOT 要求实现完整 Tools / Skills diff 检测和版本历史

### Requirement: Turn View Mode Projection
Claude Log Viewer SHALL provide a frontend data projection layer for Trace view modes without modifying the underlying minimal Turn data.

#### Scenario: Build default projection
- **WHEN** a session has loaded Conversation and minimal Turn data
- **THEN** the viewer SHALL be able to build a `default` view projection
- **AND** the projection SHALL contain only primary Step nodes
- **AND** the projection SHALL preserve group, conversation, task, turn and anchor references for every visible Step

#### Scenario: Build debug projection
- **WHEN** a session has loaded Conversation and minimal Turn data
- **THEN** the viewer SHALL be able to build a `debug` view projection
- **AND** the projection SHALL contain every minimal Turn in original order
- **AND** the projection SHALL preserve group, conversation, task, turn and anchor references for every Turn

#### Scenario: Projection does not mutate minimal Turns
- **WHEN** the viewer builds either `default` or `debug` projection
- **THEN** the underlying minimal Turn objects SHALL NOT be mutated with view-only labels or visibility fields
- **AND** repeated projection builds SHALL produce stable labels and references

### Requirement: Default View Primary Classification
Claude Log Viewer SHALL classify user-visible execution steps as primary in the default view.

#### Scenario: User message is primary
- **WHEN** a minimal Turn kind is `user_message`
- **THEN** default projection SHALL include it as a primary Step
- **AND** its display kind SHALL indicate user request

#### Scenario: Thinking is primary and complete
- **WHEN** a minimal Turn kind is `thinking` or equivalent reasoning content
- **THEN** default projection SHALL include it as a primary Step
- **AND** the Step SHALL preserve the full underlying thinking content
- **AND** the Step SHALL NOT be summarized, weakened, folded into internal events, or hidden by default

#### Scenario: Assistant text is primary
- **WHEN** a minimal Turn kind is `assistant_text`
- **THEN** default projection SHALL include it as a primary Step
- **AND** its display kind SHALL indicate Agent reply

#### Scenario: Tool use and tool result are primary
- **WHEN** a minimal Turn kind is `tool_use` or `tool_result`
- **THEN** default projection SHALL include it as a primary Step
- **AND** tool errors SHALL remain primary

#### Scenario: Execution-affecting permission is primary
- **WHEN** a permission-related Turn represents a request, approval, denial, waiting state, or execution-affecting permission change
- **THEN** default projection SHALL include it as a primary Step

### Requirement: Default View Internal Classification
Claude Log Viewer SHALL hide ordinary internal runtime events from the default projection while keeping them available in debug projection.

#### Scenario: Ordinary system is internal
- **WHEN** a minimal Turn represents ordinary system prompt injection or stable system context
- **THEN** default projection SHALL classify it as internal and omit it from primary Steps
- **AND** debug projection SHALL still include it in original order

#### Scenario: Ordinary context and hook are internal
- **WHEN** a minimal Turn represents ordinary context injection, `PostToolUse` hook, `last-prompt`, or equivalent internal lifecycle event
- **THEN** default projection SHALL classify it as internal and omit it from primary Steps
- **AND** debug projection SHALL still include it in original order

#### Scenario: Ordinary snapshots and queue events are internal
- **WHEN** a minimal Turn represents ordinary `file-history-snapshot`, `queue-operation`, attachment metadata, or ordinary unknown internal event
- **THEN** default projection SHALL classify it as internal and omit it from primary Steps
- **AND** debug projection SHALL still include it in original order

#### Scenario: Error-like internal event is promoted
- **WHEN** an otherwise internal Turn contains clear error, warning, failed, denied, rejected, blocked, or permission-impacting content
- **THEN** default projection SHALL promote it to primary
- **AND** the projection SHALL preserve the full underlying Turn content

### Requirement: View Labels
Claude Log Viewer SHALL use different display labels for default Step projection and debug Turn projection.

#### Scenario: Default labels are continuous Step labels
- **WHEN** default projection is built for a conversation or task range
- **THEN** visible nodes SHALL be labeled `Step 1`, `Step 2`, `Step 3`, and so on within their display scope
- **AND** hidden internal Turns SHALL NOT create gaps in Step numbering

#### Scenario: Debug labels preserve Turn labels
- **WHEN** debug projection is built
- **THEN** visible nodes SHALL preserve the underlying Turn labels such as `Turn 1`, `Turn 2`, `Turn 3`
- **AND** debug projection SHALL NOT renumber after filtering out nothing

### Requirement: Projection Preserves Task and Conversation Boundaries
Claude Log Viewer SHALL preserve existing Task, Conversation and Turn boundaries when building view projections.

#### Scenario: Task range unchanged
- **WHEN** an active Task Trace Overlay or confirmed Task Trace covers a range of underlying Turns
- **THEN** default projection SHALL only hide internal Turns within that range
- **AND** debug projection SHALL include all underlying Turns within that range
- **AND** neither projection SHALL change Task start or end anchors

#### Scenario: Conversation range unchanged
- **WHEN** a Conversation contains both primary and internal Turns
- **THEN** default projection SHALL preserve the Conversation node and include its primary Steps
- **AND** debug projection SHALL preserve the Conversation node and include all Turns

#### Scenario: Empty default projection range
- **WHEN** a Task or Conversation contains no primary Steps in default projection
- **THEN** projection SHALL expose metadata indicating that no default-visible Steps exist
- **AND** debug projection SHALL still expose the underlying Turns

### Requirement: First Change Does Not Modify UI Rendering
This change SHALL only introduce projection data and tests; it SHALL NOT replace Trace tree UI or Detail rendering.

#### Scenario: Existing UI remains on old source
- **WHEN** this change is implemented
- **THEN** existing Trace tree rendering MAY continue to consume the previous data source
- **AND** the new projection SHALL be available for follow-up UI changes

#### Scenario: Detail unchanged
- **WHEN** this change is implemented
- **THEN** right-side Detail behavior SHALL remain unchanged
- **AND** full Detail evidence behavior SHALL be handled by a later change

### Requirement: Session Trace 双视图切换
Claude Log Viewer SHALL 在 Session Trace 中提供 `默认视图` 和 `调试视图` 两种左侧树展示模式。

#### Scenario: 默认进入默认视图
- **WHEN** 用户加载 viewer 并选择一个 session
- **THEN** Session Trace SHALL 默认使用 `默认视图`
- **AND** 左侧树 SHALL 展示主执行链路 Step
- **AND** 页面 SHALL NOT 展示完整内部事件列表作为默认体验

#### Scenario: 用户切换到调试视图
- **WHEN** 用户点击 `调试视图`
- **THEN** Session Trace SHALL 切换到 `debug` 模式
- **AND** 左侧树 SHALL 展示完整 Turn 时间线
- **AND** Turn 的顺序 SHALL 与底层 Minimal Turn 原始顺序一致

#### Scenario: 用户切回默认视图
- **WHEN** 用户从 `调试视图` 点击 `默认视图`
- **THEN** Session Trace SHALL 切回 `default` 模式
- **AND** 左侧树 SHALL 重新展示 primary Step projection
- **AND** 主工作区 SHALL NOT 变成空白

### Requirement: Trace 树消费 View Projection
Session Trace 树 SHALL 使用 `buildTurnViewProjection(mode, source)` 的投影结果渲染 Turn/Step 节点，而不是直接展示完整 Minimal Turn 列表。

#### Scenario: 默认视图渲染 Step projection
- **WHEN** `traceViewMode` 为 `default`
- **THEN** Trace 树 SHALL 使用 default projection
- **AND** 子节点 SHALL 使用 `Step N` label
- **AND** Step 编号 SHALL 连续，不因隐藏 internal Turn 产生断号

#### Scenario: 调试视图渲染 Turn projection
- **WHEN** `traceViewMode` 为 `debug`
- **THEN** Trace 树 SHALL 使用 debug projection
- **AND** 子节点 SHALL 使用底层 `Turn N` label
- **AND** ordinary internal Turn SHALL 仍按原始时序显示在其真实位置

#### Scenario: Task-first 树保持层级
- **WHEN** 当前 session 已确认或已有 Task Trace 数据
- **THEN** projection 渲染 SHALL 保留 `Task -> 会话 -> Step/Turn` 层级
- **AND** 切换视图 SHALL NOT 改变 Task 起止锚点或 Task 归属

#### Scenario: Conversation-first 树保持层级
- **WHEN** 当前 session 没有 Task Trace 数据
- **THEN** projection 渲染 SHALL 保留 `会话 -> Step/Turn` 层级
- **AND** 切换视图 SHALL NOT 改变 Conversation 或 Turn 的底层锚点

### Requirement: 默认视图降噪
默认视图 SHALL 隐藏普通 internal Turn，只保留 primary Step。

#### Scenario: 普通内部事件默认隐藏
- **WHEN** session 包含 ordinary `permission-mode`、`last-prompt`、`PostToolUse`、`file-history-snapshot`、`queue-operation`、system/context 注入或 attachment metadata
- **THEN** 默认视图 SHALL NOT 在左侧树中展示这些 ordinary internal Turn
- **AND** 调试视图 SHALL 仍展示这些 Turn

#### Scenario: thinking 默认可见
- **WHEN** session 包含 thinking 或 reasoning Turn
- **THEN** 默认视图 SHALL 将其作为 primary Step 展示
- **AND** thinking 内容 SHALL NOT 因默认视图被隐藏

#### Scenario: 异常内部事件默认可见
- **WHEN** ordinary internal Turn 包含 error、warning、failed、denied、rejected、blocked 或 permission-impacting 内容
- **THEN** 默认视图 SHALL 将其作为 primary Step 展示
- **AND** 该 Step SHALL 保留 underlying Turn 锚点

### Requirement: 类型筛选降级为调试筛选
底层类型筛选 SHALL 只作为调试视图下的高级筛选展示。

#### Scenario: 默认视图隐藏类型筛选
- **WHEN** `traceViewMode` 为 `default`
- **THEN** `user / assistant / system / attachment / perm / fhs / queue / other` 类型筛选 SHALL 隐藏或弱化为不可见高级控件
- **AND** 默认视图主入口 SHALL 只突出 `默认视图 / 调试视图`

#### Scenario: 调试视图显示类型筛选
- **WHEN** `traceViewMode` 为 `debug`
- **THEN** 类型筛选 SHALL 可见
- **AND** 类型筛选 SHALL 只影响左侧 Trace 树的可见节点
- **AND** 类型筛选 SHALL NOT 修改底层 Turn、Task 或 Conversation 数据

#### Scenario: 筛选为空时显示明确状态
- **WHEN** 调试视图类型筛选或搜索导致某 Conversation 没有可见 Turn
- **THEN** Trace 树 SHALL 显示明确空状态
- **AND** SHALL NOT 直接渲染空白区域

### Requirement: 视图切换选择状态
Session Trace SHALL 在默认视图和调试视图之间切换时保持稳定选择状态，或给出明确回退提示。

#### Scenario: 可见节点保持选中
- **WHEN** 当前选中的 Step/Turn 在目标视图中仍可见
- **THEN** 切换视图后 SHALL 保持该节点选中
- **AND** 右侧 Detail SHALL NOT 被清空

#### Scenario: internal Turn 在默认视图不可见
- **WHEN** 当前选中普通 internal Turn
- **AND** 用户切换到默认视图
- **THEN** Trace 树 SHALL 回退选中最近可见父节点或清晰提示该 Turn 已在默认视图隐藏
- **AND** 页面 SHALL 提供切回调试视图查看完整 Turn 的提示
- **AND** 主工作区 SHALL NOT 变成空白

#### Scenario: 空 projection 范围
- **WHEN** 某 Task 或 Conversation 在默认视图中没有 primary Step
- **THEN** Trace 树 SHALL 保留 Task 或 Conversation 节点
- **AND** 子区域 SHALL 显示“默认视图无主执行 Step，切换调试视图查看完整 Turn”或等价提示

### Requirement: Task-first Trace 闭环
Claude Log Viewer SHALL 在当前 session 有 task segmentation 结果后，将 Session Trace 渲染为 `Task -> 会话 -> Step/Turn` 结构。

#### Scenario: 任务切分后立即进入 Task-first
- **WHEN** 用户对当前 session 成功运行任务切分
- **THEN** Session Trace SHALL 使用该 task segmentation result 作为 active task source
- **AND** 左侧 Trace 树 SHALL 以 Task 作为 Snapshot 后的一级节点
- **AND** SHALL NOT 要求用户额外点击确认后才进入 Task-first

#### Scenario: 确认状态不决定 Task-first 结构
- **WHEN** 当前 session 有 task segmentation result 但尚未确认
- **THEN** Session Trace SHALL 仍展示 `Task -> 会话 -> Step/Turn`
- **AND** Tasks 页面 SHALL 可以继续显示 `预览中`
- **AND** 用户点击确认后 SHALL 只更新确认状态，不改变 Task-first 数据来源

#### Scenario: 未归类会话可见
- **WHEN** 当前 session 有 task segmentation result
- **AND** 某些 Conversation 或 Turn 不属于任何 Task range
- **THEN** Session Trace SHALL 在 Task-first 结构后展示 `Unassigned`
- **AND** Unassigned 下的会话 SHALL 继续支持默认视图 Step 和调试视图 Turn

#### Scenario: 重新切分刷新 active task source
- **WHEN** 用户重新切分当前 session
- **THEN** 新结果 SHALL 替换 active task source
- **AND** Session Trace SHALL 立即刷新为新的 Task-first 结构
- **AND** 旧确认状态 SHALL 被清除或降级为未确认

### Requirement: Turn Detail 完整证据
Claude Log Viewer SHALL 在右侧 Detail 中展示当前选中 Minimal Turn 的完整证据，视图模式不得裁剪 Detail 内容。

#### Scenario: 默认视图 Step 展示完整 underlying Turn
- **WHEN** 用户在默认视图点击一个 `Step`
- **THEN** 右侧 Detail SHALL 使用该 Step 的 `underlyingTurnKey` 定位底层 Minimal Turn
- **AND** Detail SHALL 展示该 Minimal Turn 的完整主证据
- **AND** Detail SHALL 提供可展开的原始 JSON

#### Scenario: 调试视图 Turn 展示完整内容
- **WHEN** 用户在调试视图点击一个 `Turn`
- **THEN** 右侧 Detail SHALL 展示该 Turn 的完整内容
- **AND** SHALL 包含 entry/block 定位信息
- **AND** SHALL 提供可展开的原始 JSON

#### Scenario: 视图切换不清空已选证据
- **WHEN** 用户已选中一个在目标视图仍可见的 Step 或 Turn
- **AND** 用户切换默认视图和调试视图
- **THEN** 右侧 Detail SHALL 保持当前底层 Turn 的证据内容
- **AND** SHALL NOT 变成空白或只显示摘要

### Requirement: 调试筛选不裁剪 Detail
调试视图中的类型筛选 SHALL 只影响左侧 Trace 树可见节点，不得裁剪右侧 Detail 的证据内容。

#### Scenario: 已选 Turn 被筛选隐藏后 Detail 保持完整
- **WHEN** 用户在调试视图选中一个 Turn
- **AND** 用户修改类型筛选使该 Turn 不再出现在左侧树
- **THEN** 右侧 Detail SHALL 继续展示该 Turn 的完整证据
- **AND** SHALL NOT 显示"当前筛选隐藏了该 Turn 的全部事件"作为替代内容

#### Scenario: 默认视图不受类型筛选影响
- **WHEN** 用户在调试视图调整类型筛选
- **AND** 用户切回默认视图并点击任意 Step
- **THEN** 右侧 Detail SHALL 展示该 Step underlying Turn 的完整证据
- **AND** SHALL NOT 根据调试筛选裁剪内容

### Requirement: Tool Turn 证据完整
Claude Log Viewer SHALL 对 tool_use 和 tool_result Turn 展示完整工具证据。

#### Scenario: tool_use 展示完整 input
- **WHEN** 当前选中 Turn 的 kind 为 `tool_use`
- **THEN** Detail SHALL 展示工具名称
- **AND** SHALL 展示完整 tool id 或 tool_use_id
- **AND** SHALL 展示完整 input JSON
- **AND** SHALL 提供该 content block 和 entry 的原始 JSON

#### Scenario: tool_result 展示完整 result
- **WHEN** 当前选中 Turn 的 kind 为 `tool_result`
- **THEN** Detail SHALL 展示完整 result content
- **AND** SHALL 展示 `tool_use_id`
- **AND** SHALL 展示 `is_error` 或等价错误状态
- **AND** SHALL 提供该 content block 和 entry 的原始 JSON

#### Scenario: 长工具结果不被摘要截断
- **WHEN** tool_result content 长度超过左侧 summary 截断阈值
- **THEN** Detail SHALL 保留完整 content
- **AND** SHALL 使用滚动或折叠展示控制布局

### Requirement: Internal Turn 证据完整
Claude Log Viewer SHALL 对 internal Turn 展示可调试的完整证据。

#### Scenario: permission-mode 展示完整状态
- **WHEN** 当前选中 Turn 表示 `permission-mode` 或权限相关 internal event
- **THEN** Detail SHALL 展示权限状态、相关文本或 payload
- **AND** SHALL 提供 entry metadata 和原始 JSON

#### Scenario: snapshot 和 queue 展示结构化内容
- **WHEN** 当前选中 Turn 表示 `file-history-snapshot` 或 `queue-operation`
- **THEN** Detail SHALL 展示可读的结构化字段
- **AND** SHALL 提供完整原始 JSON

#### Scenario: system context unknown 有 raw fallback
- **WHEN** 当前选中 Turn 的 kind 为 `system`、`context` 或 `unknown`
- **THEN** Detail SHALL 展示可提取文本或 structured payload
- **AND** 如果无法识别主证据，SHALL 至少展示完整原始 JSON

### Requirement: Detail 定位信息
右侧 Detail SHALL 展示足够的定位信息，帮助用户从 Step/Turn 追溯到底层日志。

#### Scenario: 显示基础锚点
- **WHEN** Detail 展示任意 Minimal Turn
- **THEN** Detail SHALL 显示 turn label、kind、conversation key 或 group id
- **AND** 如果存在 SHALL 显示 file line、entry index、event id、block anchor

#### Scenario: Raw JSON 包含 entry 和 content block
- **WHEN** Detail 展示任意 Minimal Turn
- **THEN** 原始 JSON 区域 SHALL 包含对应 entry 的核心字段
- **AND** 如果 Turn 来自 content block，SHALL 包含该 block 的完整 JSON

### Requirement: Task Trace Overlay 状态
Claude Log Viewer SHALL 使用 Task Trace Overlay 表示当前 session 的可编辑任务划分，并保持 Raw Trace、Conversation 和 Turn 数据不可变。Task 的可编辑边界 SHALL 以 Conversation 为最小单位。

#### Scenario: 自动切分确认生成 overlay
- **WHEN** 用户确认自动 Task 切分结果
- **THEN** 页面 SHALL 为当前 session 创建 active Task Trace Overlay
- **AND** overlay source SHALL 为 `auto`
- **AND** Trace 树 SHALL 使用该 overlay 渲染 `Task -> 会话 -> Turn`

#### Scenario: 编辑后 overlay 标记为 edited
- **WHEN** 用户对 active overlay 执行任意人工编辑操作
- **THEN** overlay source SHALL 变为 `edited`
- **AND** overlay SHALL 标记为存在未保存修改
- **AND** Raw Trace、Conversation 和 Turn 派生数据 SHALL NOT 被修改

#### Scenario: 无 overlay 时保持普通 Trace
- **WHEN** 当前 session 没有 active Task Trace Overlay
- **THEN** Session Trace 树 SHALL 继续展示 `Tools / Skills Snapshot -> 会话 -> Turn`
- **AND** 用户 SHALL 仍可进入手动创建 Task 流程

### Requirement: Task Trace 编辑模式
Claude Log Viewer SHALL 提供 Task Trace 编辑模式，让用户对自动切分结果做人工校正。

#### Scenario: 进入编辑模式
- **WHEN** 当前 session 存在 active Task Trace Overlay 且用户点击"编辑 Task Trace"
- **THEN** 页面 SHALL 进入编辑模式
- **AND** 页面 SHALL 显示保存编辑、撤销编辑和退出编辑模式入口
- **AND** Trace 树 SHALL 继续显示当前 overlay 的 Task-first 结构

#### Scenario: 退出编辑模式
- **WHEN** 用户退出编辑模式且没有未保存修改
- **THEN** 页面 SHALL 回到浏览模式
- **AND** active overlay SHALL 保持不变

#### Scenario: 未保存修改提示
- **WHEN** 用户存在未保存 overlay 修改并尝试切换 session、重新切分或退出编辑模式
- **THEN** 页面 SHALL 显示未保存修改提示或执行明确的撤销操作
- **AND** 页面 SHALL NOT 静默丢弃编辑结果

### Requirement: 调整 Task 边界
Claude Log Viewer SHALL 允许用户通过按钮操作调整 Task 的起始会话和结束会话。

#### Scenario: 设为 Task 起始会话
- **WHEN** 用户在编辑模式下选中某个 Task 内或相邻范围内的会话并点击"设为 Task 起始会话"
- **THEN** 当前 Task 的 startConversationKey SHALL 更新为该会话
- **AND** Trace 树 SHALL 按新的 Task 范围刷新
- **AND** overlay SHALL 标记为未保存

#### Scenario: 设为 Task 结束会话
- **WHEN** 用户在编辑模式下选中某个 Task 内或相邻范围内的会话并点击"设为 Task 结束会话"
- **THEN** 当前 Task 的 endConversationKey SHALL 更新为该会话
- **AND** Trace 树 SHALL 按新的 Task 范围刷新
- **AND** overlay SHALL 标记为未保存

#### Scenario: 非法边界
- **WHEN** 用户选择的起点晚于终点或会导致 Task 范围无效
- **THEN** 页面 SHALL 阻止该操作并显示明确提示
- **AND** overlay SHALL 保持原状态

### Requirement: 移动会话到相邻 Task
Claude Log Viewer SHALL 允许用户将边界附近的完整会话移动到上一个或下一个 Task，用于快速修正相邻 Task 边界。

#### Scenario: 移到上一个 Task
- **WHEN** 用户在编辑模式下选中某个 Task 的首部会话并点击"移到上一个 Task"
- **THEN** 页面 SHALL 调整当前 Task 和上一个 Task 的边界
- **AND** 被选中会话及其全部 Turn SHALL 属于上一个 Task
- **AND** overlay SHALL 标记为未保存

#### Scenario: 移到下一个 Task
- **WHEN** 用户在编辑模式下选中某个 Task 的尾部会话并点击"移到下一个 Task"
- **THEN** 页面 SHALL 调整当前 Task 和下一个 Task 的边界
- **AND** 被选中会话及其全部 Turn SHALL 属于下一个 Task
- **AND** overlay SHALL 标记为未保存

#### Scenario: 无相邻 Task
- **WHEN** 用户选中的会话不存在可移动到的上一个或下一个 Task
- **THEN** 对应操作 SHALL disabled 或展示明确不可用提示

### Requirement: 拆分、合并和删除 Task
Claude Log Viewer SHALL 支持基础 Task 结构编辑，包括拆分、合并和删除。

#### Scenario: 从当前会话拆分 Task
- **WHEN** 用户在编辑模式下选中某个 Task 内的会话并点击"从当前会话拆分 Task"
- **THEN** 页面 SHALL 将原 Task 拆为两个连续 Task
- **AND** 新 Task SHALL 从选中会话开始
- **AND** 两个 Task SHALL 保持非重叠连续范围
- **AND** overlay SHALL 标记为未保存

#### Scenario: 合并下一个 Task
- **WHEN** 用户在编辑模式下选中 Task 并点击"合并下一个 Task"
- **THEN** 页面 SHALL 将当前 Task 与下一个 Task 合并为一个 Task
- **AND** 合并后 Task SHALL 覆盖两个原 Task 的连续范围
- **AND** overlay SHALL 标记为未保存

#### Scenario: 删除 Task
- **WHEN** 用户在编辑模式下选中 Task 并点击"删除 Task"
- **THEN** 页面 SHALL 从 overlay 中移除该 Task
- **AND** 被删除 Task 覆盖的会话 SHALL 进入 unassigned 状态或被相邻 Task 接管
- **AND** 页面 SHALL 明确展示处理结果
- **AND** overlay SHALL 标记为未保存

### Requirement: 编辑 Task 元数据
Claude Log Viewer SHALL 允许用户修改 Task 的基础人工标注信息。

#### Scenario: 修改标题
- **WHEN** 用户在编辑模式下修改 Task 标题并保存
- **THEN** overlay 中该 Task 的 title SHALL 更新
- **AND** Trace 树 Task 节点 SHALL 显示新标题

#### Scenario: 修改类型
- **WHEN** 用户在编辑模式下修改 Task 类型并保存
- **THEN** overlay 中该 Task 的 taskType SHALL 更新
- **AND** Trace 树 Task 节点 SHALL 显示新类型

### Requirement: 手动创建 Task
Claude Log Viewer SHALL 允许用户不依赖自动切分，直接从 Trace 树中选择会话范围创建 Task。

#### Scenario: 进入手动创建模式
- **WHEN** 用户点击"手动创建 Task"
- **THEN** 页面 SHALL 进入手动创建模式
- **AND** 页面 SHALL 引导用户选择起始会话和结束会话

#### Scenario: 创建手动 Task
- **WHEN** 用户选择有效起始会话、结束会话、标题和类型并点击"创建"
- **THEN** 页面 SHALL 创建或更新 active Task Trace Overlay
- **AND** 新 Task SHALL 覆盖选定的连续会话范围
- **AND** overlay source SHALL 为 `manual` 或 `edited`
- **AND** Trace 树 SHALL 刷新为 Task-first 结构

#### Scenario: 手动范围无效
- **WHEN** 用户选择的会话范围为空、顺序错误或跨越当前版本不支持的范围
- **THEN** 页面 SHALL 阻止创建并显示明确提示

### Requirement: 会话不可被拆分
Claude Log Viewer SHALL 保证一个会话内部的所有 Step/Turn 始终整体归属同一个 Task 或 unassigned 区域。

#### Scenario: 选中 Turn 时回退到会话
- **WHEN** 用户在编辑模式下选中某个 Turn 并执行 Task 边界操作
- **THEN** 页面 SHALL 使用该 Turn 所属会话作为操作对象
- **AND** 页面 SHALL NOT 只移动或拆分该 Turn

#### Scenario: 渲染 Task-first 树
- **WHEN** Trace 树使用 active overlay 渲染 Task-first 结构
- **THEN** 每个 Task SHALL 包含完整会话节点
- **AND** 会话节点下 SHALL 保留全部原始 Turn/Step 明细

### Requirement: 保存、撤销和导出 Overlay
Claude Log Viewer SHALL 提供基础 overlay 生命周期操作，用于后续数据集构建。

#### Scenario: 保存编辑
- **WHEN** 用户点击"保存编辑"
- **THEN** 当前 overlay SHALL 标记为 saved
- **AND** revision SHALL 增加或 updatedAt SHALL 更新
- **AND** Trace 树 SHALL 继续使用保存后的 overlay

#### Scenario: 撤销编辑
- **WHEN** 用户点击"撤销编辑"
- **THEN** 页面 SHALL 恢复到最近一次 saved overlay
- **AND** 未保存修改 SHALL 被丢弃
- **AND** Trace 树 SHALL 重新渲染

#### Scenario: 导出 overlay JSON
- **WHEN** 用户点击"导出 Task Trace Overlay"
- **THEN** 页面 SHALL 导出包含 sessionId、overlayId、source、revision、tasks、start/end Conversation、start/end Turn 和 start/end event anchor 的 JSON
- **AND** 导出内容 SHALL NOT 包含完整 Raw Trace JSON

### Requirement: 第一版不实现拖拽和后端持久化
本 change SHALL 使用按钮和选择模式实现 Task Trace Overlay 编辑，不要求拖拽交互或后端数据库持久化。

#### Scenario: 不要求拖拽
- **WHEN** 用户进入编辑模式
- **THEN** 页面 SHALL 提供按钮或菜单操作
- **AND** 本 change SHALL NOT 要求通过拖拽移动 Task、会话或 Turn

#### Scenario: 不要求后端持久化
- **WHEN** 用户保存 overlay
- **THEN** 第一版 MAY 只保存为前端内存态
- **AND** 页面 SHALL 提供导出 JSON 作为持久化替代
- **AND** 本 change SHALL NOT 要求新增后端数据库 API

### Requirement: Tasks 页面提供手动切分入口
Session Viewer SHALL 在 Tasks 页面提供"手动切分"入口，并与现有"自动切分"入口并列展示。

#### Scenario: 显示两个切分入口
- **WHEN** 用户打开 Tasks 页面并已选择 session
- **THEN** 页面 SHALL 显示"自动切分"和"手动切分"两个入口
- **AND** "自动切分" SHALL 沿用现有自动切分流程
- **AND** "手动切分" SHALL 不调用自动切分 API

#### Scenario: 从 Tasks 页面进入手动切分
- **WHEN** 用户点击"手动切分"
- **THEN** 页面 SHALL 自动跳转到 Session 页面
- **AND** Session 页面 SHALL 进入手动切分模式
- **AND** Trace 树 SHALL 优先展示原始会话结构，便于用户对照内容切分

### Requirement: Session 页面支持手动切分模式
Session Viewer SHALL 允许用户在原始 Session 会话树上选择连续会话范围并创建 Task。

#### Scenario: 选择起始和结束会话
- **WHEN** 用户处于手动切分模式
- **AND** 用户点击第一个会话
- **THEN** 页面 SHALL 将该会话标记为起始会话
- **WHEN** 用户点击第二个会话
- **THEN** 页面 SHALL 将该会话标记为结束会话
- **AND** 页面 SHALL 高亮当前候选会话范围

#### Scenario: 创建手动 Task
- **WHEN** 用户已选择有效起始会话和结束会话
- **AND** 用户点击"创建 Task"
- **THEN** 页面 SHALL 在当前 Task Trace Overlay 中追加一个 Task
- **AND** Task SHALL 使用 `startConversationKey` 和 `endConversationKey` 作为主边界
- **AND** Task 标题 SHALL 默认生成为 `任务 N`
- **AND** Task 类型 SHALL 默认为 `manual` 或 `unknown`
- **AND** 该 Task 覆盖的会话范围 SHALL 在手动切分模式中持续高亮
- **AND** 高亮区域 SHALL 标记对应 Task 编号

#### Scenario: 连续创建多个 Task
- **WHEN** 用户创建一个 Task 后仍处于手动切分模式
- **THEN** 页面 SHALL 清空当前起止选择
- **AND** 用户 SHALL 可以继续选择下一段会话创建下一个 Task
- **AND** 已创建 Task 的持续高亮 SHALL 保留

#### Scenario: 撤销上一次 Task 切分
- **WHEN** 用户已在手动切分模式中创建至少一个 Task
- **AND** 用户点击"撤销上一次"
- **THEN** 页面 SHALL 删除最近一次创建的 Task
- **AND** 页面 SHALL 移除该 Task 对应的持续高亮
- **AND** 该范围内的会话 SHALL 恢复为未分配状态
- **AND** 页面 SHALL 继续停留在手动切分模式

#### Scenario: 确认执行手动切分
- **WHEN** 用户点击"确认执行这次 Task 划分"
- **THEN** 页面 SHALL 退出手动切分模式
- **AND** Session Trace SHALL 使用 active Task Trace Overlay 渲染为 `Task -> 会话 -> Turn/Step`
- **AND** 未分配会话 SHALL 显示在 Unassigned 区域
- **AND** 手动切分模式中的临时候选高亮和持续标注高亮 SHALL 被清除

### Requirement: 手动切分边界安全
Session Viewer SHALL 保证手动切分不会产生重叠 Task，也不会拆分单个会话内部的 Turn/Step。

#### Scenario: 阻止重叠范围
- **WHEN** 用户选择的会话范围与已有 Task 范围重叠
- **THEN** 页面 SHALL 阻止创建 Task
- **AND** 页面 SHALL 显示明确提示
- **AND** 已有 Task 的持续高亮 SHALL 保持不变

#### Scenario: 会话不可拆分
- **WHEN** 用户创建手动 Task
- **THEN** 该 Task SHALL 覆盖完整会话
- **AND** 会话内部所有 Turn/Step SHALL 整体归属同一个 Task

#### Scenario: 无 session 时不可进入
- **WHEN** 当前没有选中的 session
- **THEN** "手动切分"入口 SHALL disabled 或显示明确不可用提示

### Requirement: 最小自动化测试
本 change SHALL 只要求最小必要自动化测试，复杂体验由真实 session 手动验收。

#### Scenario: 静态和 DOM 冒烟测试
- **WHEN** 执行测试
- **THEN** 测试 SHOULD 覆盖手动切分入口存在
- **AND** SHOULD 覆盖点击入口后进入 Session 手动切分模式
- **AND** SHOULD 覆盖选择两个会话后能创建一个 manual Task Overlay
- **AND** SHOULD 覆盖撤销上一次会移除最近创建的 Task

#### Scenario: 手动验收
- **WHEN** 实现完成
- **THEN** 用户 SHALL 使用真实 session 验收连续创建多个 Task、持续高亮、撤销上一次、确认执行、Task-first 展示和未分配会话展示

### Requirement: Viewer 显示 session 名称
Viewer SHALL 在项目/session 选择器和已加载 session 的主标题区域显示可读 session 名称，且默认可见 UI 不展示 session id。

#### Scenario: session 列表使用 displayName
- **WHEN** 前端调用 `GET /api/projects`
- **AND** 返回的 session entry 包含非空 `displayName`
- **THEN** session 选择器 SHALL 以 `displayName` 作为唯一主要标签
- **AND** 该选项 SHALL NOT 在默认可见文本中拼接 short session id 或 raw session id
- **AND** 该选项 SHALL NOT 显示形如 `[019ec10a]` 的 bracket short id

#### Scenario: 无名称时回退显示
- **WHEN** session entry 的 `title` 为空或缺失
- **THEN** Viewer SHALL 使用 adapter 返回的非 id `displayName`、现有可读摘要或 `Untitled session` 等非 id 文案展示该 session
- **AND** Viewer SHALL NOT use raw session id or short session id as the default visible fallback
- **AND** Viewer SHALL keep session id available in tooltip、详情、复制字段或辅助识别信息 for debugging and precise identification
- **AND** Viewer SHALL NOT 显示空白选项

#### Scenario: 已加载 session 显示名称
- **WHEN** 用户成功加载一个 session
- **THEN** Viewer SHALL 在当前 session 标题区域显示该 session 的 `displayName`
- **AND** Viewer SHALL NOT 在默认可见标题区域显示 raw session id
- **AND** Viewer SHALL 在标题区域显示时间范围等非 id 辅助信息（当可用时）

#### Scenario: 长名称紧凑展示
- **WHEN** session 名称超过选择器或标题区域可用宽度
- **THEN** Viewer SHALL 在紧凑区域截断显示
- **AND** Viewer SHALL 保留完整名称用于详情、悬停标题或编辑输入

#### Scenario: 同名 session 仍可区分
- **WHEN** 同一项目或跨项目中存在多个 `displayName` 相同或相近的 session
- **THEN** Viewer SHALL 在 selector option 或 session 标题区同时展示非 id 区分信息（如时间范围、agent、项目路径摘要）
- **AND** Viewer SHALL NOT 使用 raw session id 或 short session id 作为可见区分信息
- **AND** Viewer SHALL NOT 仅凭 `displayName` 让用户无法区分不同 session
- **AND** 用户定位/加载 session 时 Viewer SHALL 使用 session id 而非 `displayName`

### Requirement: Backend API rename session
Viewer server SHALL 提供 `POST /api/session/<sessionId>/rename`，用于修改当前 agent 的 session title，并只在 native 写回成功后返回成功。

#### Scenario: rename 成功
- **WHEN** 前端调用 `POST /api/session/<sessionId>/rename`
- **AND** 请求 JSON 包含非空 `title`
- **AND** 当前 agent adapter 支持 rename
- **AND** native title 写回成功
- **THEN** 后端 SHALL 返回 HTTP 200
- **AND** 响应 SHALL 包含 `ok: true`
- **AND** 响应 SHALL 包含 `agent`
- **AND** 响应 SHALL 包含 `sessionId`
- **AND** 响应 SHALL 包含更新后的 `title`
- **AND** 响应 SHALL 包含更新后的 `displayName`
- **AND** 响应 SHALL 包含 `canRenameSession: true`

#### Scenario: title 为空时拒绝
- **WHEN** rename 请求缺少 `title`
- **OR** `title` trim 后为空字符串
- **THEN** 后端 SHALL 返回 HTTP 400
- **AND** 响应 SHALL 包含 `ok: false`
- **AND** 响应 SHALL 包含 `code: "invalid_title"`
- **AND** 后端 SHALL NOT 调用 adapter native 写回

#### Scenario: session 不存在时拒绝
- **WHEN** rename 请求中的 `sessionId` 在当前 agent 数据源中不存在
- **THEN** 后端 SHALL 返回 HTTP 404
- **AND** 响应 SHALL 包含 `ok: false`
- **AND** 响应 SHALL 包含 `code: "session_not_found"`

#### Scenario: agent 不支持 rename
- **WHEN** 当前 agent adapter 返回 `canRenameSession: false`
- **OR** adapter 报告 rename unsupported
- **THEN** 后端 SHALL 返回 HTTP 501
- **AND** 响应 SHALL 包含 `ok: false`
- **AND** 响应 SHALL 包含 `code: "rename_not_supported"`
- **AND** 后端 SHALL NOT 写入任何本地-only title 缓存伪造成功

#### Scenario: native title 不可用
- **WHEN** adapter 无法定位 native title 存储
- **OR** native schema 缺少 title 写回所需表或字段
- **THEN** 后端 SHALL 返回 HTTP 500
- **AND** 响应 SHALL 包含 `ok: false`
- **AND** 响应 SHALL 包含 `code: "native_title_unavailable"`
- **AND** Viewer SHALL 保留旧名称

#### Scenario: native title 写入失败
- **WHEN** adapter 写入 native title 时遇到只读 DB、DB lock、事务失败或其他 SQLite 写入错误
- **THEN** 后端 SHALL 返回 HTTP 500
- **AND** 响应 SHALL 包含 `ok: false`
- **AND** 响应 SHALL 包含 `code: "native_title_write_failed"`
- **AND** Viewer SHALL 保留旧名称

### Requirement: Frontend rename interaction
Viewer SHALL 为可 rename 的当前 session 提供名称编辑交互，并根据后端结果更新或保留界面状态。

#### Scenario: 可 rename session 显示编辑入口
- **WHEN** 当前已加载 session 的 metadata 包含 `canRenameSession: true`
- **THEN** Viewer SHALL 显示 session 名称编辑入口
- **AND** 编辑入口 SHALL 使用当前 `title` 或 `displayName` 初始化

#### Scenario: 不可 rename session 禁用编辑
- **WHEN** 当前已加载 session 的 metadata 包含 `canRenameSession: false`
- **THEN** Viewer SHALL 禁用或隐藏 session 名称编辑入口
- **AND** Viewer SHALL 展示该 agent 暂不支持 native rename 的明确状态

#### Scenario: 取消编辑不发请求
- **WHEN** 用户进入 session 名称编辑状态后取消
- **THEN** Viewer SHALL 退出编辑状态
- **AND** Viewer SHALL 保留原名称
- **AND** Viewer SHALL NOT 调用 rename API

#### Scenario: 保存中状态
- **WHEN** 用户提交新的 session 名称
- **THEN** Viewer SHALL 调用 `POST /api/session/<sessionId>/rename`
- **AND** 保存期间 SHALL 防止重复提交同一 rename 请求
- **AND** 保存期间 SHALL 显示明确的保存中状态

#### Scenario: 保存成功后刷新当前 UI
- **WHEN** rename API 返回成功响应
- **THEN** Viewer SHALL 使用响应中的 `title` 和 `displayName` 更新当前 session 标题区域
- **AND** Viewer SHALL 更新 session selector 当前 option
- **AND** Viewer SHALL 更新内存中的项目/session 列表数据
- **AND** Viewer SHALL 退出编辑状态并显示成功反馈

#### Scenario: 保存失败时保留旧名称
- **WHEN** rename API 返回非 2xx 响应或网络错误
- **THEN** Viewer SHALL 显示可读错误
- **AND** Viewer SHALL 保留提交前的 session 名称
- **AND** Viewer SHALL 允许用户修正名称后重试

### Requirement: Windows viewer 启动
session viewer SHALL 在 Windows 原生环境下启动并打开本地浏览器。

#### Scenario: 启动 Codex viewer
- **WHEN** Windows 用户运行 `ccwhat web --agent codex`
- **THEN** viewer SHALL 绑定可用本地端口
- **AND** `/api/projects` SHALL 返回 Windows Codex session 项目

#### Scenario: viewer 端口不可绑定
- **WHEN** viewer 端口位于 Windows excluded port range 或被系统拒绝绑定
- **THEN** 系统 SHALL 输出 `--web-port` 换端口建议
- **AND** 不得只显示“Viewer may already be running”

### Requirement: Windows viewer API 错误
session viewer SHALL 对 Windows 平台错误返回 JSON 错误，而不是中断 HTTP 连接。

#### Scenario: task segmentation 后端异常
- **WHEN** `/api/task-segments` 在 Windows 下遇到资源读取或编码异常
- **THEN** API SHALL 返回包含 `ok: false` 和 `error` 的 JSON 响应
- **AND** 前端 SHALL 显示可读错误而不是静默失败

### Requirement: Windows Codex session 路径
session viewer SHALL 正确读取 Windows Codex session 和 metadata。

#### Scenario: Codex session 位于用户目录
- **WHEN** Codex session 存在于 `%USERPROFILE%\.codex\sessions`
- **THEN** Codex adapter SHALL 在 viewer 中列出这些 session
- **AND** session title、timestamp、cwd 和 events SHALL 正常展示

