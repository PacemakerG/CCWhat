## 1. OpenSpec 文档

- [x] 1.1 编写 proposal/design/spec/tasks
- [x] 1.2 运行 `openspec validate add-symptom-routed-graph-attribution --strict`

## 2. Diagnosis 代码清理

- [ ] 2.1 审计 `ccwhat/diagnosis/` 现有模块，标记保留/重写/删除
- [ ] 2.2 保留 fixed OpenSpec Action DAG 和基础 graph models
- [ ] 2.3 删除或清空不再作为主路径的粗糙 symptom/scoring 代码
- [ ] 2.4 移除 OpenSpec milestone graph 对 attribution 的主路径依赖

## 3. Symptom Router

- [ ] 3.1 定义 `SymptomReport` / `SymptomRoute` 模型
- [ ] 3.2 支持用户反馈文本分类
- [ ] 3.3 支持系统证据自动检测 symptom
- [ ] 3.4 输出 anchor Action、关键词、置信度和来源

## 4. Action Attribution

- [ ] 4.1 沿 OpenSpec Action DAG 从 anchor 反向遍历
- [ ] 4.2 实现通用 Action score
- [ ] 4.3 实现 symptom-specific Action weight
- [ ] 4.4 输出 `suspicious_actions`

## 5. Event Attribution

- [ ] 5.1 在可疑 Action 的 mapped events 内打分
- [ ] 5.2 实现 edit/command/tool_result/error/final_claim 事件加权
- [ ] 5.3 实现关键词和失败边关联加权
- [ ] 5.4 输出 `suspicious_events`

## 6. Causal Chain

- [ ] 6.1 组装 Action + Event 混合 causal chain
- [ ] 6.2 输出每个分数的 reasons 和 evidence
- [ ] 6.3 缺少 step evidence 时降级并写入 `missing_evidence`

## 7. 测试

- [ ] 7.1 为每类 symptom 添加最小 fixture
- [ ] 7.2 验证 Action 反向排序
- [ ] 7.3 验证 Event 级可疑节点排序
- [ ] 7.4 验证旧粗糙 attribution 代码不会继续作为主路径运行
