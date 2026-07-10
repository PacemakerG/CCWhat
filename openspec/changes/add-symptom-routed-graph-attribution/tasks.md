## 1. OpenSpec 文档

- [x] 1.1 按 CC Session-only MVP 重写 proposal/design/spec/tasks
- [x] 1.2 运行 `openspec validate add-symptom-routed-graph-attribution --strict`

## 2. CC Event Graph

- [x] 2.1 保证一条原始日志含多个 Tool Use 时生成唯一 Event ID
- [x] 2.2 Event Graph 保留 Tool input/result、files、command、error、result summary 和 raw reference
- [x] 2.3 Tool Call/Result 使用稳定 Tool Call ID 配对，未映射 Event 不丢失
- [x] 2.4 为真实 Claude Session 结构补 Event Graph 测试

## 3. 固定 Action Graph 与映射

- [x] 3.1 保留固定 OpenSpec 七节点并将状态收敛为 `observed|not_observed|failed`
- [x] 3.2 修复 read/edit、Assistant 文本/command 映射误判并保存映射理由
- [x] 3.3 停止以旧 Action 反向分数作为 Session feedback diagnosis 主路径
- [x] 3.4 补 Action 映射和无证据状态测试

## 4. 用户反馈 Analyzer

- [x] 4.1 定义 feedback request、compact graph context 和结构化 diagnosis result
- [x] 4.2 复用 `run_mc_analysis()` 启动一次本地 AI CLI 非交互诊断
- [x] 4.3 解析纯 JSON/Markdown code fence，并校验所有 Action/Event 引用
- [x] 4.4 对 Analyzer missing、timeout、invalid JSON 和 fabricated ID 提供结构化降级
- [x] 4.5 为 Analyzer prompt、解析和引用校验补单元测试

## 5. Viewer/API

- [x] 5.1 新增 Session/change/feedback 诊断 API
- [x] 5.2 OpenSpec Graph 区域新增 feedback 输入、按钮和运行状态
- [x] 5.3 展示诊断摘要、可疑 Action/Event、缺失证据，并支持图节点定位
- [x] 5.4 补 API 和 Viewer DOM 测试

## 6. Mock 与端到端验收

- [x] 6.1 创建真实 Claude Code JSONL 结构的 OpenSpec 驱动 Session mock 和对应 change
- [x] 6.2 使用 mock 验证双图 Event/Action 映射及诊断引用
- [x] 6.3 启动 Viewer，在前端手动输入反馈并验证诊断报告与图节点定位

## 7. 回归验证

- [x] 7.1 运行 OpenSpec strict validation 和 diagnosis/openspec/viewer 相关测试
- [x] 7.2 确认 MVP 主链路不依赖 Runtime Task、Dataset 或 `task.diff`
