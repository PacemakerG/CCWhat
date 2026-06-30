## ADDED Requirements

### Requirement: Windows viewer 启动
session viewer SHALL 在 Windows 原生环境下启动并打开本地浏览器。

#### Scenario: 启动 Codex viewer
- **WHEN** Windows 用户运行 `ccwhat web --agent codex`
- **THEN** viewer SHALL 绑定可用本地端口
- **AND** `/api/projects` SHALL 返回 Windows Codex session 项目

#### Scenario: viewer 端口不可绑定
- **WHEN** viewer 端口位于 Windows excluded port range 或被系统拒绝绑定
- **THEN** 系统 SHALL 输出 `--web-port` 换端口建议
- **AND** 不得只显示“Viewer may already be running”

### Requirement: Windows viewer API 错误
session viewer SHALL 对 Windows 平台错误返回 JSON 错误，而不是中断 HTTP 连接。

#### Scenario: task segmentation 后端异常
- **WHEN** `/api/task-segments` 在 Windows 下遇到资源读取或编码异常
- **THEN** API SHALL 返回包含 `ok: false` 和 `error` 的 JSON 响应
- **AND** 前端 SHALL 显示可读错误而不是静默失败

### Requirement: Windows Codex session 路径
session viewer SHALL 正确读取 Windows Codex session 和 metadata。

#### Scenario: Codex session 位于用户目录
- **WHEN** Codex session 存在于 `%USERPROFILE%\.codex\sessions`
- **THEN** Codex adapter SHALL 在 viewer 中列出这些 session
- **AND** session title、timestamp、cwd 和 events SHALL 正常展示
