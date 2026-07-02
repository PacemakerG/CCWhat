## Context

`deep-ai-analysis-copy/viewer/claude-log.html` 是一个 537KB 的单文件前端，左侧导航有 Session / Tasks / Overview / Timeline / Req-Resp / Diff / Diagnostics / Export / Settings 等页面。其中 Timeline 页（`data-page="timeline"`）当前由 `renderTimelinePage()`（约 line 3420）渲染，逻辑是把 `allEntries` 前 200 条扁平铺成一个列表，每条显示类型徽章 + 时间戳 + 摘要。这个视图缺少层级结构和并发时间轴，无法满足"理解工具调用链路、定位耗时瓶颈"的需求。

`deep-ai-analysis-session-report-clean/viewer/session-gantt.html`（63KB）是一个独立的甘特图页面，已经在另一个项目里实现了完整的执行树（需求 → 任务 → 步骤 → 轮次 → 工具）+ 右侧 62% 宽度甘特时间轴 + 详情面板 + 点击联动逻辑。它通过 `?sessionId=<id>` URL 参数加载数据，依赖两个后端 API：
- `GET /api/session-gantt/<sessionId>` — 返回扁平化树节点数组（含 depth、timing、tags）
- `GET /api/session-entry/<sessionId>/<nodeId>` — 返回某个节点的详情（assistant / tool_use / tool_result / user_input / compact）

这两个 API 在 session-report-clean 的 `server.py` 中实现，**重度依赖 `claude_code_log` 库**（`load_transcript`、`_integrate_agent_entries`、`deduplicate_messages`、`JsonRenderer`、typed models）。而 `deep-ai-analysis-copy` 当前**没有** `claude_code_log` 依赖，它用自己的 `ClaudeAdapter.load_session()` 解析 JSONL，返回 `{main: [...raw entries], subagents, events, turns}` 结构。

copy 的 `viewer/server.py` 是 FastAPI 应用（基于 `ccwhat` 包），现有静态路由 `/claude-log.html`、`/req-resp.html`、`/index.html` 通过 `FileResponse` 提供。

## Goals / Non-Goals

**Goals:**
- 在 `claude-log.html` 的 Timeline 页嵌入完整的甘特视图（执行树 + 时间轴 + 详情面板），替换现有扁平列表。
- 父页面 session 切换时，iframe 自动加载对应 session 的甘特数据。
- 后端提供 gantt HTML 所需的两个 API，数据契约与 session-report-clean 一致（保证 gantt HTML 无需改 JS 逻辑即可工作）。
- gantt HTML 作为静态文件由 copy 自己的 server 提供。

**Non-Goals:**
- 不统一 iframe 内外主题（gantt 自带深色主题，保持不变）。
- 不重构 gantt HTML 的内部 JS/CSS 逻辑（除一处 `?embedded=1` 顶栏隐藏的小改动，见 Decisions）。
- 不在 gantt 视图内新增任务切分、导出、诊断等分析能力（这些仍在 copy 原有页面）。
- 不处理 gantt HTML 的 CDN 依赖（highlight.js / marked）离线场景。

## Decisions

### Decision 1: 用 iframe 嵌入，不内联整合

**选择**：Timeline 页用 `<iframe src="session-gantt.html?sessionId=<sid>">` 嵌入 gantt 页面。

**理由**：
- gantt HTML 自带完整的 topbar、session 选择器、树面板、时间轴、详情面板、CSS 主题、JS 状态机，是一个自洽的单页应用。
- 内联整合需要解决：两套 CSS 变量冲突（copy 用 `--bg-surface` 等 token，gantt 用硬编码 `#0f1117` 等）、两套 JS 命名空间（copy 有 `allEntries`/`loadSession` 等全局函数，gantt 也有自己的全局）、两个 session 选择器如何合并、537KB + 63KB 合并后的可维护性。
- iframe 隔离让 gantt 内部逻辑零改动，父页面只管传 `sessionId` 参数。gantt HTML 已原生支持 `?sessionId=` URL 参数（line 343）。

**备选方案**：内联整合进 `claude-log.html`。集成度高但重构量大、风险高，违背"外科手术式修改"。

### Decision 2: 后端引入 `claude_code_log` 依赖，直接移植 API 实现

**选择**：在 `pyproject.toml` 添加 `claude-code-log>=1.4.0` 依赖，把 session-report-clean 的 `get_session_gantt()`、`get_session_entry_detail()`、`_flatten_gantt_nodes()`、`_find_session_jsonl()` 函数原样移植到 copy 的 `viewer/server.py`，并新增两个 FastAPI 路由。

**理由**：
- gantt HTML 的数据契约与 `claude_code_log.json.renderer.JsonRenderer` 的输出深度耦合：节点类型（`user`/`assistant`/`tool_use`/`tool_result`/`system`/`subagent`）、`index`/`pair_last` 配对字段、`content.tool_name`、`content.compact_trigger` 等都来自 JsonRenderer。
- 从 copy 的原始 JSONL entries 重新实现这套树构建 + 去重 + subagent 整合逻辑，估计 300+ 行代码，且容易与 JsonRenderer 行为漂移，导致 gantt HTML 渲染异常。
- `claude_code_log` 已在 session-report-clean 稳定使用，是解析 Claude Code JSONL 的权威库。copy 本身就是分析 Claude 会话的工具，使用这个库是自然的，不是过度设计。
- 该库已发布在 PyPI（`claude-code-log>=1.4.0`），本地 `/Users/elon-ge/workspace/claude-code-log` 也有源码，安装无障碍。

**备选方案**：基于 copy 现有 `ClaudeAdapter.load_session()` 返回的 raw entries 重新实现树构建。代码量大、与 gantt HTML 契约对齐风险高。

### Decision 3: 父页面 session 切换时同步 iframe src

**选择**：在 `claude-log.html` 的 `loadSession()` 流程末尾（或 `navigateToPage('timeline')` 时）调用新函数 `updateTimelineIframe(sid)`：
- 若 `sid` 为空：iframe 隐藏，显示占位文案"选择一个 session 加载后查看时间线"。
- 若 `sid` 与 iframe 当前 `data-sid` 相同：跳过（避免重复加载）。
- 否则：设置 `iframe.src = "session-gantt.html?sessionId=" + sid + "&embedded=1"`，记录 `data-sid`。

**理由**：gantt HTML 已支持 `?sessionId=`，iframe 只需改 src 即可触发其内部 fetch + 渲染。`embedded=1` 见 Decision 4。

**备选方案**：用 `postMessage` 把 sid 传给 iframe，iframe 内部调 API 切换。复杂且无收益——iframe 重新加载 src 足够简单可靠。

### Decision 4: gantt HTML 增加 `?embedded=1` 隐藏顶栏

**选择**：在复制的 `session-gantt.html` 中增加一处小改动：当 URL 含 `embedded=1` 时，通过 CSS 隐藏 `.topbar` 元素（gantt 自带的 session 选择器 + 跳转链接栏）。

**理由**：
- gantt 的 `.topbar` 含 session 选择器和"返回 claude-log"等跳转链接。嵌入 iframe 后，session 选择器与父页面重复；跳转链接在 iframe 内导航会形成嵌套 viewer，体验混乱。
- 隐藏顶栏后，iframe 只显示"树面板 + 时间轴 + 详情面板"核心三块，正好是 Timeline 页需要的内容。
- 改动量极小：一段 URL 参数解析 + 一行 CSS `display:none`，不动任何核心逻辑。

**备选方案**：保留顶栏。session 选择器重复，且 iframe 内跳转链接行为怪异，体验差。

### Decision 5: Timeline 页布局——iframe 占满 page-pad

**选择**：Timeline 页的 `#timelineContent` 容器内放一个 `<iframe>`，样式为 `width:100%; height:calc(100vh - <page-title 高度>); border:0;`。原 `renderTimelinePage()` 的列表渲染代码删除。

**理由**：gantt 视图需要足够纵向空间显示树和时间轴。iframe 高度撑满 page-pad 是最简单的做法。

### Decision 6: 静态文件路由

**选择**：在 `viewer/server.py` 仿照现有 `/claude-log.html` 路由，新增 `GET /session-gantt.html` 路由，`FileResponse(backend.viewer_dir / "session-gantt.html", media_type="text/html")`。

**理由**：保持与现有静态文件服务方式一致，不引入新机制。

## Risks / Trade-offs

- **[Risk] `claude_code_log` 版本与 copy 现有 Python 环境不兼容** → Mitigation: copy 要求 Python >=3.10，`claude-code-log>=1.4.0` 同样支持 3.10+。安装后跑一次 `python -c "from claude_code_log.converter import load_transcript"` 验证。
- **[Risk] gantt HTML 的 CDN 依赖（highlight.js / marked）在离线环境加载失败** → Mitigation: 接受。gantt 的核心树 + 时间轴不依赖这两个库，只有详情面板的 markdown 渲染和代码高亮受影响，降级为纯文本仍可读。
- **[Risk] iframe 高度计算不准，导致 gantt 内部出现双层滚动条** → Mitigation: iframe 用 `height: calc(100vh - 48px)` 之类固定公式，配合 `display:flex` 父容器；实现后手动验证。
- **[Risk] 父页面 session 切换频繁导致 iframe 频繁重载** → Mitigation: `updateTimelineIframe(sid)` 比较 `data-sid`，相同则跳过。
- **[Trade-off] iframe 内外主题不一致**（父页面可能浅色，iframe 始终深色）→ 接受。本期不统一主题，后续可单独迭代。
- **[Trade-off] gantt HTML 与原项目版本产生分叉**（因为加了 `embedded=1`）→ 接受。改动极小且有明确收益，后续若上游更新可手动 cherry-pick。
