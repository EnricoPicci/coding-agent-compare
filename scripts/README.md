# scripts/

Bash and Python entry points the user runs directly.

## Pre-flight (run once after install, and again after a CLI update)

- **`check_prereqs.sh`** — Linux / macOS / Git Bash / WSL.
  **`check_prereqs.ps1`** — native Windows PowerShell.
  Verify `git`, `uv`, `claude`, `copilot` are present on `PATH` and
  behaving like the tools they claim to be. Detects the VS Code
  Copilot Chat stub that can shadow the real Copilot CLI. Does **not**
  verify auth — that's manual.

- **`verify_wrappers.sh`** — exercise the two headless tool wrappers
  against a trivial prompt ("create a file called HELLO.txt") and
  show every artifact they produce. Supports `--tool claude|copilot|both`,
  `--model NAME` (uniform), and `--model-for tool=name` (repeatable,
  per-tool). Cheapest way to confirm auth + flag-surface + the
  acceptability of a specific `--model` name on this account *before*
  running a real matrix.

## Wrappers (called by the runner; same arg contract)

- **`run_claude.sh`** — headless invocation of Claude Code
  (`claude -p ... --output-format stream-json`).
- **`run_copilot.sh`** — headless invocation of GitHub Copilot CLI
  (`copilot -p ... --output-format json`).

Both accept:
```
--workdir <dir>      directory the agent treats as its working tree
--run-dir <dir>      directory the wrapper writes outputs into
--prompt-file <file> file whose contents are sent as the prompt
--model NAME         optional shared model override
```
Both write the same five artifacts to `<run-dir>`: `stdout.log`,
`stderr.log`, `exit_code`, `wall_clock_seconds`, `tool_info.json`.
Designed to be called by `harness.runner.run_once`, not by humans
directly — though they work standalone if you need to debug a wrapper
in isolation.

## Smoke runners (the canonical comparison invocations)

- **`grade_smoke_tasks.py`** — re-grade the smoke tasks' **gold
  patches** (the human PRs' fixes) without invoking any LLM. Zero API
  cost; exercises only the grader. Use after changing the grader, the
  providers, or per-task install specs to confirm the smoke set still
  grades cleanly.

- **`run_product_smoke.sh`** — run the smoke matrix in **Product**
  framing (each tool on its built-in default model). Answers
  *"what would my team's experience be out of the box?"*

- **`run_harness_smoke.sh`** — run the smoke matrix in **Harness**
  framing (both tools forced onto a shared model). Requires a model
  for each tool, supplied via `--model NAME` (uniform), `--model-for
  tool=name` (per-tool, for the dashed-vs-dotted naming asymmetry
  between `claude` and `copilot`), or both. Answers *"with the same
  model under both, which tool's scaffolding is more effective?"*

The last two smoke runners (i.e. those which exercise LLM calls) print a scope + cost preview and prompts for
confirmation before spending API budget. Skip the prompt with `--yes`
when scripting.

## Suggested workflow

```
1.  ./scripts/check_prereqs.sh                     # one-time, after install
2.  claude /login   &&   copilot /login            # manual, one-time
3.  ./scripts/verify_wrappers.sh                   # auth + flag-surface check
4.  ./scripts/grade_smoke_tasks.py                 # grader sanity check (no LLM)
5a. ./scripts/run_product_smoke.sh                 # the actual Product run
5b. ./scripts/run_harness_smoke.sh \
      --model-for claude=claude-sonnet-4-6 \
      --model-for copilot=claude-sonnet-4.6        # the actual Harness run
```

Steps 1–4 cost cents at most. Step 5 is the API-budget-spending one —
each smoke runner shows a scope + cost preview before the prompt; pass
`--yes` to skip the prompt for automation.

## Related documents

- [`../docs-generated-by-claude/13-product-vs-harness-modes.md`](../docs-generated-by-claude/13-product-vs-harness-modes.md)
  — what Product / Harness mean, when to use each, how to read the outputs.
- [`../docs-generated-by-claude/02-implementation-plan-step-by-step.md`](../docs-generated-by-claude/02-implementation-plan-step-by-step.md)
  — the broader plan; the smoke scripts wrap Step 11's driver.
- [`../docs-generated-by-claude/11-host-grader-pipeline.md`](../docs-generated-by-claude/11-host-grader-pipeline.md)
  — how `grade_smoke_tasks.py` and the runner's grader phase actually work.
- [`../README.md`](../README.md) — project Quickstart references the
  pre-flight scripts.
