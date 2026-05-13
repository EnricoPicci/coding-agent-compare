# Prompt
Implement Step 6

# Claude Response

Implements Step 6 of [`docs-generated-by-claude/02-implementation-plan-step-by-step.md`](../docs-generated-by-claude/02-implementation-plan-step-by-step.md) — *Single-run executor*. Wires Steps 3–5 together: load a task, prepare a fresh worktree, invoke the right wrapper with a wall-clock budget, capture the agent's diff, write a manifest.

## Verifications

```
$ uv run pytest harness/ -q -m "not integration"
  → 40 passed in 9.03s ✓
$ uv run ruff check .            → All checks passed ✓
$ uv run ruff format --check .   → 16 files already formatted ✓

# Live end-to-end against the smoke task psf__requests-1142 with a 60s
# budget (deliberately small, to exercise the timeout path and bound cost):
$ uv run python -m harness run \
    --task psf__requests-1142 --tool claude --seed 0 \
    --run-id step6-verify --budget-seconds 60
  → run-dir:  runs/step6-verify/claude/psf__requests-1142/seed-0
    exit:     -15 (timed out — SIGTERM during grace period)
    wall:     60.0s
    diff:     802 bytes — claude modified requests/models.py to fix the
              Content-Length-on-GET bug before the budget hit
    manifest: well-formed JSON; schema_version "step6-stub"; all fields
              populated including tool_info merged from the wrapper.
```

The live run produced a *real* code change from claude in 60 seconds. The exit code `-15` is the SIGTERM signal number negated (Python's `subprocess` convention), meaning claude exited cleanly during the grace period after the wall-clock fired. The diff was captured because we staged everything first.

## Files created

- `harness/runner.py` — `run_once(task, tool, seed, config) -> RunResult`,
  `RunConfig`, `RunResult`, `RunnerError`. About 250 lines. Wall-clock budget
  via `Popen(start_new_session=True)` + `os.killpg(SIGTERM)` → grace →
  `os.killpg(SIGKILL)`. Diff capture stages everything then diffs against the
  base SHA. Manifest write reads the wrapper's `tool_info.json` and merges
  it into the run's full manifest.
- `harness/tests/test_runner.py` — 12 unit tests using a stub bash wrapper
  that mimics `scripts/run_*.sh` (writes the five output files, optionally
  sleeps, optionally creates a file in the workdir). Covers: artifact
  presence, prompt construction (task.prompt + suffix), diff capture for
  created files, empty diff when agent does nothing, manifest field
  contents, non-zero exit propagation, timeout / SIGTERM-then-KILL,
  unsupported-tool rejection, missing-wrapper rejection, run-dir layout,
  cleanup-on / cleanup-off behavior.
- Updates to `harness/cli.py` — new `harness run` subcommand with
  `--task`, `--tool`, `--seed`, `--provider`, `--budget-seconds`,
  `--model`, `--framing`, `--run-id`, `--runs-root`, `--cleanup`.

## Plan deviations recorded

1. **Retries deferred to Step 11.** The plan listed retries as a Step 6
   deliverable; we explicitly moved them to the driver (Step 11) so
   `run_once` has a clean single-attempt contract. The manifest still
   carries `retries: {count: 0, reasons: []}` so Step 11 can populate it
   without a schema bump.
2. **Diff capture stages first.** Plan said `git diff <base>`; we use
   `git add -A` then `git diff --cached <base>`. Otherwise agent-created
   files (which agents do constantly) would silently disappear from
   `diff.patch`.

Plus three layout decisions locked in (consistent with the plan, more
specific than it): ISO-timestamp run-ids, the
`runs/<run-id>/<tool>/<task_id>/seed-<N>/` directory shape, and
"keep worktrees by default" — opt in to cleanup with `--cleanup`.

## Design decisions worth flagging

- **`RunConfig` is a dataclass with sensible defaults.** No "config dict"
  parsing layer; the CLI builds the dataclass directly. Tests construct
  it with `wrapper_override` and `worktree_manager` overrides so they
  never touch the real CLIs or the user's `~/.cache`.
- **`tool_info.json` is the integration point between Step 5 and 6.**
  The wrapper writes it; the runner reads it back and embeds it under
  `manifest.tool_info`. No separate "resolve binary" pass in Python —
  the wrapper already did it correctly and recorded the result.
- **Process group, not just the wrapper.** `start_new_session=True`
  makes the wrapper the leader of a fresh session/process group; SIGTERM
  goes to `os.killpg(pgid, ...)` so the whole tree dies — including the
  `claude` or `copilot` child the wrapper exec'd. Without this, signalling
  only the wrapper would leave the real tool process orphaned.
- **`subprocess.Popen` exit codes for signals.** Python returns the
  negative signal number when a child dies from a signal (`-15` for
  SIGTERM, `-9` for SIGKILL). The manifest captures this verbatim;
  Step 11's retry logic can distinguish "tool exited non-zero" from
  "we killed it for timeout" by looking at `timed_out` rather than
  parsing exit codes.
- **No `harness/manifest.py` yet.** Step 6 writes the manifest inline
  in `runner.py` because the schema is still in flux. Step 7 extracts
  a dedicated module once the trace parsers exist and the full schema
  is clear.

## Test approach: a stub bash wrapper

The runner tests can't realistically call the real `claude` / `copilot`
binaries — those cost money and require auth. They instead use a small
stub bash wrapper generated per-test that honors the same arg contract
(`--workdir`, `--run-dir`, `--prompt-file`, `--model`) and produces
the five output files (`stdout.log`, `stderr.log`, `exit_code`,
`wall_clock_seconds`, `tool_info.json`). The stub can optionally sleep
(to exercise the timeout path) and optionally create a file in the
workdir (to give the diff something to capture).

One bug worth recording during stub authoring: the first attempt built
the stub via `textwrap.dedent` over an f-string, but a test payload that
contained a literal `\n` produced a zero-indent line in the f-string,
which broke `dedent`'s common-indent calculation and left every line
prefixed with eight spaces — so the shebang wasn't first, and the
kernel returned `Exec format error`. Fixed by building the stub as a
list of lines and joining on `\n` — no indentation interpretation.

## Side effects on this machine

- `runs/step6-verify/claude/psf__requests-1142/seed-0/` is left in place
  for inspection (default `--keep` policy). Browse it the same way you
  did with the wrapper-verify run.
- The bare clone of `psf/requests` at
  `~/.cache/coding-agent-compare/repos/psf__requests.git` was reused
  from Step 4's verify; no new network fetch.
- Cost: ~$0.20 for the 60s claude run (estimated from token usage in
  `stdout.log`).

## Step 7 readiness

Step 7 (manifest + trace normalization) depends on Step 6 — done. The
manifest schema_version `"step6-stub"` makes the contract explicit:
Step 7 bumps it when it adds parsed-trace fields (`turn_count`,
normalized `events.jsonl`, etc.).
