## 1. OpenSpec 文档

- [x] 1.1 编写 proposal/design/spec/tasks
- [x] 1.2 运行 `openspec validate refactor-openspec-event-graph-to-session-steps --strict`

## 2. Source Binding

- [x] 2.1 定义 OpenSpec graph source binding schema
- [x] 2.2 `ccwhat openspec-graph sync` 支持 `--session-id`、`--task-id`、`--dataset-id`
- [x] 2.3 graph 输出写入 binding metadata 和 source confidence
- [x] 2.4 缺少 session/task 证据时写入 `missing_evidence`

## 3. Step-Level Event Graph

- [x] 3.1 复用 session normalized events 构建 step 级 Event Graph
- [x] 3.2 支持 Dataset task trace 作为最高优先级输入
- [x] 3.3 保留 milestone/artifact 作为补充 evidence 或 fallback
- [x] 3.4 Event 节点保留 turn index、tool name、tool call id、command、files、summary、raw_ref

## 4. Action Mapping 与 Attribution

- [x] 4.1 Action Graph 保持固定 OpenSpec 七节点 DAG
- [x] 4.2 Event-to-Action mapping 输出 mapping reasons
- [x] 4.3 清理 OpenSpec graph sync 中 milestone 级 Event Graph 主路径
- [x] 4.4 保留或重建最小 graph 输出骨架，不在本 change 中实现新 attribution scorer

## 5. Viewer

- [x] 5.1 Event Graph 展示 step 级节点，而不是 milestone 主干
- [x] 5.2 Action 节点展示映射的 event count 和 mapping confidence
- [x] 5.3 点击或选择 Action 时可定位/高亮对应 Event
- [x] 5.4 fallback 模式明确提示缺少 session step evidence

## 6. 测试

- [x] 6.1 添加 session step fixture 或最小 mock session
- [x] 6.2 验证 Event Graph 节点数量接近 normalized events 数量
- [x] 6.3 验证 OpenSpec Action Graph 仍为固定七节点
- [x] 6.4 验证 Viewer 加载 step-level graph
