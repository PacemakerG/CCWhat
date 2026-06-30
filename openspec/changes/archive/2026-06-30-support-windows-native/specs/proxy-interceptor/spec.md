## ADDED Requirements

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
