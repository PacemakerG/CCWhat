# Analyzer Adapter 文档

本文档说明 AgentLens 的报告生成协议。它和 Log Adapter 是两套不同抽象。

## 核心概念

### Observed Agent

Observed Agent 是用户被 AgentLens 观察的 Coding Agent。

例如：

```bash
agentlens -- opencode
agentlens -- codex
agentlens -- claude
```

这里的 `opencode`、`codex`、`claude` 是被启动和观测的目标。

### Log Adapter

Log Adapter 读取 observed agent 的本地历史日志。

例如：

- observed agent 是 `opencode`，就用 `OpenCodeAdapter` 读取 OpenCode 本地 DB。
- observed agent 是 `codex`，就用 `CodexAdapter` 读取 Codex rollout/SQLite。

### Analyzer Agent

Analyzer Agent 是用来生成报告的 agent 或分析器。

它可以和 observed agent 相同，也可以不同。

例如：

- 用 OpenCode 观察 OpenCode session，并用 OpenCode 生成报告。
- 用 Codex 观察 Codex session，但临时用 Claude 生成报告。
- 用环境变量覆盖 analyzer command。

关键原则：

```text
observed agent != analyzer command
```

`agentlens -- codex` 的 `codex` 不能直接被当成报告命令。报告生成必须走 analyzer registry 中定义的非交互协议。

## 入口文件

主要文件：

- `agentlens/analyzer.py`
- `agentlens/analyzers/base.py`
- `agentlens/analyzers/registry.py`
- `agentlens/analyzers/opencode.py`
- `agentlens/analyzers/codex.py`
- `agentlens/session_report/pipeline.py`
- `viewer/server.py`

## AnalyzerSpec

Analyzer 协议由 `AnalyzerSpec` 描述：

```python
AnalyzerSpec(
    name="opencode",
    default_command=["opencode", "run", "--format", "json"],
    output_mode="jsonl_text",
    experimental=False,
    timeout_seconds=120,
    parse_output=parse_jsonl_text,
)
```

字段说明：

- `name`：规范化后的 analyzer 名称。
- `default_command`：默认非交互命令。
- `output_mode`：输出解析模式。
- `experimental`：是否实验性。
- `timeout_seconds`：默认超时时间。
- `parse_output`：输出解析函数。

## 当前 Analyzer 协议

### Claude

默认命令：

```bash
claude -p -
```

特点：

- prompt 走 stdin。
- stdout 直接作为报告内容。
- 当前作为稳定 analyzer。

### OpenCode

默认命令：

```bash
opencode run --format json
```

特点：

- prompt 走 stdin。
- 输出为 JSONL。
- parser 从 `type == "text"` 或 `part.type == "text"` 的事件中提取文本。
- 当前已进入可用状态。

### Codex

默认命令：

```bash
codex exec --json --ephemeral --ignore-user-config -
```

备用候选：

```bash
codex exec --output-last-message <tmpfile> --ephemeral --ignore-user-config -
```

特点：

- prompt 走 stdin。
- 输出为 JSONL。
- 当前标记为 experimental。
- 默认 timeout 较短，避免报告页面长时间等待。
- 超时时会使用本地结构化 fallback 生成可读报告。

## 输出模式

### stdout

适用于 Claude：

```text
stdout -> report markdown
```

### jsonl_text

适用于 OpenCode / Codex：

```text
stdout JSONL -> parser -> report markdown
```

parser 需要忽略工具事件、状态事件，只提取最终文本。

## 配置优先级

Analyzer command：

1. 显式传入 `analyzer_cmd`
2. 环境变量 `CCWHAT_ANALYZE_CMD`
3. analyzer registry 默认命令

Analyzer agent：

1. 显式传入 `analyzer_agent`
2. 环境变量 `CCWHAT_ANALYZE_AGENT`
3. observed agent 对应 adapter 名称
4. `claude`

Timeout：

1. 显式传入 `analyzer_timeout`
2. 环境变量 `CCWHAT_ANALYZE_TIMEOUT`
3. `AnalyzerSpec.timeout_seconds`
4. 全局默认 timeout

## 报告链路

Yuanxi 报告：

```text
session
  -> normalize_session_for_report
  -> build_report_data
  -> diagnosis_context
  -> diagnosis_prompt
  -> run_mc_analysis
  -> render_html_report
```

Generic 报告：

```text
session
  -> normalize_session_for_report
  -> build_report_data
  -> diagnosis_context
  -> generic_prompt
  -> run_mc_analysis
  -> generic_template.html
```

## Fallback 策略

Analyzer 失败时不要让页面空白。

失败场景包括：

- 命令不存在
- 非 0 exit
- timeout
- stdout 为空
- JSONL parser 解析不到报告正文

当前策略：

- Yuanxi：保留结构化分析页，并在诊断区域展示本地规则诊断。
- Generic：生成本地结构化 fallback Markdown，并继续渲染 HTML。

这保证即使 Codex experimental analyzer 失败，用户也能看到工具调用、阶段摘要和基础风险提示。

## 添加新 Analyzer 的步骤

1. 新建 parser 模块，例如 `agentlens/analyzers/myagent.py`。
2. 在 `agentlens/analyzers/registry.py` 注册 `AnalyzerSpec`。
3. 明确：
   - 默认命令
   - prompt 是否走 stdin
   - 输出格式
   - timeout
   - 是否 experimental
4. 为 parser 写 JSONL/stdout fixture 测试。
5. 为 `run_mc_analysis()` 写 command、timeout、fallback 测试。
6. 手动验证报告生成。

## 常见坑

- 不要把 `target_args` 当作 `analyzer_cmd`。
- 不要默认执行裸 `opencode`，它可能进入 TUI。
- 不要让 Codex 默认等待 300 秒。
- 不要假设 JSONL 每行都是最终文本。
- 不要在 parser 中把 user prompt 当作报告输出。
- 不要让 parser 输出空字符串后还声称成功。
