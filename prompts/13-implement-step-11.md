# Prompt
Implement Step 11

# Claude Response

Implements Step 11 of [`docs-generated-by-claude/02-implementation-plan-step-by-step.md`](../docs-generated-by-claude/02-implementation-plan-step-by-step.md) — *Multi-mode driver (Product vs. Harness)*. Drives the full `(task × tool × seed)` matrix through the Step 6–10 stack, owns retry orchestration (deferred here from Step 6), and exposes a `harness run-matrix` CLI subcommand.

## Verifications

```
$ uv run pytest harness/ -q -m "not integration"
  → 132 passed in 21.38s ✓  (was 115)
$ uv run ruff check . && uv run ruff format --check .  → clean ✓
```

No live API run was performed for this step — the driver is an orchestrator on top of `run_once`, which is already verified end-to-end in Steps 6 / 9 / 10. The 17 new driver tests use the same stub-bash-wrapper pattern as `test_runner.py`, so the matrix orchestration is exercised without spending API budget. A live `run-matrix` invocation against the smoke set would cost roughly the sum of Step 9's per-task numbers (a few minutes per cell at the default 15-min budget); deferred until needed.

## Files created

- `harness/driver.py` — the driver. `run_matrix(tasks, tools, config)` and
  helper dataclasses (`MatrixConfig`, `CellResult`, `MatrixResult`).
  About 250 lines covering: tool validation, run-id allocation, the
  per-cell retry loop, manifest update after retries, crash handling,
  the framing-from-model derivation, and the CLI shim used by
  `harness/cli.py`.
- `harness/tests/test_driver.py` — 15 unit tests covering:
  - Configuration validation (unsupported tool). The originally-planned
    "bad framing" and "harness framing without model" tests were
    removed by the post-implementation framing simplification (see
    below): with no `--framing` input, those invalid states are
    unrepresentable.
  - Matrix shape (every cell visited; shared run_id; auto-generated
    run_id format).
  - Framing as derived from `model` presence: with `model=None` no
    `--model` arg is passed to the wrapper and `framing='product'` is
    recorded in each cell's manifest; with `model=<name>` the shared
    `--model` is forced on every tool's invocation and
    `framing='harness'` is recorded.
  - Retries (no retries on success; retry-then-succeed; retry-exhaustion;
    manifest's `retries` field reflects the final count + reasons).
  - Crash handling (a missing wrapper crashes the cell, captures
    `crashed_with`, but doesn't abort the matrix).
  - Helpers (`matrix_result_to_dict` JSON round-trip, defaults).

## Files modified

- `harness/cli.py` — adds the `run-matrix` subcommand. The implementation
  is a thin forwarder into `harness/driver.py::_cli_main` to keep the
  argument-handling code in one place. Args: `--tasks`, `--tools`,
  `--model` (optional; presence selects "harness" framing), `--seeds`,
  `--budget-seconds`, `--retries`, `--run-id`, `--runs-root`, `--cleanup`,
  `--provider`, `--output-json`. The pre-existing `harness run`
  subcommand also lost its `--framing` flag in the same refactor —
  framing is now always derived from `--model`.
- `harness/runner.py` — adds `framing_from_model()` helper that returns
  `"harness"` if a model is set, `"product"` otherwise. Used by both the
  manifest-writer (to record `manifest.framing`) and the driver. The
  `framing` field on `RunConfig` was removed; only `model` remains as a
  user input, and the framing label is derived everywhere it's needed.
- `docs-generated-by-claude/02-implementation-plan-step-by-step.md` —
  records the seven Step 11 implementation choices in a new
  "Changes introduced during implementation of Step 11" subsection.

## Plan deviations / decisions locked in

Detailed in the
[plan's Step 11 change-log](../docs-generated-by-claude/02-implementation-plan-step-by-step.md#changes-introduced-during-implementation-of-step-11).
Summary:

1. **Retries live in the driver** (as Step 6's deviation log promised).
   Default 2 retries = 3 attempts max. Transient classification matches
   CLAUDE.md: non-zero non-timeout exit retried; timeout is data, not a
   transient; pass=false is data, not a transient (and isn't even visible
   at the driver level — exit_code is what we see). Runner-level
   exceptions also count as retryable.
2. **Shared `run_id` across all cells** of one matrix invocation. Step
   12's report consumes one directory tree per matrix.
3. **Sequential execution** in Step 11. Parallelism deferred until the
   matrix grows beyond ~10 cells.
4. **Per-cell crashes are non-fatal.** A `RunnerError` or any other
   exception in a single cell is captured in `CellResult.crashed_with`
   and the driver moves on. The matrix completes with partial data.
5. **"Tool doesn't accept --model" branch is framework-only.** Both
   smoke-set tools accept `--model`; the documented branch in the plan
   is reachable but not currently exercised. TODO when a third tool
   without `--model` support enters the comparison.
6. **`--framing` is derived, not a user input** (post-implementation
   simplification). The plan's original CLI shape had `--framing
   product|harness` as a separate flag from `--model`, but the two
   always co-vary: product is exactly "no model override," harness is
   exactly "shared model forced on every cell." Exposing both as
   independent flags created a four-cell input space where only two
   cells were valid, plus a latent bug where `--framing product --model
   X` silently dropped the model. The CLI now exposes only `--model`;
   `framing_from_model()` derives the `"product"` / `"harness"` label
   and writes it to each cell's `manifest.framing` field. Invalid
   combinations are now unrepresentable. The canonical CLI shape is
   `harness run-matrix --tasks ... --tools claude,copilot` for product
   mode, with `--model <name>` added for harness mode.
7. **CLI exit code is a top-level signal.** 0 iff *every* cell graded
   `exit_code == 0`; 1 otherwise. The detailed per-cell verdict lives
   in `grade.json` files.

## Design decisions worth flagging

- **`MatrixConfig.runner_kwargs` is an escape hatch for tests.** It's a
  dict of extra kwargs that get forwarded into `RunConfig` (specifically
  `wrapper_override` and `worktree_manager`, which tests use to point at
  stubs). Production callers shouldn't need it — the field defaults to
  `None` and gets ignored.
- **Manifest update after retries goes through Pydantic.** The driver
  re-reads the cell's `manifest.json` via `read_manifest()`, mutates
  the `retries` field, writes it back via `write_manifest()`. Round-
  tripping through the Pydantic model means a schema drift here would
  surface immediately rather than silently producing a malformed
  manifest.
- **Each retry attempt overwrites the prior attempt's artifacts.** No
  `attempt-1/`, `attempt-2/` subdirs — the manifest's `retries.reasons`
  list captures the history, and that's what's auditable. The smoke
  phase doesn't need full attempt-level provenance; if Step 13's
  failure-mode tooling needs it later, this is the place to revisit.
- **`run-matrix --output-json <path>` is optional.** Step 12's report
  will read the runs dir directly; the matrix.json is a convenience for
  pipeline integration (CI, dashboards) that wants one file per matrix.

## Side effects on this machine

- No new runtime dependencies.
- No new caches; the matrix uses the same `~/.cache/coding-agent-compare/repos/`
  bare mirrors as the runner does.
- No new disk artifacts beyond what `run_once` already produces per cell.

## What `run-matrix` would do live (when invoked)

For the smoke set + both tools + 1 seed:

```bash
uv run python -m harness run-matrix \
  --tasks tasks/swebench_smoke.yaml \
  --tools claude,copilot \
  --budget-seconds 600 \
  --run-id smoke-product
```

No `--model` flag → product framing. Each tool uses its default model;
each cell's `manifest.framing` is recorded as `"product"`. This produces
6 cells (3 tasks × 2 tools × 1 seed) at
`runs/smoke-product/<tool>/<task_id>/seed-0/` each with the full set of
artifacts: `diff.patch`, `prompt.txt`, `stdout.log`, `stderr.log`,
`exit_code`, `wall_clock_seconds`, `tool_info.json`, `events.jsonl`,
`manifest.json`, `grade.json`. Estimated wall-clock: 30–60 minutes
total (cells run sequentially; per-cell time depends on each agent's
working pace within the budget). Estimated cost: ~$2–$5 for claude;
seat time only for copilot.

The same command with `--model claude-sonnet-4-6 --run-id smoke-harness`
would force both tools onto the shared model — `manifest.framing` is
then `"harness"` for every cell. The two run-ids' results, when read
together, isolate the harness/scaffolding variable from the model
variable — the core comparison the project is set up to support.

## Step 12 readiness

Step 12 (comparison report) depends on Step 7 (manifest) + Step 10
(all graders) + Step 11 (driver). All three are done. The report will
glob `runs/<run-id>/{tool}/{task}/seed-*/grade.json` and
`manifest.json`, aggregate into a comparison table, and write
`reports/<run-id>.md`. The driver's shared-run-id contract means the
report has one clear input directory per matrix invocation.
