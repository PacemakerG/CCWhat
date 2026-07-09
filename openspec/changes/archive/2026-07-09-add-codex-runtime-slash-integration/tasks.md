## 1. Codex Integration 文件生成

- [x] 1.1 新增 Codex runtime integration 模块，定义 managed marker、version 和 command 列表。
- [x] 1.2 实现 Codex home prompt/command 文件生成，至少覆盖 start、finish、abort、status、note。
- [x] 1.3 实现 Codex `UserPromptSubmit` hook 配置生成或更新。
- [x] 1.4 实现 Codex integration 冲突检测，遇到非 CCWhat 管理文件不得覆盖。
- [x] 1.5 增加 Codex integration 文件生成、升级和冲突检测测试。

## 2. Codex Hook 与 Controller 路由

- [x] 2.1 新增 Codex hook entry point，解析 CCWhat marker prompt。
- [x] 2.2 Codex hook 调用 runtime controller，并传入 `agent=codex`、`integration=codex_user_prompt_submit`。
- [x] 2.3 Codex hook 成功或失败后返回 block payload，阻止 marker prompt 发送模型。
- [x] 2.4 增加 hook -> controller -> task staging 集成测试，验证 `model_visible=false` 和 Codex evidence。

## 3. `ccwhat -- codex` Wiring

- [x] 3.1 调整 `ccwhat -- codex` 启动流程，创建 runtime run、自动分配端口并启动 controller。
- [x] 3.2 启动 Codex 前 ensure Codex integration，并注入 runtime env。
- [x] 3.3 将 agent process、workspace、proxy/viewer/control 端口写入 `run.json`。
- [x] 3.4 增加 CLI 层测试，验证 `ccwhat -- codex` 创建 run、注入 env 并使用自动端口。

## 4. 验收文档与 OpenSpec 状态

- [x] 4.1 增加 Codex runtime MVP 手工验收说明。
- [x] 4.2 跑通目标测试，并确认 Plan 文档已记录 Codex-first、OpenCode-spike 的 Plan 2 切分。
- [x] 4.3 完成一次自动化端到端验收：通过 Codex hook 模拟 start/finish 后，确认 task staging 文件完整。
