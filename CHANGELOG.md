# 更新日志 / Changelog

这里记录 AgentLens / agentlens 的重要版本变化。版本号以 `pyproject.toml` 和 `agentlens.__version__` 为准，发布标签使用 `v<version>`。

## v2.4.1 - 2026-07-02

### Timeline 页嵌入 Session Gantt 视图

把独立 session-gantt 页面以 iframe 方式嵌入 claude-log.html 的 Timeline 标签页，替换原扁平时间线列表。点击树节点弹出 assistant / tool_use / tool_result 详情面板，session 切换时 iframe 自动同步。

### 新增

- **依赖**：`pyproject.toml` 加入 `claude-code-log>=1.4.0`，复用其 `load_transcript` / `JsonRenderer` / typed models
- **后端路由**（`viewer/server.py`）：
  - `GET /api/session-gantt/<sessionId>` 返回扁平化 gantt 节点（depth / parentIdx / childIdxs / durationMs / tags / startMs / endMs），session 不存在返回 404
  - `GET /api/session-entry/<sessionId>/<nodeId>` 返回单条节点详情（assistant / tool_use / tool_result / user_input / compact）
  - `GET /session-gantt.html` 静态页路由
  - 辅助函数 `_iso_to_ms` / `_GANTT_BARRIER_TYPES` / `_flatten_gantt_nodes` / `_find_session_jsonl` / `get_session_gantt` / `get_session_entry_detail`
- **前端**：`viewer/session-gantt.html` 复制自 session-report-clean，支持 `embedded=1` URL 参数隐藏顶栏
- **前端**：`viewer/claude-log.html` 新增 `updateTimelineIframe(sid)`，Timeline 页改为承载 iframe；`loadSession()` 和 `navigateToPage('timeline')` 路径同步刷新 iframe

### 修复

- **空 session 未清空 Timeline iframe**：`loadSession()` 在 session 选为空时直接 return，导致上一个 session 的甘特图残留。补上 `currentLoadedSessionId = ''; updateTimelineIframe('');` 后再 return

---

## v2.4.0 - 2026-07-01

### Runtime Dataset 彻底重构：只保留 task 边界 git diff

承认 step-by-step 实时归因不可靠（PostToolUse hook 偶发不触发、fire-and-forget curl 易丢、并发 race 错位），把 runtime 产物砍到只剩 git diff ground truth + 边界元数据。Agent 行为轨迹 / instruction / changes 改由事后 dataset 导出时从原始日志抽取，可重放可校验。

### 改进

- **task.json schema 精简**：只保留 `task_id` / `run_id` / `agent` / `workspace` / `started_at` / `finished_at` / `start_tree` / `end_tree` 八个边界元数据字段，删掉 `instruction` / `success_criteria` / `expected_tests` / `paths` / `evidence_availability` / `git` / `schema` / `title` / `status`
- **task.diff 语义修正**：改为 start 时工作树快照 → finish 时工作树快照的 git diff（基于 isolated index 的 `write-tree` 对比），不再混入 task 开始前的 dirty 改动
- **git index 隔离**：全程使用 `.git/index.ccwhat`，零污染用户 `.git/index` 和工作树；untracked 文件也纳入 task.diff，但用户 `git status` 不受影响
- **CCWhatIndex 精简**：只保留 `init` / `sync_workspace` / `write_tree` / `diff_cached` 四个方法
- **升级自动清理**：install 时检测并移除旧版本残留的 `ccwhat-diff-hook.sh` 文件和 `settings.local.json` 的 `PostToolUse` 条目

### 移除

- **step-by-step diff 机制**：删除 `StepDiff` / `StepDiffBuffer` / `record_step` / `sync_step` / `remove_step` / `/step` endpoint / unattributed fallback / `diff.patch`
- **task_trace.json**：删除 `trace_extractor` 整个模块，runtime 不再在 finish 时抽取 Agent 行为轨迹（与离线 `task_dataset` builder 同源重复）
- **`diff_total.patch`**：被 `task.diff` 取代
- **Claude PostToolUse hook 安装**：删除 `_install_posttooluse_hook`，不再生成 `ccwhat-diff-hook.sh`
- **OpenCode `tool.execute.after` plugin 段**：删除 `detectFileOperation`，plugin 只保留 `command.execute.before` 用于 start/finish boundary
- **孤儿依赖 `claude-code-log`**：从 `pyproject.toml` 移除未使用的依赖，修复 uv 解析冲突

---

## v2.3.6 - 2026-06-30

### Windows 原生支持适配

将 Windows 原生环境从"暂不支持"升级为"支持 Codex 最低路径"，覆盖安装、代理、端口诊断、编码和 OpenCode 命令兼容。

### 新增

- **Windows 原生安装入口**：README 与 docs/WINDOWS.md 提供 uv/pipx/pip 的 PowerShell 安装路径
- **平台感知命令 quoting**：新增 `ccwhat/runtime/platform.py`，Windows 走 `subprocess.list2cmdline`，POSIX 走 `shlex.join`
- **端口可绑定性诊断**：`ccwhat web` 接入 `port_bind_error`，识别 Windows TCP excluded port range (WinError 10013)
- **Windows CA 证书指引**：proxy 启动输出 `%USERPROFILE%\.mitmproxy\mitmproxy-ca-cert.pem` 路径和信任步骤
- **docs/WINDOWS.md**：安装、手动验收清单、CA 证书、剩余风险

### 修复

- **UTF-8 资源读取**：`task_segment_rules.json`、`manifest.json`、marker 文件显式 `encoding="utf-8"`，避免 GBK locale 下 `UnicodeDecodeError`
- **自动切分失败保留手动 overlay**：`runTaskSegmentationForCurrentSession` 请求成功前不再 delete overlay，失败时恢复旧 task 列表（修复 [#7](https://github.com/PacemakerG/CCWhat/issues/7)）
- **task segmentation 后端异常返回 JSON**：`/api/task-segments` 捕获异常返回 `{ok:false,error}`，不再中断连接
- **OpenCode 命令文件 Windows 兼容**：`ccwhat:start.md` → `ccwhat-start.md`（colon 在 Windows 非法），plugin 同时识别新旧命令名
- **mitmdump 缺失提示**：统一给出 uv/pipx/pip/brew 四种安装方式

### 改动（review 修复）

- **Claude hook 保留 shlex.quote**：`#!/bin/sh` 脚本不跑在 Windows 原生，回退 `quote_command` 为 `shlex.quote`
- **剥离无关改动**：回退 PR 夹带的 `buildRawJsonSectionNew` contentBlock 改动
- **补 legacy colon 清理测试**：新增 `test_opencode_integration_removes_legacy_colon_commands_on_posix`

### 贡献者

本版本 Windows 原生支持适配由 [@Sugarfarmeriod](https://github.com/Sugarfarmeriod) 贡献，详见 [PR #9](https://github.com/PacemakerG/CCWhat/pull/9)。

---

## v2.3.5 - 2026-06-29

### Runtime Dataset V2 修复：OpenCode 完整支持

修复 OpenCode 集成中的关键问题，使其与 Claude Code 达到功能 parity。

### 修复

- **CCWHAT_ENABLED 环境变量**: 添加缺失的环境变量，使 OpenCode plugin 的 `tool.execute.after` hook 能正常工作
- **trace_extractor 支持 opencode**: 从 `agent != "claude"` 改为 `agent not in {"claude", "opencode"}`
- **OpenCode session log 提取**: 添加 `_find_ccwhat_session_dirs()` 函数，支持从 ccwhat proxy 日志 (`~/.ccwhat/raw-req-resp/`) 提取事件
- **task.json instruction 填充**: 现在 opencode 的 task 也能正确提取 `first_user_message` 作为 instruction

### 技术细节

- `ccwhat/commands/run.py`: 添加 `child_env["CCWHAT_ENABLED"] = "1"`
- `ccwhat/runtime/trace_extractor.py`: 支持多 agent 类型，为 opencode 添加 ccwhat 日志源
- `ccwhat/runtime/integrations/opencode.py`: plugin 添加 `tool.execute.after` hook 支持

---

## v2.3.4 - 2026-06-28

### Runtime Dataset 增强：完整文件操作追踪

优化增量 diff 追踪系统，现在可以完整记录 Agent 的所有文件操作，包括删除操作。

### 新增

- **删除操作追踪**：通过 Bash 工具的 `rm`/`unlink` 命令删除的文件现在会被记录到 diff.patch
- **完整的文件生命周期**：创建（Write）、修改（Edit）、删除（Bash rm）全部可追踪
- **Step header 增强**：diff.patch 中的步骤注释现在显示操作类型（MODIFY/DELETE）

### 改进

- **CCWhatIndex 初始化优化**：从 `read-tree --empty` 改为 `read-tree HEAD`，确保能检测所有文件变更
- **Diff 生成优化**：添加 `--cached` 参数，正确比对 index vs HEAD
- **Reconcile deletions**：finish 时自动扫描并同步已删除文件状态
- **Hook 脚本增强**：支持检测 Bash 工具的删除命令并通知 controller

### 技术细节

- `ccwhat/runtime/index.py`: `init()` 从 HEAD 开始，`diff()` 加 `--cached`，新增 `reconcile_deletions()`
- `ccwhat/runtime/staging.py`: 新增 `remove_step()` 方法
- `ccwhat/runtime/controller.py`: `/step` endpoint 支持 `action=delete`
- `ccwhat/runtime/models.py`: `StepDiff` 新增 `action` 字段
- `.claude/hooks/ccwhat-diff-hook.sh`: 支持检测 `rm`/`unlink` 命令

---

## v2.3.3 - 2026-06-26

### 报告模式名称优化

将 Viewer 中报告生成模式的显示名称从专业术语改为更直观的描述。

### 改进

- **报告模式重命名**：
  - 「元析」→「结构化报告」
  - 「通用流程」→「行为报告」
- **界面文案统一**：弹窗选项、生成状态提示、历史 badge、HTML 标题栏和 h1 全部同步更新
- **内部兼容**：mode 字符串 (`yuanxi`/`generic`) 保持不变，不影响 API 和测试

---

### Windows TCP 排除端口范围诊断增强

修复 Windows 系统默认端口落入 TCP excluded port range 导致的绑定失败问题。（Fixes #5）

### 新增

- **端口绑定诊断**：启动时添加 `bind()` 探针，识别"端口空闲但无法绑定"的情况
- **WinError 10013 友好提示**：提供 Windows TCP excluded port range 说明、netsh 检查命令和端口更换建议
- **诊断覆盖范围**：`ccwhat -- <cli>`、`ccwhat proxy`、`ccwhat discover` 和 viewer 启动路径全部支持

### 贡献者

- **Windows 端口诊断**：感谢 [@Sugarfarmeriod](https://github.com/Sugarfarmeriod)（[PR #8](https://github.com/PacemakerG/CCWhat/pull/8)）

---

## v2.3.2 - 2026-06-24

### Runtime V2 Dataset: Agent Behavior Trace

任务数据集升级到 V2，新增 Agent 完整行为轨迹记录。现在不仅知道代码改了什么，还能回放 Agent 每一步是怎么改的。

### 新增

- **task_trace.json**：`/ccwhat:finish` 时从 proxy session 日志按任务时间窗口切出 Agent 行为轨迹，写入 `tasks/<task-id>/task_trace.json`
- **任务语义字段**：`task.json` 新增 `instruction`（用户任务描述）、`success_criteria`（成功标准）、`expected_tests`（期望测试）
- **`evidence_availability.task_trace`**：标记 task_trace 提取状态
- **`trace_extractor.py`**：新增独立模块，复用已有 `extract_evidence` / `extract_change_evidence` 逻辑
- **Runtime Dataset 参考文档**：`docs/runtime-dataset/RUNTIME_DATASET_REFERENCE.md`

---

## v2.3.1 - 2026-06-23

### OpenCode Runtime Task Recording

通过 `ccwhat -- opencode` 启动时，现在支持原生 task 命令进行任务记录。OpenCode 通过 `.opencode/command/` 和 `.opencode/plugin/` 集成。

### 新增

- **OpenCode 支持**：`ccwhat -- opencode` 启动后，OpenCode 中新增 start/finish 命令，通过 `.opencode/command/` 和 `.opencode/plugin/` 注册
- **通用 runtime 架构**：`ccwhat.runtime.registry` 支持按 agent 名称分目录存储运行数据
- **Agent 统一**：Claude Code / OpenCode 均可通过 `ccwhat -- <agent>` 启动并自动注入任务记录能力

---


## v2.3.0 - 2026-06-23

### Runtime Task Recording MVP

通过 `ccwhat -- claude` 启动 Claude Code 时，现在支持原生 slash 命令进行任务记录。

### 新增

- **CCWhat Task 命令**：Claude Code slash 菜单中新增 `/ccwhat:start` 和 `/ccwhat:finish` 命令
- **任务记录**：支持记录任务开始、完成时间，自动捕获 git 快照和 diff
- **本地 staging**：任务数据保存在 `~/.ccwhat/runtime-runs/<run-id>/tasks/` 目录
- **控制事件日志**：记录所有 CCWhat 命令执行历史到 `control_events.jsonl`

### 技术细节

- 新增 `ccwhat.runtime` 模块：控制器、注册表、staging、Claude hook 集成
- 自动安装 Claude Code 集成：命令文件和 hook 配置
- 支持 HTTP 控制器本地通信

---

## v2.2.8 - 2026-06-22

### 请求回放功能增强

### 新增

- **多消息编辑支持**：请求回放功能现在支持编辑请求中的任意消息（而不只是最后一条），所有消息以可折叠列表形式展示。
- **独立对比视图**：每条被修改的消息都有独立的对比区块，清晰展示原始输入和改写输入的差异。
- **编辑状态标记**：编辑过的消息会显示 ✏️ 标记，并在消息列表中高亮显示。

### 改进

- **回放界面重构**：`renderReplayEditView` 改为多消息列表布局，默认展开最后一条消息。
- **Diff 区块可折叠**：对比视图中每个区块都可以独立折叠/展开，便于查看重点内容。
- **响应展示优化**：原始响应缺失时显示占位文本，避免空白区域。

### 技术细节

- 后端 API 改为接受 `edits` 数组格式（`[{msgIndex, editedText}]`）。
- 新增 `appliedEdits` 字段记录每次修改的原始文本和修改后文本。
- 新增辅助函数 `stripSystemReminders` 和 `extractMsgTextNoThinking`。

---

## v2.2.7 - 2026-06-22

### FastAPI 后端重构

### 改进

- **后端框架迁移**：Viewer 后端从 `BaseHTTPRequestHandler` / `ThreadingHTTPServer` 迁移到 FastAPI + uvicorn，新增 `create_app()` 应用工厂和 `ViewerServer` 生产启动封装。
- **接口兼容保留**：保留 `/api/projects`、`/api/session/{id}`、`/api/search`、分析报告、任务切分、Dataset 保存/下载、请求导出、请求回放等现有接口响应契约。
- **兼容测试层**：保留 `_make_handler()` 作为旧测试和外部调用的兼容适配层，通过 FastAPI `TestClient` 转发请求，降低迁移风险。
- **CLI 启动适配**：`ccwhat run` 的托管 Viewer 改为协议类型依赖，不再绑定 stdlib `HTTPServer` 实现。

### 文档

- 新增 FastAPI 重构说明和重构后项目结构文档，记录后端入口、路由分组、兼容边界与重点注意事项。

### 测试

- 更新 Viewer server 构造测试以覆盖新的 `ViewerServer` 封装。
- 验证 viewer/API 相关测试集：`220 passed`。
- 验证真实 uvicorn 启动 smoke：`/api/viewer/status` 返回 200。

---

## v2.2.6 - 2026-06-21

### 代码瘦身

### 改进

- **死代码清理**：移除未使用的 analyzer helper、viewer agent marker helper、legacy raw log helper、无效 `allowed_dirs` 分析参数和未引用的交互报告 prompt 模板。
- **导入整理**：清理多个后端模块中的未使用 import 和无效局部变量，降低后续 FastAPI 迁移前的噪音。
- **缓存清理**：移除仓库中的 Python `__pycache__` 和 `.DS_Store` 本地缓存文件。

---

## v2.2.5 - 2026-06-20

### Viewer 双语切换与界面优化

### 新增

- **双语切换**：`viewer/claude-log.html` 和 `viewer/req-resp.html` 新增中英双语支持，点击顶部语言按钮可在中文/英文间切换。
- **语言持久化**：语言选择保存在 `localStorage` (`ccwhat-locale`)，刷新页面后保持上次选择。

### 改进

- **界面风格统一**：优化两个 Viewer 的视觉层次，统一配色和间距，提升开发者工具使用体验。
- **仅本地化 UI 文案**：原始日志、请求/响应内容和分析数据保持原语言，仅界面元素随语言切换。

### 测试

- 新增 `tests/test_viewer_locale.py` 覆盖语言切换、动态占位符、导航文案和搜索范围文案。
- 更新现有 DOM 测试验证 `data-i18n` 属性正确性。

### 贡献者

本版本双语切换能力由 [@rmxob](https://github.com/rmxob) 贡献，详见 [PR #6](https://github.com/PacemakerG/CCWhat/pull/6)。

---

## v2.2.4 - 2026-06-20

### 修复详情面板 Thinking 字段缺失

### 修复

- **详情面板 Thinking 卡片**：修复 `buildMinimalTurnDetailHtml()` 中遗漏的 `buildThinkingSection()` 调用，Turn 详情面板现在正确显示 Thinking / Reasoning 内容。

---

## v2.2.3 - 2026-06-19

### 全局 Session / Task 搜索

### 新增

- **全局搜索 API**：新增 `/api/search`，支持当前 session、当前 project、所有 projects 三种范围，返回 session / turn / event / task 命中结果。
- **Viewer 搜索入口**：顶部搜索框新增范围选择、结果分组、加载状态和折叠/展开能力，结果可跳转到对应 session、task 或 turn。
- **Task 搜索来源**：搜索已有 task segmentation / overlay / Dataset task source，不为未切分 session 伪造 task。
- **测试覆盖**：新增后端 API 测试和前端 DOM/JS 静态测试，覆盖 scope、截断、部分读取失败、task source 和导航钩子。

### 贡献者

本版本全局搜索能力由 [@Sugarfarmeriod](https://github.com/Sugarfarmeriod) 贡献，详见 [PR #3](https://github.com/PacemakerG/CCWhat/pull/3)。

---

## v2.2.2 - 2026-06-19

### 前端展示优化

### 改进

- **Step / Turn 概览**：Viewer 详情面板首卡从低价值日志元数据升级为概览信息，展示类型、位置、Task、状态和内容长度。
- **Thinking 完整展示**：normalized reasoning 事件优先使用完整 content，避免 Detail 面板展示被 summary 截断的 thinking；Thinking 区块默认展开，并保留折叠能力。
- **Session 树交互优化**：Session 页新增全部展开/全部折叠，统计文案改为 `Steps / Total Turns / Entries`，Markdown 代码块支持行号和复制。

---

## v2.2.1 - 2026-06-18

### 零配置自动录制 + OpenAI 格式 SSE 解析

### 新增

- **零配置自动录制**：启动 `agentlens` 时自动读取目标 agent 的本地配置文件，提取 API domain，与 `~/.agentlens/config.toml` 已配置的 domain 去重合并后作为录制目标，无需手动执行 `agentlens setup`。支持三种 agent：
  - **opencode**：读取 `~/.config/opencode/opencode.jsonc`，提取全部 `provider.*.options.baseURL`
  - **claude**：读取 `~/.claude/settings.json`，提取 `env.ANTHROPIC_BASE_URL`，无则回退 `api.anthropic.com`
  - **codex**：读取 `~/.codex/config.toml`，提取 `shell_environment_policy.set` 中所有 `*_BASE_URL`，无则回退 `api.openai.com`

### 改进

- 抓包页面 SSE 解析新增 OpenAI 兼容格式支持（`chat.completion.chunk`），OpenCode 等使用 OpenAI API 格式的 agent 的流式响应现在可以正确解析和展示。

---

## v2.2.0 - 2026-06-18

### 请求回放

V2.2.0 在网络抓包页面正式引入请求回放能力，让用户能够对历史录制请求进行原文回放或改写后重新发送，无需手动构造请求体。

**回放的核心用途**：AI Coding Agent 每次请求的上下文是动态累积的，单看某条请求很难判断"AI 是真的理解了指令，还是恰好蒙对了"。回放功能让你可以把某次关键请求单独拎出来，修改用户消息再发一遍，直接验证 AI 对指令的响应质量，或对比同一上下文下不同 prompt 的输出差异。

### 新增

- **回放入口**：抓包列表中含有真实用户消息的请求自动显示「🔁 回放」按钮，点击后在右侧面板展开回放编辑区。
- **原文回放**：一键用原始消息重新发送请求，响应结果直接展示在回放区，与原始响应并排对比。
- **改写回放**：在编辑框中修改用户消息内容后重新发送，适合测试不同 prompt 在相同上下文下的表现差异。
- **消息净化**：回放前自动剥离消息头部的 `<system-reminder>` 和 `<local-command>` 系统注入块，只保留用户实际输入的内容，避免系统块干扰编辑和对比。
- **自动注入认证**：后端从 `ANTHROPIC_CUSTOM_HEADERS` 环境变量读取最新 `X-Client-Token`，覆盖录制时已过期的 token，解决直接回放报 401 的问题。
- **非流式模式**：回放请求统一以 `stream: false` 发送，响应以完整 JSON 返回，前端直接渲染，无需处理 SSE 流解析。

---

## v2.1.1 - 2026-06-17

### Session 重命名

V2.1.1 在 Viewer 中为 Codex / OpenCode session 提供原生标题重命名能力。

### 新增

- **Session 重命名**：Viewer 顶部新增 session title bar，显示 session 名称和时间范围。Codex 和 OpenCode session 支持点击「✏️ 重命名」内联编辑，直接写入各自原生 DB（Codex 写 `state_5.sqlite`，OpenCode 写 `opencode.db`）。Claude Code session 标记为不支持重命名（无原生 title 存储）。
- **`POST /api/session/<id>/rename` 接口**：标准化的重命名 API，含 session id 白名单校验、空 title 拦截，以及 `invalid_title` / `session_not_found` / `rename_not_supported` / `native_title_unavailable` / `native_title_write_failed` 五个错误码的精确 HTTP 状态映射。
- **统一 title 元数据**：三个 Adapter（Claude / Codex / OpenCode）的 `list_projects`、`list_sessions`、`get_session` 返回值统一携带 `title`、`displayName`、`canRenameSession` 字段，前端可无差别消费。

### 改进

- Codex SQLite 读取从位置索引（`row[0]`）升级为命名访问（`row["id"]`），并在读取前做 `PRAGMA table_info` 列名检查，兼容不同 Codex schema 版本。
- Codex / OpenCode 时间戳归一化逻辑统一，正确处理 Unix 秒、Unix 毫秒和 ISO 字符串三种格式，并过滤 bool / 空值输入。

### 贡献者

本版本全部改动由 [@tanzunsheng](https://github.com/tanzunsheng) 贡献，详见 [PR #2](https://github.com/PacemakerG/AgentLens/pull/2)。

---

## v2.1.0 - 2026-06-16

### Turn-Level Diff Viewer

V2.1.0 将 Diff 页面从 task evidence 文件汇总升级为 Turn 级结构化对比能力，新增 `Diff with Prev` modal 弹层。

### 新增

- **Turn Diff 数据模型**：前端基于 session Turn projection 构建 diff model，归一化 9 个稳定观测字段（文本、Thinking、工具调用、工具结果、命令、文件、错误、元数据），不依赖 task segmentation 或 Dataset。
- **`Diff with Prev` Modal**：在 Turn/Step 详情操作区新增按钮，打开弹层进行 Turn 间对比。Modal 支持：
  - 统一 LEFT (baseline) / RIGHT (current) 字段网格布局，全部 9 个字段逐行展示
  - 当前有/baseline 无 → 右侧绿色背景；baseline 有/当前无 → 左侧红色背景；变更 → 两侧橙色背景
  - 上一组/下一组 diff pair 导航
  - 手动 baseline selector，可从候选 Turn 列表中切换比较对象
  - Escape 键和背景点击关闭
- **Diff 页面升级**：左侧 `Diff` 页面从 task 文件汇总改为 Turn diff 总览，列出所有 primary Turn 的 diff 摘要，点击条目直接打开同一 diff modal。
- **前端测试**：新增 13 个测试函数覆盖数据模型、modal 渲染、字段网格、baseline 选择、无 task 依赖等场景。

### 改进

- Turn 详情区恢复为 `Agent 响应` + `原始 JSON` 两项，`Diff with Prev` 作为独立操作入口，不常驻详情区。
- Diff 展示不再引用 `taskSegmentReports`、task evidence `filesChanged`/`filesRead` 或 Dataset `changes`/`patches`。

---

## v2.0.0 preview - 2026-06-15

### Preview：Task Dataset Builder — 数据标准化

V2.0.0 preview 是 v2 系列的起点，核心变化是从"查看 Task"进入"沉淀 Task 数据"。Agent Session 中切分出的 Task 被清洗为标准格式，便于后续离线评测和诊断。

### 新增

- **Dataset 标准格式**：每个 Dataset 包含四层结构：
  - `manifest.json` — 数据集元信息（schema_version、tool、session、counts）
  - `dataset.jsonl` — 任务定义索引，每行一个 task：`id`、`input.instruction`、`input.repo`、`expected.success_criteria`、`expected.tests`、`metadata.agent/session_id/task_source/trace_path/start_event_id/end_event_id`
  - `traces/*.json` — 执行过程详情，记录 task 边界内全部 events、commands、test_commands、files.read、files.changed、changes、patches、errors、final_claim、repo_state
  - `scores.jsonl` — 评分占位，第一版为空文件，留给 evaluator 追加
- **Dataset Registry**：Dataset 保存到 `~/.agentlens/datasets/<dataset-id>/` 目录。
- **Dataset 下载**：支持浏览器下载 `dataset-*.tar.gz` 压缩包，包内根目录 `agentlens-dataset/`，通过 Dataset validator 校验。
- **Source Provenance 校验**：请求携带完整 source payload、provenance、overlay version 和 source trace 信息，后端校验 session 一致性、overlay 版本和 trace 对齐后再构建 Dataset。
- **Dirty Overlay 保护**：存在未保存 overlay 编辑时阻止保存，要求用户先保存或撤销。
- **Dataset Core 模块**：新增 `agentlens/task_dataset/` 模块，包含 models、builder、validator，支持 Claude Code / Codex / OpenCode 三个 Agent 的 fixture。
- **Change Evidence 抽取**：统一提取 Claude Code / Codex / OpenCode 的文件改动证据，写入 trace `changes` 和 `patches`。

### 改进

- Task source 选择策略：saved overlay 优先，task segmentation result 兜底。
- 第一版完全隐藏 raw session / raw req-resp 选项，相关请求直接返回 HTTP 400。

### 限制（后续版本解决）

- 不支持 evaluator score 自动评分。
- 不支持 Dataset 列表、删除、重命名等 registry 管理页面。
- 不支持拖拽调整 Task 边界（仅按钮操作）。

---

## v1.1.0 - 2026-06-13

### 新增手动任务切分 + 自动任务切分，支持人为微调

V1.1.0 新增手动任务切分，并与原有自动切分并列。用户既可以一键自动切分，也可以在 Session 会话树上手动框选范围创建 Task。自动切分的结果还支持人为微调：调整边界、拆分、合并、删除、修改标题和类型。编辑后可保存、撤销或导出 Overlay JSON。

---

## v1.0.0 - 2026-06-12

### 正式发布：Session Trace 双视图 + 自动任务切分闭环

V1.0.0 正式发布。相比 Preview 版，核心补齐了 Session 页面的双视图浏览能力和任务切分闭环。

### 新增

- **Session Trace 双视图切换**：顶部新增 `默认视图` / `调试视图` 切换控件。
- **默认视图**：只展示主执行链路 Step，隐藏普通内部事件。默认视图包含：
  - `Step N` 连续编号
  - 用户请求（user request）、思考过程（thinking）、Agent 文本回复（agent text）、工具调用（tool call）、工具结果（tool result）
  - 包含 error/warning/failed/denied 等异常信号的内部事件也会自动提升为 primary Step
- **调试视图**：展示完整 Turn 时间线，保留原始 `Turn N` 标签和时序，包括默认视图中隐藏的内部事件：
  - `permission-mode`、`last-prompt`、`PostToolUse` hook
  - `file-history-snapshot`、`queue-operation`
  - `system`、`context` 注入、`attachment` 元数据、`unknown` 事件
  - 调试视图下保留底层类型筛选（user/assistant/system/attachment/perm/fhs/queue/other）作为高级筛选
- **自动任务切分闭环**：任务切分完成后，Session Trace 自动切换为 `Task -> 会话 -> Step/Turn` 树形结构，无需额外点击确认。
- **Turn Detail 完整证据**：右侧详情区始终展示当前选中 Turn 的完整证据（不再受左侧筛选影响），包括完整 tool input/output、thinking 全文、internal event 结构化字段、可展开 raw JSON 和 entry/block 定位信息。
- **任务切分定位强化**：Task 起止事件可稳定映射回 Session Trace Turn，支持 OpenCode/Codex adapter 的 normalized event id 稳定性。

### 改进

- 默认进入 Session 页面，默认使用默认视图，减少首屏信息噪声。
- 类型筛选降级为调试视图下的高级筛选，默认视图不显示类型筛选栏。
- 搜索支持两步过滤：默认视图下搜索主执行 Step，调试视图下搜索完整 Turn + 类型筛选。
- 切换视图时，当前选中节点尽量保持选中；internal Turn 切回默认视图时自动回退到父会话并给出切换提示。
- 保留 Tasks 页面的确认状态机制，确认只影响 UI badge，不改变 Tree 结构。

---

## v1.0.0 preview - 2026-06-11

### 新增

- 发布 V1 preview版本：新增 Task Trace Workbench。
- 新增第一版规则任务切分能力，可从长 Session 中识别多个 Coding Task。
- Viewer 新增任务列表、任务详情、边界原因、Evidence、命令/错误、Raw JSON 等任务切分展示。
- 左侧导航升级为 App Shell 工作台，包含 Session、Tasks、Overview、Timeline、Req / Resp、Diff、Diagnostics、Export、Settings。

### 改进

- 默认仍进入 Session 页面，Tasks 由用户手动触发任务切分。
- 修复 Viewer 初始化递归问题，避免页面打开时栈溢出。
- 保留 Claude Code、Codex、OpenCode 三类 Agent 的日志查看、报告、时间线和任务切分入口。
- 改进 task 起止事件到原始日志 turn/event 的定位。

---

## v0.1.3 - 2026-06-09

### 新增

- 完成 Codex 报告生成链路的完整适配，元析报告和通用报告在 Codex 会话上均可正常生成。
- 至此，AgentLens 已全面支持三大主流 AI Coding Agent：**Claude Code（VS Code）**、**Codex** 和 **OpenCode**，日志查看、分析报告、时间轴、工具耗时、Agent 摘要等核心功能对三者均可用。

### 改进

- Codex 报告生成的协议解析和超时问题已修复。
- 三大 Agent 的 Analyzer 适配器统一收归 `agentlens/analyzers/` 模块，结构更清晰。

---

## v0.1.2 - 2026-06-09

### 新增

- 完成 OpenCode 报告生成链路的第一版适配。
- OpenCode Analyzer 默认使用 `opencode run --format json`，并支持真实 JSONL 输出中的 `part.text`。
- OpenCode 本地 DB 日志接入元析报告和通用报告的数据管线。

### 改进

- 修复 OpenCode 数字时间戳归一化，工具事件可正确进入时间轴、阶段统计、柱状图和饼图。
- 修复通用报告 Mermaid 渲染失败时的 fallback 展示，保留原始 Mermaid 源码并区分语法失败和库未加载。
- 收紧通用报告 prompt 中的 Mermaid 输出约束，降低 OpenCode 生成非法 Mermaid 的概率。
- 增加 OpenCode 报告链路和 Mermaid fallback 的回归测试。

### 已知问题

- Codex 已接入多 Agent 日志/Analyzer 架构，但报告生成仍存在耗时和协议解析问题，下一步会继续适配 Codex。

## v0.1.1 - 2026-06-06

### 新增

- 新增多 Coding Agent 会话查看架构。
- 新增 Claude Code、Codex、OpenCode 本地日志 Adapter。
- 新增 `agentlens web --agent <agent>`，支持按 agent 选择默认日志来源。
- 新增统一的 normalized events / turns / usage 数据结构，为后续跨 agent 展示做准备。

### 改进

- Web Viewer 保持 Claude Code 原有展示能力，同时可显示当前 agent 类型。
- `agentlens -- <target>` 会根据启动目标推断 agent 类型，并把类型传给 Viewer。
- Codex 和 OpenCode 先按各自本地日志结构适配，不假设它们和 Claude Code JSONL 相同。

## v0.1.0 - 2026-05-28（初始版本）

### 新增

- Claude Code 本地会话日志查看。
- 请求 / 响应抓包记录。
- Web Viewer、导出、导入和基础诊断流程。
