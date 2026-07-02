"""Tests for CCWhatIndex git isolation."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from ccwhat.runtime.core.index import CCWhatIndex


def _init_repo(path: Path) -> None:
    """Initialize a git repo with initial commit."""
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    (path / "README.md").write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, capture_output=True)


def _user_staged_files(workspace: Path) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=workspace,
        text=True,
        capture_output=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def test_ccwhat_index_isolated_from_main_index():
    """CCWhatIndex operations do not affect the user's main git index."""
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        _init_repo(workspace)
        user_index_before = (workspace / ".git" / "index").read_bytes()

        index = CCWhatIndex(workspace)
        index.init()
        (workspace / "new_file.py").write_text("content\n", encoding="utf-8")
        index.sync_workspace()

        # User's main index should not see the new file staged
        assert "new_file.py" not in _user_staged_files(workspace)
        # User's main index bytes unchanged
        assert (workspace / ".git" / "index").read_bytes() == user_index_before
        # Isolated index file exists
        assert (workspace / ".git" / "index.ccwhat").exists()


def test_ccwhat_index_write_tree_and_diff_cached():
    """write_tree captures a snapshot; diff_cached shows changes vs that snapshot."""
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        _init_repo(workspace)

        index = CCWhatIndex(workspace)
        index.init()
        start_tree = index.write_tree()

        # Make changes: new file + modify existing
        (workspace / "src").mkdir()
        (workspace / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
        (workspace / "README.md").write_text("modified content\n", encoding="utf-8")
        index.sync_workspace()
        end_tree = index.write_tree()

        assert start_tree != end_tree
        diff = index.diff_cached(start_tree)
        assert "new file mode 100644" in diff
        assert "src/app.py" in diff
        assert "print('hello')" in diff
        assert "-initial" in diff
        assert "+modified content" in diff


def test_ccwhat_index_includes_untracked_files():
    """sync_workspace picks up untracked files without touching user index."""
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        _init_repo(workspace)

        index = CCWhatIndex(workspace)
        index.init()
        start_tree = index.write_tree()

        (workspace / "untracked.txt").write_text("new\n", encoding="utf-8")
        index.sync_workspace()
        diff = index.diff_cached(start_tree)
        assert "untracked.txt" in diff
        assert "new file mode 100644" in diff
        # user git status should still show it as untracked (?? ), not staged
        status = subprocess.run(
            ["git", "status", "--short"],
            cwd=workspace, text=True, capture_output=True,
        ).stdout
        assert "?? untracked.txt" in status


def test_ccwhat_index_init_includes_pre_existing_dirty_state():
    """init() syncs working tree so start_tree includes pre-existing dirty changes."""
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        _init_repo(workspace)

        # pre-existing dirty change before CCWhat starts
        (workspace / "uv.lock").write_text("dirty\n", encoding="utf-8")

        index = CCWhatIndex(workspace)
        index.init()
        start_tree = index.write_tree()

        # task-time change
        (workspace / "README.md").write_text("task change\n", encoding="utf-8")
        index.sync_workspace()
        diff = index.diff_cached(start_tree)

        # task diff should include README change but NOT the pre-existing uv.lock dirty
        assert "README.md" in diff
        assert "uv.lock" not in diff
