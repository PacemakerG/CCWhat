## ADDED Requirements

### Requirement: Windows 启动 mitmdump
ccwhat SHALL 在 Windows 原生环境下通过 `mitmdump` CLI 启动本地代理。

#### Scenario: mitmdump 在 PATH 中
- **WHEN** Windows 用户运行 `ccwhat proxy` 或 `ccwhat -- codex`
- **THEN** 系统 SHALL 能从 PATH 找到并启动 `mitmdump`
- **AND** 启动命令 SHALL 使用 Windows 可接受的参数和路径

#### Scenario: mitmdump 未安装
- **WHEN** Windows 用户运行需要代理的命令但 `mitmdump` 不存在
- **THEN** 系统 SHALL 输出 Windows 可用的安装提示
- **AND** 提示不得只包含 Homebrew 命令

### Requirement: Windows 端口可绑定性
ccwhat SHALL 在启动 mitmdump 前验证目标端口可由当前进程绑定。

#### Scenario: Windows excluded port range
- **WHEN** 目标端口没有 listener 但 `bind()` 返回 `WinError 10013`
- **THEN** 系统 SHALL 拒绝启动代理
- **AND** 系统 SHALL 建议用户使用 `--port` 指定其他端口

#### Scenario: 普通 listener 占用
- **WHEN** 目标端口已有 listener
- **THEN** 系统 SHALL 保留现有 ccwhat-managed proxy 复用或非 ccwhat 占用报错语义
- **AND** 系统 SHALL 不把该场景误报为 Windows excluded port range

### Requirement: Windows CA 证书提示
ccwhat SHALL 为 Windows 用户提供 mitmproxy CA 信任提示。

#### Scenario: 代理启动输出证书路径
- **WHEN** Windows 用户启动代理
- **THEN** 系统 SHALL 输出 `mitmproxy-ca-cert.pem` 的路径
- **AND** 文档 SHALL 说明如何在 Windows 中信任该证书或临时只使用 `NODE_EXTRA_CA_CERTS`
