## Why

Plan 1 已经用 Claude Code 跑通 runtime Task recording 闭环，但自动归因诊断需要 Dataset 能覆盖多类 Coding Agent。Codex 已具备原生 slash/custom prompt 和 `UserPromptSubmit` hook 能力，适合作为第二条强证据竖切链路。

## What Changes

- 为 `ccwhat -- codex` 创建独立 runtime run，并复用现有 proxy/viewer/control 端口自动分配逻辑。
- 新增 Codex CCWhat command/prompt 文件生成，使 CCWhat start/finish 等命令出现在 Codex 原生 slash 菜单中。
- 新增 Codex `UserPromptSubmit` hook，捕获 CCWhat marker prompt 后调用本地 runtime controller。
- Codex hook 成功处理 CCWhat 命令后 SHALL block 原 prompt，避免发送给模型。
- Codex control evidence SHALL 标记 `integration=codex_user_prompt_submit`、`model_visible=false`、`confidence=high`。
- 增加 Codex integration 文件生成、冲突检测、hook 调用和 `ccwhat -- codex` wiring 测试。
- 增加 Codex runtime MVP 手工验收说明，指导用户确认 slash 菜单和 staging 输出。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `agent-slash-integration`: 增加 Codex 原生 slash 菜单、Codex hook 路由、本地 block 和安全管理要求。
- `runtime-task-recording`: 将 runtime run、端口分配和 control evidence 从 Claude-only 扩展到 Codex。

## Impact

- CLI 启动链路：`ccwhat.cli`、`ccwhat.commands.run`。
- Runtime integration：新增 Codex command/hook installer 与 Codex hook entry point。
- Runtime evidence：新增 Codex-specific integration 名称和 model visibility 记录。
- 本地配置写入：项目级 Codex prompt/hook 配置文件，带 CCWhat managed marker 和冲突检测。
- 测试：新增 Codex integration、hook、controller staging 和 CLI wiring 覆盖。
