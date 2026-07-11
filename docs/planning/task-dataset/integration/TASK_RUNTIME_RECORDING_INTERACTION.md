# Task Runtime Recording Interaction Design

## 背景

Task Dataset 的最终目标是服务自动归因诊断。为了让诊断结果可信，Dataset 不能主要依赖事后从日志和最终代码中推断，而应该在用户使用 Coding Agent 的过程中实时记录 Task 现场。

本设计聚焦 C 场景：

```text
用户通过 CCWhat 启动 Coding Agent
  -> 用户在运行过程中手动标记 Task 边界
  -> CCWhat 后台记录 Task 前后仓库现场、Agent trace、命令输出、diff 和证据来源
  -> 用户结束 Agent 后，Dataset 已经可用于自动归因诊断
```

这里先只定义用户交互和作用域，不展开 repo snapshot、diff 生成和诊断引擎实现。

## 设计目标

- 保持统一入口：用户仍然通过 `ccwhat -- <coding-agent>` 启动 Agent。
- Task 边界由用户显式标记，CCWhat 不把自动切分当作强证据来源。
- 每个 `ccwhat -- <agent>` 启动出来的 Agent run 都是独立 recording session。
- 默认只记录由当前 CCWhat run 启动的 Agent 进程树，不记录其他终端中直接启动的 Agent。
- 多个终端可以同时运行多个 CCWhat-managed Agent，每个 run 各自拥有独立 Task 状态和 Dataset staging。
- 端口、proxy、recording id 等实现细节默认对用户隐藏。

## 核心用户模型

用户心智应该是：

```text
我用 CCWhat 打开的 Agent，会被 CCWhat 记录。
我没有用 CCWhat 打开的 Agent，不会被这个 run 记录。
我在某个 Agent 界面里标记 Task，只影响这个 Agent run。
```

示例：

```text
Terminal A:
  ccwhat -- opencode
  -> run A
  -> Task 命令控制 run A

Terminal B:
  ccwhat -- codex
  -> run B
  -> Task 命令控制 run B

Terminal C:
  opencode
  -> 不经过 CCWhat
  -> 不参与 CCWhat runtime Dataset
```

这比全局抓包更符合用户直觉，也更适合自动归因诊断。诊断系统需要知道每条证据属于哪个 Task、哪个 Agent run、哪个仓库现场；全局混抓会让证据归属变脏。

## 作用域决策

### 记录作用域

默认记录作用域是：

```text
当前 `ccwhat -- <agent>` 启动出来的 Agent 进程树
```

不默认记录：

- 其他终端中直接启动的 `claude`、`codex`、`opencode`
- 其他用户进程的网络请求
- 没有继承当前 CCWhat run 环境变量的 Agent
- 机器上同类型 Agent 的全局活动

### 并发作用域

CCWhat 应该支持多个 run 并发：

```text
ccwhat -- opencode
ccwhat -- codex
ccwhat -- claude
```

每个 run 都应该有独立的：

- `run_id`
- `agent`
- `project_dir`
- proxy 端口或 proxy session
- active task state
- raw req/resp 输出目录
- Dataset staging 目录
- viewer/session status

不要把 “当前 active task” 做成机器级全局状态。它必须绑定到 run。

## 统一入口

主入口仍然是：

```bash
ccwhat -- <coding-agent> [agent args...]
```

示例：

```bash
ccwhat -- opencode
ccwhat -- codex
ccwhat -- claude
```

启动后，CCWhat 应该创建一个 runtime recording run：

```text
CCWhat recording started
Run       : run-20260622-153011-a1b2c3
Agent     : opencode
Workspace : ~/workspace/project
Task      : none
```

用户不需要理解 proxy 端口。端口可以打印在 debug 信息里，但不应该成为主交互的一部分。

## Task 切分交互

Task 切分是 C 方案里最重要的交互。其他 Dataset 拼装动作都应该由后台完成。

### 推荐主交互：Agent 界面内控制命令

最终体验应该允许用户在当前 Agent 界面中输入 CCWhat 控制命令：

```text
/ccwhat:start 修复 dataset runtime recording
/ccwhat:finish
/ccwhat:abort
/ccwhat:status
/ccwhat:note 这里测试失败了，需要后续诊断关注
```

这些命令从用户视角看是注册进 Agent 界面的 slash command，但第一实现路径应该由 CCWhat wrapper 在输入层拦截，不发送给 Coding Agent，不进入 Agent prompt，也不污染 Agent 上下文。

交互效果：

```text
用户输入:
  /ccwhat:start 修复 dataset runtime recording

CCWhat 回显:
  CCWhat: started task-001
  Snapshot before captured
  Recording trace, commands, file changes, and model traffic
```

```text
用户输入:
  /ccwhat:finish

CCWhat 回显:
  CCWhat: finalized task-001
  Snapshot after captured
  diff.patch generated
  Dataset staging updated
```

这样用户不需要离开当前 Agent 终端，Task 边界也自然落在真实工作流里。

### 旁路交互：CLI 控制当前 run

在没有 PTY wrapper 或 Agent 界面拦截能力之前，可以提供旁路命令：

```bash
ccwhat task start "修复 dataset runtime recording"
ccwhat task finish
ccwhat task abort
ccwhat task status
```

旁路命令必须能定位 run。定位策略可以按优先级：

1. 显式指定 `--run <run-id>`
2. 当前目录下唯一 active run
3. 最近一个 active run
4. 多个候选时要求用户选择或报错

示例：

```bash
ccwhat task start --run run-20260622-153011-a1b2c3 "修复导出"
```

为了避免误操作，旁路命令不应该在多个 active run 存在时静默选择。

### Viewer 辅助交互

Viewer 可以展示和控制当前 run：

```text
Recording
Run: run-20260622-153011-a1b2c3
Agent: opencode
Workspace: ~/workspace/project
Active Task: none

[开始 Task] [完成 Task] [废弃 Task]
```

Viewer 更适合作为控制面板和状态面板，不应该是唯一入口。用户实际 coding 时通常在终端里，Task 切分最好能在终端内完成。

## Task 状态机

底层应该只有一套状态机，CLI、Agent 界面命令和 Viewer 按钮都调用同一套 recording API。

```text
idle
  |
  | task start
  v
recording
  |
  | task finish
  v
finalizing
  |
  | finalize success
  v
idle

recording
  |
  | task abort
  v
idle
```

状态含义：

| 状态 | 含义 |
| --- | --- |
| `idle` | run 正在记录 session，但当前没有 active task |
| `recording` | 当前有 active task，事件和证据写入该 task |
| `finalizing` | 正在保存 after snapshot、diff、索引和 task metadata |

不允许同时存在多个 active task。一个 run 内同一时间只能有一个 Task 正在 recording。

## 命令语义

### `/ccwhat:start <title>`

用户意图：从当前位置开始一个新的诊断 Task。

后台动作：

- 创建 `task_id`
- 保存 instruction/title
- 记录 start time 和 start event cursor
- 记录当前 git commit 和 git status
- 保存 `repo_before.tar.gz`
- 开始把后续 Agent events、commands、model traffic、file evidence 归入该 Task

如果已有 active task，应提示用户先 finish 或 abort。

### `/ccwhat:finish [--status done|failed|blocked] [--note "..."]`

用户意图：当前 Task 已完成，可以封口。

后台动作：

- 记录 end time 和 end event cursor
- 保存当前 git commit 和 git status
- 保存 `repo_after.tar.gz`
- 生成 `diff.patch`
- 归档 commands/test outputs
- 生成 `task_trace.json`
- 生成或更新 `task.json`
- 将 task 标记为 finalized

如果没有 active task，应提示当前没有可完成的 Task。

### `/ccwhat:abort [--reason "..."]`

用户意图：当前 Task 边界标错或本次不想纳入 Dataset。

后台动作：

- 保留 raw recording event
- 将 task 标记为 aborted
- 不作为默认 Dataset task 输出
- 可选保留 partial 证据用于调试

不要静默删除所有证据。失败和中断本身也可能有诊断价值，但默认不进入正式 task 列表。

### `/ccwhat:status`

用户意图：查看当前 run 和 active task。

输出示例：

```text
Run       : run-20260622-153011-a1b2c3
Agent     : opencode
Workspace : ~/workspace/project
Task      : task-001 recording
Started   : 2026-06-22T15:31:12+08:00
Title     : 修复 dataset runtime recording
```

### `/ccwhat:note <text>`

用户意图：给当前 Task 追加人类备注。

后台动作：

- 将 note 写入当前 task 的 `notes.jsonl` 或 task metadata
- 记录 note time、source、raw text
- 不发送给 Coding Agent

备注不是必须证据，但对后续自动归因很有价值。用户可以显式标记“这里开始报错了”“这个测试是关键失败点”等上下文。

## 网络记录交互

现有 `ccwhat -- <agent>` 的网络记录适合保持进程树作用域：

```text
CCWhat run
  -> 启动或分配 proxy
  -> 将 HTTP_PROXY / HTTPS_PROXY 注入 Agent 子进程
  -> 只记录继承这些环境变量的 Agent 网络请求
```

交互设计上不应让用户选择“抓全局”或“抓当前终端”。默认就是当前 CCWhat run。

如果未来支持高级模式，可以另行提供：

```bash
ccwhat proxy --global
```

但这不应该是 runtime Task Dataset 的默认模式。

## Proxy 端口策略

从用户交互角度，端口应该自动管理。

推荐模型：

```text
每个 recording run 一个独立 proxy session
```

优点：

- 多个终端并发时证据天然隔离
- req/resp 可以直接绑定 run_id
- Task 边界不会影响其他 run
- 某个 Agent 崩溃不会污染其他 Agent 的 Dataset
- 后续自动归因不需要猜测请求归属

用户仍然可以通过高级参数指定端口：

```bash
ccwhat --port 7790 -- opencode
```

但默认应自动选择可用端口，不要求用户理解端口冲突。

## 多终端示例

```text
Terminal A
────────────────────────────────────────
$ ccwhat -- opencode
CCWhat recording started: run-A

> /ccwhat:start 修复导出
CCWhat: started task-001

> ...

> /ccwhat:finish
CCWhat: finalized task-001


Terminal B
────────────────────────────────────────
$ ccwhat -- codex
CCWhat recording started: run-B

> /ccwhat:start 重构 adapter
CCWhat: started task-001

> /ccwhat:finish
CCWhat: finalized task-001
```

两个终端里的 `task-001` 可以同名，因为它们属于不同 run。最终 Dataset 中应通过 `run_id`、`session_id` 或 dataset path 隔离。

## 异常交互

### Agent 退出但 Task 未完成

如果 Agent 进程退出时仍有 active task，CCWhat 应提示：

```text
CCWhat: task-001 is still recording.
Finish it now? [Y/n]
```

默认可以 finish，因为用户结束 Agent 通常意味着当前工作告一段落。

### 工作区已 dirty 时开始 Task

不要阻止用户开始，但要提示：

```text
CCWhat: workspace has existing changes.
repo_before will include current dirty state.
```

并在 `task.json` 的 evidence metadata 中记录。

### 多个 active run 时旁路命令无法定位

如果用户执行：

```bash
ccwhat task finish
```

但当前机器上有多个 active run，CLI 应报错并列出候选：

```text
Multiple active CCWhat runs found.
Use --run:
  run-A  opencode  /repo/a
  run-B  codex     /repo/b
```

不要静默选择最近 run。

## 可执行技术方案

### 总体架构

Runtime recording 需要在现有 `ccwhat -- <agent>` 启动链路中增加一层 run controller。

```text
User terminal
  |
  v
ccwhat run controller
  |
  |-- run registry
  |-- auto port allocator
  |-- runtime dataset recorder
  |-- PTY input interceptor
  |
  v
Coding Agent process
```

其中：

- run controller 负责创建 `run_id`、启动 proxy/viewer、管理 Agent 子进程生命周期。
- PTY input interceptor 负责识别 `/ccwhat:*` 命令。
- runtime dataset recorder 负责维护 active task state 和 Dataset staging。
- proxy 继续负责记录模型请求/响应，但只作为证据来源之一，不负责控制命令路由。

### 命令注册策略

目标体验是：`ccwhat -- codex`、`ccwhat -- opencode`、`ccwhat -- claude` 启动后，用户可以在对应 Agent 界面里使用 `/ccwhat:*` 命令。

第一实现路径：

```text
PTY/input 层拦截
```

也就是说，CCWhat 不直接修改 Codex、OpenCode、Claude Code 的内部文件，也不依赖网络抓包识别 slash command。用户输入先进入 CCWhat wrapper：

```text
用户输入 `/ccwhat:start 修复导出`
  -> CCWhat wrapper 识别为控制命令
  -> 调用本 run 的 task_start route
  -> 不转发给 Agent
  -> 不进入 Agent prompt
  -> 不进入 Agent 自身 session log
```

普通输入原样转发：

```text
用户输入 `帮我修复导出`
  -> CCWhat wrapper 不识别为控制命令
  -> 原样转发给 Agent
```

后续增强路径：

- 如果某个 Agent 提供稳定的官方 slash command 或 hook 机制，可以注册同名 `/ccwhat:*` 命令作为 native integration。
- native integration 必须仍然调用同一套 CCWhat run controller route。
- native integration 不应该取代 PTY/input 层方案，因为三类 Agent 的扩展机制和版本稳定性不同。

网络抓包层明确不负责拦截 `/ccwhat:*`：

- 网络层看到命令时通常已经太晚，命令可能已经进入 Agent prompt 或本地日志。
- drop 网络请求会破坏 Agent 交互状态。
- 不同 Agent 请求 schema 不同，网络层做控制路由不稳定。

### Slash Command 契约

正式命令采用短命名：

```text
/ccwhat:start <title>
/ccwhat:finish [--status done|failed|blocked] [--note "..."]
/ccwhat:abort [--reason "..."]
/ccwhat:status
/ccwhat:note <text>
```

解析规则：

- 命令必须以 `/ccwhat:` 开头。
- command name 只接受固定枚举：`start`、`finish`、`abort`、`status`、`note`。
- 未识别的 `/ccwhat:*` 不转发给 Agent，应由 CCWhat 报错，避免用户以为命令已生效。
- 非 `/ccwhat:` 输入全部原样转发给 Agent。
- 第一版可以只支持简单参数解析，不需要复杂 shell quoting。

建议内部 route：

```text
POST /runtime-runs/<run-id>/tasks/start
POST /runtime-runs/<run-id>/tasks/finish
POST /runtime-runs/<run-id>/tasks/abort
GET  /runtime-runs/<run-id>/status
POST /runtime-runs/<run-id>/tasks/note
```

如果第一版不启动 HTTP control server，也可以先做进程内函数调用。route 名称仍建议按上面设计，方便后续 Viewer 和旁路 CLI 复用。

### Run Registry

每次 `ccwhat -- <agent>` 都创建一个独立 run：

```text
~/.ccwhat/runtime-runs/
  run-20260622-153011-a1b2c3/
    run.json
    control.sock
    raw/
    session/
    tasks/
    logs/
```

`run.json` 示例：

```json
{
  "schema_version": "ccwhat-runtime-run-v1",
  "run_id": "run-20260622-153011-a1b2c3",
  "agent": "opencode",
  "workspace": "~/workspace/project",
  "started_at": "2026-06-22T15:30:11+08:00",
  "status": "running",
  "proxy": {
    "port": 7792,
    "pid": 12345
  },
  "viewer": {
    "port": 7793,
    "url": "http://127.0.0.1:7793/claude-log.html"
  },
  "agent_process": {
    "pid": 12346,
    "command": ["opencode"]
  },
  "active_task_id": null
}
```

run registry 的职责：

- 支持旁路 CLI 找到 active run。
- 支持 Viewer 展示当前 run 状态。
- 支持 Agent 崩溃后恢复 partial recording。
- 支持多终端并发，不通过全局变量保存 active task。

### 端口自动分配

当前默认端口是：

```text
proxy: 7788
viewer: 7789
```

Runtime recording 应改为默认自动分配：

```text
proxy port: 自动选择可用端口
viewer port: 自动选择可用端口
```

推荐策略：

```text
1. 如果用户显式传入 --port / --web-port，优先使用显式端口。
2. 如果未传端口，扫描端口池。
3. 找到空闲端口后立即绑定或启动服务，避免竞态。
4. 将最终端口写入 run.json。
5. 将 HTTP_PROXY / HTTPS_PROXY 注入 Agent 子进程。
```

建议端口池：

```text
proxy: 7788-7887
viewer: 7888-7987
```

用户主流程不展示端口，只展示 Viewer URL。调试模式可以展示：

```text
CCWhat recording started
Run       : run-20260622-153011-a1b2c3
Agent     : opencode
Workspace : /repo
Viewer    : http://127.0.0.1:7891/claude-log.html
Task      : none
```

端口 marker 也应从 port-centric 升级为 run-centric：

```text
旧：
  /tmp/ccwhat-proxy-7788.pid
  /tmp/ccwhat-viewer-7789.agent

新：
  ~/.ccwhat/runtime-runs/<run-id>/run.json
  ~/.ccwhat/runtime-runs/<run-id>/control.sock
```

可以保留旧 marker 兼容现有 `ccwhat proxy` 和 `ccwhat web`，但 runtime recording 主链路不应该依赖固定端口 marker。

### Agent 子进程环境

每个 run 启动 Agent 子进程时注入：

```text
HTTP_PROXY=http://127.0.0.1:<proxy-port>
HTTPS_PROXY=http://127.0.0.1:<proxy-port>
NODE_EXTRA_CA_CERTS=<mitmproxy-ca-cert.pem>
CCWHAT_RUN_ID=<run-id>
CCWHAT_RUNTIME_DIR=~/.ccwhat/runtime-runs/<run-id>
```

可选增强：

```text
CCWHAT_CONTROL_SOCK=~/.ccwhat/runtime-runs/<run-id>/control.sock
```

这些环境变量只注入当前 Agent 子进程树。其他终端中直接启动的 Agent 不继承这些变量，因此不会进入当前 run。

### Runtime Dataset Staging

Task recording 不应等到 Agent 退出才一次性生成 Dataset。运行时应持续写 staging：

```text
~/.ccwhat/runtime-runs/<run-id>/
  raw/
    req_resp/
    agent_logs/
  session/
    events.jsonl
    commands.jsonl
  tasks/
    task-001/
      task.json
      task_trace.jsonl
      notes.jsonl
      commands.jsonl
      test_outputs/
      repo_before.tar.gz
      repo_after.tar.gz
      diff.patch
      diagnosis.json
```

`/ccwhat:start` 创建 task 目录并保存 before 现场。

`/ccwhat:finish` finalize task：

- 保存 after 现场
- 生成 diff
- 将 append-only `task_trace.jsonl` 汇总为 `task_trace.json`
- 更新 `task.json`
- 将 task status 改为 finalized

如果进程崩溃，partial 文件仍然保留，后续可以恢复或标记为 incomplete。

### Task State 文件

`task.json` 应记录交互边界和证据质量：

```json
{
  "task_id": "task-001",
  "run_id": "run-20260622-153011-a1b2c3",
  "title": "修复 dataset runtime recording",
  "status": "recording",
  "boundary": {
    "started_at": "2026-06-22T15:31:12+08:00",
    "finished_at": null,
    "start_event_cursor": "session:128",
    "end_event_cursor": null
  },
  "paths": {
    "task_trace": "task_trace.json",
    "repo_before": "repo_before.tar.gz",
    "repo_after": "repo_after.tar.gz",
    "diff": "diff.patch",
    "commands": "commands.jsonl",
    "notes": "notes.jsonl",
    "diagnosis": "diagnosis.json"
  },
  "evidence_availability": {
    "raw_log": true,
    "task_trace": true,
    "repo_before": true,
    "repo_after": false,
    "git_diff": false,
    "command_outputs": true,
    "test_outputs": true
  },
  "evidence_source": {
    "trace": "ccwhat_runtime_trace",
    "repo_before": "ccwhat_runtime_snapshot",
    "repo_after": null,
    "diff": null,
    "command_outputs": "ccwhat_runtime_capture"
  },
  "confidence": "high"
}
```

Task finalize 后更新 `repo_after`、`git_diff` 和 `confidence`。

### Viewer 和旁路 CLI 复用

Viewer 和旁路 CLI 不应该实现第二套 Task 逻辑。

```text
PTY slash command
  -> run controller

ccwhat task start --run <run-id>
  -> same run controller

Viewer [开始 Task]
  -> same run controller
```

这样可以保证：

- 命令行为一致
- 状态机一致
- Dataset staging 一致
- 日志和错误处理一致

### 第一阶段落地边界

第一阶段应先打通：

```text
ccwhat -- <agent>
  -> 创建 run_id
  -> 自动分配 proxy/viewer 端口
  -> 启动 Agent
  -> 支持 /ccwhat:start
  -> 支持 /ccwhat:finish
  -> 生成 task-001/task.json
  -> 保存 repo_before/repo_after/diff.patch
```

第一阶段可以暂缓：

- natural language skill 触发
- 三个 Agent 的 native slash command 文件注册
- Viewer 控制按钮
- 自动诊断执行
- Task merge/split UI

但第一阶段的内部结构必须为这些能力预留 route 和 run registry。

## 非目标

本设计不要求：

- 记录未通过 CCWhat 启动的 Agent
- 全局系统级抓包
- 自动猜测 Task 边界作为强证据
- 强制用户 commit
- 让用户手动选择 proxy 端口
- 在 Task 过程中频繁打断用户确认
- 第一阶段实现自然语言 Skill 触发
- 第一阶段修改三类 Agent 的内部代码或私有配置

## 一句话总结

Runtime Task Dataset 的交互核心是：

```text
`ccwhat -- <agent>` 创建一个独立 recording run；
用户在这个 run 中通过 `/ccwhat:start` 和 `/ccwhat:finish` 手动切分 Task；
CCWhat 只记录这个 run 的 Agent 进程树；
多个终端可以并发运行多个独立 run；
Dataset 后台随 Task 边界自动拼接完成。
```
