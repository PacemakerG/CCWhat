## Purpose
Define proxy interception startup, recording behavior, and operator-facing diagnostics.
## Requirements
### Requirement: Start proxy server
`proxy` 子命令 SHALL 在当前 Python 进程内通过 `mitmproxy.tools.dump.DumpMaster` 启动 HTTP/HTTPS 代理服务器，使用 `asyncio.run()` 驱动事件循环。

#### Scenario: Start with default port
- **WHEN** 用户执行 `deep-ai-analysis proxy`
- **THEN** 系统在默认端口 7788 启动代理，打印代理地址（如 `Proxy listening on http://127.0.0.1:7788`）和 CA 证书安装指引

#### Scenario: Start with custom port
- **WHEN** 用户执行 `deep-ai-analysis proxy --port 9090`
- **THEN** 系统在端口 9090 启动代理

#### Scenario: mitmproxy not installed
- **WHEN** `mitmproxy` 包未安装，用户执行 `deep-ai-analysis proxy`
- **THEN** 系统打印安装指引（`pip install mitmproxy`）并以非 0 退出码退出

#### Scenario: Port already in use
- **WHEN** 指定端口已被占用，用户执行 `deep-ai-analysis proxy --port 7788`
- **THEN** 系统打印端口冲突错误信息并以非 0 退出码退出

### Requirement: Domain filtering
域名过滤列表 SHALL 在代码中以常量数组配置，默认值为 `["api.example.com"]`，不作为 CLI 参数暴露。仅匹配域名的请求和响应被记录，其他域名流量被代理但不记录。

#### Scenario: Default domain filter applied
- **WHEN** 用户执行 `deep-ai-analysis proxy`，有请求经过代理
- **THEN** 仅 `api.example.com` 的请求/响应被写入日志，其他域名流量被代理但不记录

#### Scenario: Non-matching domain not recorded
- **WHEN** 经过代理的请求目标域名不在过滤列表中
- **THEN** 该请求被正常代理转发，但不生成任何日志记录

#### Scenario: Multiple configured domains
- **WHEN** 代码中 `RECORD_DOMAINS` 配置为 `["api.example.com", "other.example.com"]`
- **THEN** 两个域名的请求/响应均被记录

### Requirement: Record raw request and response
代理 addon SHALL 在 mitmproxy 的 `response` 钩子中将完整的请求和响应原始内容以 JSONL 格式追加到对应 session 子目录下的当天日志文件。记录请求 headers 时，SHALL 过滤掉 `Authorization` header（大小写不敏感），其余 headers 完整保留。

日志路径格式为 `<output_dir>/<sessionId>/YYYY-MM-DD.jsonl`，sessionId 从请求 header `X-Claude-Code-Session-Id` 提取，不存在时使用 `unknown`。

#### Scenario: Default output directory
- **WHEN** 用户执行 `deep-ai-analysis proxy`（不带 `--output`）
- **THEN** 日志写入 `~/.deep-ai-analysis/raw-req-resp/<sessionId>/YYYY-MM-DD.jsonl`；目录不存在时自动创建

#### Scenario: Custom output directory
- **WHEN** 用户执行 `deep-ai-analysis proxy --output ~/my-logs`
- **THEN** 日志写入 `~/my-logs/<sessionId>/YYYY-MM-DD.jsonl`；目录不存在时自动创建

#### Scenario: Record standard HTTP response
- **WHEN** 一个匹配过滤域名的 HTTP 请求完成（非 SSE）
- **THEN** 一条 JSON 记录被追加到 `<output_dir>/<sessionId>/YYYY-MM-DD.jsonl`，包含：请求时间戳（ISO8601）、URL、HTTP 方法、请求 headers（dict，已排除 `Authorization`）、请求 body（字符串）、响应状态码、完整响应 headers（dict）、响应 body（字符串）、`is_sse: false`

#### Scenario: Log path includes session ID
- **WHEN** 代理收到携带 `X-Claude-Code-Session-Id` header 的请求
- **THEN** 日志写入 `<output_dir>/<sessionId>/YYYY-MM-DD.jsonl`

#### Scenario: Log path fallback for unknown session
- **WHEN** 请求不携带 `X-Claude-Code-Session-Id` header
- **THEN** 日志写入 `<output_dir>/unknown/YYYY-MM-DD.jsonl`

#### Scenario: Authorization header excluded from log
- **WHEN** 请求携带 `Authorization` header（任意大小写，如 `Authorization`、`authorization`、`AUTHORIZATION`）
- **THEN** 写入 JSONL 的记录中 `request.headers` 字段不包含该 key，其他 headers 正常保留

#### Scenario: JSONL append mode
- **WHEN** 同一 session 同一天内有多条请求被记录
- **THEN** 所有记录追加写入同一个 `<output_dir>/<sessionId>/YYYY-MM-DD.jsonl` 文件，每条记录占一行，文件内容为合法的 JSONL 格式

#### Scenario: Output directory auto-creation
- **WHEN** `<output_dir>/<sessionId>/` 目录不存在
- **THEN** 自动创建该目录

#### Scenario: Log file auto-rotation
- **WHEN** 代理运行跨越午夜（日期变更）
- **THEN** 新的请求写入新日期对应的 `YYYY-MM-DD.jsonl` 文件

### Requirement: SSE stream recording
代理 addon SHALL 检测并完整记录 SSE（Server-Sent Events）流式响应，连接关闭后将完整记录作为一行追加到 JSONL 文件。记录请求 headers 时，SHALL 过滤掉 `Authorization` header（大小写不敏感）。

#### Scenario: Detect SSE response
- **WHEN** 响应头包含 `content-type: text/event-stream`
- **THEN** addon 识别该响应为 SSE 流，为该 flow 启用流式记录模式（`flow.response.stream = True`）

#### Scenario: Buffer SSE events in memory
- **WHEN** SSE 连接活跃且新的 chunk 到达
- **THEN** addon 解析 chunk 中完整的 SSE 事件（以 `\n\n` 为边界），将每个完整事件追加到该 flow 的内存缓冲 `sse_events` 列表

#### Scenario: Partial SSE chunk buffering
- **WHEN** 接收到的 chunk 末尾不以 `\n\n` 结尾（事件边界不完整）
- **THEN** addon 将不完整部分存入该 flow 的 per-flow 缓冲区，等待后续 chunk 合并后再解析

#### Scenario: SSE session complete — write to JSONL
- **WHEN** SSE 连接关闭（flow 完成）
- **THEN** 将完整记录作为一行 JSON 追加到当天 JSONL 文件：`is_sse: true`，`sse_events` 包含本次连接所有完整事件的原始文本列表，`response.body` 为所有事件拼接的完整字符串，`request.headers` 已排除 `Authorization` header；记录中不包含 `sse_content` 字段

#### Scenario: SSE Authorization header excluded from log
- **WHEN** SSE 请求携带 `Authorization` header
- **THEN** 写入 JSONL 的 SSE 记录中 `request.headers` 字段不包含该 key

### Requirement: CA certificate guidance
代理启动时 SHALL 向用户打印 mitmproxy CA 证书的路径和安装指引，以便用户信任 HTTPS 解密。

#### Scenario: Display certificate path on startup
- **WHEN** 用户执行 `deep-ai-analysis proxy` 且代理成功启动
- **THEN** 系统打印 CA 证书文件路径（`~/.mitmproxy/mitmproxy-ca-cert.pem`）和系统安装提示

### Requirement: Graceful shutdown
代理 SHALL 在收到 SIGINT（Ctrl+C）时完成当前活跃流的记录后再退出。

#### Scenario: SIGINT shutdown
- **WHEN** 用户按下 Ctrl+C
- **THEN** 系统打印关闭提示，mitmproxy master 调用 `master.shutdown()` 停止接受新连接，等待当前活跃 SSE flow 写入完毕（最多 5 秒），然后以退出码 0 退出

### Requirement: Windows 代理录制路径
proxy interceptor SHALL 在 Windows 下正确写入 raw request/response 日志。

#### Scenario: 默认日志目录
- **WHEN** Windows 用户未指定 `--output`
- **THEN** 系统 SHALL 将 raw request/response 日志写入 `Path.home() / ".ccwhat" / "raw-req-resp"`
- **AND** 路径创建 SHALL 使用平台无关方式

#### Scenario: 自定义输出目录
- **WHEN** Windows 用户指定包含空格或非 ASCII 字符的 `--output`
- **THEN** 代理 addon SHALL 正确接收 `CCWHAT_OUTPUT_DIR`
- **AND** JSONL 日志 SHALL 以 UTF-8 写入

### Requirement: Windows 代理环境变量
proxy interceptor SHALL 在 Windows 下保持代理环境变量和录制过滤规则一致。

#### Scenario: run 命令注入代理环境
- **WHEN** `ccwhat -- codex` 启动目标 agent
- **THEN** 目标进程 SHALL 接收 `HTTP_PROXY` 和 `HTTPS_PROXY`
- **AND** 代理地址 SHALL 指向本次启动或复用的本地代理端口

#### Scenario: 录制过滤配置
- **WHEN** Windows 用户使用 `ccwhat setup` 或自动检测 agent domain
- **THEN** 代理 addon SHALL 接收去重后的 `CCWHAT_RECORD_DOMAINS` 和 `CCWHAT_RECORD_PATHS`
- **AND** 行为 SHALL 与 macOS/Linux 保持一致

