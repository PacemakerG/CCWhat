## ADDED Requirements

### Requirement: Runtime run registry supports Codex
系统 SHALL 在每次 `ccwhat -- codex` 启动时创建独立 runtime run，并将 run metadata 写入 `~/.ccwhat/runtime-runs/codex/<run-id>/run.json`。

#### Scenario: 创建 Codex runtime run
- **WHEN** 用户执行 `ccwhat -- codex`
- **THEN** 系统 SHALL 创建唯一 `run_id`
- **AND** 系统 SHALL 写入 `run.json`
- **AND** `run.json` SHALL 记录 `agent` 为 `codex`
- **AND** `run.json` SHALL 记录 workspace、agent_process、proxy、viewer、control 和 active_task_id

#### Scenario: Codex 与 Claude run 隔离
- **WHEN** 用户分别执行 `ccwhat -- claude` 和 `ccwhat -- codex`
- **THEN** 系统 SHALL 为两个进程创建不同 `run_id`
- **AND** 两个 run SHALL 写入不同 runtime run 目录
- **AND** 两个 run SHALL 不共享 active_task_id

### Requirement: Runtime ports are allocated per Codex run
系统 SHALL 在未显式指定端口时为每个 Codex runtime run 自动分配可用 proxy、viewer 和 control 端口。

#### Scenario: Codex 自动分配端口
- **WHEN** 用户执行 `ccwhat -- codex` 且未传入 `--port` 或 `--web-port`
- **THEN** 系统 SHALL 自动选择可用 proxy 端口
- **AND** 系统 SHALL 自动选择可用 viewer 端口
- **AND** 系统 SHALL 自动选择可用 control 端口
- **AND** 最终端口 SHALL 写入 `run.json`

#### Scenario: Codex 保留显式端口
- **WHEN** 用户执行 `ccwhat --port 7790 --web-port 7791 -- codex`
- **THEN** 系统 SHALL 使用用户指定的 proxy 和 viewer 端口
- **AND** 系统 SHALL 在端口不可用时报错

### Requirement: Codex runtime control evidence is recorded
系统 SHALL 为每次 Codex CCWhat Task 控制命令写入 control event，并记录该命令是否对模型可见。

#### Scenario: Codex local command records high confidence evidence
- **WHEN** Codex slash command 被本地拦截并成功调用 controller
- **THEN** 系统 SHALL 在 `control_events.jsonl` 写入 command、raw_args、agent、integration、model_visible、agent_log_visible 和 confidence
- **AND** agent SHALL 为 `codex`
- **AND** integration SHALL 为 `codex_user_prompt_submit`
- **AND** model_visible SHALL 为 false
- **AND** confidence SHALL 为 high
