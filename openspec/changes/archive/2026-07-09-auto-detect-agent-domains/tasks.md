## 1. 新建 agent_config 模块

- [x] 1.1 新建 `agentlens/agent_config.py`，定义 `detect_domains(agent_name: str) -> list[str]` 公共接口
- [x] 1.2 实现 JSONC 注释剥离函数 `_strip_jsonc_comments(text: str) -> str`（正则剥离 `//` 行注释和 `/* */` 块注释）
- [x] 1.3 实现 `_detect_opencode_domains() -> list[str]`：读取 `~/.config/opencode/opencode.jsonc` 的自定义 provider baseURL，并合并 `opencode models --verbose` 暴露的内置 provider `api.url`
- [x] 1.4 实现 `_detect_claude_domains() -> list[str]`：读取 `~/.claude/settings.json` 和当前环境中的 `ANTHROPIC_*_BASE_URL`，无此字段时返回 `["api.anthropic.com"]`
- [x] 1.5 实现 `_detect_codex_domains() -> list[str]`：读取 `~/.codex/config.toml` 的 `openai_base_url`、`chatgpt_base_url`、`model_providers.*.base_url`、`shell_environment_policy.set` 中所有 `*_BASE_URL` 字段，无匹配时返回 `["api.openai.com"]`
- [x] 1.6 在 `detect_domains` 中按 agent_name 分发到对应函数，未知 agent 返回 `[]`，所有 host 去重后返回

## 2. 修改 run.py 接入自动检测

- [x] 2.1 在 `run.py` 中，每次正常启动都调用 `agent_config.detect_domains(agent_name)`，并与 config.toml 的有效 domain 去重合并
- [x] 2.2 自动检测到 domain 时，打印提示行（如 `Auto-detected domains: aigc.sankuai.com`）告知用户当前录制目标
- [x] 2.3 自动检测结果同样传入 `effective_paths`：opencode/claude 默认补充 `/v1/messages`，codex 补充 `/v1/responses`（仅在 path 列表为空时）

## 3. 单元测试

- [x] 3.1 新建 `tests/test_agent_config.py`，使用 `tmp_path` fixture 模拟各 agent 配置文件，测试 opencode 单/多 provider 提取、配置缺失回退
- [x] 3.2 补充 claude 和 codex 的配置读取测试，覆盖「有自定义 URL」和「无自定义 URL」两个分支
- [x] 3.3 测试 JSONC 注释剥离：含 `//` 行注释、含 `/* */` 块注释、两者混合的输入均能正确解析
- [x] 3.4 测试 `detect_domains("unknown-agent")` 返回空列表
- [x] 3.5 测试 OpenCode 内置 provider catalog、Codex provider table 和 Claude env baseURL 均会进入检测结果

## 4. 验收验证

- [ ] 4.1 删除（或备份）`~/.agentlens/config.toml`，执行 `agentlens -- opencode`，确认控制台打印自动检测的 domain 且不触发 setup wizard
- [ ] 4.2 与 opencode 对话后，确认 `~/.agentlens/raw-req-resp/` 下有 JSONL 文件落盘
- [ ] 4.3 恢复 `config.toml`，确认手动配置与自动检测 domain 会同时进入录制列表
