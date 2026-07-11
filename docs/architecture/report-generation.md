# 报告生成链路

## 目录与文件职责

```
agentlens/
├── session_report/          ← 报告生成核心（纯 Python，不依赖 web）
│   ├── model.py             → 数据模型定义（ReportSession/ReportEvent/ReportTurn…）
│   ├── normalize.py         → 原始 session → 统一 ReportSession 的适配层
│   ├── core.py              → 结构化分析引擎（阶段拆分、工具统计、规则发现、上下文武装）
│   ├── pipeline.py          → 两条报告 Pipeline 的编排入口 + HTML 渲染
│   └── __init__.py          → 公开 API：build_html_session_report / build_generic_html_report
│
├── analyzer.py              → LLM 调用器（subprocess 调用 AI CLI，支持回退链）
├── analyzers/               → 各 AI CLI 的输出解析协议
│   ├── base.py              → AnalyzerSpec 协议定义
│   ├── claude.py / codex.py / opencode.py  → 各 CLI 的解析器
│   └── registry.py          → 注册所有分析器，管理回退候选
│
├── assets/session-report/   → 静态资源（模板）
│   ├── diagnosis_prompt.md       → yuanxi 诊断模式的 LLM prompt
│   ├── generic_prompt.md         → generic 通用流程分析的 LLM prompt
│   ├── report_template.html      → yuanxi 报告的 HTML 模板（4227行，多Tab SPA）
│   ├── generic_template.html     → generic 报告的 HTML 模板（232行，Markdown渲染）
│   └── vendor/mermaid.min.js     → Mermaid 流程图渲染库
│
├── adapters/                → 多 Agent 日志适配器（Claude/Codex/OpenCode）
└── task_segments/           → 任务切分引擎（独立功能，非报告链路一部分）

viewer/
├── server.py                → HTTP API 服务器（接收前端请求，调度报告生成）
├── claude-log.html          → 主会话查看器前端页面
└── ...
```

---

## 调用链路（按文件串）

```
┌─────────────────────────────────────────────────────────────┐
│  viewer/server.py:300  do_POST()                            │
│  前端 POST /api/analyze 到达，解析 sessionId + mode         │
│  读取 session 数据（从 adapter 或本地 JSONL）                │
│  根据 mode 分流：                                            │
│    mode="yuanxi"  → build_html_session_report()             │
│    mode="generic" → build_generic_html_report()             │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│  agentlens/session_report/normalize.py:231                     │
│  normalize_session_for_report(session_dict)                 │
│                                                             │
│  将原始 dict → ReportSession 数据模型（model.py 定义）       │
│  推断 agent 类型 (claude/codex/opencode)                     │
│  按类型分流：                                                │
│    agent=="claude"  → _normalize_claude_agents/events/turns │
│    agent=="codex"   → _normalize_generic_agents/events      │
│    agent=="opencode"→ _normalize_generic_agents/events      │
│  输出：ReportSession { events[], turns[], agents[] }        │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│  agentlens/session_report/core.py:700                          │
│  build_report_data(report_session)                          │
│                                                             │
│  逐步骤调用内部函数：                                         │
│    extract_tool_events()     → 配对 tool_use↔tool_result    │
│                                计算 duration_ms，截断输入     │
│    build_phases()            → 以 Skill/Turn 为阶段边界      │
│    ├─ compute_phase_metrics()→ 每阶段 wall/tool/think/idle   │
│    │                         → >10min 间隔=人工等待           │
│    │                         → ≤10min 间隔=LLM思考           │
│    build_agent_summaries()   → 每 agent 耗时/工具/阶段归属    │
│    rule_findings()           → 规则化问题发现                  │
│    build_context()           → 压缩为≤60KB诊断上下文文本       │
│  输出：ReportData {                                          │
│    phases[], tool_events[], agent_summaries[],               │
│    findings[], diagnosis_context, summary{}, compression     │
│  }                                                          │
└──────┬──────────────────┬───────────────────────────────────┘
       │                  │
       │ (yuanxi)         │ (generic)
       ▼                  ▼
┌──────────────────┐  ┌──────────────────┐
│ agentlens/assets/   │  │ agentlens/assets/   │
│ session-report/  │  │ session-report/  │
│ diagnosis_prompt │  │ generic_prompt   │
│ .md              │  │ .md              │
│                  │  │                  │
│ "你是Agent       │  │ "You are an      │
│  Session性能     │  │  expert analyst  │
│  诊断专家..."    │  │  of Agent-LLM    │
│                  │  │  systems..."     │
└──────┬───────────┘  └──────┬───────────┘
       │                     │
       ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│  agentlens/analyzer.py:216                                     │
│  run_mc_analysis(prompt)                                    │
│                                                             │
│  _resolve_analyzer_agent()  → 选 AI CLI（claude/codex/...） │
│  _analyze_cmd()             → 解析命令路径                   │
│  _run_one_try()             → subprocess.run(cmd, input=… ) │
│    ├─ 成功 → 返回 (markdown, elapsed_ms)                    │
│    └─ 失败 → 自动尝试回退候选（analyzers/registry.py 管理）  │
│       全失败 → AnalysisError                                │
└──────┬──────────────────────────────────────────────────────┘
       │
       │  成功 → diagnosis_markdown
       │  失败 → _fallback_diagnosis_markdown() / _fallback_generic_markdown()
       │         (只用 core.py 产出的阶段数据拼一份基础 Markdown)
       ▼
┌─────────────────────────────────────────────────────────────┐
│  agentlens/session_report/pipeline.py                          │
│                                                             │
│  【yuanxi】build_html_session_report():148 →                 │
│    render_html_report(data)  ──调用──►  core.py:746         │
│    将 ReportData + LLM markdown 注入 report_template.html   │
│                                                             │
│  【generic】build_generic_html_report():222 →                │
│    _render_generic_html()  ──调用──►  pipeline.py:148       │
│    将 LLM markdown 注入 generic_template.html                │
│    + _get_mermaid_script_tag() 嵌入 mermaid.min.js           │
└──────┬──────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│  返回 viewer/server.py:300                                  │
│                                                             │
│  {                                                          │
│    reportHtml: "<!doctype html>…",                          │
│    reportUrl: "/api/analysis-report/<uuid>",                │
│    summary: { phaseCount, toolEventCount, totalWallMin … }, │
│    compression: { rawChars, compressedChars, … },           │
│    diagnosisStatus / llmStatus,                             │
│    elapsedMs, llmElapsedMs                                  │
│  }                                                          │
│                                                             │
│  同时 report_store[report_id] = {html, mode, sessionId}     │
│  前端拿到 reportUrl 后 iframe 打开                          │
└─────────────────────────────────────────────────────────────┘
```

---

## 两张流水线对比

| 维度 | yuanxi（诊断模式） | generic（通用模式） |
|------|-------------------|---------------------|
| 入口 | `build_html_session_report()` | `build_generic_html_report()` |
| LLM prompt | `diagnosis_prompt.md` — 性能诊断角色 | `generic_prompt.md` — 编排分析角色 |
| HTML 模板 | `report_template.html` — 多Tab SPA，数据注入为 JSON | `generic_template.html` — Markdown 渲染，前端 JS 解析 |
| 数据注入方式 | `render_html_report()` 把 phases/tools/findings/diagnosis 全注入 JSON | 只有 LLM 产出的 markdown 文本注入，附 Mermaid.js |
| 失败降级 | `_fallback_diagnosis_markdown()` — 简要指标+规则发现 | `_fallback_generic_markdown()` — 完整结构化的降级报告 |

---

## Agent 路由与子进程调用的完整链路

### Agent → 命令的映射（在 `analyzers/registry.py` 注册）

在模块加载时，`registry.py:79-101` 用 `_register()` 把每个 Agent 的路由表写入全局 `_REGISTRY`：

```
_REGISTRY = {
  "claude":   AnalyzerSpec(
                default_command=["claude", "-p", "-"],     ← 从 stdin 读 prompt，输出到 stdout
                output_mode="stdout",                       ← 直接把 stdout 当结果用
                experimental=False,                         ← 生产可用
              ),

  "opencode": AnalyzerSpec(
                default_command=["opencode", "run", "--format", "json"],
                output_mode="jsonl_text",                   ← 需要解析 JSONL
                experimental=False,
                parse_output=opencode_parsers.parse_jsonl_text,  ← 解析器函数
              ),

  "codex":    AnalyzerSpec(
                default_command=["codex", "exec", "--json", "--ephemeral", "--ignore-user-config", "-"],
                output_mode="jsonl_text",
                experimental=True,
                parse_output=codex_parsers.parse_jsonl_text,
                timeout_seconds=45,                         ← 更短的超时
              ),
}
```

---

### Agent 解析优先级（`analyzer.py:101-122`）

`_resolve_analyzer_agent()` 按优先级决定最终用哪个 AI CLI：

```
# 优先级从高到低：
1. 调用方显式传入的 analyzer_agent 参数  → 来自 viewer/server.py:375
2. 环境变量 CCWHAT_ANALYZE_AGENT        → 如 "export CCWHAT_ANALYZE_AGENT=claude"
3. default_agent（session 的 primary_agent_type）→ 记录该 session 的 agent 类型
4. 兜底 "claude"
```

---

### 命令解析优先级（`analyzer.py:75-85`）

`_analyze_cmd()` 决定最终执行的 shell 命令：

```
# 优先级从高到低：
1. 调用方显式传入的 cmd 参数           → viewer/server.py 的 analyzer_cmd
2. 环境变量 CCWHAT_ANALYZE_CMD         → 如 "claude -p -"
3. 从 registry 查 default_command       → 根据 agent 名查上面的路由表
```

然后用 `_resolve_binary()` 把二进制路径补全（查 PATH → 查已知路径 `/Applications/{Codex,OpenCode}.app/...`）。

---

### 子进程调用（`analyzer.py:148-213`）

`_run_one_try()` 是真正执行的地方：

```python
# analyzer.py:160
result = runner(resolved, input=prompt, capture_output=True, text=True, timeout=timeout_sec)
#                      ▲              ▲                ▲              ▲
#                      │              │                │              └─ subprocess 的超时
#                      │              │                └─ 文本模式，不返回 bytes
#                      │              └─ 通过 stdin 灌入组装好的 prompt
#                      └─ ["claude", "-p", "-"]  或  ["codex", "exec", "--json", ...]
```

```
  agentlens 进程
  ┌─────────────┐     stdin = prompt     ┌──────────────────┐
  │ analyzer.py │ ──────────────────────→│ claude -p -       │
  │             │                        │  (子进程)          │
  │             │←── stdout = markdown ──│  读取 prompt       │
  │ 等待中...    │                        │  生成诊断报告      │
  │ (阻塞)       │     timeout=120s       │  写入 stdout       │
  │             │                        │  退出              │
  └─────────────┘                        └──────────────────┘
```

**谁在等？** `viewer/server.py` 的 `do_POST()` 线程在等——因为是同步 HTTP 请求，从 `build_html_session_report()` 一路阻塞到 `subprocess.run()` 返回为止。

---

### 结果解析（`analyzer.py:189-213`）

子进程返回后，根据 `AnalyzerSpec.output_mode` 决定怎么处理 stdout：

| output_mode | 处理方式 | 对应 Agent | 解析文件 |
|-------------|---------|-----------|---------|
| `"stdout"` | 直接 `stdout.strip()` 就是最终 markdown | **claude** | 不需要 |
| `"jsonl_text"` | 调 `spec.parse_output(stdout, stderr)` | **opencode, codex** | `opencode.py:10` / `codex.py:67` |
| `"last_message_file"` | 从 `<tmpfile>` 读文件内容 | **codex 回退** | `codex.py:105` |

以 **codex JSONL 解析**（`codex.py:67-102`）为例：

```
codex 输出是逐行 JSON：
{"type":"assistant","content":[{"type":"text","text":"# Agent 交互分析报告\n"}]}
{"type":"assistant","content":[{"type":"text","text":"## 概述\n业务目标..."}]}

↓ parse_jsonl_text() 遍历每一行 ↓

跳过 "thread.started" / "turn.started" / "error" 等状态事件
提取 type=="assistant" 且 content 中有文本的块
拼成完整 markdown 字符串
```

---

### 结果流向与存储

返回的 `(report_markdown, elapsed_ms)` 继续往上传：

```
_run_one_try() → (markdown_str, int) 元组
     │
     ▼
run_mc_analysis() → (markdown_str, elapsed_ms)
     │
     ▼
pipeline.py:
  build_html_session_report() → data.diagnosis_markdown = markdown_str
     │                           ↓
     │                     render_html_report(data)
     │                     把 markdown 注入 report_template.html
     │                     生成完整 <!doctype html>...
     │                           │
     ▼                           ▼
viewer/server.py:            report_store[report_id] = {
  result = {                    "html": "<!doctype html>...",
    reportHtml: "...",          "mode": "yuanxi",
    summary: {...},             "sessionId": session_id
    reportUrl: "/api/...",    }
    compression: {...},
  }
     │
     ▼
  self._send_json(result)  ──→ 前端拿到 JSON，iframe.src = reportUrl
                                    │
                                    ▼
                              GET /api/analysis-report/<report_id>
                              从 report_store 取 html 返回
```

**存储位置**：
- **内存**：`report_store`（字典，`viewer/server.py` 顶层变量），key 是 UUID，存 `{"html": ..., "mode": ..., "sessionId": ...}`。进程重启后丢失。
- **不落盘**：报告是热生成的，不写文件。用户要保存的话，前端提供导出按钮下载 HTML。

---

### 失败处理

每个 Analyzer 只执行注册表中的主命令。失败时抛出 `AnalysisError`，由
`pipeline.py` 直接生成本地结构化报告，不再启动第二个 CLI 候选命令。

---

## 一条完整数据的流动总结

```
viewer/server.py POST /api/analyze  ← 前端发起，HTTP 线程阻塞等待
  │
  │ sessionId → 读 session dict
  │ mode → yuanxi / generic
  │
  ├─ normalize.py         session dict → ReportSession（内存对象）
  ├─ core.py              ReportSession → ReportData（阶段/工具/Agent/发现 + 诊断上下文文本）
  │
  ├─ analyzer.py          诊断上下文文本 + prompt 模板 → subprocess.run("claude -p -")
  │   │                    stdin 灌入，阻塞等待 120s，stdout 捕获
  │   └─→ markdown 字符串
  │       失败 → 本地 fallback markdown
  │
  ├─ pipeline.py          markdown + ReportData → 注入 HTML 模板 → <!doctype html>...
  │
  └─ server.py            返回 JSON {reportHtml, reportUrl, ...} 给前端
                          reportStore[UUID] = html  ← 存在内存里，供后续 GET 使用
```
