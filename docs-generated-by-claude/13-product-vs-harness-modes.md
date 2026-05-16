# 13 — Product and Harness framings

Generated from `prompts/13-implement-step-11.md`.

> **See also:**
> - [`02-implementation-plan-step-by-step.md`](02-implementation-plan-step-by-step.md) — the broader plan; Step 11 implements the driver that runs both runnable framings.
> - [`12-grade-json-schema.md`](12-grade-json-schema.md) — what each cell of a matrix produces. The `manifest.framing` and `manifest.model` fields are how a run records which framing it was in.
> - The project root `README.md` and `CLAUDE.md` — both reference the three framings at a higher level.

The harness supports two **runnable framings** for comparing Claude Code and Copilot CLI: **Product** and **Harness**. They are not different tools; they are different *experimental setups* of the same `run-matrix` invocation. Pick a framing based on the question you're trying to answer.

This document explains:

1. What a framing is (and which of the project's three framings actually run anything).
2. What each runnable framing operationalizes (the concrete difference).
3. The reason both exist, and what reading them together tells you.
4. The exact commands to run each framing against the smoke task set.
5. How to read the outputs together to draw a conclusion.
6. Caveats — what NOT to compare.

## What is a framing?

A **framing** is an experimental setup for the comparison — a specific configuration of how the two tools are invoked, what model each runs on, and how their outputs are read. The project defines three framings:

1. **Product** — each tool runs with its built-in default model. Answers *"what should my team adopt?"* Confounds the model variable with the scaffolding variable.
2. **Harness** — both tools are forced onto the same shared model via the wrapper's `--model` flag. Answers *"which tool is better engineered?"* Holds the model variable constant so any remaining gap is attributable to scaffolding.
3. **Failure-mode analysis** — a qualitative read of traces from runs that already happened, looking for *how* the two tools fail differently. Answers *"what kinds of mistakes does each tool make?"*

**Only the first two require running the tools.** Product and Harness each invoke `harness run-matrix` (or `harness run`), which means **real LLM calls, real API budget, real test installs, and real grading**. Each invocation produces a directory tree of artifacts under `runs/<run-id>/`. Costs scale with the number of cells (tasks × tools × seeds) and the per-cell wall-clock budget.

The third framing — failure-mode analysis — **does not run anything and does not use any LLM**. It operates on the artifacts produced by Product or Harness runs: a human (or, eventually, Step 13's failure-mode tooling) reads `events.jsonl`, `manifest.json`, `stdout.log`, and `grade.json` for runs that failed or timed out, and writes up the patterns. Zero additional API cost; the only resource it consumes is human attention.

The rest of this document is about the two **runnable** framings — Product and Harness. Failure-mode analysis appears only in passing; see [`11-host-grader-pipeline.md`](11-host-grader-pipeline.md) and (forthcoming) Step 13's failure-mode tooling for that side of the project.

## Why two runnable framings (the conceptual reason)

Each tool you compare is not a single thing. Claude Code and Copilot CLI are each a *stack*:

```
+----------------------+
|  Model               |  ← the LLM (claude-sonnet-4-6, gpt-5, ...)
+----------------------+
|  System prompt       |  ← who the agent thinks it is
+----------------------+
|  Planning loop       |  ← when to call tools, when to stop, how to recover
+----------------------+
|  Tool surface        |  ← Bash, Read, Write, Grep, etc.
+----------------------+
|  Headless invocation |  ← the CLI binary, flag parsing, output format
+----------------------+
```

When you give both tools the same task and read the diffs they produce, you are comparing the *entire stack* of one against the entire stack of the other. A difference in outcome could come from any layer — different model, different system prompt, different planning loop, different tool surface, different default permissions.

That ambiguity is fine for one question: **"what should my team adopt?"** A decision-maker comparing two products doesn't care which layer is responsible for the difference — they care about the realistic out-of-the-box experience their team will get. That's the **Product framing**.

But it's *not* fine for the question **"which tool is better engineered?"** If Claude Code beats Copilot CLI by 10 percentage points on the smoke set, you can't tell whether that's because:

- Claude Code's scaffolding (prompts, planning loop, tool surface) is better, or
- Claude Code's default model is better than Copilot's default model.

To isolate the *scaffolding* variable, you have to hold the *model* variable constant. That's the **Harness framing**: both tools run with `--model <shared-name>` so the LLM is the same on both sides. Any remaining performance gap has to come from the layers above the model.

The **delta between Product and Harness** is the third interesting number:

- If Product gap ≈ Harness gap, the gap is mostly *scaffolding*. The model swap didn't change anything.
- If Product gap >> Harness gap, the gap is mostly *model*. When you force the same model, the tools perform similarly.
- If Product gap << Harness gap, surprising — the forced model is *worse* for one tool than its default. Worth investigating qualitatively.

That three-way reading is what makes running both framings worthwhile. Either framing alone gives a less interpretable number.

## What each runnable framing operationalizes (concrete)

The only mechanical difference between the two runnable framings is **whether the driver passes `--model <name>` to the wrappers**.

### Product framing

- The driver passes **no** `--model` argument to either wrapper.
- Each tool uses whatever its built-in default model is.
- Each cell's manifest records `framing: "product"` and `model: null`.
- No promise that both tools are running the same model. That's the point — you're measuring whole-stack performance as a user would experience it.

### Harness framing

- The driver passes `--model <shared-name>` to **every** wrapper invocation.
- Both tools are forced onto the same model.
- Each cell's manifest records `framing: "harness"` and `model: "<shared-name>"`.
- The model name must be one both tools accept. If a tool doesn't accept the flag, the cell is marked ineligible for harness comparison via the driver's per-cell crash path (this is currently framework-only; both smoke-set tools accept `--model`).

### How the framing label is derived

It is **not** a CLI flag. The framing string is **derived** from whether `--model` is set:

```python
def framing_from_model(model: str | None) -> str:
    return "harness" if model else "product"
```

The CLI exposes only `--model`; the framing label is computed once per run and recorded in `manifest.framing` for the reporter and human readers. There is no way to mismatch the two — passing a model means harness; omitting a model means product. (See the Step 11 deviation log in [`02-implementation-plan-step-by-step.md`](02-implementation-plan-step-by-step.md) for the rationale.)

## Commands to run the smoke tasks in each framing

The smoke task list at `tasks/swebench_smoke.yaml` contains three modern, pure-Python tasks (flask, pytest, requests — see Step 9's deviation log for the re-curation history). Running it against both tools in both framings is four commands total, but you'd usually invoke just one framing at a time.

### Convenience scripts (recommended)

Two ready-made bash scripts wrap the canonical invocations. Each prints a summary of the planned scope and costs, then prompts for confirmation before spending any API budget. Pass `--yes` to skip the prompt for automation.

```bash
./scripts/run_product_smoke.sh
./scripts/run_harness_smoke.sh --model claude-sonnet-4-6
```

Defaults:

- `--budget-seconds 600` (10 minutes per cell).
- `--run-id smoke-{product,harness}-<UTC-ISO-TIMESTAMP>` — each invocation generates a fresh, sortable run-id, so re-running doesn't overwrite prior runs. The matching prefix between the two scripts also makes "find both runs from the same comparison session" easy: glob `runs/smoke-product-2026-05-15T*` and `runs/smoke-harness-2026-05-15T*`.

The Harness script requires `--model <name>` — there is no default, because the Harness framing has no meaning without choosing which shared model to force. See "Choosing the shared model" below for guidance.

The rest of this section explains the underlying `harness run-matrix` commands the scripts wrap. Use them directly when you want finer control (different smoke list, different seed count, output JSON, etc.).

### Prerequisites

Before running either framing, verify the prerequisites:

```bash
./scripts/check_prereqs.sh         # macOS / Linux / WSL / Git Bash
./scripts/check_prereqs.ps1        # native Windows PowerShell
```

Both `claude` and `copilot` must be installed and pre-authenticated (the harness doesn't manage login). On a fresh machine the wrappers can also be sanity-checked with:

```bash
./scripts/verify_wrappers.sh
```

This runs a trivial prompt through each wrapper and confirms the headless invocation path works end-to-end. It costs a few cents.

### Product framing

Use the Product framing when you want to know "what would my team's experience be if they adopted either tool out of the box?"

```bash
uv run python -m harness run-matrix \
  --tasks tasks/swebench_smoke.yaml \
  --tools claude,copilot \
  --run-id smoke-product \
  --budget-seconds 600
```

Per-cell manifest fields:
- `manifest.framing` = `"product"`
- `manifest.model` = `null`

Outputs (3 tasks × 2 tools × 1 seed = 6 cells):

```
runs/smoke-product/
├── claude/
│   ├── pallets__flask-5014/seed-0/
│   │   ├── prompt.txt, diff.patch, stdout.log, stderr.log
│   │   ├── exit_code, wall_clock_seconds, tool_info.json
│   │   ├── events.jsonl, manifest.json, grade.json
│   │   └── grade-venv/
│   ├── pytest-dev__pytest-10051/seed-0/...
│   └── psf__requests-5414/seed-0/...
└── copilot/
    └── (same three task subdirectories)
```

Estimated wall-clock: ~30–60 minutes total (sequential; per-cell time depends on each agent's working pace within the 600 s budget). Estimated cost: ~$2–5 for claude; seat time only for copilot.

### Harness framing

Use the Harness framing when you want to know "with the same model under both, which tool's scaffolding is more effective?"

```bash
uv run python -m harness run-matrix \
  --tasks tasks/swebench_smoke.yaml \
  --tools claude,copilot \
  --model claude-sonnet-4-6 \
  --run-id smoke-harness \
  --budget-seconds 600
```

Per-cell manifest fields:
- `manifest.framing` = `"harness"`
- `manifest.model` = `"claude-sonnet-4-6"` (or whatever you passed)

Same six cells, same directory shape, but every cell's underlying agent runs on the shared model. The two `run_id`s are independent and produce independent directory trees.

**Choosing the shared model.** It must be a model both `claude` and `copilot` accept via `--model <name>`. Recommended starting point: a current Claude family model (e.g., `claude-sonnet-4-6` for balanced cost/quality, `claude-opus-4-7` if you want maximum capability). The actual list of accepted names depends on:

- The version of `claude` and `copilot` installed (both CLIs' model lists evolve).
- Your Copilot subscription's enabled model providers (Copilot routes to multiple LLM providers behind the scenes).

If a model name doesn't work, the wrapper fails with a clear error and that cell ends up in the matrix's crash path with `crashed_with` capturing the message. You can re-run with a different `--model` and a fresh `--run-id`.

### Running both back-to-back

A typical comparison session is both framings in sequence, with distinct run-ids so the two output trees can be diffed:

```bash
# Framing 1: Product — each tool uses its default model
uv run python -m harness run-matrix \
  --tasks tasks/swebench_smoke.yaml \
  --tools claude,copilot \
  --run-id smoke-product \
  --budget-seconds 600

# Framing 2: Harness — both tools forced onto a shared model
uv run python -m harness run-matrix \
  --tasks tasks/swebench_smoke.yaml \
  --tools claude,copilot \
  --model claude-sonnet-4-6 \
  --run-id smoke-harness \
  --budget-seconds 600
```

This produces two parallel directory trees under `runs/`. Step 12 (comparison report — forthcoming) will read each run-id and emit a markdown table; reading the two reports together is the analysis step.

### Running just one framing (smaller scope)

You don't have to run both. Useful one-at-a-time invocations:

- **Just Product, just claude:** `--tools claude` and no `--model`. Tells you "how does Claude Code do on the smoke set with its default model?" One tool's individual performance, no comparison.
- **Just Harness, just one task:** edit a temporary YAML containing one task ID, pass `--model <name>` and `--tools claude,copilot`. Smallest meaningful comparison; useful for iteration when adjusting the grader, the spec, or the prompt suffix.

## Reading the outputs together

Each cell's `grade.json` is the structured per-cell verdict (see [`12-grade-json-schema.md`](12-grade-json-schema.md) for the field reference). The interesting cross-cell comparisons are:

### Within one framing

For a fixed `run_id`, compare cells with the same `task_id` but different `tool`:

```
runs/smoke-product/claude/pallets__flask-5014/seed-0/grade.json
runs/smoke-product/copilot/pallets__flask-5014/seed-0/grade.json
```

Identical task, identical framing, different tool. Differences in `pass`, `files_touched_precision`, `diff_size_lines`, etc., reflect what happened in this configuration.

### Across the two framings

For a fixed `(task_id, tool)` pair, compare cells with different `run_id`:

```
runs/smoke-product/claude/pallets__flask-5014/seed-0/grade.json
runs/smoke-harness/claude/pallets__flask-5014/seed-0/grade.json
```

Same task, same tool. The two `grade.json`s differ only in what model the underlying agent used. If Claude's default model is similar in capability to the harness-shared model, these will look similar. If not, the delta tells you how much of Claude's scaffolding performance depends on its default model.

The fully interesting **2×2 corner** is per-task:

| | Product (default models) | Harness (`claude-sonnet-4-6`) |
|---|---|---|
| **claude** | pass, diff_size, precision | pass, diff_size, precision |
| **copilot** | pass, diff_size, precision | pass, diff_size, precision |

Step 12's report will build exactly this kind of table over the whole smoke set. Until that lands, manual inspection of the four `grade.json` files per task is the path.

## Caveats — what NOT to compare

- **Don't mix `run_id`s casually.** Each matrix invocation has a wall-clock, an environment, a tool version. Comparing cells from runs taken weeks apart conflates tool-version changes with framing changes. If you re-run an old matrix, give it a fresh `run_id` and compare against the latest run, not a stale one (see bolow for more details about this point).
- **Don't compare across different smoke task lists.** If you edited `tasks/swebench_smoke.yaml` between two runs (e.g., to add a fourth task), the average metrics aren't comparable cell-for-cell unless you only look at the tasks that both runs share.
- **Don't infer "tool X is worse" from a single seed.** Agent runs have real variance. Multi-seed runs (`--seeds 0,1,2`) are deferred to a later phase; one-seed-per-cell numbers in the smoke set are *directional*, not statistically conclusive.
- **Don't claim the Harness framing is "fair" in an absolute sense.** It controls for the model variable, which is the most important confounder, but not for the prompt-rendering variable. Each tool wraps the user's prompt in its own system-prompt overlay; that overlay differs even when the underlying LLM is the same. The Harness framing isolates the scaffolding-as-a-whole, not any specific sub-layer.
- **Don't treat `pass=null` cells as failures.** A null primary verdict means the grader couldn't reach one (install failed, host can't run the tests, etc.). It's data about the *grader's* ability to grade, not the tool's ability to solve. Step 12's report will handle these distinctly.

### More details about "Dont' mix run ids"
⏺ The caveat is about a specific pitfall: comparing two cells from different run_ids assumes everything except the framing is held 
  constant — but run_ids taken at different times aren't constant. Here's the full meaning, with a worked example.

  What a run_id actually is. Each harness run-matrix invocation produces a directory tree under runs/<run-id>/.... That tree is a
  snapshot of one experiment at one point in time. Inside it, every cell shares:

  - The same tool versions (claude --version, copilot --version — recorded in each cell's tool_info.json).
  - The same smoke task definitions (whichever tasks/swebench_smoke.yaml was on disk when the run started).
  - The same grader logic (whatever harness/graders/swebench_host.py was at that commit).
  - The same Python environment for the grader (whatever was in your uv cache).
  - The same wall-clock conditions (same machine, same network, same time of day).

  The whole point of the Product-vs-Harness comparison is to vary only the framing, with everything else above held identical.
  That's only true if both run_ids were taken back-to-back.

  The pitfall, made concrete. Imagine this scenario:
  
  2026-03-01:  harness run-matrix ... --run-id old-product
               # at this time: claude 2.0.0, copilot 1.0.40,
               # smoke list still had requests-1142 (the 2013 task),
               # grader was Step 9's first iteration.

  2026-05-15:  harness run-matrix ... --model X --run-id new-harness
               # by now: claude 2.1.140, copilot 1.0.46,
               # smoke list has been re-curated to flask/pytest/requests-5414,
               # grader has Step 10's secondary metrics, and the
               # parametrized-name stitching fix in the provider.
  
  If you then opened runs/old-product/claude/.../grade.json next to runs/new-harness/claude/.../grade.json and saw a difference,
  you'd have no way to tell which of these is responsible:

  - Framing change (default model → forced shared model) — the variable you meant to study.
  - Tool version drift — claude 2.0.0 might handle prompts differently than 2.1.140.
  - Smoke task drift — the tasks aren't even the same; comparing requests-1142 vs requests-5414 answers nothing meaningful.
  - Grader drift — the older grade.json was produced by a grader that didn't have parametrized-name stitching, so its unresolved
  count for requests-5414 would be inflated.
  - Environmental drift — different pip resolutions, different transitive deps, different Python patch versions.

  All five confounders get baked into the delta. You can't disentangle them after the fact.

  What "casually" hedges. The caveat isn't absolute — there are legitimate use cases for comparing across distant run_ids:
  
  - Tool-version regression studies. "Did claude 2.2.0 perform worse than claude 2.1.140 on the same smoke set?" Here the version
  drift IS the variable of interest, so you want the run-ids to differ in tool version while holding everything else fixed. That's
  a deliberate cross-run_id comparison.
  - Grader-improvement validation. "After I refined the grader, did its pass verdicts on already-recorded runs change?" Here you'd
  re-grade existing diffs against the new grader (cheap; the diffs are stored) — but you'd be holding the tool version and run
  artifacts fixed and varying only the grader logic.

  For the ordinary Product-vs-Harness comparison this document is about, none of those apply. You want everything except framing
  held identical, which means both run-ids taken in the same session.

  The practical rule it boils down to. When you sit down to do a Product-vs-Harness comparison:
  
  1. Run the Product matrix (fresh run-id).
  2. Immediately run the Harness matrix (different fresh run-id, but moments later, same machine, same tool versions, same smoke
  list, same grader).
  3. Compare cells across those two run-ids only. That's the section earlier in the doc titled "Running both back-to-back."
  4. Don't pair either of those with a run-id from last month. That older run's environment has drifted; the comparison would be
  polluted by confounders that have nothing to do with the framing variable you're trying to study.

  That's the meaning. The wording could probably be tightened — happy to rewrite it more explicitly along the lines above if you'd
  like.

## Sanity-checking a framing before running it

Before paying for a full matrix in either framing, run the cheap pre-flight checks. Each one catches a different class of failure-before-it-spends-money:

1. **Verify your auth works.** `./scripts/verify_wrappers.sh` runs both wrappers against a trivial prompt. ~10–20 s on success; both tools' auth state and headless flag surface verified. Costs cents.
2. **Verify the smoke set still grades the gold patches.** `uv run python scripts/grade_smoke_tasks.py` re-runs the grader against the human PR's gold patch for each smoke task. ~30–60 s. Zero LLM cost. If a smoke task's gold patch no longer grades as `pass: true`, your install spec or test environment has drifted — fix that before running real agents.
3. **For the Harness framing specifically: verify the chosen model is accepted by BOTH tools** (this is the most common pitfall — `claude` and `copilot` have disjoint model namespaces, and a name accepted by one is often rejected by the other). Two sub-cases worth understanding:

   **3a. Same name works for both tools.** Rare but simplest. The check is one line:

   ```bash
   # Cheapest Harness-framing pre-flight — strongly recommended.
   # ~30 seconds total; no API budget burned on rejection.
   ./scripts/verify_wrappers.sh --model claude-sonnet-4-6
   ```

   **3b. The two tools want different names for the same model.** Common in practice — Anthropic-canonical names use dashes (`claude-sonnet-4-6`) while Copilot's catalog re-labels with dots (`claude-sonnet-4.6`) for the same underlying weights. Use `--model-for <tool>=<name>` (repeatable) to give each tool the name it accepts:

   ```bash
   # Per-tool model override — supports the dashed-vs-dotted asymmetry.
   ./scripts/verify_wrappers.sh \
     --model-for claude=claude-sonnet-4-6 \
     --model-for copilot=claude-sonnet-4.6
   ```

   The Results section at the end shows each tool's `exit_code`, `stderr.log` size, and — for failed cells — the captured stderr inline. If either tool exited fast with a non-empty `stderr.log`, that model name was rejected — read the stderr to see why (typical errors: `"Model 'X' from --model flag is not available."` from copilot, `"It may not exist or you may not have access to it."` from claude). Cells from rejected tools are unsafe to take to the full matrix; pick a different name (re-probe one tool at a time with `--tool <tool> --model NAME` if needed) until both succeed.

   Both forms work the same way when invoking the actual matrix — `harness run-matrix` and `./scripts/run_harness_smoke.sh` accept both `--model NAME` (uniform) and `--model-for tool=name` (per-tool), and the per-tool override always wins for the named tool.

4. **(Optional, costs ~1 cell's worth) Verify the full agent pipeline on one tool.** Useful when step 3 passed but you want to confirm the agent actually does work on a real task at the chosen model:

   ```bash
   uv run python -m harness run \
     --task pytest-dev__pytest-10051 \
     --tool claude \
     --model claude-sonnet-4-6 \
     --budget-seconds 120 \
     --run-id harness-preflight
   ```

   Look for `manifest.framing == "harness"` and `manifest.model == "claude-sonnet-4-6"` in the resulting `manifest.json`. If that's good, the full matrix is safe to run.

For Product framing, only steps 1 and 2 apply (there's no `--model` to validate).

## Related documents

- [`02-implementation-plan-step-by-step.md`](02-implementation-plan-step-by-step.md) — the implementation plan; Step 11 is the driver that runs the matrix in either framing. The Step 11 deviation log explains why `--framing` is derived from `--model` rather than a separate CLI input.
- [`12-grade-json-schema.md`](12-grade-json-schema.md) — what every cell produces. The `framing` and `model` fields are populated by the runner using the framing-from-model rule documented here.
- [`02-grader-role-explained.md`](02-grader-role-explained.md) — what a grader is and why it's separate from the runner. The grader runs identically regardless of framing; the framing affects only the agent invocation.
- [`11-host-grader-pipeline.md`](11-host-grader-pipeline.md) — implementation deep-dive into the host grader. Framing-agnostic; the same pipeline runs after every cell regardless of which framing produced the run.
- Project root `README.md` and `CLAUDE.md` — both summarize the three framings at the highest level.
