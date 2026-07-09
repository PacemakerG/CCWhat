## Context

agentlens 通过 mitmproxy 拦截 coding agent 的 HTTPS 流量，录制的 domain 列表由 `~/.agentlens/config.toml` 提供。当前用户必须提前执行 `agentlens setup` 完成配置，否则 `run` 命令会触发交互式向导或直接报错退出。

各主流 coding agent 在固定路径存储自己的 API 配置：

| Agent | 配置文件 | 格式 |
|-------|---------|------|
| opencode | `~/.config/opencode/opencode.jsonc` + `opencode models --verbose` | JSONC + CLI catalog |
| claude | `~/.claude/settings.json` + 当前环境变量 | JSON + env |
| codex | `~/.codex/config.toml` + 当前环境变量 | TOML + env |

agent 名在 `run.py` 中已通过 `infer_agent_from_target()` 推断出来，可直接复用。

## Goals / Non-Goals

**Goals:**
- `agentlens -- opencode` 无需任何前置配置即可录制流量
- 从 agent 配置和 provider catalog 读取**全量** provider baseURL，支持用户中途切换 model/provider 仍能被录制
- `~/.agentlens/config.toml` 中已有的 domain 配置继续生效，并与 agent 配置自动检测结果合并

**Non-Goals:**
- 不支持运行时动态追加新 domain（代理启动后 domain 列表固定）
- 不解析 `--model` 参数做精确 provider 匹配
- 不修改 recorder.py 逻辑
- 不废弃 `agentlens setup` 命令

## Decisions

### 决策一：全量提取所有 provider 的 baseURL，而非按 --model 精确匹配

**选择**：读取 config、provider catalog 和环境变量里所有 provider 的 `baseURL`，全部加入录制 domain。

**理由**：
- 用户在会话中可随时切换 model/provider，精确匹配只能命中启动时的 provider，切换后流量漏录
- domain 列表多几项对 mitmproxy 过滤性能无实质影响
- 实现简单，不需要解析 CLI 参数与 config 做映射

**放弃的方案**：解析 `--model` 参数反查 provider → 复杂且容易漏录

---

### 决策一补充：OpenCode 内置 provider 通过模型 catalog 提取

**选择**：OpenCode 同时读取 `~/.config/opencode/opencode.jsonc` 和 `opencode models --verbose` 输出。

**理由**：
- 用户自定义 provider 的 baseURL 在 `opencode.jsonc`
- OpenCode 内置 provider（如 `opencode/deepseek-v4-flash-free`）不落在用户配置文件里，但 CLI catalog 的 `api.url` 会暴露真实 baseURL
- `/connect` 写入的 `~/.local/share/opencode/auth.json` 只保存凭据，不保存完整 provider baseURL

---

### 决策二：新建独立模块 `agent_config.py`，不在 run.py 内联

**选择**：将各 agent 的配置读取逻辑封装到 `agentlens/agent_config.py`。

**理由**：
- 每个 agent 的解析逻辑不同（JSONC vs JSON vs TOML），集中管理便于后续扩展新 agent
- `run.py` 保持职责单一，只调用 `detect_domains(agent_name) -> list[str]`

---

### 决策三：JSONC 注释剥离用正则，不引入额外依赖

**选择**：用正则去掉 `//` 行注释和 `/* */` 块注释，再交给 `json.loads()`。

**理由**：
- opencode.jsonc 仅含 `//` 行注释，模式简单可控
- 引入 `jsonc-parser` 等第三方库增加依赖成本，不值得

**风险**：字符串中含 `//` 的值会被误删 → 针对 baseURL 字段不会出现此模式，可接受

---

### 决策四：domain 填充合并策略

```
1. 读取 config.toml 的 effective domains（显式 domains + preset 默认 domains）
2. 读取 agent_config.detect_domains(agent_name) 的自动检测结果
3. 将两边结果按顺序去重后传给 recorder
```

`run.py` 每次正常启动都会触发 agent 配置检测；用户已有配置不会被覆盖，而是与自动检测结果同时录制。

## Risks / Trade-offs

**[风险] 配置文件路径在不同平台或安装方式下可能不同**
→ 缓解：用 `Path.home()` 拼接相对路径，覆盖 macOS/Linux 主流安装；路径不存在时静默跳过，不报错

**[风险] opencode.jsonc 格式更新，字段路径变化导致读取失败**
→ 缓解：读取失败时回退到环境变量 `ANTHROPIC_BASE_URL`，再回退到默认值，不影响启动

**[风险] 用户配置了多个 provider 但只有一个有效（其余是废弃的测试配置）**
→ 可接受：多录不漏录，流量不匹配也只是透明转发，不影响用户体验

**[Trade-off] 读取 env var 作为补充来源**
→ Cici Water 等启动器可能通过环境变量注入 baseURL；读取 env 可以覆盖未写入配置文件的运行时网关。
