## Context

Plan 1 已经实现 `ccwhat -- claude` 的 runtime recording MVP：每次启动创建 runtime run，自动分配 proxy/viewer/control 端口，Claude slash command 通过本地 hook 调用 runtime controller，并生成 `task.json`、`control_events.jsonl`、repo before/after snapshot 和 `diff.patch`。

Codex 是 Plan 2 的第一条扩展链路。根据官方文档和本地调研，Codex 支持 custom prompts/skills 进入 slash 菜单，也支持 `UserPromptSubmit` hook 在 prompt 发送给模型前运行并 block。因此 Codex 可以采用和 Claude 类似的 marker command + local hook 方案。

当前实现里 runtime controller、task staging、port allocation 和 run registry 已经是 agent-neutral 的，主要缺口是 Codex integration installer、Codex hook entry point，以及 `ccwhat -- codex` 的 runtime wiring。

## Goals / Non-Goals

**Goals:**

- `ccwhat -- codex` 创建独立 runtime run，并复用现有 runtime staging 输出。
- Codex 原生 slash 菜单中出现 CCWhat Task 命令，至少包含 start 和 finish。
- 当前 Codex CLI 不加载自定义 slash 菜单时，提供短文本 hook 兜底入口。
- Codex CCWhat 命令触发后调用当前 run 的 localhost runtime controller。
- Codex hook 在 `UserPromptSubmit` 阶段 block CCWhat marker prompt，避免发送给模型。
- control evidence 写入 `integration=codex_user_prompt_submit`、`model_visible=false`、`confidence=high`。
- 所有 Codex integration 文件使用 CCWhat managed marker，遇到非 CCWhat 同名文件不得覆盖。
- 增加自动化测试和手工验收说明，让用户可以启动 Codex 后做菜单和 Dataset staging 验收。

**Non-Goals:**

- 不实现 OpenCode 正式适配。
- 不实现 `ccwhat integrations doctor/install/uninstall` 完整 CLI。
- 不升级 Dataset v2 schema。
- 不实现自动归因诊断。
- 不实现自然语言 skill 触发。
- 不修改 Codex 全局 `config.toml`；source-command skill 写入当前 workspace，custom prompt 仅作为兼容文件写入 Codex home 的 `prompts/` 目录。

## Decisions

### Decision: Codex 使用 workspace source-command skill + 项目级 UserPromptSubmit hook

Codex 的 source-command skill 使用和 OpenSpec `/opsx:*` 一致的命名方式：`.agents/skills/source-command-ccwhat-start/SKILL.md` 对应 `/ccwhat:start`，`.agents/skills/source-command-ccwhat-finish/SKILL.md` 对应 `/ccwhat:finish`。

Command 文件只负责让 CCWhat 命令出现在原生 slash 菜单中，并展开成稳定 marker：

```text
CCWHAT_COMMAND=start
CCWHAT_ARGS=$ARGUMENTS
```

真实逻辑由 Codex hook 完成。Hook 读取 stdin 事件，解析 marker，调用 runtime controller，并返回 block payload。

备选方案是让 command 直接提示模型“调用 CCWhat”，但这会污染上下文，也无法保证 Task 边界证据的强度。

### Decision: Codex 菜单不可用时使用短文本 hook 兜底

当前 Codex CLI `v0.140.0-alpha.2` 可以加载并激活 `UserPromptSubmit` hook，但一级 slash 菜单只显示内建命令，未显示 CCWhat 自定义命令。因此 MVP 增加短文本入口：

```text
ccwhat start
ccwhat finish
```

这些文本不是 slash command，不依赖菜单注册。它们会在 `UserPromptSubmit` 阶段被同一个 Codex hook 解析、调用 runtime controller，并返回 block，避免发送给模型。Start 不接收用户参数；runtime staging 按顺序自动生成 `Task1`、`Task2`。Evidence 仍记录 `integration=codex_user_prompt_submit`、`model_visible=false`、`confidence=high`。

### Decision: 复用 runtime controller，不新增 Codex 专用控制通道

Codex hook 通过 `CCWHAT_RUNTIME_CONTROL_PORT` 和 `CCWHAT_RUNTIME_TOKEN` 调用现有 localhost HTTP controller。这样 Codex 与 Claude 共享 task state machine、snapshot/diff 和 evidence 逻辑。

备选方案是让 hook 直接写 staging 文件。该方案会复制状态机和 git snapshot 逻辑，后续多 Agent 维护成本更高。

### Decision: 新增 Codex integration 模块，不提前抽象通用 installer framework

本 change 只实现 Codex 竖切。Claude 和 Codex 的文件布局、settings 格式、hook 配置都不同，过早抽象会让实现变重。先保持 `claude_integration.py` 与 `codex_integration.py` 并列，后续 doctor/install CLI 再抽公共接口。

### Decision: 第一版使用 workspace source-command、项目级 hook，并保留 prompt 兼容文件

本地实测表明当前 Codex CLI 未稳定展示 `~/.codex/prompts/*.md` 为 slash 菜单项，而项目内已经验证过 `/opsx:*` 通过 `.agents/skills/source-command-opsx-*` 进入菜单。因此 Codex MVP 的主路径改为写入当前 workspace 的 `.agents/skills/source-command-ccwhat-*`。

Prompt 文件仍写入 `~/.codex/prompts/` 或测试注入的 Codex home，作为后续版本兼容和排查线索。Hook 配置写入当前 workspace 的 `.codex/hooks.json`，避免修改用户全局 `config.toml`。

这样 start/finish 菜单项能被 Codex 原生 slash 菜单发现，同时 hook 仍与当前项目 run 绑定，避免多个 workspace 之间共享 active task。

### Decision: Codex evidence 先标记 high confidence，agent_log_visible 保留实测字段

Hook 能 block prompt 发送模型时，`model_visible=false`、`confidence=high`。如果手工验收发现 Codex transcript 仍记录 blocked prompt，则 `agent_log_visible` 应按实测改为 true，但不影响 model-visible 的强证据判断。

## Risks / Trade-offs

- Codex source-command 命名决定菜单命名，当前目标是显示 `/ccwhat:start`、`/ccwhat:finish`；如果 Codex CLI 未来调整 source-command 规则，需要跟随 OpenSpec 命令的最新生成方式更新。
- 当前 Codex CLI 不展示自定义菜单 → 短文本兜底会牺牲菜单发现性，但仍保持本地拦截、模型不可见和 Dataset 证据链路可用。
- Block 后 Codex transcript 可能仍保留 marker prompt → evidence 中保留 `agent_log_visible` 字段，手工验收后按真实行为修正。
- `~/.codex/prompts/*.md` 在当前版本未出现在菜单 → 不再作为主注册路径，只保留兼容文件。
- 与用户已有 `.agents`、`.codex` 或 prompt 文件冲突 → 只覆盖包含 CCWhat managed marker 的文件，非托管文件直接报错。
- 本 change 不做通用 integration CLI → 用户主要通过 `ccwhat -- codex` 自动 ensure，doctor/uninstall 放到后续生产化 change。

## Migration Plan

本 change 不迁移已有 runtime Dataset，也不影响 `ccwhat -- claude`。用户升级后，在 Codex 项目目录执行 `ccwhat -- codex` 会写入 CCWhat-managed source-command skill、兼容 prompt 文件和项目 `.codex/hooks.json`。回滚时删除这些 managed 文件即可；实现必须只自动更新带 managed marker 的文件。

## Open Questions

- Codex `UserPromptSubmit` block 后是否完全不进入本地 transcript？
- Codex slash 菜单是否原生显示 `/ccwhat:start`，需要手工验收确认。
