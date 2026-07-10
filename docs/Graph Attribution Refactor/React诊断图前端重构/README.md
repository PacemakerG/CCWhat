# React 诊断图前端重构方案

## 1. 结论

React 诊断图不做成需要跳转的独立页面，也不通过 iframe 嵌入。

第一阶段采用 **React Island（React 子应用）**：

```text
现有 Viewer 外壳
├── Session 列表
├── Task / Turn 导航
├── Detail 主区域
│   ├── 原始 Trace
│   ├── Task Detail
│   └── Graph Diagnosis   ← React 子应用挂载在这里
└── 现有主题、语言和全局状态
```

也就是说：

- 用户仍然留在现有 Detail 界面中；
- 点击 `Graph Diagnosis` Tab 后，在当前 Detail 区域直接展示 React 图界面；
- 不打开新页面，不改变用户当前 Session/Task 上下文；
- 后续如果 React 方案稳定，再逐步将整个 Viewer 迁移为 React。

---

## 2. 为什么不先重写整个 Viewer

当前 Viewer 已经承担：

- Session 选择；
- Task/Turn 展示；
- 原始日志查看；
- 搜索、主题、语言；
- 多种已有诊断和导出功能。

一次性整体重写会同时引入大量与 Graph Diagnosis 无关的迁移工作，也容易造成已有功能回归。

因此采用以下边界：

```text
旧前端：继续负责产品外壳和已有功能
React：先负责最复杂、最需要交互能力的诊断图
```

这样可以直接在新架构上实现钻取能力，避免先在旧的单文件 JavaScript 中实现一遍，再在 React 中重写一遍。

---

## 3. 页面入口

在现有 Detail 区域增加一个 Tab：

```text
Trace | Task Detail | Graph Diagnosis | Diagnosis Report
```

点击 `Graph Diagnosis` 时，显示：

```html
<div id="graph-diagnosis-root"></div>
```

React 应用挂载到这个容器：

```ts
createRoot(document.getElementById("graph-diagnosis-root")!).render(
  <GraphDiagnosisApp context={context} />
)
```

当前页面的 Session、Task、Change 等上下文通过明确的数据接口传给 React，而不是让 React 自己从 DOM 中反向解析。

建议上下文：

```ts
interface GraphDiagnosisContext {
  sessionId?: string;
  taskId?: string;
  changeName: string;
  locale: "zh" | "en";
  theme: "light" | "dark";
}
```

---

## 4. 前端整体布局

```text
┌──────────────────────────────────────────────────────────────┐
│ Change / 搜索 / 过滤 / 诊断状态 / Fit View / 返回总览       │
├───────────────────────────────────────────────┬──────────────┤
│                                               │              │
│                                               │  Node        │
│              Graph Canvas                     │  Inspector   │
│                                               │              │
│                                               │              │
├───────────────────────────────────────────────┴──────────────┤
│ Timeline / Evidence Coverage / Diagnosis Path                │
└──────────────────────────────────────────────────────────────┘
```

核心区域分为四部分：

1. 顶部工具栏；
2. 中央单一 Graph Canvas；
3. 右侧节点详情面板；
4. 底部时间轴和诊断证据状态。

---

## 5. 单画布钻取设计

后端仍然保留两层数据：

```text
Action Run Graph
Event Evidence Graph
```

但前端只展示一个画布。

### 5.1 默认视图：Action Run Graph

```text
Proposal → Specs → Design → Tasks → Apply#1 → Verify#1
                                      ↓
                                   Apply#2 → Verify#2
```

粗图采用稳定的从左到右布局，重点展示：

- Action Run 类型；
- 执行序号；
- 状态；
- Event 数量；
- 输入/输出产物数量；
- 是否命中诊断候选；
- 证据覆盖情况。

粗图不能使用完全随机的力导向布局，否则用户无法快速理解工作流顺序。

### 5.2 点击 Action：原地钻取

点击 `Apply#2` 后：

1. 镜头平滑聚焦到该节点；
2. 其他 Action 节点降低透明度；
3. `Apply#2` 展开为一个 Action 容器；
4. 容器内部加载该 Action Run 对应的 Event Evidence 子图；
5. 保留和当前 Symptom 有关的跨 Action 证据边。

```text
┌──────────────────── Apply #2 ────────────────────┐
│                                                  │
│ Read Spec → Edit File → Artifact V2              │
│                              ↓                   │
│                          Run Test → Failed        │
│                              ↓                   │
│                          Edit File → Passed       │
│                                                  │
└──────────────────────────────────────────────────┘
```

左上角显示面包屑：

```text
add-auth / Apply #2
```

点击 `add-auth` 返回 Action 总览。

### 5.3 不是简单隐藏另一张图

钻取不是把原来的两张图做成 Tab 切换，而是同一画布的语义缩放：

```text
Change 总览
  ↓ 点击 Action Run
Action 内部 Event 子图
  ↓ 点击 Event/Artifact
具体证据详情
```

---

## 6. 图的视觉风格

整体参考 Obsidian Graph View 的动态感，但不能完全照搬随机漂浮的布局。

### 6.1 Action 层

- 使用圆角卡片节点；
- 固定工作流方向；
- 允许轻微拖动，但自动吸附回层级布局；
- Apply/Verify 多轮循环清晰分叉；
- 状态使用边框、图标和小标签表达，不只依赖颜色。

### 6.2 Event 层

- Event 使用较小的圆形或胶囊节点；
- 时间总体从左到右；
- 同一文件和同一 Artifact 相关节点自然聚集；
- Tool Call 与 Tool Result 靠近；
- Requirement、Artifact、Outcome 作为外围证据节点；
- 节点拖动后有轻微弹性回弹；
- 每次重新加载保持稳定位置，不能完全随机变化。

### 6.3 边的表达

```text
next_in_agent          灰色实线
reads / writes         普通关系线
validates              带方向关系线
supports               强调线
contradicts            警告线
inferred relationship  虚线
诊断主链               高亮动态流线
```

时间相邻关系和因果/证据关系必须视觉区分。

---

## 7. 右侧 Node Inspector

点击任意节点后，右侧显示结构化详情。

例如 `file_edit`：

```text
节点：E42
类型：file_edit
所属 Action：Apply #2
文件：viewer/router.js
时间：18:32:14

Summary
Tool Input
Diff / Artifact Version
Tool Result
关联 Requirement
关联 Validation Outcome
支持/反驳证据
原始 Session 引用
```

点击原始 Session 引用后，回到现有 Trace 页面并定位到对应事件，而不是在 React 中重新实现一套完整日志查看器。

---

## 8. 诊断结果在图上的展示

用户提交反馈后：

```text
用户反馈
  ↓
Symptom Router
  ↓
Top-K Action Run
  ↓
Evidence 子图
  ↓
Cause Hypotheses
```

前端表现：

1. 在 Action 总览中高亮 Top-K Action Run；
2. 节点显示候选原因和 evidence tier；
3. 点击候选 Action 自动钻取；
4. Event 子图只突出诊断相关节点和证据链；
5. 右侧面板展示主要原因、促成原因、反证和下一步验证；
6. 支持一键切换“全部节点 / 仅诊断相关节点”。

不能只把一段大模型报告放在图旁边，诊断结果必须能够定位到真实的 Action、Event、Artifact 和 Outcome。

---

## 9. 技术选型

### 9.1 基础技术

```text
React
TypeScript
Vite
React Flow
ELK 或 Dagre
D3 Force（仅用于 Event 层动态布局）
```

### 9.2 布局职责

```text
Action Run Graph：ELK / Dagre，稳定层级布局
Event Evidence Graph：时间约束 + D3 Force，轻度动态关系布局
React Flow：统一画布、节点、边、缩放、拖动和交互
```

不要让 D3 Force 直接控制整个 Action 流程图；它只负责 Event 层的动态聚集效果。

### 9.3 为什么选择 React Flow

- Action 节点需要复杂卡片内容；
- 支持自定义 Node 和 Edge；
- 容易实现选中、缩放、拖动、MiniMap 和 Controls；
- 适合实现 Action 容器和内部 Event；
- 和右侧 Inspector、过滤器、诊断状态联动更直接。

---

## 10. 工程目录建议

```text
viewer/
├── claude-log.html                 # 现有 Viewer 外壳，第一阶段保留
├── graph-diagnosis/                # React 源代码
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── main.tsx
│   │   ├── GraphDiagnosisApp.tsx
│   │   ├── api/
│   │   ├── components/
│   │   │   ├── GraphCanvas.tsx
│   │   │   ├── GraphToolbar.tsx
│   │   │   ├── NodeInspector.tsx
│   │   │   ├── DiagnosisPanel.tsx
│   │   │   └── GraphBreadcrumb.tsx
│   │   ├── graph/
│   │   │   ├── actionLayout.ts
│   │   │   ├── eventLayout.ts
│   │   │   ├── graphAdapter.ts
│   │   │   └── graphStyles.ts
│   │   ├── nodes/
│   │   ├── edges/
│   │   ├── stores/
│   │   └── types/
│   └── tests/
└── static/graph-diagnosis/         # Vite 构建产物
```

生产构建后，由现有 `viewer/server.py` 继续提供静态资源和 API。

---

## 11. 旧 Viewer 与 React 的通信

建议暴露明确挂载接口：

```ts
window.CCWhatGraphDiagnosis.mount(element, context)
window.CCWhatGraphDiagnosis.updateContext(context)
window.CCWhatGraphDiagnosis.unmount()
```

旧 Viewer 在用户切换 Session、Task 或 Change 时，只调用 `updateContext()`。

React 需要跳回原始 Trace 时，向外发送事件：

```ts
window.dispatchEvent(
  new CustomEvent("ccwhat:navigate-to-event", {
    detail: { sessionId, eventId, rawRef }
  })
)
```

旧 Viewer 监听该事件并完成页面切换和日志定位。

这样两部分通过稳定接口通信，不直接互相操作内部 DOM。

---

## 12. API 边界

React 页面主要调用：

```text
GET  /api/openspec-graph/<change>
POST /api/openspec-graph-diagnose
```

后续建议拆分为：

```text
GET  /api/diagnosis/changes/<change>/overview
GET  /api/diagnosis/changes/<change>/actions/<action-run-id>/evidence
GET  /api/diagnosis/nodes/<node-id>
POST /api/diagnosis/changes/<change>/run
```

目的：

- 默认只加载 Action 总览；
- 用户点击 Action 后再加载局部 Event 子图；
- 避免一次把完整 Evidence Graph 全部传到浏览器；
- 支持后续大型任务和多 Agent Trace。

---

## 13. 分阶段实现

### Phase 1：React 岛接入

- 创建 React + TypeScript + Vite 工程；
- 在现有 Detail 区域增加 Graph Diagnosis Tab；
- 完成主题、语言和上下文传递；
- 加载并展示静态 Action Run Graph。

### Phase 2：单画布钻取

- Action 总览；
- 点击 Action 原地展开 Event 子图；
- 面包屑返回；
- 镜头动画、节点拖动和 Fit View；
- 右侧 Node Inspector。

### Phase 3：诊断联动

- Top-K Action 高亮；
- Cause Hypothesis 证据链高亮；
- 仅显示诊断相关节点；
- 从节点返回原始 Session；
- Evidence Coverage 和缺失证据提示。

### Phase 4：逐步替换旧前端

React Graph Diagnosis 稳定后，再评估迁移：

- Detail 外壳；
- Session/Task 导航；
- Trace Viewer；
- 搜索和全局状态。

不要求第一阶段同时完成整个 Viewer 重写。

---

## 14. 验收标准

1. 用户不离开当前 Detail 页面即可打开诊断图；
2. 默认只看到清晰的 Action Run 总览；
3. 点击 Action 能在同一画布钻取 Event Evidence 子图；
4. 能从 Event 回到所属 Action 和原始 Session；
5. 诊断结果能高亮真实证据链；
6. 右侧面板能展示 Tool Input/Result、Diff、Requirement 和 Outcome；
7. 旧 Viewer 的已有功能不受影响；
8. React 模块和旧页面通过明确接口通信，不互相直接修改内部 DOM；
9. 后端粗图、细图仍保持独立数据模型，前端只在交互层合并展示；
10. 后续能够在不推翻 Graph Diagnosis 的前提下继续把整个 Viewer 迁移到 React。

---

## 15. 最终定义

> React 诊断图作为一个子应用嵌入现有 Detail 页面。后端保留 Action Run Graph 和 Event Evidence Graph 两层模型，前端使用一个 React Flow 画布完成 Action 总览、Event 钻取、证据查看和诊断高亮。第一阶段只重构诊断图，不跳转、不使用 iframe，也不强制一次性重写整个 Viewer。