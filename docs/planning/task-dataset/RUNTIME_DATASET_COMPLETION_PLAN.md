# Runtime Dataset Completion Plan

## 目标

CCWhat 的最终目标是支持自动归因诊断。为此，Task Dataset 必须从"事后日志导出"升级为"运行时 Task 现场包"。

最终链路：

```text
ccwhat -- <agent>
  -> 启动 Coding Agent
  -> 原生 slash 菜单出现 CCWhat 命令
  -> 用户用 /ccwhat:start 和 /ccwhat:finish 手动切 Task
  -> CCWhat 后台记录 repo_before、repo_after、diff、trace、commands、test outputs
  -> Dataset 落盘为可复盘、可诊断、可评测的 Task 现场包
  -> 自动归因诊断消费 Dataset 并生成 diagnosis.json
```

本文档只定义后续 OpenSpec change 的总体切分。原则是：

- 子计划尽量少。
- 每个子计划里的 change 尽量少。
- 每个 change 都必须能独立验收。
- 不做 A/B 场景的事后推断主线，优先 C 场景运行时强证据。

## 总体切分（当前状态）

```text
Plan 1: Runtime Recording MVP
  Change 1: add-runtime-task-recording-mvp          ✅ 已完成并归档

Plan 2: Multi-Agent Slash Integration
  Change 2: add-codex-runtime-slash-integration     ⚠️  部分完成，暂停
  Change 3: add-opencode-runtime-command-integration ⚠️  部分完成，暂停
  Change 4: investigate-opencode-local-intercept     🚫 取消，不再推进

Plan 2.5: Dataset V2 Enrichment（新增）
  Change 5: enrich-runtime-task-trace               ✅ 已完成

Plan 2.6: Runtime Dataset Slim & Incremental Diff（新增）
  Change 6: slim-runtime-dataset-core               🔲 阶段一：删除废弃文件
  Change 7: add-incremental-diff-tracking           🔲 阶段二：增量 diff 基础设施
  Change 8: integrate-diff-with-hooks               🔲 阶段三：Hook 集成与条件激活
  Change 9: task-trace-always-persist               🔲 阶段四：task_trace 始终写入

Plan 3: Auto Attribution Diagnosis（下一阶段）
  Change 10: add-auto-attribution-diagnosis         🔲 待开始
```

---

## Plan 1: Runtime Recording MVP ✅

### Change 1: `add-runtime-task-recording-mvp` [已完成并归档]

**结果**：Claude Code 完全跑通。

打通的完整链路：

```text
ccwhat -- claude
  -> 创建 runtime run，自动分配端口
  -> 安装 Claude Code slash command integration
  -> /ccwhat:start 从原生菜单触发，本地 controller 拦截，不发给模型
  -> 保存 repo_before.tar.gz
  -> /ccwhat:finish 从原生菜单触发
  -> 保存 repo_after.tar.gz + diff.patch
  -> 写 task.json / control_events.jsonl
```

落盘结构：

```text
~/.ccwhat/runtime-runs/claude/<run-id>/
  run.json
  tasks/task-001/
    task.json                 (task_id, status, git before/after, paths, evidence_availability)
    control_events.jsonl      (model_visible=false, confidence=high)
    repo_before.tar.gz
    repo_after.tar.gz
    diff.patch
```

---

## Plan 2: Multi-Agent Slash Integration ⚠️

### 现状与决策

Plan 2 已部分实现，但主动选择暂停，优先推进归因诊断主线。

| Agent | 实现状态 | 已知问题 | 决策 |
|-------|---------|---------|------|
| Claude Code | ✅ 完全跑通 | 无 | 主线继续 |
| Codex | ⚠️ 部分完成 | slash command 不出现在菜单 | 暂停，不再投入 |
| OpenCode | ⚠️ 部分完成 | slash 可见但 model_visible=true；对话框有红色 UI 问题 | 暂停，不再投入 |

**判断依据**：Codex 和 OpenCode 的 slash 适配是"更多 agent 可以产数据"，而归因诊断是"数据转化为洞察"。Claude Code 已经能稳定产出完整 Dataset，足以支撑 Plan 3 的诊断引擎建设。等诊断引擎成熟后再回头补 agent 适配，届时有更强的动力和验收标准。

### Change 2: `add-codex-runtime-slash-integration` [暂停]

已完成的部分：
- `.codex/hooks.json` 已写入，hook 注册成功
- `ccwhat/runtime/codex_integration.py` + `codex_hook.py` 实现完整

未解决的问题：
- Codex slash command 不出现在菜单（命名格式或目录结构与 Codex 预期不符，原因未查明）

### Change 3: `add-opencode-runtime-command-integration` [暂停]

已完成的部分：
- `.opencode/command/ccwhat-start.md` + `ccwhat-finish.md` 写入
- `.opencode/plugin/ccwhat-runtime.js` 写入
- slash command 在 OpenCode 菜单中可见

未解决的问题：
- 命令触发后 model_visible=true（OpenCode 架构限制，command prompt 会发给模型）
- 对话框中显示红色渲染问题（原因未查明）

### Change 4: `investigate-opencode-local-intercept` [取消]

结论：当前阶段不具备技术条件做到 OpenCode 的真正本地拦截，且收益不足以覆盖调研成本。取消。

---

## Plan 2.5: Dataset V2 Enrichment ✅

本 plan 不在原始计划中，是在推进过程中发现的关键缺口后补充的。

### 背景：V1 vs V2 数据集对比

Runtime Staging（V2，新版）相比 Dataset v1（旧版）的本质区别：

| 维度 | V1（旧版，viewer 导出） | V2（新版，Runtime Staging） |
|------|----------------------|--------------------------|
| 任务边界 | 算法推断，不可靠 | 用户显式标定，可靠 |
| 真实改动证据 | ❌ 只有 Agent 自报 old/new_string | ✅ git diff + before/after 快照 |
| Agent 行为轨迹 | ✅ 完整 events、commands、errors | ❌ 完全没有 |
| 文件内容快照 | ❌ 只有路径 | ✅ 完整 tar.gz |

**关键缺口**：V2 知道代码改了什么，但不知道 Agent 是怎么改的。做归因诊断两类证据缺一不可。

### Change 5: `enrich-runtime-task-trace` [已完成]

**目标**：在 `/ccwhat:finish` 时，从 proxy session 日志按任务时间边界提取 Agent 行为轨迹，写成 `task_trace.json`，放入 task 目录，补齐 V2 缺口。

**新增文件**：

- `ccwhat/runtime/trace_extractor.py`：按时间窗口从 Claude 原生 session JSONL 提取事件，复用 `extract_evidence` + `extract_change_evidence`

**task 目录变化**：

```text
tasks/task-001/
  task.json                 新增: instruction, success_criteria, expected_tests
                            新增: paths.task_trace, evidence_availability.task_trace
  task_trace.json           ← 新文件
    {
      task_id, run_id, agent,
      time_window: {started_at, finished_at},
      events[],
      commands[], test_commands[],
      files: {read[], changed[]},
      changes[], patches[],
      errors[],
      final_claim,
      first_user_message,
      repo_state: {cwd, base_commit, head_commit}
    }
  control_events.jsonl
  repo_before.tar.gz
  repo_after.tar.gz
  diff.patch
```

**降级策略**：session 日志不存在时 `evidence_availability.task_trace=false`，不中断 finish 流程。

**完成后 V2 Dataset 具备的能力**：

```text
✅ 真实 git diff（代码改了什么）
✅ 完整 repo 快照（before/after）
✅ 可靠任务边界（用户标定）
✅ Agent 行为轨迹（events、commands、errors、final_claim）
✅ 任务语义（instruction、expected_tests）
```

---

## Plan 2.6: Runtime Dataset Slim & Incremental Diff 🔲

### 背景与动机

当前 V2 Dataset 存在以下问题：

1. **数据冗余**：`repo_before.tar.gz` / `repo_after.tar.gz` 打包整个仓库，真实场景不可能对大型仓库这样做
2. **诊断盲区**：单次 `diff.patch` 只能看到前后状态，不知道"哪一步引入了什么变更"
3. **污染风险**：新增文件如果不 `git add`，`diff.patch` 记录不到；但 `git add` 会污染用户工作区
4. **结构臃肿**：`control_events.jsonl` 对用户透明，增加复杂度但诊断价值有限

本 Plan 的目标：精简数据结构，实现不污染工作区的增量 diff 追踪。

### 技术方案概览

```text
问题：如何在不影响主 git 工作区的情况下，追踪每次文件修改？
方案：GIT_INDEX_FILE 环境变量

原理：
  GIT_INDEX_FILE=.git/index.ccwhat git add <file>
  → 更新备用 index，主 index 完全不受影响
  GIT_INDEX_FILE=.git/index.ccwhat git diff HEAD
  → 基于备用 index 生成 diff，包含未追踪的新增文件
```

Hook 条件激活：
```text
正常 session: claude → CCWHAT_ENABLED 未设置 → hook exit 0，零开销
追踪 session: ccwhat start → CCWHAT_ENABLED=1 → hook 激活，记录 diff
```

---

### Change 6: `slim-runtime-dataset-core` [阶段一]

**目标**：删除废弃文件，简化数据结构。

**删除内容**：

| 文件 | 删除原因 |
|------|---------|
| `control_events.jsonl` | 诊断不依赖，对用户透明，增加复杂度 |
| `repo_before.tar.gz` | 真实场景不会打包整个仓库 |
| `repo_after.tar.gz` | 同上，增量 diff 替代 |

**代码变更**：

1. **staging.py**
   - 删除 `ControlEvidence` dataclass
   - 删除 `_append_control_event()` 方法
   - 删除 `note()` 方法
   - 方法签名移除 `evidence: ControlEvidence` 参数
   - `start_task()` / `finish_task()` / `abort_task()` 移除 `_append_control_event()` 调用
   - `task["paths"]` 移除 `"control_events"` 键
   - `task["evidence_availability"]` 移除 `"control_events"` 键
   - 移除 `git diff --binary HEAD` 和写文件逻辑
   - `task["paths"]` 移除 `"diff"` 键（阶段二重新实现）
   - `task["evidence_availability"]` 移除 `"diff"` 键
   - 移除 `repo_before.tar.gz` / `repo_after.tar.gz` 写入逻辑
   - `task["paths"]` 移除 `"repo_before"` / `"repo_after"` 键

2. **controller.py**
   - 删除 `ControlEvidence` import
   - 删除 `"note"` 从合法 action 列表
   - 删除 note 处理分支
   - 调用 staging 方法时去掉 `evidence=` 参数

3. **claude_integration.py**
   - 删除 `"note"` 从 `COMMANDS` 字典

4. **claude_hook.py**
   - payload 删除 `integration`、`model_visible`、`agent_log_visible`、`confidence` 字段

**验收标准**：

- `pytest tests/test_task_dataset_core.py` 通过
- Task 目录不再生成 `control_events.jsonl`、`repo_before.tar.gz`、`repo_after.tar.gz`
- `/ccwhat:start` / `/ccwhat:finish` 正常工作

---

### Change 7: `add-incremental-diff-tracking` [阶段二]

**目标**：建立 GIT_INDEX_FILE 基础设施，支持增量 diff 生成。

**新增内容**：

1. **staging.py**
   - 新增 `CCWhatIndex` 类，封装 GIT_INDEX_FILE 操作：
     - `init()`：创建空 index（`git read-tree --empty`）
     - `add(file_path)`：添加文件到备用 index
     - `remove(file_path)`：从备用 index 删除
     - `diff(base_commit)`：生成当前 index vs HEAD 的 diff
     - `diff_step(prev_commit)`：生成单步 diff
   - 新增 `step_diffs: list[StepDiff]` 字段到 task 数据结构

2. **StepDiff 数据结构**：
   ```json
   {
     "step_index": 1,
     "timestamp": "2024-01-15T10:30:00Z",
     "diff": "... unified diff 内容 ...",
     "files_changed": ["path/to/file.py"]
   }
   ```

3. **diff.patch 格式**：
   ```diff
   # Step 1: Write /path/to/file.py
   # Timestamp: 2024-01-15T10:30:00Z
   diff --git a/file.py b/file.py
   new file mode 100644
   index 0000000..abc1234
   --- /dev/null
   +++ b/file.py
   @@ -0,0 +1 @@
   +content
   
   # Step 2: Edit /path/to/file.py
   # Timestamp: 2024-01-15T10:31:00Z
   diff --git a/file.py b/file.py
   index abc1234..def5678 100644
   --- a/file.py
   +++ b/file.py
   @@ -1 +1 @@
   -content
   +updated content
   ```

**验收标准**：

- `CCWhatIndex` 类可独立测试
- 新增文件、修改文件、删除文件都能正确生成 diff
- 主 git 工作区 `git status` 完全不受影响

---

### Change 8: `integrate-diff-with-hooks` [阶段三]

**目标**：通过 Hook 捕获工具调用，将 diff 与具体 tool_call 关联。

**Hook Payload 结构**（Claude Code 提供）：
```json
{
  "session_id": "abc123",
  "hook_event_name": "PostToolUse",
  "tool_name": "Write|Edit|MultiEdit|Bash",
  "tool_input": {"file_path": "...", "old_string": "...", "new_string": "..."},
  "tool_result": {...}
}
```

**变更内容**：

1. **ccwhat 脚手架脚本**（新增）
   ```bash
   #!/bin/bash
   # ccwhat - 启动带追踪的 Claude Code session
   export CCWHAT_ENABLED=1
   export CCWHAT_RUNTIME_CONTROL_PORT=$(python -c "...")
   export CCWHAT_RUNTIME_TOKEN=$(python -c "...")
   claude "$@"
   ```

2. **PostToolUse Hook**（`.claude/hooks/ccwhat-diff-hook.sh`）
   ```bash
   #!/bin/bash
   # 条件激活检查
   if [[ "$CCWHAT_ENABLED" != "1" ]]; then
     exit 0
   fi
   
   input=$(cat)
   tool_name=$(echo "$input" | jq -r '.tool_name')
   file_path=$(echo "$input" | jq -r '.tool_input.file_path // empty')
   
   # 只处理文件类工具
   if [[ "$tool_name" =~ ^(Write|Edit|MultiEdit)$ && -n "$file_path" ]]; then
     # 通知 controller 记录此步骤
     curl -X POST "http://localhost:$CCWHAT_RUNTIME_CONTROL_PORT/step" \
       -H "Authorization: Bearer $CCWHAT_RUNTIME_TOKEN" \
       -d "{\"tool_name\":\"$tool_name\",\"file_path\":\"$file_path\"}"
   fi
   
   exit 0
   ```

3. **controller.py**
   - 新增 `/step` endpoint
   - 调用 `staging.record_step(tool_name, file_path)`
   - 内部使用 `CCWhatIndex.add(file_path)` 更新备用 index
   - 生成单步 diff 并追加到 diff.patch

4. **.claude/settings.json 配置**
   ```json
   {
     "hooks": {
       "PostToolUse": [
         {
           "matcher": "Write|Edit|MultiEdit",
           "hooks": [
             {
               "type": "command",
               "command": "bash ~/.claude/hooks/ccwhat-diff-hook.sh"
             }
           ]
         }
       ]
     }
   }
   ```

**Tool Call 关联**：

```text
PostToolUse hook
  -> tool_name: "Write"
  -> file_path: "/path/to/file.py"
  -> controller /step
     -> CCWhatIndex.add("/path/to/file.py")
     -> git diff HEAD > step_N.patch
     -> 写入 diff.patch（带 step 注释头）
     -> 记录 metadata: {step_index, tool_name, file_path, timestamp}
```

**验收标准**：

- `ccwhat start` 启动的 session，PostToolUse hook 激活
- `claude` 正常启动的 session，hook 不触发（零开销）
- 每次 Write/Edit 后，diff.patch 追加对应片段
- diff.patch 中每个 diff 块都可追溯到具体 tool_call

---

### Change 9: `task-trace-always-persist` [阶段四]

**目标**：`task_trace.json` 始终写入，消除 None 分支。

**背景**：当前 `trace_extractor.py` 在以下情况返回 `None`：
- agent 不是 claude
- 时间窗口解析失败
- 找不到项目目录
- 时间窗内无事件

**变更内容**：

1. **trace_extractor.py**
   - 返回类型从 `dict | None` 改为 `dict`
   - 添加 `extraction_status` 字段：
     - `"ok"`：正常提取
     - `"unsupported_agent"`：agent 不是 claude
     - `"invalid_time_bounds"`：时间窗口解析失败
     - `"log_not_found"`：找不到项目目录
     - `"no_events"`：时间窗内无事件

2. **staging.py**
   - 删除 `if trace is not None / else` 分支
   - 始终写 `task_trace.json`
   - 始终设置 `task["paths"]["task_trace"] = "task_trace.json"`
   - 始终设置 `task["evidence_availability"]["task_trace"] = True`

**task_trace.json 结构**（异常时）：
```json
{
  "task_id": "task-001",
  "run_id": "run-001",
  "extraction_status": "unsupported_agent",
  "extraction_status_reason": "Agent 'codex' is not supported for trace extraction",
  "events": [],
  "commands": [],
  "files": {"read": [], "changed": []},
  "changes": [],
  "errors": [],
  "final_claim": null,
  "repo_state": {"cwd": null, "base_commit": null, "head_commit": null}
}
```

**验收标准**：

- `pytest tests/test_task_dataset_change_evidence.py` 通过
- 所有 task 目录都包含 task_trace.json
- extraction_status 正确反映提取结果

---

### Plan 2.6 实施顺序

```text
Change 6: slim-runtime-dataset-core
  ├── 删除 control_events.jsonl
  ├── 删除 repo_before/after.tar.gz
  └── 清理相关代码

Change 7: add-incremental-diff-tracking
  ├── CCWhatIndex 类（GIT_INDEX_FILE 封装）
  └── diff.patch 格式定义

Change 8: integrate-diff-with-hooks
  ├── ccwhat 脚手架脚本
  ├── PostToolUse hook 实现
  └── controller /step endpoint

Change 9: task-trace-always-persist
  └── extraction_status + 始终写入
```

四个 change 依次依赖，必须顺序执行。

---

## Plan 3: Auto Attribution Diagnosis 🔲

V2 Dataset 现在已具备归因诊断所需的全部数据。Plan 3 是最终目标层。

### 现有诊断能力评估

当前 V2 Dataset 已经可以支撑的判断：

```text
✅ Agent 有没有真的改文件（diff.patch 为空？）
✅ 改动是否与任务描述相关（instruction vs files.changed）
✅ 有没有跑测试（test_commands 是否存在）
✅ 测试有没有报错（errors[] 是否有测试失败信息）
✅ final_claim 与实际 diff 是否矛盾
✅ Agent 只读没改（files.read 有，files.changed 为空）
```

### Change 6: `add-auto-attribution-diagnosis`

**目标**：消费 V2 Dataset，生成初版归因诊断结果 `diagnosis.json`。

**两层诊断架构**：

```text
task_trace.json + diff.patch + repo_before/after
  -> 规则层（快，确定性强）
       命令未运行 / 测试失败 / diff 为空但声称完成 / final_claim 矛盾
  -> LLM 层（深，覆盖规则层遗漏的语义问题）
       只消费 Dataset evidence，不全量读文件
       输出结构化 diagnosis，标注 confidence 和 evidence links
  -> diagnosis.json
```

**diagnosis.json 结构**：

```json
{
  "task_id": "task-001",
  "summary": "...",
  "likely_root_causes": [
    {
      "cause": "测试未通过",
      "evidence": ["errors[0]: AssertionError ..."],
      "confidence": "high",
      "source": "rule"
    }
  ],
  "missing_evidence": ["success_criteria 未填写"],
  "confidence": "high",
  "recommended_next_steps": ["..."]
}
```

**验收标准**：

- 对一个 finalized task 能生成 `diagnosis.json`
- 测试失败时，诊断能引用具体 command/error 证据
- diff 为空但 final_claim 非空时，诊断能指出矛盾
- evidence_availability 有缺失项时，诊断明确说明不能判断
- medium-confidence boundary 不被当作 high-confidence 证据引用

**不在本 change 中做**：

- 训练数据转换（SFT/DPO/RL）
- 批量 benchmark
- 完整 evaluator 平台
- 诊断 UI（只做 JSON 输出，viewer 展示可后续补）

---

## 推荐执行顺序（更新后）

```text
✅ 1. add-runtime-task-recording-mvp              Claude Code 完整竖切
⚠️  2. add-codex-runtime-slash-integration          Codex 适配（暂停）
⚠️  3. add-opencode-runtime-command-integration     OpenCode 适配（暂停）
✅ 4. enrich-runtime-task-trace                    V2 Dataset 补齐行为轨迹
🔲 5. slim-runtime-dataset-core                    阶段一：删除废弃文件
🔲 6. add-incremental-diff-tracking                阶段二：增量 diff 基础设施
🔲 7. integrate-diff-with-hooks                    阶段三：Hook 集成
🔲 8. task-trace-always-persist                    阶段四：task_trace 始终写入
🔲 9. add-auto-attribution-diagnosis               归因诊断引擎（下一步）
```

当前聚焦：**Plan 2.6（Dataset 精简与增量 diff）**。这是归因诊断的数据基础，必须先完成才能确保诊断引擎消费的数据结构是稳定的。

**关键依赖**：
- Change 5/6/7/8 必须顺序执行（后一个依赖前一个的基础设施）
- Plan 2.6 全部完成后，才能开始 Plan 3（归因诊断），因为 diagnosis.json 的结构依赖精简后的 Dataset
