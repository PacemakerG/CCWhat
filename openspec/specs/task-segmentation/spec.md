## Purpose
Define how session events are normalized, segmented into tasks, and surfaced in the viewer.
## Requirements
### Requirement: 归一化 session 事件流
系统 SHALL 将当前 session 的 main 日志和 subagent 日志转换为统一的 normalized events，供规则切分算法消费。

#### Scenario: 归一化 main session 事件
- **WHEN** 系统对包含 user、assistant、tool_use 和 tool_result 的 session 执行任务切分
- **THEN** 系统返回的内部事件 SHALL 包含稳定的 `eventId`、`source`、`turnIndex`、`eventType`、`text`、`timestamp` 和原始行号引用
- **AND** tool call 与 tool result SHALL 尽可能通过 tool use id 关联

#### Scenario: 归一化 subagent 事件
- **WHEN** session 包含 subagent 日志和 subagent metadata
- **THEN** 系统 SHALL 将 subagent 事件纳入 normalized events
- **AND** 每个 subagent 事件 SHALL 保留 `source`、`agentId` 和可用的 metadata 摘要

### Requirement: 规则化用户意图分类
系统 SHALL 使用配置化关键词、短语和正则规则对 user message 进行意图分类，不使用 LLM 判断 Task 边界。

#### Scenario: 识别新任务倾向
- **WHEN** user message 命中“帮我”“新增”“实现”“修复”“review”“fix”“add”“implement”等新任务 marker
- **THEN** 系统 SHALL 为该消息产生新任务倾向分数
- **AND** 分数原因 SHALL 记录在 boundary debug reasons 中

#### Scenario: 识别延续反馈
- **WHEN** user message 命中“继续”“刚才”“这个”“还是不对”“报错了”“没通过”“重新改”“根据你的 review”等延续 marker
- **THEN** 系统 SHALL 将该消息优先视为当前 Task 的延续
- **AND** 除非同一消息同时命中强边界 marker，否则 SHALL NOT 因该消息开新 Task

#### Scenario: 识别模糊消息
- **WHEN** user message 是“为什么”“什么意思”“这样可以吗”等模糊或确认类消息
- **THEN** 系统 SHALL 默认将该消息归入当前 Task
- **AND** SHALL NOT 仅凭该消息开新 Task

#### Scenario: 识别任务类型
- **WHEN** user message 命中 bugfix、feature、doc、refactor、test、review、explanation 或 planning 的任务类型 marker
- **THEN** 系统 SHALL 为 Task Segment 输出候选 `taskType`
- **AND** 无法确定时 SHALL 输出 `unknown`

### Requirement: 抽取任务 evidence
系统 SHALL 从 normalized events 中抽取用于切分和展示的 evidence。

#### Scenario: 抽取文件 evidence
- **WHEN** 工具调用或结果中包含读取、搜索、打开、编辑、写入或 patch 文件的信息
- **THEN** 系统 SHALL 抽取 `filesRead` 和 `filesChanged`
- **AND** 文件路径 SHALL 规范化为相对路径，无法相对化时保留原路径

#### Scenario: 抽取命令和测试 evidence
- **WHEN** 工具调用执行 shell 命令、构建命令或测试命令
- **THEN** 系统 SHALL 抽取 `commands`
- **AND** 对 pytest、unittest、npm test、npm run build 等命令 SHALL 标记为 test/build evidence

#### Scenario: 抽取错误 evidence
- **WHEN** tool result、assistant text 或命令输出包含失败、异常、Traceback、Error、failed、non-zero exit 等错误信号
- **THEN** 系统 SHALL 抽取 `errors`
- **AND** 错误 evidence SHALL 可用于抑制错误反馈后的新 Task 切分

#### Scenario: 抽取 final claim
- **WHEN** assistant text 在前序存在执行 evidence 后包含“已完成”“修复了”“总结”“现在可以”“Done”“Fixed”等完成声明
- **THEN** 系统 SHALL 将该文本记录为当前 Task 的 `finalClaim`
- **AND** final claim SHALL 只关闭当前 Task，不得单独创建新 Task

### Requirement: 关联 Todo 与后续 evidence
系统 SHALL 将 Todo 分为用户目标 Todo、assistant 计划 Todo 和工具 Todo，并仅将有证据支撑的目标 Todo 升级为 Task。

#### Scenario: 用户目标 Todo 生成候选任务
- **WHEN** user message 包含多个目标型 Todo item
- **THEN** 系统 SHALL 为每个目标型 Todo 生成 CandidateTask
- **AND** CandidateTask SHALL 在后续 evidence 分数达标后才升级为 Task Segment

#### Scenario: 执行步骤 Todo 不直接切分
- **WHEN** assistant 或工具 Todo item 只是“读取代码”“修改实现”“运行测试”“总结”等执行步骤
- **THEN** 系统 SHALL 将这些 Todo 作为当前 Task 的 timeline/evidence
- **AND** SHALL NOT 仅凭这些 Todo 开新 Task

#### Scenario: 本地 BM25 关联 Todo 和 evidence
- **WHEN** CandidateTask 需要判断后续 evidence 是否相关
- **THEN** 系统 SHALL 使用本地内存 BM25 计算 Todo 文本与 evidence 文档的相关性
- **AND** BM25 分数 SHALL 乘以 evidence 权重后用于 CandidateTask 升级判断

### Requirement: 使用加权 overlap 判断文件主题变化
系统 SHALL 使用 file-level 和 module-level 加权 Jaccard overlap 判断候选边界前后的文件主题是否明显变化。

#### Scenario: 计算文件权重
- **WHEN** 系统抽取文件 evidence
- **THEN** Edit、Write、Patch、MultiEdit 类 evidence SHALL 高于 Read、Grep、Open 类 evidence
- **AND** README、docs、lockfile、pyproject、package config 等通用文件 SHALL 降权

#### Scenario: 文件主题变化支持切分
- **WHEN** 候选边界后的窗口与当前 Task 的 `file_overlap` 低于阈值
- **AND** `module_overlap` 低于阈值
- **AND** 新窗口包含 edit、write、test 或 build evidence
- **AND** 附近存在 user、todo 或 final summary 边界信号
- **THEN** 系统 SHALL 将文件主题变化作为开新 Task 的正向信号

#### Scenario: 文件主题变化不得单独切分
- **WHEN** 只有文件集合变化
- **AND** 附近没有 user、todo 或 final summary 边界信号
- **THEN** 系统 SHALL NOT 仅凭文件集合变化开新 Task

### Requirement: 使用边界评分构建 Task Segments
系统 SHALL 使用 boundary score、抑制规则和状态机将事件流构建为 Task Segments。

#### Scenario: 分数达标时开新 Task
- **WHEN** 候选边界的最终 boundary score 达到开新 Task 阈值
- **THEN** 系统 SHALL 关闭当前 Task Segment
- **AND** 从该边界开始创建新的 Task Segment
- **AND** 新 Task Segment SHALL 记录 `boundaryReasons`

#### Scenario: 延续反馈抑制切分
- **WHEN** 候选边界命中延续反馈 marker
- **AND** 文件 overlap 高或错误 evidence 与最近 Task 重叠
- **THEN** 系统 SHALL 将后续事件归入当前或最近关闭的 Task
- **AND** SHALL NOT 开新 Task

#### Scenario: 用户反馈失败时重开最近 Task
- **WHEN** 最近 Task 已因 final claim 关闭
- **AND** 后续用户消息命中“还是报错”“没通过”“不对”“继续改”等反馈
- **AND** 反馈与最近 Task 的文件、错误或 final claim 有重叠
- **THEN** 系统 SHALL reopen 最近 Task
- **AND** 该反馈 SHALL 作为该 Task 的 evidence

#### Scenario: 复杂交错任务标记模糊
- **WHEN** 事件在两个或多个低重叠文件主题之间反复切换
- **AND** 规则无法稳定确定边界
- **THEN** 系统 SHALL 将相关 Task 或 session summary 标记为 `ambiguous`
- **AND** SHALL NOT 自信地产生多个无依据 Task

### Requirement: 提供 task segments API
系统 SHALL 提供 `POST /api/task-segments` 接口，对当前 session 返回结构化 Task Segment 结果。

#### Scenario: 成功返回当前 session task segments
- **WHEN** 前端或调用方向 `/api/task-segments` 提交有效 `sessionId`
- **THEN** 后端 SHALL 读取该 session 的 main 日志和 subagent 日志
- **AND** SHALL 返回 JSON，包含 `ok: true`、`sessionId`、`summary` 和 `tasks`
- **AND** 每个 task SHALL 包含 `taskId`、`title`、`taskType`、`status`、起止事件、evidence、file weights 和 boundary reasons

#### Scenario: API 限制为当前 session
- **WHEN** 调用方请求 `/api/task-segments`
- **THEN** 请求体 SHALL 只需要 `sessionId`
- **AND** 第一版 SHALL NOT 支持 turns、筛选结果、跨 session 或多 session 分析参数

#### Scenario: session 不存在
- **WHEN** 调用方提交不存在的 `sessionId`
- **THEN** 接口 SHALL 以 404 响应
- **AND** 返回 JSON，包含 `ok: false` 和可读错误信息

#### Scenario: 第一版不评测成功率
- **WHEN** 系统返回 Task Segment
- **THEN** 每个 Task Segment 的 `status` SHALL 默认为 `unevaluated`
- **AND** 系统 SHALL NOT 在第一版输出 success、failed 或 success rate

### Requirement: 输出可解释调试信息
系统 SHALL 为每个切分边界输出可解释的调试信息，用于后续规则调参和前端诊断展示。

#### Scenario: 记录切分原因
- **WHEN** 系统创建新的 Task Segment
- **THEN** Task Segment SHALL 包含 `boundaryReasons`
- **AND** 每条 reason SHALL 表示信号名称、信号值和分数贡献

#### Scenario: 记录抑制切分原因
- **WHEN** 候选边界未达到开新 Task 条件
- **THEN** 系统 SHALL 在调试输出中保留主要抑制原因
- **AND** 抑制原因 SHALL 可用于测试断言和人工复盘

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

