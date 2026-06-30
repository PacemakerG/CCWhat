## Why

ccwhat 此前文档声明“Windows 原生环境暂不支持”，但代码已经开始覆盖 Codex Windows 会话、端口诊断和本地 viewer 等路径，实际状态变成“部分能用、部分隐性失败”。需要一次系统性的 Windows native 适配设计，把安装、启动、代理、证书、路径、编码和 viewer 功能纳入同一套可验证标准。

## What Changes

- 明确 Windows native 作为受支持平台，定义最低支持范围：安装、`ccwhat -- <cli>`、`ccwhat proxy`、`ccwhat discover`、`ccwhat web --agent codex`、Session 查看、自动任务切分、Dataset 保存/导出。
- 增加 Windows 安装入口和文档，避免用户只能使用 Bash/WSL installer。
- 统一端口可绑定性诊断和端口选择策略，覆盖 Windows TCP excluded port range、普通 listener 占用、viewer 端口冲突。
- 统一 UTF-8 文件读写和控制台输出策略，避免 GBK 环境下的 `UnicodeDecodeError` / `UnicodeEncodeError`。
- 审核并修正 Windows 路径、可执行文件查找、子进程启动、hook command quoting、CA 证书提示和 Downloads/AppData 目录使用。
- 为 Windows native 关键路径补充单元测试和可在 Windows 上执行的最小验收清单。

## Capabilities

### New Capabilities

- `windows-native-support`: 定义 ccwhat 在 Windows 原生环境下的安装、运行、诊断、编码、路径和验收行为。

### Modified Capabilities

- `cli-framework`: Windows native 平台支持、错误输出和命令入口行为需要成为 CLI 合约的一部分。
- `mitmproxy-cli-launch`: 代理启动、端口绑定、子进程启动和 CA 证书提示需要支持 Windows。
- `proxy-interceptor`: Windows 下代理录制路径和 mitmproxy 环境变量注入需要保持一致。
- `session-viewer`: Windows 下 viewer 启动、浏览器打开、Codex 项目路径和 API 错误返回需要明确。
- `task-segmentation`: 自动切分必须在 Windows 默认编码环境下正常读取规则资源，并在失败时不破坏已有 task overlay。

## Impact

- 影响 CLI 和运行链路：`ccwhat/cli.py`、`ccwhat/commands/run.py`、`ccwhat/commands/proxy.py`、`ccwhat/commands/discover.py`、`ccwhat/commands/web_server.py`、`ccwhat/runtime/ports.py`。
- 影响 Windows 安装和文档：新增 Windows 安装脚本或安装说明，更新 `README.md` / `README.en.md`。
- 影响资源读取和任务切分：`ccwhat/task_segments/rules.py`、`viewer/claude-log.html`、`viewer/server.py`。
- 影响 agent 集成和路径处理：`ccwhat/runtime/*_integration.py`、`ccwhat/adapters/codex.py`、`ccwhat/agent_config.py`。
- 影响测试：新增 Windows 行为单测，扩展现有 run/proxy/discover/viewer/task segmentation 测试；不引入重型 GUI 自动验收作为默认测试要求。
