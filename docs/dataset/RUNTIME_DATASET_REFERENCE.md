# CCWhat Task Dataset：运行时与离线切分

> 核心原则：CCWhat 只有一套标准 Task Dataset。运行时切分和离线切分只是两种 Task 边界来源，不是两种 Dataset 格式。

## 1. 两种切分来源

```text
运行时切分：/ccwhat:start → Agent 执行 → /ccwhat:finish
             明确边界 + 隔离 Git Index 记录任务级真实 Diff
                                      │
                                      ├──→ 同一个 Dataset Builder
                                      │
离线切分：历史 Session → 规则/BM25/文件关联度 → 人工修正
             推断或确认边界，无任务开始时的仓库基线
```

两条路径最终都先得到 Task 边界，再将边界内的 Session 事件交给同一个 Dataset Builder。因此，任务输入、事件、命令、文件、测试、错误和最终声明的结构完全一致。

差异只在证据完整度：运行时切分知道任务开始和结束时的仓库状态，可以提供高可信任务级 Git Diff；离线切分没有任务开始时的仓库基线，不能事后伪造同等含义的 Git Diff。

## 2. 统一 Dataset 结构

```text
ccwhat-dataset/
├── manifest.json
├── dataset.jsonl
├── scores.jsonl
├── traces/
│   └── trace-task-001.json
└── diffs/                         # 仅有运行时 Git Diff 时出现
    └── trace-task-001.diff
```

| 文件 | 作用 |
|---|---|
| `manifest.json` | Dataset 版本、生成时间、Agent、Session 和样本数量 |
| `dataset.jsonl` | 一行一个 Task，保存任务输入、预期、边界来源和 Trace 索引 |
| `traces/*.json` | Task 范围内的事件、命令、测试、文件变化、错误和仓库状态 |
| `scores.jsonl` | 评分和诊断结果的扩展入口；当前 v1 可为空 |
| `diffs/*.diff` | 运行时显式切分得到的任务级真实 Git Diff；离线 Dataset 不生成 |

Dataset 的用途不是展示压缩包本身，而是为任务复盘、失败诊断、跨 Agent 评测、回归测试和后续训练数据转换提供统一输入。

## 3. `task_diff` 的统一表达

每个 Trace 都包含同样的 `task_diff` 字段。

运行时切分：

```json
{
  "task_diff": {
    "available": true,
    "source": "isolated_git_index",
    "confidence": "high",
    "path": "diffs/trace-task-001.diff"
  }
}
```

离线切分：

```json
{
  "task_diff": {
    "available": false,
    "source": null,
    "confidence": null,
    "path": null
  }
}
```

离线 Trace 仍可能从 Agent 日志中提取 Edit、Write、Patch 等操作证据，但这些是“日志声明过的修改”，不等价于任务开始到结束之间的仓库真实 Diff。

## 4. `task.json` 和 `task.diff` 的定位

运行时命令先在 `~/.ccwhat/runtime-runs/<agent>/<run-id>/tasks/<task-id>/` 写入：

- `task.json`：内部暂存元数据，记录 Run、Task、Workspace、标题、状态、开始/结束时间和 Git Tree；
- `task.diff`：隔离 Git Index 在 Task 开始和结束之间计算出的仓库 Diff。

这两个文件用于保存运行时边界证据。标准 Dataset 导出时，系统按时间窗口将 Runtime Task 对齐到所选 Session，把 `task.diff` 复制到统一 Dataset 的 `diffs/`，并在 Trace 的 `task_diff` 中建立引用。不要把 `task.json + task.diff` 单独称为最终 Dataset。

运行时导出请求使用 `taskSource = runtimeTasks`，提供 `runId` 和可选 `taskIds`。离线导出继续使用自动切分结果或人工修正后的 Overlay。三种来源最终都进入同一个 Builder 和 Validator。

## 5. 为什么使用隔离 Git Index

运行时开始时，CCWhat 用独立的 `GIT_INDEX_FILE` 记录包含既有未提交修改的任务基线；结束时再次同步工作区并计算两棵 Tree 之间的 Diff。这样可以：

- 不污染用户自己的暂存区；
- 排除任务开始前已经存在的脏改动；
- 捕获 Bash 产生的修改和未跟踪文件；
- 为任务级代码变化提供比日志推断更高可信的仓库证据。

## 6. 面试口径

> 我设计的是一套统一 Task Dataset，两种切分方式只负责提供边界。运行时通过 start/finish 显式记录边界，并用隔离 Git Index 补充任务级真实 Diff；历史 Session 则基于规则、BM25 和文件关联度自动切分，并允许人工修正。两者导出的 Dataset Schema 相同，只是运行时多一份高可信 Git Diff 证据。
