# 11 — Host-grader pipeline: how `grade-work/` and `grade-venv/` cooperate

Generated from `prompts/11-implement-step-9.md`.

> **See also:**
> - [`02-grader-role-explained.md`](02-grader-role-explained.md) — high-level explanation of what a grader is in this project, why it's a separate component from the runner, and how the plan stages graders across Steps 8–10. Read that one first if you don't already know what "grader" means here; this document assumes you do.
> - [`12-grade-json-schema.md`](12-grade-json-schema.md) — per-field reference for the `grade.json` artifact this grader (and the others) contribute fields to. Pair this doc's "what happens during a grade run" with that doc's "what each field in the result means."

This document explains the internal workings of `harness/graders/swebench_host.py` — the primary grader. Specifically, it answers two questions:

1. **What does the grader create on disk during a run, and in what order?**
2. **How does code that lives in `grade-work/` end up executing inside the Python interpreter installed in `grade-venv/`?**

The mechanism is standard Python tooling — `pip install -e .` plus venv activation — but it isn't always obvious how those pieces fit together inside the grader's pipeline. The goal here is to make the linkage explicit so a future reader can debug a misbehaving grade or extend the grader to new tasks.

## Why two directories?

When the grader runs against a completed agent run, it has to:

- Take the agent's `diff.patch`.
- Apply it on top of the repo at `task.base_sha`.
- Apply SWE-bench's `test_patch` (the new tests added in the human PR) on top of *that*.
- Run those tests in a Python environment that contains the repo's dependencies.

We split this into two directories with distinct responsibilities:

| Directory | Role | Lifetime |
|---|---|---|
| `<run_dir>/grade-work/repo/` | **Workspace** — the source code with patches applied. A fresh git worktree at the task's `base_sha`. | Removed when grading completes; left intact if the grader crashed mid-run (for debugging). |
| `<run_dir>/grade-venv/` | **Toolchain** — Python interpreter + `pytest` + every package the repo declares as a dependency, installed by the per-task install commands from `tasks/swebench_smoke_grade.yaml`. | Always preserved (slow to recreate; useful for re-grading or debugging). |

Keeping them separate matters for two reasons:

1. **Reproducibility.** The workspace is a deterministic function of `(base_sha, agent diff, test patch)`. Recreating it is cheap. The venv is the slow part (`pip install` plus dependency resolution can take 10–30 s). Separating their lifecycles lets us throw away the workspace freely while keeping the venv.
2. **Isolation from the agent's worktree.** The agent's own worktree from the `harness run` pipeline sits at `<run_dir>/repo/`. The grader must never mutate that — it would falsify the captured agent state. Using `<run_dir>/grade-work/repo/` for grading gives us a separate place to apply patches.

## Final directory layout

After a successful grade (e.g. running `scripts/grade_smoke_tasks.py` for `pytest-dev__pytest-10051`):

```
runs/<run-id>/<task_id>/
├── diff.patch                    ← the agent's / gold patch (input to grading)
└── grade-venv/                   ← isolated Python environment
    ├── bin/python                    Python 3.11 interpreter
    ├── bin/pytest                    pytest CLI installed here
    └── lib/python3.11/site-packages/
        ├── pytest/...                regular install
        └── _pytest.pth | flask.egg-link | …
                                      ← POINTER back into grade-work/repo
```

`grade-work/` is removed in the `finally` block once grading completes. While grading is still in flight (or crashed mid-run), it looks like:

```
runs/<run-id>/<task_id>/
├── diff.patch
├── grade-venv/                   (as above, but possibly partially populated)
└── grade-work/
    └── repo/                     ← git worktree at task.base_sha
        ├── src/<package>/...         source code w/ agent diff + test_patch applied
        ├── tests/...                 includes the new bug-reproducing tests
        ├── pyproject.toml | setup.py
        └── .git                      worktree pointer file (not a full git dir)
```

## Sequence of actions

The full pipeline lives in `harness/graders/swebench_host.py::grade()`. Steps in order:

### 1. Load the per-task spec

```python
spec = _load_spec(spec_path or DEFAULT_SPEC_PATH, task.task_id)
```

Reads `tasks/swebench_smoke_grade.yaml`, returns a `GradeSpec` with `python_version`, `host_runnable`, `install_cmds`, `pytest_extra_args`, `skip_tests`. Used by every subsequent step. If the spec is missing or marked `host_runnable: false`, the grader returns `pass=null` early.

### 2. Create the empty parent for the worktree

```python
grade_root = run_dir / "grade-work"
grade_root.mkdir(parents=True, exist_ok=True)
```

A directory the worktree will live inside. Separate from `<run_dir>/repo/` (the agent's worktree) on purpose.

### 3. Prepare the grade worktree

```python
worktree = mgr.prepare(task, grade_root)
# worktree == <run_dir>/grade-work/repo
```

Delegated to `WorktreeManager.prepare()` (Step 4 of the plan). Two git-level operations:

- Ensure `~/.cache/coding-agent-compare/repos/<owner>__<repo>.git` exists as a bare clone (network on cache miss; reused otherwise).
- Run `git -C <bare> worktree add --detach <grade_root>/repo <base_sha>`. This populates `grade-work/repo/` with the repo files at the bug's pre-fix commit.

The worktree's `.git` is a pointer file back to the shared bare mirror — not a full clone — so it's cheap.

### 4. Apply the agent's diff

```python
diff_patch = (run_dir / "diff.patch").read_text() ...
if diff_patch.strip():
    err = _git_apply(worktree, diff_patch)
```

`_git_apply` runs `git -C <worktree> apply --whitespace=nowarn -` with the patch on stdin. Files inside `grade-work/repo/` are modified to include the "fix." If the patch doesn't apply (conflict, malformed input), the grader returns `pass=false` with a `grader_notes` explaining where it failed.

### 5. Apply SWE-bench's `test_patch`

```python
test_patch = task.metadata.get("test_patch") or ""
if test_patch.strip():
    err = _git_apply(worktree, test_patch)
```

Same mechanism. Adds the bug-reproducing test(s) the human PR added. After this step, `grade-work/repo/` contains: base SHA + fix + new tests.

### 6. Create the venv

```python
venv_dir = run_dir / "grade-venv"
err = _create_venv(venv_dir, spec.python_version)
```

Runs `uv venv --python 3.11 <venv_dir>`. uv fetches the interpreter if it's not already installed. After this step, `grade-venv/` contains an empty Python environment — just a Python interpreter and pip, no project, no pytest.

### 7. Install dependencies (the bridge-building step)

```python
for cmd in spec.install_cmds:
    err = _run_in_venv(venv_dir, cmd, cwd=worktree)
```

For `pallets__flask-5014`, the install command is `uv pip install -e . pytest 'werkzeug<3'`. `_run_in_venv` shells out via `bash -c <cmd>` with:

- **`cwd` set to the worktree** (`grade-work/repo/`).
- **Environment vars** mimicking `source venv/bin/activate`: `VIRTUAL_ENV=<grade-venv>` and `PATH=<grade-venv>/bin:<original PATH>`.

Two consequences fall out of those two settings:

- `uv pip install` finds the venv via `VIRTUAL_ENV` + the modified PATH and installs **into `grade-venv/`**.
- The `.` in `pip install -e .` resolves against `cwd`, which is `grade-work/repo/`. So pip reads `pyproject.toml` / `setup.py` from the worktree.

**The `-e` (editable) flag is the linchpin.** With `-e`:

- Pip does **not** copy the source into `site-packages`.
- Pip writes an `.egg-link` (legacy) or `direct_url.json` + a `.pth` entry (modern) into `grade-venv/lib/python3.11/site-packages/` that **points at the worktree's source directory**.
- The package's metadata (its `entry_points`, `console_scripts`, etc.) gets installed normally, but the actual code is *referenced*, not copied.

From the venv's Python's perspective after step 7:

```
import flask  →  Python walks sys.path
              →  Finds flask.egg-link in <grade-venv>/lib/.../site-packages/
              →  Reads the path inside: "<run_dir>/grade-work/repo/src/flask"
              →  Loads patched source from that path
```

So any change we made to `grade-work/repo/` (in steps 4–5) is **immediately live** when Python imports the package — we never need to reinstall after re-patching.

### 8. Run pytest

```python
pytest_out, pytest_err = _run_pytest(
    venv_dir, worktree, runnable, extra_args=spec.pytest_extra_args
)
```

`_run_pytest` invokes:

```
pytest -v --tb=short -p no:cacheprovider --no-header [extra_args] [test_names...]
```

with the same `cwd=worktree` + the same env (`VIRTUAL_ENV` + modified `PATH`) as step 7.

The cascade of effects from those two settings:

- The `pytest` binary that runs is `<grade-venv>/bin/pytest` (because `PATH` has the venv's `bin/` first).
- That `pytest` binary has a shebang pointing at `<grade-venv>/bin/python`, so it uses the venv's interpreter.
- Pytest's `cwd` is `grade-work/repo/`, so test discovery walks `grade-work/repo/tests/` (including the new tests from `test_patch`).
- When a test does `import flask`, Python's import system finds the `.egg-link` in the venv's site-packages and loads the **patched source from `grade-work/repo/`**.

### 9. Parse results

```python
results = _parse_pytest_results(pytest_out + "\n" + pytest_err)
```

Line-by-line regex match for `PASSED` / `FAILED` / `ERROR` markers; build a `{test_name: outcome}` dict; cross-reference against `FAIL_TO_PASS + PASS_TO_PASS` to compute `pass`, `tests_passed`, `tests_failed`, `unresolved`.

### 10. Cleanup

```python
finally:
    try:
        mgr.cleanup(worktree)
    except Exception:
        pass
    try:
        grade_root.rmdir()
    except OSError:
        pass
```

Two things happen in the cleanup block:

- `mgr.cleanup(worktree)` removes `grade-work/repo/` and prunes the bare mirror's worktree record. The worktree is recreatable from cache, so deleting it costs nothing.
- `grade_root.rmdir()` removes the now-empty `grade-work/` parent. `rmdir` only succeeds on empty directories, so this is safe — if the grader crashed *before* cleanup, the worktree is still inside, `rmdir` raises `OSError`, and we leave the dir alone for inspection.

`grade-venv/` is **deliberately left in place** — it's the slow-to-recreate part and useful for re-grading without re-installing.

## The bridge, visualized

The crucial bit — how step 7's editable install connects the workspace to the toolchain — is worth seeing as a diagram. This shows the state at the moment pytest is running (step 8):

```
                     ┌──────────────────────────────────────────────────┐
                     │  subprocess env, set by _run_pytest()            │
                     │                                                  │
                     │    PATH        = <grade-venv>/bin:<orig PATH>    │
                     │    VIRTUAL_ENV = <grade-venv>                    │
                     │    cwd         = <grade-work>/repo               │
                     └────────────────────┬─────────────────────────────┘
                                          │
                                          ▼
                            ┌─────────────────────────┐
                            │   shell looks up        │
                            │   `pytest` on PATH      │
                            └────────────┬────────────┘
                                          │
                                          ▼
                ┌─────────────────────────────────────────────────────┐
                │                  grade-venv/                        │
                │                                                     │
                │  bin/pytest      ─►  bin/python (venv interpreter)  │
                │  bin/python                                          │
                │                                                     │
                │  lib/python3.11/site-packages/                      │
                │     pytest/         (regular install — code here)   │
                │     flask.egg-link  ──── (a path file) ────┐         │
                │                                            │         │
                └────────────────────────────────────────────┼─────────┘
                                                              │
                                                              │ (points to)
                                                              ▼
                ┌─────────────────────────────────────────────────────┐
                │                  grade-work/repo/                   │
                │                                                     │
                │  src/flask/...                                      │
                │     ◀──── this is what `import flask` loads ────    │
                │                                                     │
                │  tests/...                                          │
                │     ◀──── this is what pytest collects from cwd ─   │
                │                                                     │
                │  pyproject.toml                                     │
                └─────────────────────────────────────────────────────┘
```

Reading the diagram:

- **Top half (toolchain):** the venv provides the interpreter and 3rd-party deps. Code that's not the project under test (e.g. pytest itself, werkzeug, urllib3) lives here and is loaded normally.
- **Bottom half (workspace):** the project under test plus the new tests. Source files here are the *patched* state — base SHA + agent diff + test_patch.
- **The arrow between them** is the `flask.egg-link` (or `direct_url.json`) — a tiny pointer file pip wrote during step 7 that contains the absolute path back to the worktree's source directory. Python's import system follows it transparently. No `PYTHONPATH` manipulation, no `sys.path.insert` — it's a fully standard pip mechanism.

## Why this design

A few alternatives were considered and rejected:

- **Install the project non-editably (`pip install .` without `-e`).** This would copy source into `site-packages/`. Any change to `grade-work/repo/` after install would *not* be live until re-install. Acceptable for grading the gold patch only, but wasteful — and it would mean re-installing after every applied patch in a more complex pipeline.
- **Skip the venv; install into the system Python.** Tested briefly — falls over fast. Two different smoke tasks need different dep versions (flask wants `werkzeug<3`, pytest-itself has its own pinning). Sharing one Python environment causes constant version churn between tasks.
- **Set `PYTHONPATH` to point at the worktree.** This works for trivial cases but breaks anything that uses `pkg_resources`, `importlib.metadata`, or `entry_points` — including pytest's own plugin discovery. `pip install -e .` does the right thing for all of these because it installs proper package metadata.
- **Use Docker images per task** (the official SWE-bench approach). Heaviest weight, slowest, most reproducible across environments. Explicitly out of scope per `CLAUDE.md`. The plan's escape hatch (Option B in the open questions) is to fall back to SWE-bench's prebuilt Docker images *only* for the grader on tasks that can't be made to work on the host. For the current 3-task smoke set, host venvs are sufficient.

## Debugging recipes

A few common situations and where to look:

| Symptom | Likely cause | Where to look |
|---|---|---|
| `grade.json` reports `pass: null, grader_notes: "agent diff did not apply: ..."` | The agent's `diff.patch` had a conflict against the worktree at `base_sha`. | `grade-work/repo/` is gone after cleanup; re-run with the same inputs and check `grade-work/repo/.rej` files before the next attempt. |
| `pass: null, grader_notes: "install failed [...]"` | A `uv pip install` command in `spec.install_cmds` returned non-zero. | The `grader_notes` truncates the stderr. Re-run the install command by hand inside the leftover `grade-venv/` to see the full message. |
| `pass: false`, all listed tests fail | The agent's diff didn't fix the bug. Real result. | Compare `grade-work/repo/src/<pkg>/` to the gold patch in `task.metadata["patch"]`. |
| `pass: null, grader_notes: "pytest exceeded 300s"` | A test hung or the test suite is too slow. | Re-run pytest manually inside `grade-venv/` with a longer timeout: `source grade-venv/bin/activate && pytest --override-ini=addopts= -v <test>`. |
| `unresolved` count is non-zero with a `data-corrupted` note | SWE-bench Verified's F2P/P2P list has a parametrized test name split on whitespace. | See `_stitch_parametrized` in `harness/providers/swebench.py` and the discussion in this prompt's session log. |

## Re-grading without re-running the agent

Because the venv is preserved and `grade.json` is the only file the grader writes, you can re-grade an existing run dir without recreating anything:

```python
from pathlib import Path
from harness.graders.swebench_host import grade
from harness.providers.swebench import SWEBenchVerifiedProvider

task = next(t for t in SWEBenchVerifiedProvider().load(["pytest-dev__pytest-10051"]))
result = grade(Path("runs/<run-id>/pytest-dev__pytest-10051"), task)
```

This recreates the worktree from the cached bare mirror (fast, no network), re-applies the patches, and re-uses the existing `grade-venv/` (no install). Typical re-grade takes < 5 seconds. Useful when the grader's logic changes and you want to verify the new logic against old runs without re-paying for the agent runs.

## Files of interest

- `harness/graders/swebench_host.py` — the grader itself.
- `harness/graders/base.py` — the `Grade` schema (Pydantic v2, schema 1.0).
- `harness/graders/__init__.py` — the plug-in registry that exposes `swebench_host` to the runner.
- `harness/worktree.py` — `WorktreeManager.prepare()` / `.cleanup()` used in step 3 / 10.
- `harness/providers/swebench.py::_stitch_parametrized` — repairs the SWE-bench Verified data corruption in F2P/P2P lists.
- `tasks/swebench_smoke_grade.yaml` — the per-task install + skip + pytest-arg specs.
- `scripts/grade_smoke_tasks.py` — convenience wrapper that runs the whole pipeline against the smoke set's gold patches.
- `harness/tests/test_graders_swebench_host.py` — unit + integration tests covering the above.

## Related documents

- [`02-grader-role-explained.md`](02-grader-role-explained.md) — the conceptual companion to this doc: *what* a grader is, *why* it's separate from the runner, and how Steps 8 / 9 / 10 layer their graders. Start there if the design rationale is what you need; come back here for the wiring.
- [`12-grade-json-schema.md`](12-grade-json-schema.md) — per-field reference for the `grade.json` artifact this pipeline produces. Use it when you need to interpret a specific field's value or null state.
- [`02-implementation-plan-step-by-step.md`](02-implementation-plan-step-by-step.md) — the broader implementation plan; the Step 9 section and its "Changes introduced during implementation of Step 9" change-log capture the per-task install wrinkles (werkzeug pin, addopts override, env-dependent test skips) that drove the spec YAML's shape.
