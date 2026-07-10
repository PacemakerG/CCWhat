# MVP 手动验收

## Mock

- Session ID：`22222222-3333-4444-8555-666666666666`
- OpenSpec change：`add-symptom-routed-graph-attribution`
- CC projects dir：`openspec/changes/add-symptom-routed-graph-attribution/mock-claude-projects`

Mock 中的隐藏问题：Apply 阶段把 Event 高亮查询范围从 `#openspecGraphContent` 错改成了 `#openspecGraphDiagnosisReport`，但 Verify 只运行静态 DOM 测试，没有执行真实点击行为。

## 生成 Session 图

```bash
uv run ccwhat openspec-graph sync \
  --change add-symptom-routed-graph-attribution \
  --session-id 22222222-3333-4444-8555-666666666666 \
  --projects-dir openspec/changes/add-symptom-routed-graph-attribution/mock-claude-projects
```

## 启动 Viewer

```bash
uv run ccwhat web \
  --port 7789 \
  --agent claude \
  --analyzer-agent codex \
  --projects-dir openspec/changes/add-symptom-routed-graph-attribution/mock-claude-projects
```

示例使用 Codex 作为一次性 Analyzer，因为本机 Claude CLI 可能尚未登录；这不改变 Claude Code 原始 Session 作为唯一日志数据源。若 Claude CLI 已登录，可以省略 `--analyzer-agent codex`。

## 前端操作

1. 选择 mock project 和 Session。
2. 打开“图诊断”。
3. 输入 change：`add-symptom-routed-graph-attribution`。
4. 点击“加载图”。
5. 输入反馈：

```text
诊断报告可以生成，但是点击可疑 Event 后细图没有高亮，也没有定位到对应节点。
```

6. 点击“生成诊断”。

预期：报告引用 Apply 的错误 Edit Event，并指出 Verify 只做静态测试、没有覆盖真实点击定位行为；点击报告中的 Action/Event 能高亮对应图节点。
