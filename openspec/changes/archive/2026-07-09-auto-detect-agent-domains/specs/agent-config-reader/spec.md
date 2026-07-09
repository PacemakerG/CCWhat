## ADDED Requirements

### Requirement: 从 agent 配置文件自动提取录制 domain
`agent_config` 模块 SHALL 提供 `detect_domains(agent_name: str) -> list[str]` 函数，根据 agent 名称读取其在 `Path.home()` 下固定路径的配置文件、运行时 provider catalog 或相关环境变量，提取所有 API provider 的 baseURL host，返回去重后的 domain 列表。当配置文件不存在或解析失败时，SHALL 静默返回该 agent 类型对应的默认 domain，不抛出异常、不打印错误。

#### Scenario: opencode 单 provider 配置
- **WHEN** `~/.config/opencode/opencode.jsonc` 存在，且含单个 provider，`options.baseURL` 为 `https://aigc.sankuai.com/v1/openai/native`
- **THEN** `detect_domains("opencode")` 返回 `["aigc.sankuai.com"]`

#### Scenario: opencode 多 provider 配置
- **WHEN** `~/.config/opencode/opencode.jsonc` 中配置了两个 provider，`baseURL` 分别为 `https://a.example.com/v1` 和 `https://b.example.com/api`
- **THEN** `detect_domains("opencode")` 返回包含 `"a.example.com"` 和 `"b.example.com"` 的列表

#### Scenario: opencode 配置文件不存在
- **WHEN** `~/.config/opencode/opencode.jsonc` 不存在
- **THEN** `detect_domains("opencode")` 返回内置 provider catalog 中的 domain；若 catalog 不可用则返回 `["opencode.ai"]`，不报错

#### Scenario: opencode 配置文件解析失败
- **WHEN** `~/.config/opencode/opencode.jsonc` 存在但内容无法解析
- **THEN** `detect_domains("opencode")` 返回内置 provider catalog 中的 domain；若 catalog 不可用则返回 `["opencode.ai"]`，不抛出异常

#### Scenario: opencode 内置 provider catalog
- **WHEN** `opencode models --verbose` 输出中存在模型 `api.url = "https://opencode.ai/zen/v1"`
- **THEN** `detect_domains("opencode")` 返回包含 `"opencode.ai"` 的列表

#### Scenario: claude 配置了自定义 ANTHROPIC_BASE_URL
- **WHEN** `~/.claude/settings.json` 存在，`env.ANTHROPIC_BASE_URL` 为 `https://mcli.sankuai.com`
- **THEN** `detect_domains("claude")` 返回 `["mcli.sankuai.com"]`

#### Scenario: claude 未配置自定义 base URL
- **WHEN** `~/.claude/settings.json` 存在但不含 `env.ANTHROPIC_BASE_URL` 字段
- **THEN** `detect_domains("claude")` 返回 `["api.anthropic.com"]`

#### Scenario: codex 配置了自定义 BASE_URL
- **WHEN** `~/.codex/config.toml` 的 `[shell_environment_policy.set]` 节中含有值为 `https://gateway.example.com` 的 `*_BASE_URL` 字段
- **THEN** `detect_domains("codex")` 返回 `["gateway.example.com"]`

#### Scenario: codex 配置了 model provider base_url
- **WHEN** `~/.codex/config.toml` 中含 `[model_providers.portkey] base_url = "https://portkey.example.com/v1"`
- **THEN** `detect_domains("codex")` 返回包含 `"portkey.example.com"` 的列表

#### Scenario: codex 配置了内置 OpenAI provider base URL override
- **WHEN** `~/.codex/config.toml` 中含 `openai_base_url = "https://us.api.openai.com/v1"`
- **THEN** `detect_domains("codex")` 返回包含 `"us.api.openai.com"` 的列表

#### Scenario: codex 使用官方 API
- **WHEN** `~/.codex/config.toml` 的 `[shell_environment_policy.set]` 中无 `*_BASE_URL` 字段
- **THEN** `detect_domains("codex")` 返回 `["api.openai.com"]`

#### Scenario: 未知 agent 名
- **WHEN** 调用 `detect_domains("unknown-agent")`
- **THEN** 返回空列表 `[]`，不报错

### Requirement: JSONC 注释剥离
`agent_config` 模块 SHALL 在解析 `.jsonc` 文件前剥离行注释（`//` 至行尾）和块注释（`/* ... */`），再交由标准 `json.loads()` 解析，无需引入额外依赖。

#### Scenario: 含行注释的 JSONC 解析成功
- **WHEN** 文件内容包含 `// 注释文字` 形式的行注释
- **THEN** 剥离注释后正常解析为 Python dict，注释内容不出现在结果中

#### Scenario: 含块注释的 JSONC 解析成功
- **WHEN** 文件内容包含 `/* 块注释 */` 形式的块注释
- **THEN** 剥离注释后正常解析，不影响实际 JSON 字段
