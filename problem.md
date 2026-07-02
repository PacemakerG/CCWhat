# 缺失依赖记录

## 问题

2026-07-03 从 GitHub 拉取最新代码后，访问 Viewer 的甘特图页面（`/session-gantt`）报错：

```
ModuleNotFoundError: No module named 'claude_code_log'
```

## 原因

甘特图功能（`viewer/server.py`）引入了依赖包 `claude-code-log`，但该包**未写入 `pyproject.toml` 的 `dependencies` 列表**。

因此无论 `install.sh` 一键安装还是 `uv sync`，都不会自动安装这个包。

## 影响范围

- 拉取了包含甘特图功能的代码但未手动安装 `claude-code-log` 的人
- 不影响 Viewer 的 Session 页、Timeline 页等其他功能

## 临时解决

```bash
uv pip install claude-code-log
```

## 根本修复

在 `pyproject.toml` 的 `[project] dependencies` 中加上 `"claude-code-log"`。
