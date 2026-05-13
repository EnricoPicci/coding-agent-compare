# Prompt
Implement Step 8

# Claude Response

Implements Step 8 of [`docs-generated-by-claude/02-implementation-plan-step-by-step.md`](../docs-generated-by-claude/02-implementation-plan-step-by-step.md) — *Mock grader (machinery-only)*. Smallest possible signal that the pipeline produced data, wired in as the default grader so every run gets one.

## Verifications

```
$ uv run pytest harness/ -q -m "not integration"
  → 77 passed in 12.68s ✓
$ uv run ruff check . && uv run ruff format --check .  → clean ✓

# Live grader sanity against existing step6-verify diffs (zero API cost):
  claude    diff=  802 B  →  {'produced_nonempty_diff': True}
  copilot   diff= 4572 B  →  {'produced_nonempty_diff': True}
```

## Files created

- `harness/graders/__init__.py` — plug-in registry. `register(name, fn)` +
  `get_grader(name)` with lazy module import on first use, mirroring the
  parser registry from Step 7.
- `harness/graders/base.py` — `Grade` Pydantic model. Schema 1.0; strict
  (`extra="forbid"`). Step 8 contributes `produced_nonempty_diff`; Step 9
  / Step 10 placeholder fields are already declared so the schema
  doesn't need a bump when those graders land.
- `harness/graders/mock.py` — `grade(run_dir, task) -> {"produced_nonempty_diff": bool}`.
  Reads `<run_dir>/diff.patch` and reports whether it's non-empty.
- `harness/tests/test_graders_mock.py` — 4 tests: true on nonempty diff,
  false on empty diff, false on missing diff, registry dispatch.
- 4 new tests in `harness/tests/test_runner.py` — `grade.json` written
  with the right shape, `produced_nonempty_diff` reflects the agent's
  actual diff, `graders=[]` skips grading entirely, a buggy grader is
  recorded as `grader_notes` without failing the run.

## Files modified

- `harness/runner.py` — adds `RunConfig.graders: list[str]` (default
  `["mock"]`), `RunResult.grade_path: Path | None`, and `_run_graders`
  internal that merges each grader's partial dict into a single
  `grade.json`. Grader failures are captured, not raised.

## Plan deviations / decisions locked in

Five implementation-time decisions logged in
[the plan's Step 8 change-log](../docs-generated-by-claude/02-implementation-plan-step-by-step.md#changes-introduced-during-implementation-of-step-8):

1. `grade.json` is one accreting document (graders contribute fields),
   not per-grader files. Avoids a schema migration when Step 9/10 land.
2. `Grade` schema is named (`1.0`) and strict; Step 9 + Step 10 fields
   are already declared as Optional placeholders.
3. Grader plug-in registry mirrors the parser one (`register` /
   `get_grader`); `RunConfig.graders` is the list of grader names to
   invoke per run, default `["mock"]`, pass `[]` to skip entirely.
4. Grader exceptions are non-fatal — recorded in `grade.grader_notes`,
   the run is still complete.
5. The Pydantic field for the primary `"pass"` metric is named `pass_`
   in Python (reserved-keyword workaround) but serializes as `"pass"`
   in JSON via Pydantic's `alias=` mechanism.

## Why this grader is worth shipping

`produced_nonempty_diff` looks trivial — and it is. But it answers four
real questions cheaply, before Step 9's host-venv grader is online:

1. **Did the agent produce any code change at all?** A `false` here is
   often a sign that the wrapper crashed, the wall-clock fired before
   the agent could write anything, or auth lapsed mid-run.
2. **Is the harness still wired end-to-end?** If every run reports
   `false` after a code change, something upstream broke (wrapper,
   diff capture, run-dir layout, …) — easier to catch with a
   one-bit-per-run signal than from reading traces.
3. **Are the two tools at least *attempting* the same tasks?** Step 6
   already showed claude and copilot produce visibly different diffs
   on the same prompt; a `true / false` split between tools is a
   coarser version of that signal across the smoke list.
4. **Baseline for Step 9 calibration.** When the host-venv grader is
   wired up, runs where Step 8 says `true` and Step 9 says `pass=false`
   are the interesting failure-mode cases — the agent produced a diff
   but the diff was wrong. The mock signal makes that two-axis split
   visible before Step 9's heavier machinery is available.

## Side effects

- No new runtime dependencies (Pydantic was added in Step 7).
- Existing step6-verify run dirs don't have a `grade.json` yet because
  Step 8 didn't exist when those runs were produced. Re-running through
  `harness run` or invoking the grader manually adds it.

## Step 9 readiness

Step 9 (host-venv grader) is unblocked. The `Grade` schema already has
the placeholder fields (`pass_`, `tests_passed`, `tests_failed`,
`unresolved`, `grader_notes`); Step 9's grader just needs to register
itself with the same `register("swebench_host", grade_fn)` pattern and
return those fields from `grade()`. The plan's note that Step 9 is the
riskiest step (host venv + dep isolation pain) is independent of the
infrastructure landed here.
