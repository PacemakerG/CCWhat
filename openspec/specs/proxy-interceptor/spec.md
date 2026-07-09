## MODIFIED Requirements

### Requirement: Domain filtering
录制 domain 列表 SHALL 合并以下来源并去重：
1. `~/.ccwhat/config.toml` 中已有的有效 domain（包括 `[recording] domains` 和 preset 展开的默认 domain）
2. `agent_config.detect_domains(agent_name)` 自动从目标 agent 配置文件、provider catalog 和环境变量提取的 domain（无需 setup）

若合并后仍为空，则 domain 列表为空，`run` 命令打印提示但仍启动代理（仅透明转发，不录制）。

仅匹配 domain 列表中的请求被录制，不在列表中的流量被代理但不记录。

#### Scenario: config.toml 已配置 domain，同时合并 agent 配置 domain
- **WHEN** `~/.ccwhat/config.toml` 含 `domains = ["mcli.sankuai.com"]`，用户执行 `ccwhat -- opencode`
- **AND** `~/.config/opencode/opencode.jsonc` 含 provider baseURL `https://aigc.sankuai.com/v1/openai/native`
- **THEN** ccwhat 同时录制 `mcli.sankuai.com` 和 `aigc.sankuai.com` 的流量

#### Scenario: config.toml 无 domain，自动从 opencode 配置读取
- **WHEN** `~/.ccwhat/config.toml` 不存在或 `domains` 为空，`~/.config/opencode/opencode.jsonc` 含 provider baseURL `https://aigc.sankuai.com/v1/openai/native`
- **THEN** ccwhat 自动使用 `aigc.sankuai.com` 作为录制 domain，启动代理并开始录制，无需用户执行 `ccwhat setup`

#### Scenario: opencode 配置多个 provider，全量录制
- **WHEN** opencode 配置了两个 provider，baseURL 分别指向 `a.example.com` 和 `b.example.com`，用户在会话中切换 model
- **THEN** 两个 domain 的流量均被录制，切换前后的请求均不遗漏

#### Scenario: opencode 内置 provider 全量录制
- **WHEN** 用户选择 OpenCode 内置 provider，例如 `providerID=opencode`
- **AND** `opencode models --verbose` 暴露 `api.url = "https://opencode.ai/zen/v1"`
- **THEN** ccwhat 将 `opencode.ai` 加入录制 domain，内置 provider 请求不会因不在 `opencode.jsonc` 中而漏录

#### Scenario: claude 自定义网关自动检测
- **WHEN** `~/.ccwhat/config.toml` 无 domain 配置，`~/.claude/settings.json` 含 `env.ANTHROPIC_BASE_URL = "https://mcli.sankuai.com"`
- **THEN** ccwhat 自动使用 `mcli.sankuai.com` 作为录制 domain

#### Scenario: 无自定义配置，回退默认 domain
- **WHEN** config.toml 无配置，agent 配置文件中也无自定义 baseURL
- **THEN** 使用该 agent 类型的默认 domain（claude → `api.anthropic.com`，codex → `api.openai.com`，opencode → `opencode.ai`）

#### Scenario: Non-matching domain not recorded
- **WHEN** 经过代理的请求目标域名不在录制 domain 列表中
- **THEN** 该请求被正常代理转发，不生成任何日志记录

#### Scenario: Multiple configured domains
- **WHEN** 录制 domain 列表含多个 domain（`["aigc.sankuai.com", "api.anthropic.com"]`）
- **THEN** 所有列出 domain 的请求/响应均被录制
