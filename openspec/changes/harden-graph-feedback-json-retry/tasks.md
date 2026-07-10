## 1. Asset 与实现

- [x] 1.1 创建 `ccwhat/assets/graph_attribution_fix_prompt.md`，包含只修 JSON 语法、不增新事实的提示
- [x] 1.2 修改 `ccwhat/diagnosis/feedback.py` 的 `analyze_graph_feedback`，增加首次解析失败后的格式修复子调用逻辑

## 2. 测试

- [x] 2.1 新增测试：未转义引号导致首次解析失败后格式修复成功
- [x] 2.2 新增测试：首次解析合法只调用一次 Analyzer
- [x] 2.3 新增测试：第二次分析仍失败时降级为 unavailable

## 3. 验证

- [x] 3.1 运行 `openspec validate harden-graph-feedback-json-retry --strict`
- [x] 3.2 运行 `python -m pytest tests/test_graph_feedback.py -v`
