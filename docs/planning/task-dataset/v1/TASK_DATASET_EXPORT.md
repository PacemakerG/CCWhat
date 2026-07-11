# Task Dataset Save and Export — 下一阶段任务规划

## 背景

AgentLens 已经从单纯的 session log viewer，进入了 task trace viewer 阶段：

- 支持 Claude Code / Codex / OpenCode 本地 session 读取。
- 支持自动和手动 Task 切分。
- 支持 Task Trace Overlay 的人工校正。
- 支持从 Task 回看对话、工具调用、文件、命令、错误和 final claim。

下一阶段的重点不是继续美化 detail 页面，也不是马上做失败归因或自动评分，而是把已经切分出来的 Task 固化成可保存、可导出、可被后续 evaluator 消费的数据资产。

目标是新增 **Task Dataset Save and Export**：

```text
当前 session
  -> Task segmentation / Task Trace Overlay
  -> 前端 Tasks 页面保存为 Dataset
  -> ~/.agentlens/datasets/<dataset-id>/
  -> 可选下载 dataset-*.tar.gz
```

这个 Dataset 目录是后续 evaluator、离线分析、失败归因、prompt/workflow 优化和训练数据转换的统一输入。`.tar.gz` 只是分享、迁移和下载格式，不是产品主线本身。

## 产品收口

本阶段只做 **Dataset 保存与导出**，不做 evaluator。

也就是说，本阶段链路是：

```text
Session Log
  -> Task Segmentation / Overlay
  -> Task Dataset Save
  -> optional Task Dataset Export
```

不是：

```text
Session Log
  -> Task Dataset Save
  -> Evaluator
  -> Score
```

Evaluator 和自动评分放到后续阶段。第一阶段只保证 Dataset 格式稳定、证据完整、可保存、可下载、可校验。

## 交互设计

入口放在 Viewer 的 `Tasks` 页面，而不是新增 CLI 主路径。

原因：

- 用户已经在前端完成 session 选择、task segmentation 和人工 overlay 校正。
- AgentLens 已经支持 session 压缩包导出，Task Dataset 可以复用相同的下载心智。
- Task Dataset 是“当前 session 的 task 数据资产”，自然属于 Tasks 页面。
- 后续 evaluator 不应依赖用户手动上传压缩包，而应优先读取本地 Dataset Registry。

### Tasks 页面按钮

在 Tasks 页面右上角增加：

```text
[保存为 Dataset]
```

按钮状态：

| 状态 | 行为 |
| --- | --- |
| 未加载 session | disabled |
| 已加载 session，但没有 task segmentation / overlay | 点击后提示先进行任务切分 |
| 有未保存 Task Trace 编辑 | 点击后提示先保存或撤销编辑 |
| 有 active saved overlay 或 task segmentation result | 允许保存 |

### 保存确认弹窗

点击按钮后打开 modal：

```text
保存 Task Dataset

范围：
- 当前 session 的全部 tasks

包含内容：
[x] manifest.json
[x] dataset.jsonl
[x] traces/*.json
[x] scores.jsonl 空文件
[ ] 包含原始 session log
[ ] 包含 raw req/resp

[取消] [保存 Dataset] [保存并下载 .tar.gz]
```

第一版可以只实现必选项。`include raw` 和 `include req/resp` 可以先作为 disabled 或后续 change。

保存成功后写入本地 Dataset Registry：

```text
~/.agentlens/datasets/
  dataset-<timestamp>-<session-short-id>/
    manifest.json
    dataset.jsonl
    traces/
    scores.jsonl
```

如果用户选择下载，再由浏览器下载：

```text
dataset-<timestamp>-<session-short-id>.tar.gz
```

## Dataset 目录结构

第一版先生成本地 Dataset 目录。下载 `.tar.gz` 时，压缩包内部目录固定为同一结构：

```text
agentlens-dataset/
  manifest.json
  dataset.jsonl
  traces/
    trace-task-001.json
    trace-task-002.json
  scores.jsonl
```

第一版不要拆成大量 `steps.jsonl` / `changes.jsonl` / `messages.jsonl` 文件。保持简单：Dataset、Trace、Score 三层。

### `manifest.json`

记录数据包自身信息：

```json
{
  "schema_version": "agentlens-dataset-v1",
  "created_at": "2026-06-13T12:00:00Z",
  "tool": "agentlens",
  "session": {
    "session_id": "...",
    "agent": "claude | codex | opencode",
    "project_dir": "/path/to/repo"
  },
  "counts": {
    "dataset_items": 3,
    "traces": 3,
    "scores": 0
  }
}
```

### `dataset.jsonl`

一行一个 task，只放任务定义和索引，不放完整执行过程。

```json
{
  "id": "task-001",
  "input": {
    "instruction": "修复 task segmentation 页面空白问题",
    "repo": "AgentLens",
    "base_commit": "abc123"
  },
  "expected": {
    "success_criteria": null,
    "tests": ["pytest tests/test_task_segmentation_frontend.py"]
  },
  "metadata": {
    "agent": "codex",
    "session_id": "...",
    "task_source": "auto | manual | edited",
    "trace_id": "trace-task-001",
    "trace_path": "traces/trace-task-001.json",
    "start_event_id": "main:42",
    "end_event_id": "main:88"
  }
}
```

含义：

```text
Dataset = 要做什么
```

### `traces/*.json`

每个 task 一个 trace JSON，保存 agent 实际执行过程。

```json
{
  "trace_id": "trace-task-001",
  "task_id": "task-001",
  "session_id": "...",
  "agent": "codex",
  "boundary": {
    "start_event_id": "main:42",
    "end_event_id": "main:88",
    "start_turn": 3,
    "end_turn": 7
  },
  "events": [],
  "commands": [],
  "test_commands": [],
  "files": {
    "read": [],
    "changed": []
  },
  "changes": [],
  "patches": [],
  "errors": [],
  "final_claim": null,
  "repo_state": {
    "cwd": "~/workspace/AgentLens",
    "base_commit": "abc123",
    "head_commit": null,
    "git_dirty_at_export": true
  }
}
```

含义：

```text
Trace = 实际怎么做
```

### `scores.jsonl`

第一版生成空文件。

后续 evaluator 可以追加：

```json
{
  "id": "score-001",
  "dataset_item_id": "task-001",
  "trace_id": "trace-task-001",
  "name": "task_success",
  "value": 1,
  "data_type": "BOOLEAN",
  "source": "human | eval | test",
  "comment": "测试通过，页面恢复正常"
}
```

含义：

```text
Score = 做得好不好
```

## Patch / Diff 设计原则

三个 agent 的落盘日志不同，不能把 `patch` 当成公共必填字段。

本机日志和官方资料综合结论：

| Agent | 落盘日志里是否有 patch/diff | AgentLens 第一版处理 |
| --- | --- | --- |
| Claude Code | 没有统一 patch/diff 字段 | 存 `Edit.old_string/new_string`、`Write.content`、`Bash.command` |
| OpenCode | 有 diff/patch 证据 | 存 `edit.metadata.diff/filediff`、`apply_patch.patchText`、`oldString/newString` |
| Codex | 有 `patch_apply_end` 事件 | 存 `changes[path].unified_diff` 或新增文件 `content` |

限制：

- Claude Code 的 `Edit.old_string/new_string` 不是 patch。
- Claude Code 的 `Write.content` 不是 patch。
- OpenCode 的 `apply_patch.patchText` 是 apply_patch 格式，不等同于标准 `git diff`。
- Codex 的 `unified_diff` 通常是 diff hunk，不一定带完整 `diff --git` header。
- 如果任何 agent 用 Bash / shell 脚本改文件，而日志里没有后续 `git diff` 或 patch 事件，就只记录 command，不强行生成 patch。

### `changes`

`changes` 记录“改动证据”：

```json
{
  "change_id": "change-001",
  "event_id": "main:51",
  "file": "viewer/claude-log.html",
  "kind": "edit | write | patch | command | git_diff",
  "source": "claude_edit | opencode_edit | opencode_patch | codex_patch_apply_end | bash_command | export_git_diff",
  "old_string": null,
  "new_string": null,
  "content": null,
  "patch_id": "patch-001",
  "confidence": "high | medium | low"
}
```

### `patches`

`patches` 只存真实存在或确定性派生的 diff/patch：

```json
{
  "patch_id": "patch-001",
  "scope": "step | task",
  "file": "viewer/claude-log.html",
  "source": "codex_patch_apply_end",
  "format": "unified_diff | apply_patch | git_diff | opencode_diff",
  "confidence": "high | medium",
  "patch": "@@ -10,7 +10,7 @@\n-old\n+new\n"
}
```

规则：

```text
原生日志 patch/diff -> confidence: high
old_string/new_string 确定性派生 -> confidence: medium
Bash 命令但没有 diff -> 不生成 patch
LLM 猜测 -> 禁止
```

## 后端 API

新增：

```http
POST /api/save-task-dataset
Content-Type: application/json
```

请求：

```json
{
  "sessionId": "...",
  "taskSource": "activeOverlay | taskSegments",
  "download": false,
  "includeRawSession": false,
  "includeReqResp": false
}
```

保存响应：

```json
{
  "ok": true,
  "datasetId": "dataset-20260613-aabb1122",
  "datasetPath": "~/.agentlens/datasets/dataset-20260613-aabb1122",
  "downloadUrl": "/api/task-datasets/dataset-20260613-aabb1122/download"
}
```

下载响应：

```text
200 OK
Content-Type: application/gzip
Content-Disposition: attachment; filename="dataset-20260613-aabb1122.tar.gz"
```

失败：

| 场景 | HTTP |
| --- | --- |
| session 不存在 | 404 |
| session 尚未切分 task | 400 |
| active overlay 未保存或无效 | 400 |
| 保存或打包内部错误 | 500 |

## 不做什么

本阶段明确不做：

- 不做自动 evaluator。
- 不自动给 task 打分。
- 不做失败归因。
- 不做 repo 全量快照。
- 不强行生成 patch。
- 不把所有 step 拆成很多独立小文件。
- 不把 Dataset 保存/导出做成 CLI 主入口。
- 不要求 Dataset 可完整复现 repo 环境。

## 验收标准

本阶段完成时应满足：

1. 用户在 Tasks 页面完成切分后，可以点击“保存为 Dataset”。
2. 后端将 Dataset 保存到 `~/.agentlens/datasets/<dataset-id>/`。
3. 用户可以选择下载 `.tar.gz`。
4. Dataset 目录或包内包含 `manifest.json`、`dataset.jsonl`、`traces/*.json`、`scores.jsonl`。
5. 每个 task 对应 `dataset.jsonl` 一行和一个 trace JSON。
6. trace 包含 events、commands、test commands、files、changes、patches、errors、final claim。
7. Claude Code / OpenCode / Codex 三个 agent 都能生成 Dataset。
8. patch/diff 有就保存，没有就为空，不硬编。
9. 提供 validator 测试 Dataset 目录、tar 包结构和 JSON schema。
10. 不引入 evaluator 或自动 score。

## 建议拆分的 OpenSpec Changes

### Change 1: `add-task-dataset-core`

目标：定义 Dataset 数据契约，并从 Task Segmentation / Overlay 构建基础 Dataset 内容。

范围：

- 定义 `manifest.json`、`dataset.jsonl`、`traces/*.json`、`scores.jsonl` schema。
- 新增 Python 数据模型或 typed dict。
- 新增 builder 模块，例如 `agentlens/task_dataset/`。
- 输入：normalized session + task segments / active overlay。
- 输出：内存态 Dataset 文件集合。
- 生成 `dataset.jsonl`、每个 `traces/*.json` 和空 `scores.jsonl`。
- trace 包含 events、commands、test commands、files、errors、final claim。
- 新增 validator，能校验 Dataset 目录或 tar 包。
- 加 schema、builder、validator 单元测试。

不做：

- 不接 viewer 下载。
- 不解析 agent 特定 patch/diff。
- 不做 evaluator。

验收：

- 给定一个最小 Dataset fixture，validator 通过。
- 缺少必需文件或 JSONL 格式错误时，validator 报清晰错误。
- Claude / OpenCode / Codex 的 fixture session 都能生成 Dataset。
- 每个 task 都有 dataset item 和 trace。
- task 边界只包含该 task 范围内 events。

### Change 2: `extract-dataset-change-evidence`

目标：把三家 agent 的文件改动证据统一进 `changes` / `patches`。

范围：

- Claude Code：抽取 `Edit.old_string/new_string`、`Write.content`、`Bash.command`。
- OpenCode：抽取 `edit.oldString/newString`、`metadata.diff/filediff`、`patch` part / `apply_patch.patchText`。
- Codex：抽取 `patch_apply_end.changes[path].unified_diff/content`。
- 为每条 evidence 标注 `source`、`kind`、`confidence`。
- 保留无 patch 的 command evidence，不硬生成 patch。

不做：

- 不用 LLM 猜 patch。
- 不做 repo 现场 `git diff`。
- 不做 before/after 文件快照。

验收：

- 三家 agent fixture 覆盖各自关键字段。
- Codex `patch_apply_end` 能生成 patch entry。
- Claude `Edit` 生成 change entry，但 patch 可为空。
- Bash-only 改动只生成 command/change evidence，不生成 patch。

### Change 3: `save-and-export-task-dataset-from-viewer`

目标：在 Tasks 页面提供“保存为 Dataset”，并支持可选下载 `.tar.gz`。

范围：

- 新增 `POST /api/save-task-dataset`。
- 新增本地 Dataset Registry 目录：`~/.agentlens/datasets/`。
- 复用现有 tar.gz 打包工具风格。
- 前端 Tasks 页面新增“保存为 Dataset”按钮。
- 新增保存确认 modal。
- 保存成功后显示 dataset id / path。
- 支持“保存并下载 .tar.gz”，浏览器下载 `dataset-*.tar.gz`。
- 处理未加载 session、未切分 task、未保存 overlay、保存失败、打包失败等状态。

不做：

- 不做 evaluator。
- 不做 raw session / req-resp 勾选项，或者先显示 disabled。
- 不做 CLI 主入口。

验收：

- 已切分 session 可保存到 `~/.agentlens/datasets/<dataset-id>/`。
- 保存后的 Dataset 目录符合 validator。
- 可选下载的 tar.gz 结构符合 validator。
- 未切分时有明确提示。
- 未保存 overlay 时阻止导出。

## 后续 Changes

以下能力不属于本次三阶段改造，可后续单独开 change：

- `include-raw-sources-in-dataset-export`：可选包含原始 session log 和 req/resp。
- `evaluate-dataset-scores`：读取 Dataset，运行 evaluator，写入 `scores.jsonl`。

## 本次推荐执行顺序

```text
1. add-task-dataset-core
2. extract-dataset-change-evidence
3. save-and-export-task-dataset-from-viewer
```

本阶段只做到这 3 个 change。raw sources 和 evaluator 都是后续增强。

## 实现交接：`save-and-export-task-dataset-from-viewer`

Viewer server 新增 `POST /api/save-task-dataset`，请求必须包含 `sessionId`、`taskSource`、完整 `source.payload`、`source.provenance`、版本信息和 `sourceTrace`。`activeOverlay` source 使用 `overlayVersion = task-trace-overlay-v1`，`taskSegments` source 使用 `sourceSchemaVersion = task-segmentation-v1`。响应为 `{ ok, datasetId, datasetPath, downloadUrl }`，其中 `downloadUrl` 指向 `/api/task-datasets/<dataset-id>/download`。

后端保存到默认 registry `~/.agentlens/datasets/<dataset-id>/`，`datasetId` 使用 `dataset-YYYYMMDD-HHMMSS-<session-short-id>`，同秒冲突时追加数字 suffix。保存流程以请求 payload 为主数据源，server cache 只用于加载当前 session 并校验 normalized event boundary/source trace 对齐；缺 provenance、session 不一致、overlay version 不支持、dirty/未保存 overlay 或 task boundary 无法对齐都会返回 400。Dataset 写入后必须通过 Dataset validator，失败返回 500，不报告保存成功。

下载 handler 只接受合法 dataset id，读取 registry 下对应目录，打包为 `dataset-*.tar.gz`，包内根目录固定 `agentlens-dataset/`，仅包含 `manifest.json`、`dataset.jsonl`、`traces/*.json`、`scores.jsonl`，并在返回前通过 Dataset validator 校验。

Tasks 页面新增“保存为 Dataset”入口和确认 modal。modal 只展示当前 session 全部 tasks、task 数量和 Dataset v1 必选文件；第一版完全隐藏 raw session / raw req-resp 选项。前端优先发送 saved Task Trace Overlay；没有 saved overlay 时发送 task segmentation result；dirty overlay 会阻止保存并提示先保存或撤销编辑。API 收到 `includeRawSession=true` 或 `includeReqResp=true` 时返回 400，不会 warning 后继续保存。
