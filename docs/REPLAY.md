# 请求回放与通用性修正

## 当前项目阶段

截至此次修改，包版本为 2.5.0，main 已包含后续的诊断证据引用、诊断预检，以及 runtime/offline Task Dataset 统一。

已实现的主要链路：

- Claude Code、Codex、OpenCode 原生日志适配，Session / Task / Turn 浏览与搜索。
- HTTP/HTTPS 请求录制、请求与响应查看、上下文 Diff。
- Task 切分、运行时任务边界 Git diff、统一 Dataset 保存和导出。
- 会话分析报告，以及基于显式 Marker 的 OpenSpec 流程图和归因诊断。

过去原生日志适配比请求链路走得更远。本次针对请求链路和公共入口中仍绑定特定 CLI、服务商或操作系统的假设进行修正。

## 修正内容

| 原问题 | 当前行为 |
| --- | --- |
| 回放固定使用 Anthropic URL，并追加 beta 查询参数 | 使用记录中的完整 URL 和查询参数 |
| 自动读取旧内部 CLI 的凭据，注入专用 Header | 移除历史认证信息，按当前目标 origin 重新构造认证 Header；自定义网关自行指定 Header 名称 |
| 强制将 stream 改为 false | 保留原始 stream 设置，支持 JSON 和 SSE 响应 |
| 编辑只识别 messages，且可能覆盖工具结果、错误的文本块 | 同时支持 messages、Responses input 字符串/数组；精确编辑文本字段，保留图片、工具 ID 和其他字段 |
| 非 SSE 请求没有回放入口，截断请求也可能被发送 | 完整 JSON POST 可回放；截断或非法 JSON 在发送前明确拒绝 |
| SSE 整理漏写 content，只识别 Anthropic，Chat 工具调用和 reasoning 混杂 | 统一解析 Anthropic Messages、Chat Completions、Responses，保留内容、工具调用、思考、ID 与 usage |
| 网络分块直接 UTF-8 解码，只按 LF 分帧 | 增量解码，兼容 CRLF/LF/CR 分帧；保存通用 session_id |
| 回放缓存只以消息 ID/文件行号区分 | 使用会话、日期、文件行号组成记录键 |
| 自动根据 CLI 名称强加 /v1 路径，漏录自定义网关 | 自动模式只匹配已配置/发现的域名；仅用户设置的路径或 preset 限制路径 |
| Codex 默认只覆盖 API key 的域名/路径 | 默认域名和 Codex preset 同时覆盖 ChatGPT 登录的 HTTP endpoint |
| 完整可执行文件路径和 Windows 扩展名导致 agent 识别失败 | 根据文件名识别，并处理 .exe/.cmd/.bat |
| 非 Claude 时间线使用 Claude 专用日志解析器 | Codex/OpenCode 时间线使用各自 adapter 的标准事件；保留原始顺序和显式工具关联 |
| Windows 用 os.kill(pid, 0) 检查存活会终止进程 | Windows 使用查询 API，POSIX 保留信号零检查 |

## 凭据配置

回放先移除历史认证信息，包括未脱敏的旧凭据、Cookie 及已脱敏值，再从当前环境重新构造认证 Header。请在启动 Viewer 的同一终端配置环境变量，然后启动 `ccwhat web --agent <agent>`。

敏感头按通用名称/模式及当前 `config.toml` 的 `recording.redact_headers`、`recording.redact_header_patterns` 识别；没有明显认证特征的私有 Header 名称应加入该配置。Viewer 的 `--config` 同时指定这组规则。

标准服务：

- `ANTHROPIC_API_KEY` 或 `ANTHROPIC_AUTH_TOKEN` 仅用于 `ANTHROPIC_BASE_URL` 对应的 origin；未设置 base URL 时为 `https://api.anthropic.com`。`ANTHROPIC_CUSTOM_HEADERS` 也仅用于该 origin。
- `OPENAI_API_KEY` 仅用于 `OPENAI_BASE_URL` 对应的 origin；未设置 base URL 时为 `https://api.openai.com`。
- 不自动读取其他 CLI 的登录文件，也不会把 OpenAI API key 当成 ChatGPT 登录凭据。

自定义网关、ChatGPT 登录或其他 Header 认证，使用 `CCWHAT_REPLAY_HEADERS`。它是 **origin → Header 对象** 的 JSON 映射；origin 包含协议、主机及非默认端口。它不改变请求目标。

PowerShell 示例（将示例值替换为对应服务的有效凭据）：

```powershell
$env:CCWHAT_REPLAY_HEADERS = '{"https://gateway.example.com":{"Authorization":"Bearer YOUR_TOKEN","X-Custom-Token":"YOUR_CUSTOM_TOKEN"}}'
ccwhat web --agent opencode
```

Bash 示例：

```bash
export CCWHAT_REPLAY_HEADERS='{"https://gateway.example.com":{"Authorization":"Bearer YOUR_TOKEN"}}'
ccwhat web --agent codex
```

匹配 origin 的显式 Header 映射完整替代标准环境变量推导出的 Header 集合，避免同时混入多套认证；Header 名称不区分大小写。显式设置为空对象可用于不需要认证的目标。历史记录中的认证字段不代表当前网关的必填字段，不再要求逐项补回旧 `X-Client-Token` 或 Cookie。未配置有效凭据且目标需要认证时，由目标服务返回认证错误，不会回退到历史凭据。重定向不会被自动跟随。

## 支持边界

- 回放以历史请求为模板，替换选中的 Prompt/文本字段后重新序列化 JSON，并构造新的 POST 请求；未编辑时也重新序列化，保留字段内容。它不会执行响应中的工具调用，也不是恢复整个 CLI 会话。
- 标准化展示支持上述三种协议。其他 JSON 响应保留可查看的数据，但不承诺任意私有协议的语义解析。
- WebSocket、AWS SigV4 等请求签名、过期的服务端 conversation/previous_response_id 不会自动重建；需重新录制或提供适用凭据。此前已损坏或截断的录制也无法凭空恢复。
- 使用 preset 或显式 paths 时仍保留用户的过滤选择；自定义网关若采用不同路径，应调整该配置。
- OpenSpec Marker 诊断仍是明确面向 Claude Code 的 Workflow Adapter；它没有被宣称为任意 CLI 的通用归因器。

参考：[OpenAI 对 Codex 两种登录 endpoint 的说明](https://openai.com/index/unrolling-the-codex-agent-loop/)、[Anthropic SSE 协议](https://platform.claude.com/docs/en/build-with-claude/streaming)、[Python Windows 信号零问题](https://bugs.python.org/issue14480)。
