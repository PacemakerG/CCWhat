# OpenCode Hooks 参考

## 一、OpenCode 配置体系

OpenCode 使用以下配置路径：

```
~/.local/share/opencode/opencode.db  # SQLite 数据库（会话存储）
~/.config/opencode/                   # 用户配置目录（OpenCode 1.17.x）
~/.config/opencode/package.json       # Plugin 依赖
```

### Plugin 系统

OpenCode 有官方 Plugin SDK：`@opencode-ai/plugin`

```json
// ~/.opencode/package.json
{
  "dependencies": {
    "@opencode-ai/plugin": "1.15.5"
  }
}
```

## 二、Hook 支持现状

### 当前结论：OpenCode 支持项目级 command + plugin before hook

OpenCode 1.17.9 支持项目级 command 和自动发现项目级 plugin：

```
.opencode/command/<name>.md
.opencode/plugin/<name>.js
```

`opencode debug config` 已验证项目级 CCWhat 文件会合并进运行配置：

```json
{
  "plugin": ["file:///.../.opencode/plugin/ccwhat-runtime.js"],
  "command": {
    "ccwhat-start": { "description": "CCWhat Task start" },
    "ccwhat-finish": { "description": "CCWhat Task finish" }
  }
}
```

Plugin SDK 提供 `command.execute.before` hook。CCWhat MVP 使用该 hook 调用 runtime controller。实测 OpenCode 仍会把 command prompt 发送给模型，因此 OpenCode 适配采用“本地记录 + 模型可见安全提示”的降级路径：命令 prompt 要求模型只回复“收到”，不探索文件、不解释 CCWhat。

### OpenCode 架构

```
OpenCode App (Electron)
├── Core Engine
├── Plugin System (@opencode-ai/plugin)
├── Tool Registry
└── Session Manager (SQLite)
```

### Plugin 能力矩阵（待验证）

| 能力 | 是否支持 | 验证状态 |
|------|----------|----------|
| 注册自定义命令 | ✅ 支持 | `.opencode/command/*.md` 已验证 |
| 拦截 command 执行 | ✅ 支持 | `command.execute.before` 已验证配置面 |
| cancel/prevent 默认 prompt | ❌ 未通过 | 实测 prompt 仍进入模型 |
| 修改模型响应 | 待验证 | ❓ |
| 访问会话数据 | ✅ 支持 | 通过 SQLite |

## 三、CCWhat 集成路径评估

### 方案对比

| 方案 | 可行性 | 复杂度 | 备注 |
|------|--------|--------|------|
| A. 开发 OpenCode Plugin | ✅ 可行 | 中 | 已确认 command before hook |
| B. MCP Server 集成 | ✅ 可行 | 中 | OpenCode 支持 MCP |
| C. 外部 Wrapper | ✅ 可行 | 中 | 类似 Codex |
| D. 手动命令触发 | ✅ 可行 | 低 | 降级方案 |

### 推荐方案：项目级 command + plugin before hook

CCWhat 生成：

```text
.opencode/command/ccwhat-start.md
.opencode/command/ccwhat-finish.md
.opencode/plugin/ccwhat-runtime.js
```

用户在 OpenCode 中触发：

```text
/ccwhat-start
/ccwhat-finish
```

plugin 读取 `CCWHAT_RUNTIME_CONTROL_PORT` 和 `CCWHAT_RUNTIME_TOKEN`，调用本地 runtime controller。命令 prompt 允许进入模型，但只包含 task boundary marker 和“只回复收到”的约束。

为兼容 macOS/Linux 上已有的历史命令，plugin 仍识别 `/ccwhat:start` 和 `/ccwhat:finish`；但仓库和新生成文件使用横杠命名，避免 Windows 文件系统不支持冒号路径。

### 降级标记

```json
{
  "model_visible": true,
  "agent_log_visible": true,
  "confidence": "medium",
  "integration": "opencode_command_execute_before"
}
```

## 四、Spike 任务：验证 OpenCode Plugin 能力

在正式开发前，建议进行以下验证：

```bash
# 1. 检查 OpenCode Plugin API 文档
npm show @opencode-ai/plugin

# 2. 查看 OpenCode 安装目录结构
ls -la /Applications/OpenCode.app/Contents/Resources/

# 3. 检查是否有 plugin/hook 配置项
strings /Applications/OpenCode.app/Contents/Resources/app.asar | grep -i "hook\|plugin" | head -20
```

## 五、OpenCode 特有考量

### 多 Agent 支持

OpenCode 支持多个内置 Agent（通过 `agent` 字段区分）：

```json
{
  "opencodeAgent": "default",
  "agent": "opencode"
}
```

CCWhat 集成需要兼容不同 Agent 的行为差异。

### SQLite 数据库结构

OpenCode 将会话数据存储在 SQLite 中，表结构：

```sql
-- 主要表
session      -- 会话信息
message      -- 消息
part         -- 消息分段
project      -- 项目
```

CCWhat 可以通过监听数据库变化或轮询来检测命令。

## 六、相关文件

- 适配器实现：`ccwhat/adapters/opencode.py`
- 数据库路径：`~/.local/share/opencode/opencode.db`
