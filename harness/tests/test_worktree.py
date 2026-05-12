"""Tests for the worktree manager — uses local bare repos, no network."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness.task import Task
from harness.worktree import WorktreeError, WorktreeManager, _parse_owner_repo


def _git(*args: str, cwd: Path | None = None) -> str:
    """Run a git command; return stdout. Helper for test setup + assertions."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def local_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """Build a local non-bare repo with two commits, then a sibling bare clone.

    Returns (bare_repo_path, first_sha, second_sha). Tests use the bare path as
    a `file://` URL for Task.repo_url.
    """
    source = tmp_path / "source"
    source.mkdir()
    _git("init", "--quiet", "--initial-branch=main", cwd=source)
    _git("config", "user.email", "test@example.com", cwd=source)
    _git("config", "user.name", "test", cwd=source)
    (source / "README.md").write_text("v1\n")
    _git("add", "README.md", cwd=source)
    _git("commit", "--quiet", "-m", "first", cwd=source)
    first_sha = _git("rev-parse", "HEAD", cwd=source)

    (source / "README.md").write_text("v2\n")
    _git("commit", "--quiet", "-am", "second", cwd=source)
    second_sha = _git("rev-parse", "HEAD", cwd=source)

    bare = tmp_path / "owner__repo.git"
    _git("clone", "--bare", "--quiet", str(source), str(bare))
    return bare, first_sha, second_sha


def _task_for(bare_repo: Path, sha: str) -> Task:
    return Task(
        task_id="owner__repo-1",
        repo_url=f"file://{bare_repo}",
        base_sha=sha,
        prompt="",
        test_command="",
    )


def test_prepare_creates_worktree_at_requested_sha(tmp_path, local_repo):
    bare, first_sha, _ = local_repo
    cache = tmp_path / "cache"
    run_dir = tmp_path / "run"

    mgr = WorktreeManager(cache_root=cache)
    worktree = mgr.prepare(_task_for(bare, first_sha), run_dir)

    assert worktree == (run_dir / "repo").resolve()
    assert worktree.is_dir()
    assert (worktree / "README.md").read_text() == "v1\n"
    assert _git("rev-parse", "HEAD", cwd=worktree) == first_sha


def test_prepare_reuses_mirror_across_calls(tmp_path, local_repo):
    bare, first_sha, second_sha = local_repo
    cache = tmp_path / "cache"

    mgr = WorktreeManager(cache_root=cache)
    mgr.prepare(_task_for(bare, first_sha), tmp_path / "run1")
    mgr.prepare(_task_for(bare, second_sha), tmp_path / "run2")

    # Mirror cloned exactly once; two worktrees registered against it.
    mirrors = list(cache.glob("*.git"))
    assert len(mirrors) == 1
    worktrees_listing = _git("-C", str(mirrors[0]), "worktree", "list")
    # bare + 2 working trees = 3 entries
    assert len(worktrees_listing.splitlines()) == 3


def test_prepare_recreates_when_target_exists(tmp_path, local_repo):
    bare, first_sha, second_sha = local_repo
    cache = tmp_path / "cache"
    run_dir = tmp_path / "run"

    mgr = WorktreeManager(cache_root=cache)
    mgr.prepare(_task_for(bare, first_sha), run_dir)
    # Re-prepare at a different SHA into the same run_dir.
    worktree = mgr.prepare(_task_for(bare, second_sha), run_dir)
    assert _git("rev-parse", "HEAD", cwd=worktree) == second_sha


def test_prepare_raises_when_sha_missing(tmp_path, local_repo):
    bare, _, _ = local_repo
    cache = tmp_path / "cache"
    bad = "0" * 40
    mgr = WorktreeManager(cache_root=cache)
    with pytest.raises(WorktreeError, match="not found"):
        mgr.prepare(_task_for(bare, bad), tmp_path / "run")


def test_cleanup_removes_worktree(tmp_path, local_repo):
    bare, first_sha, _ = local_repo
    cache = tmp_path / "cache"
    run_dir = tmp_path / "run"

    mgr = WorktreeManager(cache_root=cache)
    worktree = mgr.prepare(_task_for(bare, first_sha), run_dir)
    assert worktree.exists()
    mgr.cleanup(worktree)
    assert not worktree.exists()


def test_cleanup_refuses_unmanaged_path(tmp_path):
    bogus = tmp_path / "not-a-worktree"
    bogus.mkdir()
    (bogus / "some_file").write_text("hi")

    mgr = WorktreeManager(cache_root=tmp_path / "cache")
    with pytest.raises(WorktreeError, match="not a managed worktree"):
        mgr.cleanup(bogus)


def test_parse_owner_repo_https():
    assert _parse_owner_repo("https://github.com/sympy/sympy") == ("sympy", "sympy")


def test_parse_owner_repo_with_dot_git_suffix():
    assert _parse_owner_repo("https://github.com/sympy/sympy.git") == ("sympy", "sympy")


def test_parse_owner_repo_file_url_uses_parent_dir():
    # Multi-segment file path: parent dir is the 'owner' namespace.
    assert _parse_owner_repo("file:///tmp/owner__repo.git") == ("tmp", "owner__repo")


def test_parse_owner_repo_single_segment_falls_back():
    # Single-segment path (e.g., a bare clone with no parent dir context).
    assert _parse_owner_repo("repo.git") == ("_local", "repo")


# Marker 'integration': real network on first run (clones psf/requests bare),
# fast on subsequent runs once the bare mirror is in ~/.cache/. Kept in the
# main suite for the same reason as the swebench integration test — catches
# real-world failures the mocked tests can't. To exclude:
#   uv run pytest harness/ -m "not integration"
@pytest.mark.integration
def test_prepare_against_real_smoke_task(tmp_path: Path):
    from harness.providers.swebench import (
        SWEBenchVerifiedProvider,
        load_task_ids_from_yaml,
    )

    smoke_yaml = Path(__file__).parents[2] / "tasks" / "swebench_smoke.yaml"
    ids = load_task_ids_from_yaml(smoke_yaml)
    # psf/requests is the smallest repo in the smoke set — keeps the clone cheap.
    task = next(t for t in SWEBenchVerifiedProvider().load(ids) if "requests" in t.repo_url)

    mgr = WorktreeManager()  # uses the real ~/.cache root for cross-test reuse
    run_dir = tmp_path / "run"
    worktree = mgr.prepare(task, run_dir)
    try:
        head = _git("rev-parse", "HEAD", cwd=worktree)
        assert head == task.base_sha
        assert (worktree / ".git").is_file()
    finally:
        mgr.cleanup(worktree)
    assert not worktree.exists()
