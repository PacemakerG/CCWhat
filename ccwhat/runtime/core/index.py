"""GIT_INDEX_FILE based isolated git index for task boundary diff."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


class CCWhatIndexError(RuntimeError):
    """Error related to CCWhatIndex operations."""

    pass


class CCWhatIndex:
    """Isolated git index using GIT_INDEX_FILE.

    This class provides a staging area that is completely separate from the
    main git index, allowing us to snapshot the working tree for task boundary
    diff without polluting the user's working directory.
    """

    def __init__(self, workspace: Path, index_path: str = ".git/index.ccwhat") -> None:
        """Initialize CCWhatIndex.

        Args:
            workspace: Path to the git workspace
            index_path: Relative path to the isolated index file
        """
        self.workspace = Path(workspace)
        self.index_path = self.workspace / index_path
        self._env = {**os.environ, "GIT_INDEX_FILE": str(self.index_path)}

    def init(self) -> None:
        """Initialize index from HEAD plus current working-tree state.

        Creates a git index starting from HEAD commit's tree, then syncs the
        working tree so the baseline includes pre-existing uncommitted changes.
        """
        self._git_cmd(["read-tree", "HEAD"])
        self.sync_workspace()

    def sync_workspace(self) -> None:
        """Stage all working-tree changes into the isolated index.

        Uses ``git add -A`` with the isolated GIT_INDEX_FILE so the user's
        real index is never touched.
        """
        self._git_cmd(["add", "-A"])

    def write_tree(self) -> str:
        """Write the isolated index to a tree object and return its hash.

        Raises:
            CCWhatIndexError: If write-tree fails.
        """
        result = self._git_cmd(["write-tree"])
        if result.returncode != 0 or not result.stdout.strip():
            raise CCWhatIndexError(f"write-tree failed: {result.stderr}")
        return result.stdout.strip()

    def diff_cached(self, tree: str) -> str:
        """Generate diff between isolated index and *tree*.

        Uses ``git diff --cached --binary <tree>`` to compare the staged
        isolated index against the given tree hash (e.g. start_tree).

        Args:
            tree: Tree hash to diff against

        Returns:
            Unified diff (with binary support) as string
        """
        result = subprocess.run(
            ["git", "diff", "--cached", "--binary", tree],
            cwd=self.workspace,
            env=self._env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return result.stdout

    def _git_cmd(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess[Any]:
        """Run a git command with the isolated index.

        Args:
            args: Git command arguments
            check: Whether to check return code

        Returns:
            CompletedProcess instance
        """
        result = subprocess.run(
            ["git", *args],
            cwd=self.workspace,
            env=self._env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if check and result.returncode != 0:
            raise CCWhatIndexError(f"Git command failed: {result.stderr}")
        return result
