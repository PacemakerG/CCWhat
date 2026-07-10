你正在修正一次 OpenSpec 归因诊断的 JSON 输出。下方提供了原始诊断输出和 JSON 解析错误。

你的任务：只修正 JSON 语法错误，使其成为合法 JSON。不新增字段、不改变数据值、不修改已有的字段名或字段值。

约束：
- 保持原始输出的所有语义、字段结构和数据值不变。
- 只修复导致 JSON 解析失败的语法问题（如字符串中的未转义双引号、缺少逗号、括号不匹配等）。
- 不添加新的 symptoms、suspicious_actions、suspicious_events、missing_evidence 或任何其他字段。
- 不删除任何现有字段。
- 不在"summary"字段之外做任何解释。
- 输出必须是合法 JSON 对象，放在 ```json ``` 代码块内。

## 原始输出

```
{{original_output}}
```

## 解析错误

{{parse_error}}
