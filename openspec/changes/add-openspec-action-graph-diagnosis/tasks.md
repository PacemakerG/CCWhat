## 1. OpenSpec 文档

- [x] 1.1 编写 proposal/design/spec/tasks
- [x] 1.2 运行 `openspec validate add-openspec-action-graph-diagnosis --strict`

## 2. 诊断图模型与构建

- [x] 2.1 新增 `ccwhat/diagnosis/models.py`
- [x] 2.2 新增 Event Graph 构建器
- [x] 2.3 新增 OpenSpec Action Graph 构建器
- [x] 2.4 新增 Event-to-Action mapping

## 3. 症状检测与归因

- [x] 3.1 实现 missing/failed/unsupported claim 症状检测
- [x] 3.2 实现反向传播和可疑分打分
- [x] 3.3 输出 `diagnosis.json`

## 4. CLI

- [x] 4.1 新增 `ccwhat diagnose`
- [x] 4.2 支持 Dataset 目录和 tar 输入
- [x] 4.3 输出三个 JSON 文件
- [x] 4.4 新增 `ccwhat openspec-graph sync`
- [x] 4.5 改造 OpenSpec skill / slash command 文档，在流程节点同步 graph

## 5. 测试

- [x] 5.1 编写 Event Graph 测试
- [x] 5.2 编写 Action Graph 和 mapping 测试
- [x] 5.3 编写 symptom 和 attribution 测试
- [x] 5.4 编写 CLI 测试
- [x] 5.5 运行 `uv run python -m unittest tests.test_diagnosis_graph -v`
- [x] 5.6 编写 OpenSpec graph sync 测试
