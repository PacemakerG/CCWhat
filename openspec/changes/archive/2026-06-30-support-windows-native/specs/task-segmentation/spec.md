## ADDED Requirements

### Requirement: Windows UTF-8 任务切分规则
task segmentation SHALL 在 Windows 默认 locale 下读取 UTF-8 规则资源。

#### Scenario: Windows 中文 locale 自动切分
- **WHEN** Windows 中文环境调用 `segment_session()`
- **THEN** 系统 SHALL 使用 UTF-8 读取 `task_segment_rules.json`
- **AND** 不得抛出 `UnicodeDecodeError: 'gbk' codec can't decode`

### Requirement: 自动切分失败不破坏手动 overlay
task segmentation 前端 SHALL 在自动切分请求成功前保留已有 task overlay。

#### Scenario: 手动 task 后自动切分失败
- **WHEN** 用户先手动创建 task overlay 后点击自动切分
- **AND** `/api/task-segments` 请求失败
- **THEN** 前端 SHALL 恢复或保留原有手动 task overlay
- **AND** 左侧 task 列表不得变为空

#### Scenario: 自动切分成功替换 overlay
- **WHEN** 用户确认重新自动切分且 `/api/task-segments` 成功返回 tasks
- **THEN** 前端 SHALL 用新的自动切分结果替换当前 overlay
- **AND** 旧 overlay 的替换行为 SHALL 可由用户确认或撤销

### Requirement: Windows 自动切分错误展示
task segmentation 前端 SHALL 在 Windows 后端错误时显示可理解的错误信息。

#### Scenario: 后端返回 JSON 错误
- **WHEN** `/api/task-segments` 返回 `ok: false`
- **THEN** 前端 SHALL 显示后端 `error` 内容
- **AND** “重试”和“查看上次结果”行为 SHALL 不清空已有 overlay
