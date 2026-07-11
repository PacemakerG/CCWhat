## 1. 显性 Precheck

- [x] 1.1 新增七字段 Finding 构造与 `ArtifactMissingVerifier`
- [x] 1.2 实现 `BasicVerifyChecker` 的 missing、failed、result missing 和 stale 判断
- [x] 1.3 添加 Precheck 单元测试，覆盖异常、正常和数据边界

## 2. 路径驱动诊断 Agent

- [x] 2.1 后端生成并校验 Graph 与 change root 绝对路径
- [x] 2.2 将反馈诊断改为“路径 + feedback + Findings + 输出契约”Prompt
- [x] 2.3 更新诊断 Prompt 的只读访问、读取顺序和证据边界
- [x] 2.4 保持 Analyzer JSON 解析、ID 校验和前端响应兼容

## 3. 验证

- [x] 3.1 添加路径 Prompt、Precheck 注入、不可读和隐性错误场景测试
- [x] 3.2 运行相关测试、静态检查和 `openspec validate --strict`
