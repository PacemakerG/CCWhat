## 1. 诊断引擎核心模块

- [ ] 1.1 创建 `ccwhat/diagnosis/` 目录结构
- [ ] 1.2 实现 `diagnosis/models.py`：DiagnosisResult、RootCause 等数据模型
- [ ] 1.3 实现 `diagnosis/rules.py`：规则层诊断（diff 为空、测试失败、命令缺失）
- [ ] 1.4 实现 `diagnosis/llm_layer.py`：LLM 层诊断（语义分析、相关性判断）
- [ ] 1.5 实现 `diagnosis/engine.py`：DiagnosisEngine 主类，协调两层诊断
- [ ] 1.6 实现诊断结果聚合逻辑：合并规则层和 LLM 层结果，计算整体 confidence

## 2. CLI 命令

- [ ] 2.1 创建 `ccwhat/commands/diagnose.py`：diagnose 命令实现
- [ ] 2.2 实现 `--task-id` 参数支持：对指定 task 生成诊断
- [ ] 2.3 实现 `--run-id` 参数支持：批量诊断 run 下所有 task
- [ ] 2.4 实现 `--dry-run` 参数支持：只输出到 stdout
- [ ] 2.5 实现 `--no-llm` 参数支持：禁用 LLM 层
- [ ] 2.6 实现 `--output` 参数支持：自定义输出路径
- [ ] 2.7 在 `ccwhat/cli.py` 注册 diagnose 子命令

## 3. 集成与配置

- [ ] 3.1 复用现有 LLM 配置：从 config.toml 读取 API key 和 endpoint
- [ ] 3.2 可选集成到 finish 流程：添加 `auto_diagnose` 标志（默认关闭）
- [ ] 3.3 实现 LLM 调用失败降级：LLM 失败时只返回规则层结果

## 4. 测试

- [ ] 4.1 编写规则层单元测试：diff 为空、测试失败、命令缺失场景
- [ ] 4.2 编写引擎集成测试：验证完整诊断流程
- [ ] 4.3 编写 CLI 测试：验证命令行参数处理
- [ ] 4.4 编写端到端测试：使用 mock task 数据验证诊断生成
- [ ] 4.5 运行全部测试：确保无回归

## 5. 文档与审查

- [ ] 5.1 编写诊断引擎使用文档
- [ ] 5.2 编写 CLI 帮助文档
- [ ] 5.3 代码审查：错误处理边界
- [ ] 5.4 示例：提供示例 task 和生成的 diagnosis.json
