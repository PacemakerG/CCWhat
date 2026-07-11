## Why

当前 OpenSpec 图诊断把裁剪后的 Graph JSON 直接拼进 Prompt，显性错误和隐性错误都交给一次模型判断，既增加上下文噪声，也缺少稳定的程序化事实。P0 需要用最小改动将确定性显性检查与本地诊断 Agent 的语义判断分开。

## What Changes

- 新增极简 `precheck_findings`，只报告已执行阶段的明确产物缺失和基础验证问题。
- 将反馈诊断改为路径驱动：Prompt 只携带图文件路径、OpenSpec change 路径、用户反馈、`precheck_findings` 和输出契约。
- 允许本地诊断 Agent 只读 Action/Event Graph 与 OpenSpec 产物，自行定位隐性错误。
- 保留现有诊断 JSON、ID 校验、单次 Analyzer 调用和前端粗到细交互。
- 明确排除原始 Session、Diff、Git Snapshot、Runtime Task 和 Dataset 证据。

## Capabilities

### New Capabilities
- `graph-diagnosis-precheck`: 定义产物缺失和基础验证两个确定性 Precheck 及其极简 `precheck_finding` 契约。

### Modified Capabilities
- `action-graph-diagnosis`: 将用户反馈诊断从内嵌裁剪图上下文改为本地诊断 Agent 按受控路径只读图和 OpenSpec 产物。

## Impact

- 新增 `ccwhat/diagnosis/precheck.py`。
- 修改 `viewer/server.py`、`ccwhat/diagnosis/feedback.py` 和诊断 Prompt。
- 增加 Precheck、路径 Prompt、Analyzer 输出和兼容性测试。
- 不修改 Marker、图构建、Runtime Task、Dataset、Git 相关模块和 React 图交互。
