"""Worktree manager: per-task isolated git working trees backed by shared bare mirrors.

For each Task, `prepare()` materializes a clean worktree checked out at
`task.base_sha` under the caller-supplied run dir. Repositories are mirrored
once into a local cache (`~/.cache/coding-agent-compare/repos/<owner>__<repo>.git`)
and reused across worktrees via `git worktree add`. A POSIX file lock serializes
worktree adds on the same mirror so concurrent runs don't race the bare repo's
`worktrees/` directory.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

from harness.task import Task

DEFAULT_CACHE_ROOT = Path.home() / ".cache" / "coding-agent-compare" / "repos"


class WorktreeError(RuntimeError):
    """Raised for any failure inside the worktree manager."""


class WorktreeManager:
    def __init__(self, cache_root: Path | None = None) -> None:
        self.cache_root = Path(cache_root) if cache_root else DEFAULT_CACHE_ROOT

    def prepare(self, task: Task, run_dir: Path) -> Path:
        """Prepare a clean worktree at `run_dir/repo` checked out at `task.base_sha`.

        Returns the absolute path to the worktree. Idempotent enough to be safe to
        re-run if the run dir was cleaned: an existing worktree at the target path
        is removed and recreated.
        """
        run_dir = Path(run_dir).resolve()
        worktree = run_dir / "repo"
        mirror = self._mirror_path(task.repo_url)

        run_dir.mkdir(parents=True, exist_ok=True)
        self.cache_root.mkdir(parents=True, exist_ok=True)

        with self._lock(mirror):
            if not mirror.exists():
                self._git_clone_bare(task.repo_url, mirror)
            if not self._has_commit(mirror, task.base_sha):
                self._git_fetch(mirror)
                if not self._has_commit(mirror, task.base_sha):
                    raise WorktreeError(
                        f"commit {task.base_sha} not found in {task.repo_url} even after fetch"
                    )
            # If the worktree dir already exists, remove and recreate. We can't
            # trust its state.
            if worktree.exists():
                self._remove_worktree(mirror, worktree)
            self._git_worktree_add(mirror, worktree, task.base_sha)

        return worktree

    def cleanup(self, worktree_path: Path) -> None:
        """Remove a worktree previously created by `prepare()`.

        Refuses to operate on a path that doesn't look like one of our worktrees
        (no `.git` file linking back to a bare mirror's `worktrees/` directory).
        Prunes the mirror's stale worktree record afterwards.
        """
        worktree = Path(worktree_path).resolve()
        mirror = self._mirror_for_worktree(worktree)
        if mirror is None:
            raise WorktreeError(
                f"refusing to clean up {worktree}: not a managed worktree "
                f"(no .git → <mirror>/worktrees/* link found)"
            )
        with self._lock(mirror):
            self._remove_worktree(mirror, worktree)

    # ----- internals -------------------------------------------------------

    def _mirror_path(self, repo_url: str) -> Path:
        owner, repo = _parse_owner_repo(repo_url)
        return self.cache_root / f"{owner}__{repo}.git"

    @staticmethod
    def _has_commit(mirror: Path, sha: str) -> bool:
        result = subprocess.run(
            ["git", "-C", str(mirror), "cat-file", "-e", sha],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0

    @staticmethod
    def _git_clone_bare(repo_url: str, mirror: Path) -> None:
        mirror.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", "--bare", "--quiet", repo_url, str(mirror)])

    @staticmethod
    def _git_fetch(mirror: Path) -> None:
        _run(["git", "-C", str(mirror), "fetch", "--quiet", "--all"])

    @staticmethod
    def _git_worktree_add(mirror: Path, worktree: Path, sha: str) -> None:
        worktree.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "-C", str(mirror), "worktree", "add", "--detach", str(worktree), sha])

    @staticmethod
    def _remove_worktree(mirror: Path, worktree: Path) -> None:
        # 'git worktree remove' may fail if the dir has been moved/corrupted;
        # fall back to direct removal + prune so cleanup is robust.
        subprocess.run(
            ["git", "-C", str(mirror), "worktree", "remove", "--force", str(worktree)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if worktree.exists():
            shutil.rmtree(worktree, ignore_errors=True)
        subprocess.run(
            ["git", "-C", str(mirror), "worktree", "prune"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    @staticmethod
    def _mirror_for_worktree(worktree: Path) -> Path | None:
        """Inspect <worktree>/.git to find the bare mirror it belongs to.

        A git worktree's `.git` is a file containing 'gitdir: <mirror>/worktrees/<name>'.
        We reject anything else as a safety check against accidental deletes.
        """
        dotgit = worktree / ".git"
        if not dotgit.is_file():
            return None
        try:
            content = dotgit.read_text()
        except OSError:
            return None
        if not content.startswith("gitdir:"):
            return None
        gitdir = Path(content.split(":", 1)[1].strip()).resolve()
        # Expected: <mirror>/worktrees/<name>. Walk two parents back to the mirror.
        if gitdir.parent.name != "worktrees":
            return None
        mirror = gitdir.parent.parent
        if not mirror.exists() or mirror.suffix != ".git":
            return None
        return mirror

    @contextmanager
    def _lock(self, mirror: Path):
        """Advisory exclusive lock on a sentinel file per mirror.

        Uses fcntl on POSIX. On Windows the lock is a no-op for now — concurrent
        worktree adds against the same mirror are not expected in the smoke phase,
        and a portable locking story will land alongside Windows runner work later.
        """
        lock_path = self.cache_root / f"{mirror.name}.lock"
        self.cache_root.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            # Touch the sentinel for visibility but skip the OS-level lock.
            lock_path.touch(exist_ok=True)
            yield
            return
        import fcntl

        with open(lock_path, "w") as fp:
            fcntl.flock(fp.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fp.fileno(), fcntl.LOCK_UN)


def _parse_owner_repo(repo_url: str) -> tuple[str, str]:
    """Extract '<owner>/<repo>' from a GitHub-style URL or file path."""
    parsed = urlparse(repo_url)
    path = parsed.path if parsed.scheme else repo_url
    # Strip trailing .git and leading slash.
    if path.endswith(".git"):
        path = path[: -len(".git")]
    path = path.strip("/")
    parts = path.split("/")
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    # file:///some/local/repo.git → single segment; fall back to a single bucket.
    return "_local", parts[-1] or "repo"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        raise WorktreeError(
            f"command failed ({result.returncode}): {' '.join(cmd)}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result
