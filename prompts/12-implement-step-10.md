# Prompt
Implement Step 10

# Claude Response

Implements Step 10 of [`docs-generated-by-claude/02-implementation-plan-step-by-step.md`](../docs-generated-by-claude/02-implementation-plan-step-by-step.md) — *Secondary graders*. Two small graders that contribute fields to the same `grade.json`, plus a runner-default update so every run produces a fully-populated grade document by default.

## Verifications

```
$ uv run pytest harness/ -q -m "not integration"
  → 114 passed in 13.13s ✓ (was 91)
$ uv run ruff check . && uv run ruff format --check .  → clean ✓

# Live re-grade of all 3 smoke tasks via the gold-patch path:
$ uv run python scripts/grade_smoke_tasks.py
  pallets__flask-5014:        pass=True | precision=1.0 recall=1.0 | size=3  human=3
  pytest-dev__pytest-10051:   pass=True | precision=1.0 recall=1.0 | size=7  human=7
  psf__requests-5414:         pass=True | precision=1.0 recall=1.0 | size=2  human=2
```

The 1.0/1.0 precision/recall and matching size counts are the expected verify-clause result: the input is literally the human's gold patch, so the agent's file set and the human's file set are identical and the diff sizes match exactly. Plan's verify clause ("hand-check on one smoke task: precision/recall numbers match a manual diff of the file sets") satisfied for all three.

## Files created

- **`harness/graders/scope.py`** — secondary grader that measures how well
  the agent's set of touched files lines up with the set of files touched
  by the human PR. The question it answers in one line: *"did the agent
  edit the right files?"*

  **How it works.** The grader walks two patches in parallel: the agent's
  `diff.patch` produced by the runner, and the human's gold patch from
  `task.metadata["patch"]`. For each patch it extracts the set of files
  touched by regex-matching `diff --git a/<old> b/<new>` headers — the
  canonical file-change header in a unified diff. Both the `a/` (old) and
  `b/` (new) paths from each header go into the set, so a *rename* (where
  the two paths differ) counts as touching both names. Ordinary
  modifications, deletions, and new files emit identical `a/` and `b/`
  paths so each file appears in the set exactly once.

  It then computes the standard precision/recall pair against the human
  as ground truth:

  - `precision = |agent ∩ human| / |agent|` — of the files the agent
    touched, what fraction also appear in the human PR. Higher means more
    on-target editing.
  - `recall = |agent ∩ human| / |human|` — of the files the human
    touched, what fraction did the agent cover. Higher means wider
    coverage of the relevant code.

  **What it adds to `grade.json`.** Two new fields:

  - `files_touched_precision: float | None`
  - `files_touched_recall: float | None`

  **Null semantics for defined-zero cases.** When either side's file set
  is empty the corresponding ratio is mathematically undefined (division
  by zero). The grader returns `None` for those cases rather than fake
  `0.0`, preserving the distinction between *"we couldn't measure it"*
  (e.g. the agent produced no diff at all) and *"we measured and the
  answer was zero"* (e.g. the agent touched files but none overlapped).
  Step 12's report can then display `null` as `—` and exclude those runs
  from precision/recall averages without dragging the average toward
  zero artificially. The full case matrix is in
  [`docs-generated-by-claude/12-grade-json-schema.md`](../docs-generated-by-claude/12-grade-json-schema.md).

- **`harness/graders/size.py`** — secondary grader that captures the raw
  line-count of the agent's diff alongside the line-count of the human's
  gold patch. The question it answers: *"did the agent edit roughly the
  right amount of code?"*

  **How it works.** The grader walks each patch line by line and counts
  every line whose first character is `+` or `-`. Three categories of
  line are explicitly excluded:

  - Lines starting with `+++` or `---` are unified-diff file headers
    (e.g. `--- a/foo.py`, `+++ b/foo.py`), not actual additions or
    deletions. They're filtered before the count.
  - Lines starting with a space (` ` — single space) are context lines
    (unchanged code shown around an edit). They don't count.
  - Lines starting with `@@` are hunk headers (e.g. `@@ -1,5 +1,7 @@`).
    They don't count.

  The two counts (agent's diff and human's gold patch) are reported
  separately rather than as a precomputed ratio, so downstream consumers
  (chiefly Step 12's report) can derive whatever shape they want —
  ratio, log-ratio, simple delta — from the same raw inputs.

  **What it adds to `grade.json`.** Two new fields:

  - `diff_size_lines: int` — count of changed lines in the agent's diff.
  - `human_diff_size_lines: int` — count of changed lines in the human
    PR's gold patch (the reference point).

  **Use as an over-/under-editing detector.** An agent diff that's
  several multiples of the human's diff often signals scope creep —
  the agent refactored more than the bug required. A diff that's a
  small fraction of the human's often signals an under-scoped fix —
  the agent touched the most obvious file but missed related changes
  the human had to make. Neither extreme is automatically wrong (a
  cleaner refactor *can* legitimately be smaller; a wider rewrite *can*
  legitimately be larger), but both are signals a human reader benefits
  from seeing surfaced in the report.
- `harness/tests/test_graders_scope.py` — 13 tests: `files_touched`
  parsing (empty, single mod, multi-file, rename, new file), `grade()`
  computation across perfect / partial / no overlap, both empty-side
  cases, registry dispatch.
- `harness/tests/test_graders_size.py` — 10 tests: `count_diff_lines`
  on empty, all-additions, all-deletions, mixed, file-header exclusion,
  context exclusion, multi-hunk; `grade()` end-to-end including missing-
  diff handling; registry dispatch.

## Files modified

- `harness/graders/__init__.py` — adds `scope` and `size` to the lazy-
  import dispatch alongside `mock` and `swebench_host`.
- `harness/runner.py` — default `RunConfig.graders` is now
  `["mock", "swebench_host", "scope", "size"]` (was just `["mock"]`).
  A real `harness run` now produces a fully-populated `grade.json`
  including precision/recall/size in addition to the primary pass/fail.
- `scripts/grade_smoke_tasks.py` — same default change, so the gold-
  patch smoke script produces the same `grade.json` shape as a real
  agent run.
- `harness/tests/test_runner.py` — `_cfg` fixture now defaults to
  `graders=["mock"]` so the runner-orchestration tests keep their
  original focus (assert about merging + plumbing) and don't have to
  track the global default's evolution. Individual graders have their
  own dedicated test files.

## Files modified (documentation)

- `docs-generated-by-claude/02-implementation-plan-step-by-step.md` —
  records the five Step 10 implementation choices: rename handling,
  defined-zero semantics, file-header exclusion in size, runner default
  bump, smoke-script default bump.

## What appears in grade.json now

Sample from a `gold-smoke` run on `pallets__flask-5014`:

```json
{
  "schema_version": "1.0",
  "graders": ["mock", "swebench_host", "scope", "size"],
  "produced_nonempty_diff": true,
  "pass": true,
  "tests_passed": [...],
  "tests_failed": [],
  "unresolved": [],
  "grader_notes": null,
  "files_touched_precision": 1.0,
  "files_touched_recall": 1.0,
  "diff_size_lines": 3,
  "human_diff_size_lines": 3
}
```

Every Pydantic `Optional` field in the `Grade` schema is now either
populated by a grader or explicitly null. No more placeholder fields.

## Design decisions worth flagging

- **Rename handling unions both paths.** A `diff --git a/old b/new` line
  contributes both `old` and `new` to the file set. This means a rename
  counts as touching 2 files for precision/recall purposes. Rationale:
  an agent that renames a file the human also modified should be
  credited for touching the relevant code, not penalized for using
  a different name. Edge case noted in the implementation deviation
  log; not worth adding complexity (e.g. similarity scoring) for now.
- **`precision=None` when the agent did nothing.** Some metrics
  conventions would set precision to 0.0 in this case. We chose None
  because "the agent touched zero files, of which zero were correct"
  is genuinely undefined; reporting 0.0 would imply 0% accuracy when
  the right answer is "we can't measure it." Step 12's report can
  treat None as "—" or skip the run from the precision average.
- **Both new graders are pure-Python text parsing.** No subprocess, no
  filesystem operations beyond reading `diff.patch`, no network. Total
  runtime <10 ms per run. Always safe to run by default.
- **Tests use synthetic patches, not real ones.** Each test case is a
  hand-crafted ~5-line diff string. Faster than checking in fixtures
  and more obvious to a future reader what each test is asserting.
  The real-data smoke is `scripts/grade_smoke_tasks.py` against the
  gold patches.

## Side effects on this machine

- The `runs/gold-smoke/<task>/grade.json` files from the previous Step 9
  verification now have additional `files_touched_*` and `diff_size_*`
  fields after this Step 10 re-run. The venvs were reused from Step 9
  (no re-install).
- No new runtime dependencies.

## Step 11 readiness

Step 11 (multi-mode driver) depends on Step 7 (manifest) and Step 10 (all
graders for the comparison columns). Both done. The driver will iterate
over `(task × tool × seed)` and call `run_once` for each, producing a
matrix of run dirs that Step 12's report consumes. With Step 10 complete
every cell of that matrix has the full `grade.json` shape; the report
can build its comparison table without dealing with optional fields.
