# 图归因诊断流程

```text
程序生成 Action Graph、Event Graph 和 precheck_findings
  -> 本地诊断 Agent 读取图路径、OpenSpec change 目录和用户反馈
  -> Agent 返回 suspicious_actions / suspicious_events 和证据引用
  -> 后端校验 Action、Event、precheck_finding 和文档引用
  -> 前端高亮可疑 Action 粗节点，并下钻到可疑 Event
```

- `precheck_findings` 是 P0 程序规则确认的显性异常事实。
- `suspicious_actions` 和 `suspicious_events` 是主要诊断结果。
- `precheck_finding_ids` 和 `document_refs` 只是可疑 Action 的诊断依据。

后端只校验引用是否真实存在，不判断模型结论是否正确。OpenSpec 文档和 `precheck_finding` 不会成为图节点或同级诊断对象。
