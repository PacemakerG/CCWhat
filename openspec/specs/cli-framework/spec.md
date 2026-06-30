## Purpose
Define the command-line entry points, subcommand routing, and package installation expectations.
## Requirements
### Requirement: Main CLI entry point
`deep-ai-analysis` 命令 SHALL 通过 Python 包的 `[project.scripts]` 入口点注册，安装后可在系统 PATH 中直接调用。CLI 使用 `click` 框架实现，入口函数为 `deep_ai_analysis.cli:cli`。

#### Scenario: Show help
- **WHEN** 用户执行 `deep-ai-analysis --help`
- **THEN** 系统打印用法说明、可用子命令列表和全局选项，退出码为 0

#### Scenario: Show version
- **WHEN** 用户执行 `deep-ai-analysis --version`
- **THEN** 系统打印当前版本号（与 `pyproject.toml` 中的 `version` 字段一致），退出码为 0

#### Scenario: Unknown subcommand
- **WHEN** 用户执行 `deep-ai-analysis unknowncmd`
- **THEN** 系统打印错误信息提示未知子命令，并展示帮助，退出码为非 0

### Requirement: Subcommand routing
CLI 框架 SHALL 使用 `click.group()` 实现插件式子命令注册，每个子命令在独立模块中定义并通过 `cli.add_command()` 注册。已注册的子命令包括 `proxy`、`start-mc`、`clear-req-resp` 和 `web-server`。

#### Scenario: Subcommand help
- **WHEN** 用户执行 `deep-ai-analysis proxy --help`
- **THEN** 系统打印 proxy 子命令的用法说明、所有选项及默认值，退出码为 0

#### Scenario: No subcommand provided
- **WHEN** 用户执行 `deep-ai-analysis`（不带任何子命令）
- **THEN** 系统打印全局帮助信息，退出码为 0

#### Scenario: start-mc subcommand available
- **WHEN** 用户执行 `deep-ai-analysis --help`
- **THEN** 帮助信息中包含 `start-mc` 子命令及其简要描述

#### Scenario: clear-req-resp subcommand available
- **WHEN** 用户执行 `deep-ai-analysis --help`
- **THEN** 帮助信息中包含 `clear-req-resp` 子命令及其简要描述

#### Scenario: web-server subcommand available
- **WHEN** 用户执行 `deep-ai-analysis --help`
- **THEN** 帮助信息中包含 `web-server` 子命令及其简要描述

### Requirement: Package installable via pip
Python 包 SHALL 通过 `pyproject.toml` 定义，支持 `pip install -e .` 开发安装和 `pip install .` 正式安装。

#### Scenario: Development install
- **WHEN** 用户在项目根目录执行 `pip install -e .`
- **THEN** `deep-ai-analysis` 命令在当前 Python 环境中可用，修改源码立即生效无需重新安装

#### Scenario: Dependency declaration
- **WHEN** 用户在空 Python 环境中执行 `pip install .`
- **THEN** `click` 和 `mitmproxy` 等依赖自动安装，`deep-ai-analysis` 命令可用

### Requirement: Windows 平台入口
ccwhat CLI SHALL 在 Windows 原生环境中提供与 macOS/Linux 一致的命令入口和错误处理。

#### Scenario: Windows 显示帮助和版本
- **WHEN** 用户在 PowerShell 中运行 `ccwhat --help` 或 `ccwhat --version`
- **THEN** CLI SHALL 正常输出帮助或版本
- **AND** 输出不得因为控制台编码失败而崩溃

#### Scenario: Windows 命令不存在
- **WHEN** 用户通过 `ccwhat -- <command>` 启动不存在的目标命令
- **THEN** CLI SHALL 返回 command not found 错误
- **AND** 错误 SHALL 保留目标命令名称和非 0 退出码

### Requirement: Windows 子进程启动
ccwhat CLI SHALL 使用 Windows 可兼容方式启动目标 agent 和内部 helper 进程。

#### Scenario: 目标命令路径包含空格
- **WHEN** 目标 agent 可执行文件或 Python executable 路径包含空格
- **THEN** 系统 SHALL 正确启动进程
- **AND** 不得使用仅适用于 POSIX shell 的 quoting 破坏 Windows 命令

#### Scenario: 环境变量注入
- **WHEN** `ccwhat -- codex` 在 Windows 下启动目标进程
- **THEN** 子进程环境 SHALL 包含 `HTTP_PROXY`、`HTTPS_PROXY` 和 `NODE_EXTRA_CA_CERTS`
- **AND** 这些值 SHALL 使用 Windows 可接受的路径和 localhost URL

### Requirement: Windows-safe OpenCode command files
ccwhat SHALL NOT create or track OpenCode command files whose names are invalid on Windows filesystems.

#### Scenario: OpenCode integration writes task commands
- **WHEN** ccwhat installs OpenCode task boundary commands
- **THEN** generated command filenames SHALL avoid characters that are invalid on Windows, including `:`
- **AND** the runtime plugin SHALL continue to recognize legacy `ccwhat:start` and `ccwhat:finish` command names for macOS/Linux compatibility

### Requirement: Windows 平台诊断
ccwhat CLI SHALL 对 Windows 常见系统限制提供可执行诊断信息。

#### Scenario: 端口被 Windows 系统拒绝绑定
- **WHEN** CLI 遇到 Windows `WinError 10013`
- **THEN** 错误信息 SHALL 提到 Windows TCP excluded port range
- **AND** 错误信息 SHALL 给出 `netsh interface ipv4 show excludedportrange protocol=tcp` 检查命令

