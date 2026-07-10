## Context

当前 `ccwhat/diagnosis/feedback.py` 的 `analyze_graph_feedback` 设计约束为"只调用一次 Analyzer"。真实用户运行时，Analyzer（Claude/Codex CLI）首次输出可能包含近似 JSON——结构正确但字符串内嵌了未转义的双引号字符。`parse_graph_attribution_output` 的 `json.loads` / `raw_decode` 在此场景下报 `Expecting comma delimiter` 错误，整个诊断降级为 `unavailable`，Viewer 无法展示任何结果。

实际上，首次输出的信息内容基本正确，仅 JSON 语法不合法。如果允许用一次专有格式修复小调用纠正语法，可以挽救大量本可用的诊断结果。

本 change 调整 Analyzer 调用流程为"一次主分析 + 最多一次格式修复调用"，且修复调用严格限定为纯 JSON 语法修复，不得引入新事实。

## Goals / Non-Goals

**Goals:**
- Analyzer 首次输出解析失败时，允许且仅允许一次格式修复子调用。
- 修复提示必须只修正 JSON 语法错误，不改变语义、不增加新事实。
- 修复提示携带原始输出和解析异常信息。
- 第二次解析仍非法则沿用现有 `_unavailable_result` 降级。
- 首次解析合法不产生第二次调用。
- 所有 Action/Event 引用仍然经过 `validate_graph_attribution_result`。
- 补测试覆盖三个场景：未转义引号首次失败后修复成功、首次合法只调用一次、第二次仍失败降级。

**Non-Goals:**
- 不增加超过一次额外的格式修复调用（即最多两次 Analyzer 总调用）。
- 不改动 `parse_graph_attribution_output` 或 `validate_graph_attribution_result` 的签名或行为。
- 不引入新的依赖或外部库。
- 不改变 Analyzer Registry 或 `run_mc_analysis` 接口。
- 不修改 Viewer 前端代码。

## Decisions

### Decision: 修复调用复用现有 `run_mc_analysis` 管道

格式修复调用与主分析调用使用相同的 `run_mc_analysis()` 函数和相同的 CLI 上下文（analyzer_cmd/agent/timeout/runner）。不创建新的 MCP 或 API 调用路径。

**替代方案考虑：**
- 使用纯本地字符串修复器（正则/简单替换）：不可靠，无法处理模型输出的复杂嵌套字符串。
- 使用内联修复（在同一个子进程中追加提示语）：需要侵入 `run_mc_analysis` 签名，与现有抽象不一致。

**选择：** 复用 `run_mc_analysis`。修复提示是独立的 prompt 文本，调用即可。

### Decision: 修复提示通过新 asset 文件承载

创建 `ccwhat/assets/graph_attribution_fix_prompt.md` 作为独立 asset 文件，与主提示 `graph_attribution_prompt.md` 平行。提示内容：
- 要求只修正 JSON 语法错误，不改变语义、不增加字段。
- 说明错误类型（Expecting comma delimiter 等），附上原始输出。
- 输出必须是合法 JSON 对象（与主提示相同的 schema 约束）。
- 必须在 ```json ... ``` fence 内输出。

**替代方案考虑：**
- 硬编码在 feedback.py 中：可行，但违背项目一致风格（主提示使用 asset 文件）。
- 复用主提示并附加指令：混入原本的诊断请求，可能诱导模型重新分析而非仅修语法。

**选择：** 独立 asset 文件。

### Decision: 修复流程嵌入 `analyze_graph_feedback` 内部

格式修复逻辑作为 `analyze_graph_feedback` 内的 try/except 扩展，不提取为独立函数。原因是：
- 调用路径完全绑定于 `analyze_graph_feedback` 的 try/except 结构。
- 提取新函数会增加一次重试所需的参数传递复杂度（prompt、raw 输出、错误信息），且没有其他地方复用此逻辑。
- 保持改动外科手术式——只改变一处函数的控制流。

**流程伪代码：**
```
def analyze_graph_feedback(...):
    raw, elapsed_ms = run_mc_analysis(...)      # 主分析
    try:
        parsed = parse_graph_attribution_output(raw)
    except ValueError as exc:
        fix_prompt = build_fix_prompt(raw, exc)  # 格式修复提示
        fixed_raw, _ = run_mc_analysis(...)      # 格式修复调用
        try:
            parsed = parse_graph_attribution_output(fixed_raw)
        except ValueError as exc2:
            return _unavailable_result(...)       # 第二次仍失败，降级
    result = validate_graph_attribution_result(parsed, ...)  # 校验引用
    ...
```

### Decision: 原有设计约束从"一次主分析调用"更新为"一次主分析加最多一次格式修复调用"

对应更新 design.md 中的相关描述，确保设计文档与实际行为一致。

## Risks / Trade-offs

- **[开销]** 格式修复调用消耗一次附加的模型推理（约一次 round trip）。但仅在首次解析失败时发生，正常路径无额外开销。对于需要修复的 case，增加一次 token 消耗换取完整诊断结果的价值更为重要。
- **[修复失败]** 二次修复仍可能失败。设计明确在此情况下降级，避免无限重试循环。
- **[修复污染]** 修复提示可能引导模型重写而非仅修语法。通过严格要求"只修正 JSON 语法，不改变语义、不新增字段"并将这个约束写入 prompt asset 来缓解。
- **[可测试性]** 测试需要模拟一次错误输出和一次修复输出。可以通过 `runner` 参数控制行为：第一次返回非法 JSON，第二次返回合法 JSON。
