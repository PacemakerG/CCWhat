## ADDED Requirements

### Requirement: Windows 原生支持范围
ccwhat SHALL 将 Windows 原生环境定义为受支持平台，并明确最低支持入口包括安装、代理启动、自动发现、viewer 启动、Codex session 浏览、自动任务切分和 Dataset 保存导出。

#### Scenario: Windows 原生最低支持入口
- **WHEN** 用户在 Windows PowerShell 中安装并运行 ccwhat
- **THEN** 系统 SHALL 支持 `ccwhat -- codex`、`ccwhat proxy`、`ccwhat discover` 和 `ccwhat web --agent codex`
- **AND** 文档 SHALL 明确 Windows 原生支持范围和已知限制

#### Scenario: 非最低支持范围
- **WHEN** Windows 用户使用尚未验证的 agent 或系统功能
- **THEN** 系统 SHALL 给出明确限制或诊断提示
- **AND** 不得继续声明整个 Windows 原生环境“暂不支持”

### Requirement: Windows 安装入口
ccwhat SHALL 提供不依赖 Bash/WSL 的 Windows 安装路径。

#### Scenario: PowerShell 安装说明
- **WHEN** 用户阅读 Windows 安装文档
- **THEN** 文档 SHALL 提供 PowerShell 可执行的安装命令
- **AND** 文档 SHALL 说明 Python 版本、`mitmproxy`、PATH 和验证命令

#### Scenario: Bash installer 保持原用途
- **WHEN** 用户在 macOS、Linux 或 WSL 中使用 `install.sh`
- **THEN** 现有 Bash installer 行为 SHALL 保持可用
- **AND** Windows 原生用户 SHALL 被引导到 Windows 安装路径

### Requirement: Windows 编码安全
ccwhat SHALL 在 Windows 默认 GBK locale 下避免因读取 UTF-8 资源或输出中文/特殊字符导致命令崩溃。

#### Scenario: 读取包内 UTF-8 资源
- **WHEN** 系统读取包内 JSON、Markdown、HTML、TOML 或任务切分规则文件
- **THEN** 系统 SHALL 显式使用 UTF-8 解码

#### Scenario: 控制台输出包含非 ASCII 文本
- **WHEN** CLI 在 Windows 控制台输出中文或特殊字符
- **THEN** 系统 SHALL 避免抛出 `UnicodeEncodeError`
- **AND** 输出失败不得中断主要业务流程

### Requirement: Windows 路径和目录约定
ccwhat SHALL 在 Windows 下使用 `pathlib` 和平台目录约定处理配置、日志、导入导出和 agent session 路径。

#### Scenario: 默认用户目录
- **WHEN** Windows 用户运行 ccwhat
- **THEN** 系统 SHALL 正确解析 `Path.home()` 下的 `.ccwhat`、`.codex` 和 `.mitmproxy` 路径
- **AND** 路径中包含空格或非 ASCII 字符时不得破坏命令启动

#### Scenario: Downloads 目录不可用
- **WHEN** Windows 用户的 `~/Downloads` 不存在或不可写
- **THEN** 导入导出功能 SHALL 给出明确错误或使用文档化的替代路径

### Requirement: Windows 验收清单
ccwhat SHALL 为 Windows 原生支持提供最小验收清单。

#### Scenario: Windows 手动验收
- **WHEN** 维护者准备发布 Windows 原生支持
- **THEN** 验收清单 SHALL 覆盖安装、`gh` 无关 CLI 运行、端口诊断、Codex session 浏览、自动任务切分、Dataset 保存导出和代理录制
- **AND** 清单 SHALL 说明哪些步骤需要用户手动信任 mitmproxy CA
