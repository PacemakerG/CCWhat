# CCWhat Runtime Dataset 参考

> Runtime Dataset（运行时数据集）是 CCWhat 在记录 AI 编程会话时，按任务边界切分并持久化的结构化证据集合。
> 版本：v2（`ccwhat-runtime-task-v1` schema）

---

## 目录

- [一、概述](#一概述)
- [二、目录结构](#二目录结构)
- [三、文件详解](#三文件详解)
  - [3.1 run.json — Run 元信息](#31-runjson--run-元信息)
  - [3.2 task.json — 任务元信息（核心索引）](#32-taskjson--任务元信息核心索引)
  - [3.3 control_events.jsonl — 控制事件流](#33-controleventsjsonl--控制事件流)
  - [3.4 task_trace.json — Agent 行为轨迹 ★ V2 新增](#34-tasktracejson--agent-行为轨迹--v2-新增)
  - [3.5 repo_before / repo_after.tar.gz — 工作区快照](#35-repo_before--repo_aftertargz--工作区快照)
  - [3.6 diff.patch — 代码变更](#36-diffpatch--代码变更)
- [四、数据流与生命周期](#四数据流与生命周期)
- [五、V1 → V2 演进](#五v1--v2-演进)
- [六、典型使用路径](#六典型使用路径)

---

## 一、概述

**Runtime Dataset** 是 CCWhat Runtime Controller 在每一次 `/ccwhat:start` → `/ccwhat:finish` 周期内产出的数据集合，目的是将 AI 编程会话中的**任务意图**、**Agent 行为**和**代码变更**三者关联起来，形成一个可回放、可诊断、可归因的结构化数据集。

```
┌──────────────────────────────────────────────────────────┐
│                    Runtime Dataset                        │
├─────────────┬─────────────────────┬─────────────────────┤
│  任务意图   │    Agent 行为轨迹    │     代码变更        │
│  task.json  │  task_trace.json    │  repo_before/after  │
│  instruction│  events / commands  │  diff.patch         │
│  git 信息   │  files / changes    │  tar.gz 快照        │
└─────────────┴─────────────────────┴─────────────────────┘
```

---

## 二、目录结构

```
.ccwhat/runtime-runs/
│
├── claude/                            ← 平台：claude / opencode / codex
│   └── run-20260624-130534-2fc651d1/  ← Run 目录（一次 ccwhat --claude 会话）
│       ├── run.json                   ← Run 级别元信息
│       └── tasks/
│           └── task-001/              ← 一次 /ccwhat:start → /ccwhat:finish
│               ├── task.json          ← 任务元信息（核心索引）
│               ├── control_events.jsonl ← 控制事件流
│               ├── task_trace.json    ← Agent 行为轨迹 ★ V2 新增
│               ├── repo_before.tar.gz ← start 时 workspace 的快照
│               ├── repo_after.tar.gz  ← finish 时 workspace 的快照
│               └── diff.patch         ← before → after 的 git diff
│
│           └── task-002/              ← 同 run 内的后续任务（如果有）
│               └── ...
│
└── opencode/
    └── run-20260623-140244-81e29752/
        └── tasks/task-001/
            └── ...
```

### 层级结构解析

```
Run      ─── 一次 ccwhat --claude 会话
 │
 ├── Task-001  ─  /ccwhat:start → /ccwhat:finish
 │    ├── control_events  任务边界锚点（start/finish 时间戳）
 │    ├── task_trace      Agent 行为恢复（中间发生了什么）
 │    └── repo snapshot   代码快照（start 和 finish 各一次）
 │
 └── Task-002  ─  下一次 start → finish（相同 Run 内可多个 task 连续执行）
```

### 命名约定

| 层级 | 命名格式 | 示例 |
|------|---------|------|
| Run 目录 | `run-YYYYMMDD-HHmmss-<random>` | `run-20260624-130534-2fc651d1` |
| Task 目录 | `task-NNN` | `task-001`, `task-002` |
| control_events | `control_events.jsonl` | 不变 |
| task_trace | `task_trace.json` | V2 新增 |

---

## 三、文件详解

### 3.1 `run.json` — Run 元信息

**概述：** Run 启动时创建，记录整条会话的基础配置和状态。

**关键字段：**

| 字段 | 类型 | 必选 | 说明 |
|------|------|:----:|------|
| `schema` | string | ✅ | schema 版本（如 `ccwhat-run-v1`） |
| `run_id` | string | ✅ | 与目录名一致 |
| `platform` | string | ✅ | 平台标识（claude / opencode / codex） |
| `started_at` | string | ✅ | Run 启动时间（UTC ISO8601） |
| `finished_at` | string | ✅ | Run 结束时间 |
| `workspace` | string | ✅ | 被监控的工作区路径 |
| `status` | string | ✅ | `running` / `finished` / `failed` |
| `proxy` | object | ✅ | proxy 配置（端口、output 目录等） |
| `current_task_id` | string | - | 当前活跃 task 的 ID |
| `task_count` | int | ✅ | 本 Run 内已创建的 task 数量 |

---

### 3.2 `task.json` — 任务元信息（核心索引）

**概述：** 每个 task 的入口索引文件。必须先读它才知道有哪些证据文件可看，以及任务的基本属性。

**关键字段：**

| 字段 | 类型 | V2 变化 | 说明 |
|------|------|:-------:|------|
| `schema` | string | - | `ccwhat-runtime-task-v1` |
| `task_id` | string | - | 本 task 的 ID（如 `task-001`） |
| `run_id` | string | - | 所属 Run |
| `title` | string | - | 任务标题（传递给 start 的说明） |
| `status` | string | - | `recording` → `finalized` / `aborted` |
| `started_at` | string | - | 开始时间（UTC ISO8601） |
| `finished_at` | string | - | 结束时间 |
| `workspace` | string | - | workspace 绝对路径 |
| **`instruction`** | string | **★ 新增** | 用户的任务描述（从首条 user_message 提取） |
| **`success_criteria`** | string|null | **★ 新增** | 成功标准（暂未提取时为 null） |
| **`expected_tests`** | string[] | **★ 新增** | 期望的测试命令列表 |
| `git` | object | - | git 版本信息 |
| `git.before_commit` | string | - | start 时的 HEAD commit |
| `git.before_status` | string | - | start 时的 git status 输出 |
| `git.after_commit` | string | - | finish 时的 HEAD commit |
| `git.after_status` | string | - | finish 时的 git status 输出 |
| `paths` | object | - | 关联证据文件的相对路径映射 |
| **`paths.task_trace`** | string | **★ 新增** | `task_trace.json` |
| `evidence_availability` | object | - | 各证据文件是否成功提取 |
| **`evidence_availability.task_trace`** | bool | **★ 新增** | task_trace 提取是否成功 |

**完整示例：**

```json
{
  "schema": "ccwhat-runtime-task-v1",
  "task_id": "task-001",
  "run_id": "run-20260624-130534-2fc651d1",
  "title": "Task1",
  "status": "finalized",
  "started_at": "2026-06-24T13:05:57.464946Z",
  "finished_at": "2026-06-24T13:11:44.805095Z",
  "workspace": "~/workspace/CCWhat",
  "instruction": "hello",
  "success_criteria": null,
  "expected_tests": [],
  "git": {
    "before_commit": "666b1e4e67541c474b506cc4b50e45b088f4d1f8",
    "before_status": "",
    "after_commit": "666b1e4e67541c474b506cc4b50e45b088f4d1f8",
    "after_status": "?? self.docs/"
  },
  "paths": {
    "repo_before": "repo_before.tar.gz",
    "repo_after": "repo_after.tar.gz",
    "diff": "diff.patch",
    "control_events": "control_events.jsonl",
    "task_trace": "task_trace.json"
  },
  "evidence_availability": {
    "repo_before": true,
    "repo_after": true,
    "diff": true,
    "control_events": true,
    "task_trace": true
  }
}
```

---

### 3.3 `control_events.jsonl` — 控制事件流

**格式：** JSONL（每行一个独立 JSON 对象）

**概述：** 记录 task 生命周期中的控制事件（start / finish / abort / note）。这些事件提供了**任务的时间边界**，是切分 session 日志的依据。

**关键字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `timestamp` | string | 事件时间戳（UTC ISO8601） |
| `command` | string | `start` / `finish` / `abort` / `note` |
| `raw_args` | string | 用户输入的命令参数 |
| `agent` | string | `claude` / `opencode` / `codex` |
| `integration` | string | 触发方式（如 `claude_user_prompt_submit`） |
| `model_visible` | bool | start/finish 事件是否对 AI 模型可见 |
| `agent_log_visible` | bool | 是否在 agent 日志中可见 |
| `confidence` | string | `high` / `medium`（事件置信度） |
| `result` | object | 处理结果 |

**完整示例：**

```json
{"timestamp": "2026-06-24T13:05:57.885046Z",
 "command": "start",
 "raw_args": "",
 "agent": "claude",
 "integration": "claude_user_prompt_submit",
 "model_visible": false,
 "agent_log_visible": false,
 "confidence": "high",
 "result": {"task_id": "task-001", "status": "recording"}}

{"timestamp": "2026-06-24T13:11:44.842265Z",
 "command": "finish",
 "raw_args": "",
 "agent": "claude",
 "integration": "claude_user_prompt_submit",
 "model_visible": false,
 "agent_log_visible": false,
 "confidence": "high",
 "result": {"task_id": "task-001", "status": "finalized"}}
```

---

### 3.4 `task_trace.json` — Agent 行为轨迹 ★ V2 新增

**概述：** V2 最重要的新增文件。它从 proxy 记录的完整 session 日志中，按 `control_events` 的 start/finish 时间窗口切出属于本 task 的片段，然后提取成结构化字段。

**顶层字段：**

| 字段 | 类型 | 必选 | 说明 |
|------|------|:----:|------|
| `agent` | string | ✅ | Agent 类型 |
| `task_id` | string | ✅ | 所属 task |
| `run_id` | string | ✅ | 所属 run |
| `first_user_message` | string | ✅ | 用户的第一句话 |
| `time_window` | object | ✅ | 时间边界 |
| `time_window.started_at` | string | ✅ | 任务开始时间 |
| `time_window.finished_at` | string | ✅ | 任务结束时间 |
| `events` | Event[] | ✅ | 完整事件流（见下方） |
| `commands` | string[] | ✅ | 执行过的 shell 命令列表 |
| `test_commands` | string[] | ✅ | 测试命令列表 |
| `files` | object | ✅ | 文件操作记录 |
| `files.read` | string[] | ✅ | 读取过的文件路径列表 |
| `files.changed` | string[] | ✅ | 修改/创建的文件路径列表 |
| `changes` | Change[] | ✅ | 每次实质变更的详情 |
| `patches` | Patch[] | ✅ | git patch（如有） |
| `errors` | string[] | ✅ | 遇到的错误信息 |
| `final_claim` | string|null | ✅ | Agent 对结果的最终总结 |
| `repo_state` | object | ✅ | 代码仓库状态（与 task.json git 字段对齐） |

#### events 事件类型

events 数组中的每条事件包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| `event_id` | string | 唯一事件 ID（如 `main:9`） |
| `source` | string | 事件来源（`main` / agent name） |
| `agent_id` | string | Agent 标识 |
| `turn_index` | int | 对话轮次 |
| `event_type` | string | 事件类型：`user_message` / `assistant_text` / `tool_call` / `tool_result` |
| `text` | string | 消息正文 |
| `tool_name` | string|null | 如果是 tool_call，填工具名（如 `Read`、`Bash`） |
| `tool_use_id` | string|null | 工具调用 ID |
| `files` | string[] | 关联的文件路径 |
| `command` | string|null | 如果是 bash 命令，这里填命令内容 |
| `timestamp` | string | 时间戳 |
| `metadata` | object | 扩展元数据（如 tool_call 的输入参数、tool_result 的输出） |

#### changes 字段结构

```json
{
  "change_id": "change-004",
  "event_id": "main:89",
  "file": "~/workspace/project/slash-commands.md",
  "kind": "write",               // write / edit / command
  "source": "claude_write",
  "old_string": null,
  "new_string": null,
  "content": "文件内容...",
  "patch_id": null,
  "confidence": "medium"
}
```

| 字段 | 说明 |
|------|------|
| `kind` | 变更类型：`write`（写新文件）、`edit`（编辑现有文件）、`command`（执行命令） |
| `source` | 触发方式：`claude_write` / `bash_command` 等 |
| `confidence` | `high` / `medium` / `low`（内容提取置信度） |

---

### 3.5 `repo_before.tar.gz` / `repo_after.tar.gz` — 工作区快照

| 文件 | 时机 | 内容 |
|------|------|------|
| `repo_before.tar.gz` | `/ccwhat:start` 执行时 | workspace 完整 git 工作树 tar 压缩 |
| `repo_after.tar.gz` | `/ccwhat:finish` 执行时 | workspace 完整 git 工作树 tar 压缩 |

**用途：**
- 可以直接解压查看 task 开始前/完成后的代码状态
- 配合 `diff.patch` 做精确的代码变更对比
- 与 `task_trace.json` 的 `files.changed` 交叉验证

---

### 3.6 `diff.patch` — 代码变更

| 情况 | 文件状态 | 说明 |
|:----|:--------:|------|
| 有代码改动 | ✅ 有内容 | `git diff before..after` 标准 patch 格式 |
| 无代码改动 | ⚠️ 空文件（0 bytes） | 仅文档、配置等操作，未修改代码 |

**与 task_trace 的配合：**

```
diff.patch 告诉你  →  代码前后差了什么
task_trace.json   →  Agent 是怎么一步步改成这样的
```

两者结合才能做完整的**归因分析**——不光知道改了什么，还知道为什么改、怎么改的。

---

## 四、数据流与生命周期

```
用户输入 /ccwhat:start
       │
       ▼
Runtime Controller.start_task()
       │
       ├── 创建 task.json（带 started_at、git.before_commit）
       ├── 写入 control_events.jsonl（start 事件）
       └── 打包 repo_before.tar.gz
       │
       ▼
   [Agent 执行任务（中间过程只记 session 日志，不直接写入 task）]
       │
       ▼
用户输入 /ccwhat:finish
       │
       ▼
Runtime Controller.finish_task()
       │
       ├── 打包 repo_after.tar.gz
       ├── 生成 diff.patch
       ├── 写入 control_events.jsonl（finish 事件）
       │
       ├── ★ V2 新增：
       │   ├── 定位 session 日志文件
       │   ├── 按 start/finish 时间窗口切出事件片段
       │   ├── 提取 commands / files / changes / errors 等字段
       │   └── 写入 task_trace.json
       │
       └── 更新 task.json（finished_at、paths、evidence_availability）
```

**关键设计决策：**
- task_trace 在 **finish 时一次性提取**，不做实时流式写入
- session 日志**不存在时降级**（`task_trace: false`），不打断 finish 流程
- 从 `control_events` 的时间戳推断时间窗口，各留 **1 秒 buffer** 消除时钟偏差
- 复用已有的 `extract_evidence` / `extract_change_evidence` 逻辑，不重复实现

---

## 五、V1 → V2 演进

| 维度 | V1 | V2 |
|:----|:--:|:--:|
| schema | `ccwhat-runtime-task-v1` | 同（兼容） |
| task.json | 基础元信息 | + `instruction`、`success_criteria`、`expected_tests` |
| evidence_availability | 4 个字段 | + `task_trace` |
| task_trace.json | ❌ 不存在 | ✅ **新增**（~163KB / ~1200 行） |
| diff.patch | ✅ | ✅（无代码改动时为空） |
| 控制事件完整性 | start / finish | start / finish |
| Agent 行为可见性 | ❌ 黑盒（只知道起止时间） | ✅ **白盒**（完整事件回放） |
| 任务语义 | 仅 title | title + instruction（用户任务描述） |
| 归因能力 | 仅代码级 | 代码级 + 行为级 |

**一句话：V1 只知道"任务什么时候开始结束、代码改了什么"；V2 加上了"Agent 每一步是怎么干的"。**

---

## 六、典型使用路径

### 场景：分析一个 task

```
1. 读 task.json
   → 确定任务时间、git 版本、instruction、有哪些证据文件可用

2. 读 control_events.jsonl
   → 确认任务边界完整、没有 abort

3. 读 task_trace.json
   → 查看 events 回放 Agent 的每一轮对话
   → 查看 commands 知道执行过什么 shell 命令
   → 查看 files.read/changed 知道操作了哪些文件
   → 查看 changes 知道每次实质变更的内容
   → 查看 errors 知道是否遇到过错误

4. 读 diff.patch（有改动时）
   → 对比代码变更

5. 解压 repo_before / repo_after.tar.gz（需要精确还原时）
   → 完整查看 task 前后的代码状态
```

### 关键数据关联图

```
task.json.started_at ────┐
                          ├──► task_trace.json.time_window ──► 切 session 日志
task.json.finished_at ───┘
                               │
                               ▼
                          task_trace.json.events
                          task_trace.json.commands
                          task_trace.json.files
                          task_trace.json.changes
                               │
                               ▼
task.json.git.before_commit ──► diff.patch (before → after)
task.json.git.after_commit  ──► repo_before/after.tar.gz
```
