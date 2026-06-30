## Context

当前仓库对 Windows 的支持是不一致的：

- 变更发起时，`README.md` / `README.en.md` 和 `install.sh` 明确写着 Windows 原生环境暂不支持，安装入口只有 Bash/WSL。
- Codex adapter 已经按 `Path.home() / ".codex"` 读取 Windows 上的 Codex session，说明项目已经有 Windows 使用场景。
- 运行链路已有一部分端口 bind probe 和 `WinError 10013` 提示，但只覆盖部分入口，且默认端口仍可能撞上 Windows TCP excluded port range。
- 自动任务切分的规则文件读取需要显式指定 UTF-8，避免 Windows 中文环境按 GBK 读取并触发 `UnicodeDecodeError`。
- CLI 输出、README 文案和部分测试 fixture 包含中文/特殊字符，Windows GBK 控制台可能触发输出编码问题。
- hook command 需要避免只使用 POSIX shell 风格 quoting，Windows 下 Python 路径包含空格时必须可执行。
- CA 证书提示仍偏 macOS/Linux，Windows 信任 mitmproxy CA 的操作路径未成为文档或 CLI 合约。

因此本 change 不应只修一个 bug，而应把 Windows native 定义为一个平台能力：先建立可验证的最低支持范围，再逐项修正安装、端口、编码、路径、子进程和 viewer 行为。

## Goals / Non-Goals

**Goals:**

- Windows native 用户可以不依赖 WSL 完成安装，并能运行 `ccwhat -- codex`、`ccwhat proxy`、`ccwhat discover`、`ccwhat web --agent codex`。
- 所有本地资源读取、配置读取、JSON/TOML/Markdown 读取和 task segmentation 规则读取必须显式使用 UTF-8 或安全降级。
- 端口诊断必须覆盖 Windows excluded port range、普通 listener 占用、viewer 端口占用和自动分配端口。
- Windows 下子进程启动、PATH 查找、环境变量注入和 hook command 必须可测试。
- Windows 用户看到的错误提示应说明下一步行动，而不是只提示 “mitmproxy 未安装” 或 “port free”。
- 文档必须把 Windows 从“不支持”更新为“支持范围清晰、限制明确”的状态。

**Non-Goals:**

- 不要求一次性支持所有 agent 的 Windows 原生完整能力；第一阶段以 Codex Windows 为最低验收目标，Claude/OpenCode Windows 能力按已有 adapter 能力列为后续验证。
- 不要求自动修改系统证书信任或调用管理员权限命令；只提供明确可执行的 Windows CA 指引。
- 不要求默认测试在非 Windows CI 上模拟完整 Windows GUI 或真实 Chrome/Edge 行为。
- 不要求重写 viewer 前端或迁移后端框架；只修复 Windows 平台相关行为。
- 不要求隐藏所有 Windows 环境差异；遇到需要用户手动处理的系统策略时，输出应明确解释。

## Decisions

1. **把 Windows native 支持拆成“平台基础 + 入口验收”。**

   平台基础包括安装、编码、路径、端口、子进程、证书提示；入口验收包括 `run`、`proxy`、`discover`、`web`、task segmentation。这样比在单个命令里打补丁更稳，也能让测试覆盖按层次组织。

2. **显式 UTF-8 是默认策略。**

   项目里所有包内资源、配置、JSONL、OpenSpec/README 相关读取应指定 `encoding="utf-8"`；读取用户外部日志时可以使用 `errors="replace"` 降级。控制台输出不应因为 emoji 或中文导致命令崩溃，必要时避免在 CLI 必经路径输出难编码字符。

3. **端口策略沿用“用户指定优先，必要时自动分配”的最小变更。**

   `ccwhat -- <cli>` 未显式指定 `--port` / `--web-port` 时使用自动分配端口；`ccwhat proxy` 和 `ccwhat web` 保持固定默认入口，同时接入统一 bindability 诊断。这样保留直接启动命令的低冲突体验，也避免改变独立 proxy/web 命令的可预期 URL。

4. **Windows 安装入口应优先使用 Python/pipx/uv 能力，而不是要求 Bash。**

   第一阶段不新增 `install.ps1`，而是在 README 和 `docs/WINDOWS.md` 中提供 PowerShell 可执行的 `uv tool install`、`pipx install` 和 `py -m pip install --user` 路径。由于项目已是 Python 包，不需要引入额外安装器依赖。

5. **hook command 要按目标运行环境生成。**

   `shlex.quote()` 适合 POSIX shell，但 Windows command line 需要不同 quoting。集成层使用小的 command builder：Windows 走 `subprocess.list2cmdline()`，POSIX 走 `shlex.join()`。测试用带空格的 Python 路径覆盖。

6. **CA 证书支持先做提示，不做自动提权安装。**

   自动导入 Windows root store 会涉及管理员权限和安全风险。CLI 应打印 mitmproxy CA 路径和 Windows 可执行步骤，必要时提示重新启动目标 agent。

7. **OpenSpec 范围包含已有窄变更。**

   `handle-windows-excluded-ports` 可以作为实现参考，但本 change 应覆盖更完整的平台适配。实现时可以吸收该变更，避免两个 change 分别修改同一组端口工具造成冲突。

## Risks / Trade-offs

- [Risk] Windows 上不同终端、Python 版本和系统 locale 差异较大。
  Mitigation: 用单元测试覆盖编码和 command builder，用最小手动验收清单覆盖真实 PowerShell。

- [Risk] 改默认端口或自动分配端口可能改变老用户脚本行为。
  Mitigation: 若改默认策略，必须保留显式 `--port` / `--web-port` 行为，并在 release note 中说明；也可以先只增强诊断。

- [Risk] mitmproxy 在 Windows 上的安装、证书和网络策略可能受安全软件影响。
  Mitigation: CLI 不承诺自动修复系统策略，只提供可诊断错误和手动操作路径。

- [Risk] hook command 在不同 agent 中执行方式不同。
  Mitigation: 将 command builder 与 agent-specific 配置写入分离，并为 Codex/Claude/OpenCode 分别增加 fixture 测试。

- [Risk] 已有未完成 Windows 端口变更会和本 change 重叠。
  Mitigation: 实现前先决定是否合并/替代 `handle-windows-excluded-ports`，避免重复 spec 和重复 helper。

## Migration Plan

1. 先修不改变用户行为的基础问题：UTF-8、错误返回、Windows command builder、端口诊断复用。
2. 再补 Windows 安装文档和 `docs/WINDOWS.md` 手动验收清单。
3. 保持独立 proxy/web 命令默认端口不变，`ccwhat -- <cli>` 使用自动分配并保留显式端口覆盖。
4. 保留 macOS/Linux/WSL 现有命令行为，通过现有测试和 targeted tests 验证无回归。

## Open Questions

- 是否要新增 `ccwhat doctor` 或 `ccwhat doctor --windows`，集中检查 mitmdump、证书、端口、Codex 配置和 PATH？
