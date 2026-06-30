# 发布流程

本文档是每次发版时的操作手册。按顺序执行，不要跳步。

---

## 一、版本号规则

遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)：

```
v<MAJOR>.<MINOR>.<PATCH>

MAJOR  不兼容的 API 变更
MINOR  向后兼容的新功能
PATCH  向后兼容的 bug 修复
```

**示例**：`v2.3.2`

---

## 二、发布前：需要更新的文件清单

每次发版必须同步更新以下文件，缺一不可：

| 文件 | 更新内容 | 时机 |
|------|---------|------|
| `pyproject.toml` | `version` 字段 | 改版本号时 |
| `CHANGELOG.md` | 新增版本条目 | 写完所有改动后 |
| `README.md` | 顶部 Changelog 链接的版本号 + `v2 版本演进` 章节 | minor/major 发版 |

---

## 三、逐文件操作说明

### 3.1 `pyproject.toml` — 更新版本号

找到 `version` 字段，直接改数字：

```toml
[project]
name = "ccwhat"
version = "2.3.2"   # ← 改这里
```

改完后验证：

```bash
uv run ccwhat --version
# 应输出新版本号
```

---

### 3.2 `CHANGELOG.md` — 写新版本条目

在文件**最顶部**（现有内容之前）插入新条目。标准格式如下（以 PR #3、PR #8 为准）：

```markdown
## v<version> - <YYYY-MM-DD>

### <本次发布的主题标题，一句话>

一段话说明这次改动的背景或动机（1-2 句，简洁，不展开细节）。

### 新增

- **`功能名`**：做了什么（一句话）

### 修复

- 修复了 XXX 在 YYY 时崩溃的问题

### 改进

- `module.py`：调整了 XXX 行为

### 贡献者

本版本 XXX 能力由 [@username](https://github.com/<username>) 贡献，详见 [PR #N](https://github.com/PacemakerG/CCWhat/pull/<N>)。

---
```

**格式规范**：
- 日期用当天日期，格式 `YYYY-MM-DD`
- 主题标题下一行写 1-2 句简述，概括这次 PR 做了什么，不展开技术细节
- 每条条目加粗关键词，后跟冒号和说明，一句话为限，不冗长
- issue / PR 引用必须写成可点击链接：`[#7](https://github.com/PacemakerG/CCWhat/issues/7)`、`[PR #9](https://github.com/PacemakerG/CCWhat/pull/9)`，不要写纯文本 `#7`
- 用户名必须写成可点击链接：`[@Sugarfarmeriod](https://github.com/Sugarfarmeriod)`，不要写纯文本 `@Sugarfarmeriod`
- 条目之间用 `---` 水平线分隔

**贡献者栏规范**：
- 贡献者栏固定放在版本条目**最末尾**，独立一节，标题叫 `### 贡献者`
- **不在每条新增/修复/改进后重复署名**，只在末尾贡献者栏写一次
- 固定句式：`本版本 <功能名> 能力由 [@username](url) 贡献，详见 [PR #N](url)。` 或 `感谢 [@username](url)（[PR #N](url)）`
- **只有别人合并进来的 PR 才标贡献者**。maintainer 自己的提交（含 Claude 代 maintainer 做的 review 修复）不标贡献者栏
- 如果一个版本只有 maintainer 自己的改动，没有外部 PR，则**不写贡献者栏**
- 如果同一版本有多个外部贡献者，在贡献者栏分行写

---

### 3.3 `README.md` — 两处更新

**第一处：顶部 Changelog 链接**（第 21 行附近）

```markdown
<a href="./CHANGELOG.md">v2.3.2</a> ·
```

把版本号改成新版本号。

**第二处：`v2 版本演进` 章节**（仅 minor 及以上版本发版时更新）

规则：
- 把新 minor 版本加到最顶部，标注 `— 当前版本`
- 把上一个 minor 版本的 `— 当前版本` 标记去掉
- patch 版本（如 v2.3.1 → v2.3.2）不需要新增一行，在现有 minor 条目里补充即可

```markdown
## 📈 v2 版本演进

**v2.4** — 当前版本        ← 新加

- 新功能描述 1
- 新功能描述 2

**v2.3**                   ← 去掉"— 当前版本"标记

- ...
```

---

## 四、发布操作

### 4.1 本地验证

```bash
# 确认版本号一致
grep 'version' pyproject.toml
grep 'v2\.' README.md | head -5
head -5 CHANGELOG.md

# 跑测试
uv run python -m unittest
```

### 4.2 提交并打 Tag

```bash
git add pyproject.toml CHANGELOG.md README.md
git commit -m "chore: release v<version>"
git tag v<version>
git push origin main
git push origin v<version>
```

### 4.3 GitHub Release（可选）

在 GitHub 仓库页面 → Releases → Draft a new release：
- Tag：选刚打的 `v<version>`
- Title：`v<version> — <主题>`
- Body：直接粘贴 CHANGELOG.md 里对应条目的内容

---

## 五、接收 PR 时如何标记贡献者

### 5.1 Merge commit 里加 Co-authored-by

合并 PR 时，在 merge commit message 里加上共同作者行：

```
chore: merge PR #42 - add attribution diagnosis engine

Co-authored-by: 贡献者名字 <贡献者邮箱>
```

GitHub 识别 `Co-authored-by:` 格式后，会自动在 commit 页面和 contributor 列表里显示贡献者头像。

贡献者的邮箱获取方式：
- 对方的 GitHub profile → 公开邮箱
- 或用 `<username>@users.noreply.github.com`（GitHub 匿名邮箱，始终有效）

### 5.2 CHANGELOG.md 里注明

按 3.2 节的规范，在版本条目**末尾**写独立的 `### 贡献者` 栏，不要在每条新增/修复后重复署名：

```markdown
### 贡献者

本版本 XXX 能力由 [@contributor-name](https://github.com/<contributor-name>) 贡献，详见 [PR #N](https://github.com/PacemakerG/CCWhat/pull/<N>)。
```

**注意**：
- 只有外部贡献者的 PR 才写贡献者栏。maintainer 自己的提交（含 Claude 代 maintainer 做的修复）不写
- 一个版本只有 maintainer 自己的改动时，整个条目不出现贡献者栏

### 5.3 操作顺序

```
1. 审核 PR，在 GitHub 页面 Review
2. 合并时选择 "Squash and merge" 或 "Create a merge commit"
3. 在 commit message 里加 Co-authored-by
4. 在 CHANGELOG.md 对应版本条目末尾写 ### 贡献者 栏（带可点击链接）
5. 照常走发布流程（打 tag、push）
```

### 5.4 不需要做的事

- 不需要维护单独的 `CONTRIBUTORS.md`（GitHub 的 Contributors 页面自动统计）
- 不需要在 README 里加贡献者头像墙（除非项目到了需要这么做的规模）
- 不需要在 CHANGELOG 每条新增/修复后重复署名，只在末尾贡献者栏写一次

---

### 5.5 PR 内容需要本地修复后再合并

当 PR 整体方向可接受，但 review 发现需要小幅修复（无关改动、bug、缺测试等），且修复仍想归在贡献者名下时，走这个流程：

**前提**：PR 勾选了 "Allow edits from maintainers"（PR 页面右侧栏可见，默认勾选）。可在 GitHub API 查 `maintainer_can_modify` 字段确认。

**操作步骤**：

```bash
# 1. 拉取 PR 分支到本地
git fetch origin pull/<N>/head:pr-<N>
git checkout pr-<N>

# 2. 在 PR 分支上 apply 修复（不是在 main 上）
#    编辑文件、跑测试、commit
git add -A
git commit -m "fix: address review feedback on PR #<N>"

# 3. push 到贡献者的 fork 分支（maintainer_can_modify=true 时允许）
git push git@github.com:<贡献者>/<repo>.git HEAD:<PR 源分支名>
# 例如：git push git@github.com:Sugarfarmeriod/CCWhat.git HEAD:feature/windows-full-support

# 4. 回到 GitHub 页面，对 PR 点 "Squash and merge"
#    - squash commit 的 author = PR 贡献者（GitHub 自动）
#    - 在 squash message 里追加 review 修复说明 + Co-authored-by: <修复者>

# 5. 切回 main 拉取合并结果
git checkout main
git pull origin main
```

**为什么不在本地 main 上 squash**：那样 commit author 会变成 maintainer 自己，贡献者在 git history 里消失。push 到 PR 分支再 squash merge，author 才是贡献者。

**如果 PR 没勾选 Allow edits**：只能走兜底方案——本地 main 做 squash commit（author = maintainer），在 commit message 里写 `Based on PR #<N> by @<贡献者>`，并 close PR 时留言说明。贡献者不会出现在 GitHub contributor 统计里，但 release notes 可署名。

---

## 六、发版前核对清单

发版前确认以下各项均已完成：

- `pyproject.toml` 的 version 已更新
- `CHANGELOG.md` 顶部已插入新版本条目，日期正确
- `README.md` 顶部链接版本号已更新
- `README.md` v2 版本演进章节已更新（minor/major 版本时）
- `uv run ccwhat --version` 输出正确
- 测试全部通过
- git tag 已打，已 push
- 如有 PR 贡献者，Co-authored-by 和 CHANGELOG 已注明
- 检查历史版本无漏 tag：`git tag --sort=-v:refname | head` 对比 `pyproject.toml` 历史版本号，确认每个发布版本都有对应 tag
