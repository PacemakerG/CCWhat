## 1. Windows 问题基线确认

- [x] 1.1 复核当前 Windows 原生失败点：`install.sh` 不支持、默认端口可能不可绑定、`task_segment_rules.json` GBK 解码失败、hook command quoting、CA 证书提示偏 macOS/Linux。
- [x] 1.2 决定是否吸收或替代 `handle-windows-excluded-ports` change，避免端口诊断实现重复。
- [x] 1.3 明确第一阶段支持矩阵：Windows native + Codex 为必须支持，Claude/OpenCode Windows 能力标注为已知限制或后续验证。

## 2. 编码和资源读取

- [x] 2.1 修复 `ccwhat/task_segments/rules.py`，读取包内规则文件时显式使用 UTF-8。
- [x] 2.2 审核包内 `read_text()` / `open()` 调用，补齐缺失的 `encoding="utf-8"` 或 `errors="replace"`。
- [x] 2.3 为 Windows GBK locale 下的任务切分规则读取增加单元测试。
- [x] 2.4 避免 CLI 必经路径输出导致 `UnicodeEncodeError`，必要时调整输出文本或输出 helper。

## 3. 端口和代理启动

- [x] 3.1 统一端口 bindability helper，覆盖普通 listener、Windows `WinError 10013` 和其他 `OSError`。
- [x] 3.2 将统一端口诊断接入 `ccwhat -- <cli>`、`ccwhat proxy`、`ccwhat discover` 和 `ccwhat web`。
- [x] 3.3 决定并实现默认端口策略：保持固定默认并增强诊断，或将未显式指定端口改为自动分配。
- [x] 3.4 更新 mitmdump 未安装提示，提供 Windows 可用安装命令，不只提示 Homebrew。
- [x] 3.5 为端口诊断和代理启动路径补充单元测试。

## 4. Windows 子进程和 Hook 命令

- [x] 4.1 增加平台感知 command builder，Windows 下正确处理 Python executable 和路径中的空格。
- [x] 4.2 更新 Codex/Claude/OpenCode runtime integration 中的 hook command 生成逻辑。
- [x] 4.3 为 Windows command quoting 增加 fixture 测试，包括带空格路径。
- [x] 4.4 验证 `HTTP_PROXY`、`HTTPS_PROXY`、`NODE_EXTRA_CA_CERTS` 在 Windows 子进程中正确注入。

## 5. Viewer 和任务切分前端

- [x] 5.1 确保 `ccwhat web --agent codex` 在 Windows 下正确列出 `%USERPROFILE%\.codex\sessions`。
- [x] 5.2 `/api/task-segments` 捕获后端异常并返回 JSON 错误，避免 HTTP 连接中断。
- [x] 5.3 修改自动切分前端流程，在请求成功前保留已有 manual/edited overlay，失败时恢复旧 task 列表。
- [x] 5.4 为自动切分失败不清空手动 overlay 增加 DOM 或静态回归测试。

## 6. Windows 安装和文档

- [x] 6.1 新增 Windows 原生安装说明，覆盖 Python、pipx/uv/pip、mitmproxy、PATH、验证命令。
- [x] 6.2 如采用脚本安装，新增 `install.ps1` 或等价 PowerShell 安装入口。
- [x] 6.3 更新 `README.md` 和 `README.en.md`，将 Windows 从“不支持”改为“支持范围和限制明确”。
- [x] 6.4 增加 Windows CA 证书信任说明，明确自动信任不属于默认行为。

## 7. 验证

- [x] 7.1 运行与本 change 直接相关的 Python 单元测试：run/proxy/discover/web/task segmentation/runtime integration。
- [x] 7.2 在 Windows PowerShell 中执行最小手动验收：安装、`ccwhat --version`、`ccwhat -- codex`、`ccwhat web --agent codex`、自动任务切分。
- [x] 7.3 记录无法自动化验证的 Windows 手动步骤和剩余风险。
