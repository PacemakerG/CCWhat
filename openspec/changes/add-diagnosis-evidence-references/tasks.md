## 1. precheck_finding 字段迁移

- [x] 1.1 更新 Precheck 测试，要求 `precheck_finding_id` 和 `precheck-finding-NNN` 格式
- [x] 1.2 更新 `ccwhat/diagnosis/precheck.py` 并通过 Precheck 测试

## 2. 诊断引用契约与后端校验

- [x] 2.1 为 `precheck_finding_ids`、四类 `document_refs`、无效引用和路径逃逸增加后端测试
- [x] 2.2 让 Precheck 只运行一次，并把 `precheck_findings` 传入校验器及诊断响应
- [x] 2.3 实现可疑 Action 的 `precheck_finding_ids` 和 `document_refs` 存在性校验
- [x] 2.4 更新诊断 Prompt 的输出契约和文档引用规则

## 3. 前端最小展示

- [x] 3.1 更新前端类型，在现有诊断详情中展示被引用的 `precheck_finding` 和文档依据
- [x] 3.2 保持粗图高亮、Action 下钻和可疑 Event 高亮，并完成前端 typecheck/build

## 4. 文档与整体验证

- [x] 4.1 同步极简诊断流程说明和 P1 实施文档
- [x] 4.2 运行后端完整测试、OpenSpec 严格校验和 `git diff --check`
