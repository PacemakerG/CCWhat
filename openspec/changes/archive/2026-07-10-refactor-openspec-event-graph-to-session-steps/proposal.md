## Why

当前 OpenSpec Graph 已经能生成粗图和细图，但细图的数据源仍偏 milestone/artifact 级，例如 `artifact_present`、`code_changed`、`validate_ran`。这只能说明流程里发生过某个节点，不能定位到具体是哪一次工具调用、哪一次文件改动、哪一次命令失败或哪一句 final claim 导致问题。

产品目标是两层图：

- 粗图：固定 OpenSpec Action DAG，用来定位流程阶段。
- 细图：真实 session step 级 Event Graph，用来定位具体证据。

因此本 change 只做一件事：把 OpenSpec Graph 的细图主干从 milestone 事件升级为 Cloud/Claude session normalized step 事件，并把这些 step 事件映射到固定 OpenSpec Action 粗图。

## What Changes

- 为 OpenSpec graph 增加 source binding，明确 change 对应的 `session_id`、`task_id` 或 `dataset_id`。
- `ccwhat openspec-graph sync` 支持从 Dataset trace 或 session normalized events 构建 step 级 Event Graph。
- OpenSpec Action Graph 继续固定为 proposal、specs、design、tasks、apply、verify、archive。
- 每个 Action 节点通过 `event_ids` 和 mapping reasons 绑定细图 step 事件。
- milestone/artifact 事件保留为补充证据或 fallback，不再作为细图主干。
- Viewer 展示 step 级 Event Graph，并能呈现粗图 Action 与细图 Event 的绑定关系。

## Non-Goals

- 不重做 OpenSpec 粗图模板。
- 不重新设计 symptom 分类、反向归因和打分机制；这些放到后续 `add-symptom-routed-graph-attribution`。
- 不让 LLM 直接在原始日志里自由猜根因。
- 不做通用 workflow schema 编辑器。
- 不在第一版实现手动修正 mapping UI。
- 不归档既有 OpenSpec changes。
