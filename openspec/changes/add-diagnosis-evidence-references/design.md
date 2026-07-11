## Context

P0 已经生成 `precheck_findings`，并让本地诊断 Agent 返回 `suspicious_actions` 和 `suspicious_events`。后端现有逻辑会校验 Action/Event ID，但没有校验模型对显性异常和 OpenSpec 文档的引用，前端也只展示可疑 Action 文本。

P1 需要保持当前图结构、单次 Agent 调用和粗图到细图交互，只在现有诊断结果上增加最小证据引用。

## Goals / Non-Goals

**Goals:**

- 统一 `precheck_finding_id` 字段和 `precheck-finding-NNN` 格式。
- 给可疑 Action 增加可选 `precheck_finding_ids` 和 `document_refs`。
- 后端校验引用存在性、文档类型和路径边界。
- 在现有诊断详情中展示被引用的显性异常和文档锚点。

**Non-Goals:**

- 不新增 Precheck 规则或判断模型结论正确性。
- 不修改 Action Graph/Event Graph 或创建新节点、新边。
- 不增加 LLM 调用、打分、Diff、Snapshot 或证据页面。
- 不改变粗图、细图主要布局和下钻方式。

## Decisions

### 1. 证据引用附着在 `suspicious_actions`

保留现有 `suspicious_actions / suspicious_events` 为主要结果，只在可疑 Action 上增加引用字段。这样前端仍以 Action 作为粗定位入口，Event 继续承担细粒度定位，文档和显性异常不会变成同级诊断对象。

### 2. `precheck_findings` 只生成一次

`analyze_graph_feedback()` 在调用 Agent 前运行一次 Precheck，同一列表同时传入 Prompt 和结果校验器。校验完成后将该列表作为辅助数据附到诊断响应，前端仅展示被 `precheck_finding_ids` 引用的记录。

### 3. 文档引用使用 `path / kind / anchor`

`path` 相对当前 change root；`kind` 仅允许 `requirement`、`section`、`document`、`task`；`anchor` 使用真实标题或 checklist 文本。整文件引用仅允许 proposal/design，且 `anchor` 为 `null`。不使用易漂移的行号。

### 4. 文档路径按解析后边界校验

后端拒绝绝对路径和包含 `..` 的路径，并在 `resolve()` 后确认目标仍位于当前 change root。允许文件仅限 `proposal.md`、`design.md`、`tasks.md` 和单层 `specs/*/spec.md`。

### 5. 无效引用局部删除

单个无效引用只从对应 Action 中删除，并追加 `missing_evidence`；不因一个坏引用丢弃同一诊断中的其他有效 Action、Event 或依据。后端不做证据语义判断。

### 6. 前端只扩展现有诊断详情

类型层增加可选引用字段和 `precheck_findings` 辅助列表；当前诊断面板在每个可疑 Action 下展示简单证据文本。现有 Action 点击、细图下钻和可疑 Event 高亮逻辑保持不变。

## Risks / Trade-offs

- [模型引用真实但不相关的证据] → 后端明确只保证存在性；诊断仍是模型假设。
- [Markdown 标题或任务文本被改名] → 引用会失效并进入 `missing_evidence`，避免错误定位。
- [字段迁移影响旧结果] → 新字段均为可选；前端兼容缺少引用字段的旧诊断 JSON。
- [路径或符号链接越界] → 使用拒绝绝对路径、拒绝 `..` 和解析后根目录校验三层限制。

## Migration Plan

1. 更新 P0 输出字段及测试。
2. 更新 Prompt 和后端校验，保持旧诊断主体字段不变。
3. 更新前端可选类型和诊断详情。
4. 运行后端测试、前端 typecheck/build 和 OpenSpec 严格校验。

回滚时可整体撤销 P1 commit；P1 不迁移持久化数据，也不修改 Graph 文件结构。

## Open Questions

无。字段、文档类型和前端边界已在 P1 计划中确认。
