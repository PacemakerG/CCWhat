## ADDED Requirements

### Requirement: Codex shows CCWhat slash commands
系统 SHALL 在 `ccwhat -- codex` 启动前安装或检查 Codex 的 CCWhat slash command integration，使 CCWhat 命令出现在 Codex 原生 slash 菜单中。

#### Scenario: Codex commands are installed before launch
- **WHEN** 用户执行 `ccwhat -- codex`
- **THEN** 系统 SHALL 检查 Codex CCWhat integration
- **AND** 如果 integration 缺失，系统 SHALL 安装 CCWhat 管理的 prompt 或 skill 文件
- **AND** 如果 integration 已过期，系统 SHALL 升级 CCWhat 管理的文件

#### Scenario: Codex slash menu contains task commands
- **WHEN** Codex 启动并显示原生 slash 菜单
- **THEN** 用户 SHALL 能看到 CCWhat Task 命令
- **AND** 菜单 SHALL 至少包含 start 和 finish 命令

### Requirement: Codex slash commands call local CCWhat controller
系统 SHALL 将 Codex 中触发的 CCWhat slash command 路由到当前 runtime run 的本地 controller。

#### Scenario: Codex start command calls local controller
- **WHEN** 用户在 Codex 中选择 CCWhat start 命令并提供 title
- **THEN** 系统 SHALL 调用当前 run 的 controller start route
- **AND** 系统 SHALL 创建 active task
- **AND** 系统 SHALL 向用户显示 start 成功反馈

#### Scenario: Codex finish command calls local controller
- **WHEN** 用户在 Codex 中选择 CCWhat finish 命令
- **THEN** 系统 SHALL 调用当前 run 的 controller finish route
- **AND** 系统 SHALL finalize active task
- **AND** 系统 SHALL 向用户显示 finish 成功反馈

### Requirement: Codex command is not sent to model
系统 SHALL 阻止 Codex CCWhat Task slash command 作为普通 prompt 发送给模型。

#### Scenario: Codex start command is locally intercepted
- **WHEN** 用户在 Codex 中触发 CCWhat start 命令
- **THEN** 系统 SHALL 在 prompt 被发送给模型前通过 `UserPromptSubmit` 拦截该命令
- **AND** 系统 SHALL 阻止该命令作为用户 prompt 继续处理
- **AND** runtime evidence SHALL 记录 `model_visible` 为 false
- **AND** runtime evidence SHALL 记录 `integration` 为 `codex_user_prompt_submit`

#### Scenario: Codex finish command is locally intercepted
- **WHEN** 用户在 Codex 中触发 CCWhat finish 命令
- **THEN** 系统 SHALL 在 prompt 被发送给模型前通过 `UserPromptSubmit` 拦截该命令
- **AND** 系统 SHALL 阻止该命令作为用户 prompt 继续处理
- **AND** runtime evidence SHALL 记录 `model_visible` 为 false
- **AND** runtime evidence SHALL 记录 `integration` 为 `codex_user_prompt_submit`

### Requirement: Codex integration files are managed safely
系统 SHALL 只自动写入或更新由 CCWhat 管理的 Codex integration 文件。

#### Scenario: Managed Codex files can be upgraded
- **WHEN** Codex integration 文件存在且包含 CCWhat managed marker
- **THEN** 系统 SHALL 可以更新该文件到当前 integration version

#### Scenario: User Codex files are not overwritten
- **WHEN** 目标 prompt、skill 或 hook 文件已存在但不包含 CCWhat managed marker
- **THEN** 系统 SHALL NOT 覆盖该文件
- **AND** 系统 SHALL 返回明确冲突错误

### Requirement: Codex command naming can degrade when colon names are unsupported
系统 SHALL 优先使用 `/ccwhat:start` 和 `/ccwhat:finish` 命名；如果 Codex 不支持冒号命令名，系统 SHALL 使用等价降级命名。

#### Scenario: Codex colon names supported
- **WHEN** Codex 支持冒号命令名
- **THEN** 菜单命令 SHALL 使用 `/ccwhat:start` 和 `/ccwhat:finish`

#### Scenario: Codex colon names unsupported
- **WHEN** Codex 不支持冒号命令名
- **THEN** 菜单命令 SHALL 使用 `/ccwhat-start` 或 `/ccwhat/start` 等价命名
- **AND** 命令描述 SHALL 明确显示 CCWhat Task start/finish 语义
