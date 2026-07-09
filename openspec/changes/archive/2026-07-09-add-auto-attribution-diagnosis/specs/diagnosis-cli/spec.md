## ADDED Requirements

### Requirement: CLI 支持对指定 task 生成诊断

`ccwhat diagnose` 命令 SHALL 支持通过 `--task-id` 参数指定 task，生成 diagnosis.json。

#### Scenario: 对指定 task 生成诊断
- **WHEN** 用户执行 `ccwhat diagnose --task-id task-001 --run-id run-001`
- **THEN** 系统 SHALL 读取对应 task 的现场包数据
- **AND** 运行诊断引擎生成 diagnosis.json
- **AND** 将结果写入 task 目录

#### Scenario: 缺少 task-id 参数时报错
- **WHEN** 用户执行 `ccwhat diagnose` 但不提供 `--task-id`
- **THEN** 系统 SHALL 输出错误信息提示缺少必需参数
- **AND** exit code SHALL 非零

### Requirement: CLI 支持对指定 run 批量诊断

`ccwhat diagnose` 命令 SHALL 支持通过 `--run-id` 参数对 run 下所有 finalized task 批量生成诊断。

#### Scenario: 对指定 run 批量诊断
- **WHEN** 用户执行 `ccwhat diagnose --run-id run-001`
- **THEN** 系统 SHALL 遍历该 run 下所有 finalized task
- **AND** 为每个 task 生成 diagnosis.json
- **AND** 输出批量诊断进度

### Requirement: CLI 支持 dry-run 模式

`ccwhat diagnose` 命令 SHALL 支持 `--dry-run` 参数，只输出诊断结果到 stdout 而不写入文件。

#### Scenario: dry-run 模式不写入文件
- **WHEN** 用户执行 `ccwhat diagnose --task-id task-001 --dry-run`
- **THEN** 系统 SHALL 输出 diagnosis.json 内容到 stdout
- **AND** 不修改 task 目录任何文件

### Requirement: CLI 支持配置 LLM 层开关

`ccwhat diagnose` 命令 SHALL 支持 `--no-llm` 参数，只运行规则层诊断。

#### Scenario: 禁用 LLM 层
- **WHEN** 用户执行 `ccwhat diagnose --task-id task-001 --no-llm`
- **THEN** 系统 SHALL 只执行规则层诊断
- **AND** 不调用任何 LLM API
- **AND** 所有结果 source 为 "rule"

### Requirement: CLI 支持指定输出路径

`ccwhat diagnose` 命令 SHALL 支持 `--output` 参数指定 diagnosis.json 输出路径。

#### Scenario: 自定义输出路径
- **WHEN** 用户执行 `ccwhat diagnose --task-id task-001 --output /path/to/diagnosis.json`
- **THEN** 系统 SHALL 将结果写入指定路径而非默认 task 目录
