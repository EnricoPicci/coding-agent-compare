# Prompt
Implement step 4

# Claude response

Implements Step 4 of [`docs-generated-by-claude/02-implementation-plan-step-by-step.md`](../docs-generated-by-claude/02-implementation-plan-step-by-step.md) — *Worktree manager*.

## Verifications

```
$ uv run pytest harness/ -q       # → 30 passed in 6.72s ✓
$ uv run ruff check .             # → All checks passed ✓
$ uv run ruff format --check .    # → 14 files already formatted ✓

# Manual end-to-end against a real smoke task (plan's verify clause):
Task:     psf__requests-1142
Base SHA: 22623bd8c265b78b161542663ee980738441c307
HEAD:     22623bd8c265b78b161542663ee980738441c307
Match:    True
After cleanup, worktree exists? False
```

## Files created

- `harness/worktree.py` — `WorktreeManager` with `prepare(task, run_dir)` and `cleanup(worktree_path)`, plus `WorktreeError` exception and helpers. Backed by bare mirrors at `~/.cache/coding-agent-compare/repos/<owner>__<repo>.git`, reused across worktrees via `git worktree add`.
- `harness/tests/test_worktree.py` — 11 tests:
  - 10 unit tests using a locally-built bare repo as the "remote" (no network): SHA correctness, mirror reuse across calls, re-prepare into an existing dir, missing-SHA error, cleanup, cleanup-safety on unmanaged paths, three URL parsing cases.
  - 1 `@pytest.mark.integration` test that clones `psf/requests` and prepares the real `psf__requests-1142` smoke task end-to-end.

## Design decisions worth flagging

- **Bare mirrors + `git worktree add`**, not per-task full clones. Each repo is cloned once (cache hit forever) and multiple worktrees can coexist on different SHAs against the same mirror. Network cost is paid once per repo, not once per `(task, tool, seed)`.
- **Conditional fetch.** Mirrors are only `fetch`ed when the requested SHA isn't already present (`git cat-file -e` check). SWE-bench Verified SHAs are old and stable; refetching on every call would burn bandwidth for nothing.
- **POSIX `fcntl.flock` for locking**, no-op stub on Windows. The smoke phase doesn't run concurrent prepares against the same mirror, so the Windows gap is documented but not yet blocking. A portable locking story lands alongside any future Windows-runner work.
- **Cleanup safety check.** `cleanup()` refuses to remove a path unless its `.git` file is a `gitdir: <mirror>/worktrees/<name>` pointer to a `.git`-suffixed mirror directory. This makes accidental deletion of unrelated paths extremely unlikely.
- **`git worktree remove --force` first, then `shutil.rmtree` fallback.** Git's own removal handles the bookkeeping; `rmtree` ensures we always succeed even if git's view is corrupted. `worktree prune` afterward cleans up stale records.
- **No `WorktreeManager.__init__` knobs beyond `cache_root`.** Anything more (retry, timeout, alternate remote) is pre-mature.

## Side effects on this machine

Real bare clone now lives at `~/.cache/coding-agent-compare/repos/psf__requests.git` (~5 MB). Created during the manual verify and reused by the integration test. The two heavier smoke-list repos (`sympy`, `pylint`) will land there the first time their tasks are prepared.

## Step 5 readiness

Step 5 (tool wrappers) depends on Step 4. Ready to proceed.
