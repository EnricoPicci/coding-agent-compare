# 02 — Implementation plan, step by step

Generated from `prompts/02-plan-in-details.md`.

> **See also:** [`02-grader-role-explained.md`](02-grader-role-explained.md) — what a "grader" is in this harness, why it's a separate component from the runner, and why step 9 below is the riskiest step.

## Goal of this plan

Define the smallest sequence of concrete steps that takes the repo from "docs only" to "we can run a curated handful of SWE-bench Verified tasks through both Claude Code and Copilot CLI and produce a side-by-side comparison." Each step is small enough to verify on its own; later steps depend only on earlier ones.

## What this plan is **not**

- Not a final design. Several decisions are deliberately deferred (see *Open questions* and *Out of scope*).
- Not a schedule. Estimates are rough — "S/M/L" — to triage what to do first, not to commit.
- Not the full evaluation. The smoke loop intentionally uses 3–5 hand-picked task IDs; scaling to the full Verified set is a follow-on.

## Architectural decisions (locked in by prior conversation)

| Decision | Value | Why |
|---|---|---|
| Phase | Pragmatic start | Smallest scaffolding that produces signal; grow as it proves out. |
| Orchestrator language | Python 3.11+ | Familiar; good for parsing + grading. |
| Python tooling | `uv` | Single binary; per-task venvs are fast; lockfile by default. |
| Shell glue | bash scripts under `scripts/` (canonical) + PowerShell mirrors for user-facing entry points only | Bash is the canonical interpreter; runner internals stay bash-only to avoid doubling maintenance. PowerShell mirrors exist only for entry-point scripts (e.g., `check_prereqs.ps1`) so native-Windows users aren't blocked at first contact. |
| Per-task isolation (agent runtime) | git worktrees under `runs/` | No Docker for the *agent's* working environment in this phase. |
| Per-task isolation (Python deps) | per-task `uv` venv | Covers Python deps cleanly; doesn't cover native deps — that's a known limitation. |
| Task data source | Official `swebench` package + HuggingFace Verified dataset | Reuse the dataset and instance metadata; do not reuse their Docker eval runner. |
| Task selection | `task_ids` filter on the provider | Hand-pick 3–5 IDs for smoke; scale by widening the filter. |
| Comparison framings | Product, Harness, Failure-mode | All three as modes of the same harness. |
| Retries | Default 2, transient infra only | A failed-test run is signal, not retried. |
| Wall-clock budget | 15 min per `(task, tool, seed)` default | Configurable; enforced by Python supervisor. |
| Seeds per task | 1 in smoke phase | Multi-seed deferred until smoke produces signal. |

## Open architectural questions (decide before or during the step that touches them)

1. **Grader execution environment.** SWE-bench's published evaluation harness runs tests inside per-instance Docker images. We've decided against Docker for *agent runtime* but the grader is a separate question. Three options:
   - **A. Host venv grader.** Replicate SWE-bench's install commands inside a per-task `uv` venv on the host, apply the test patch, run the test command, parse FAIL_TO_PASS / PASS_TO_PASS. Works for tasks with no native deps; breaks on others. The smoke list must be curated to host-runnable instances.
   - **B. SWE-bench Docker grader.** Use SWE-bench's prebuilt eval images *only* for grading — agent still runs in a host worktree. Cleanest signal but introduces Docker for the smoke phase.
   - **C. Mock grader for smoke phase.** Skip real test execution entirely; assert only that the agent produced a non-empty diff and the harness captured trace/manifest correctly. Validates the *machinery* without validating *results*.
   - **Recommended:** start with **C** (steps 1–8 don't need a real grader), then promote to **A** in step 9, with **B** as a documented escape hatch when **A** fails on a task we care about.
2. **CLI auth in headless mode.** Both `claude` and `copilot` expect prior interactive auth. The plan assumes the user has logged in once on this machine before any run. We document this in step 0 but do not automate it.
3. **Wall-clock enforcement semantics.** SIGTERM, grace period, then SIGKILL? Does each tool flush its trace cleanly on SIGTERM? Step 7 decides.
4. **Trace format normalization.** Each tool emits its own format. We capture raw + write a thin per-tool parser to a normalized `events.jsonl`. Schema decided in step 8 once we've seen real output from both tools.
5. **Cost tracking.** Out of scope for the smoke phase; revisit when we have multi-seed runs and the volume justifies it.

## Prerequisites (manual, one-time)

Supported hosts: **Linux, macOS, or Windows**. On Windows, the harness runs under either Git Bash or WSL — both ship a POSIX-compatible bash and are the path of least friction since Git for Windows includes Git Bash. Native-Windows PowerShell users can run the entry-point checker but will still need bash (Git Bash / WSL) for the runner scripts in step 5 onward.

- [ ] Host runs Linux, macOS, or Windows. On Windows, install Git for Windows (provides Git Bash) or WSL2.
- [ ] `git` and `uv` installed.
- [ ] `claude` CLI installed and authenticated (`claude --version` works, prior `/login`).
- [ ] `copilot` CLI installed and authenticated (`copilot --version` works, prior `gh auth login` with Copilot access). Note: a `copilot` binary shipped by VS Code's Copilot Chat extension can shadow the real CLI; the checker below detects this.
- [ ] HuggingFace token if SWE-bench Verified gating ever requires it (it currently doesn't, but the `datasets` library caches under `~/.cache/huggingface`).
- [ ] ~5GB free disk for worktrees + venvs in the smoke phase.

### Verify the prerequisites

Run the bundled checker before starting Step 1:

```bash
# Linux, macOS, Windows-with-Git-Bash, WSL
./scripts/check_prereqs.sh

# Native Windows PowerShell (or pwsh anywhere)
./scripts/check_prereqs.ps1
```

The checker exits non-zero if any required tool is missing or if a binary on `PATH` claims to be a tool but doesn't behave like one (e.g., the VS Code Copilot stub). It does **not** verify CLI authentication — that's a manual step. Authentication can only be confirmed by an interactive login.

## Steps

Each step lists: **Goal** (what's true when done), **Deliverables** (files/code), **Verify** (how we know), **Effort** (S ≈ <2h, M ≈ ½ day, L ≈ 1+ day), **Depends on**.

### Step 1 — Repo skeleton & `uv` project

- **Goal:** `uv` project initialized; the harness can be installed in editable mode and imported as `import harness`.
- **Deliverables:**
  - `pyproject.toml` (uv-managed, package name `coding-agent-compare`, Python ≥ 3.11)
  - `.python-version` pinned (e.g., `3.11`)
  - `harness/__init__.py`, `harness/__main__.py` (CLI entry stub: `python -m harness --help`)
  - `.gitignore` (covers `.venv/`, `runs/`, `__pycache__/`, `.uv-cache/`, `*.egg-info`)
  - `ruff.toml` (formatter + linter, default config)
  - `tasks/.gitkeep`, `runs/.gitkeep` only where the dir must exist. `scripts/` already exists and contains `check_prereqs.{sh,ps1}`.
- **Verify:** `uv sync && uv run python -m harness --help` prints a usage line. `uv run ruff check .` passes.
- **Effort:** S.
- **Depends on:** —

### Step 2 — Task model & `TaskProvider` interface

- **Goal:** A typed `Task` dataclass and an abstract `TaskProvider` exist. No real provider yet.
- **Deliverables:**
  - `harness/task.py` defining `Task(task_id, repo_url, base_sha, prompt, test_command, fail_to_pass, pass_to_pass, expected_changed_files, metadata)`.
  - `harness/providers/base.py` with `class TaskProvider(Protocol): def load(self, task_ids: list[str] | None) -> list[Task]: ...`.
  - Unit test for `Task` round-tripping to/from dict (used later for manifests).
- **Verify:** `uv run pytest harness/` green.
- **Effort:** S.
- **Depends on:** 1.

### Step 3 — `SWEBenchVerifiedProvider`

- **Goal:** Loading the Verified dataset returns a `list[Task]`; filtering by `task_ids` returns only those.
- **Deliverables:**
  - `harness/providers/swebench.py` using `datasets.load_dataset("princeton-nlp/SWE-bench_Verified", split="test")`.
  - Mapping from SWE-bench instance fields (`instance_id`, `repo`, `base_commit`, `problem_statement`, `test_patch`, `FAIL_TO_PASS`, `PASS_TO_PASS`) → our `Task`.
  - Rely on HuggingFace's built-in `~/.cache/huggingface/` dataset cache; no project-local cache layer. *[Δ Step 3 — see Changes log below.]*
  - `tasks/swebench_smoke.yaml` listing 3 hand-picked instance IDs locked in during Step 3 implementation: `sympy__sympy-20154`, `pylint-dev__pylint-7080`, `psf__requests-1142`. All three validated against the Verified split and span easy/medium difficulty across three repos. *[Δ Step 3 — see Changes log below.]*
  - `datasets>=3.0` + `pyyaml>=6.0` added to `pyproject.toml`. *[Δ Step 3 — see Changes log below.]*
- **Verify:** `uv run python -m harness tasks list --provider swebench --filter tasks/swebench_smoke.yaml` prints the smoke task IDs with title/repo/SHA.
- **Effort:** M.
- **Depends on:** 2.

#### Changes introduced during implementation of Step 3

Three deviations from the originally written plan were approved before coding (see `prompts/05-implement-step-3.md` for the conversation) and one decision was locked in at implementation time:

1. **Dropped the `swebench` PyPI package as a dependency.** The package is heavy (pulls in Docker SDKs and the Docker-based evaluation harness). The plan's architectural decisions explicitly say *"we do not reuse their Docker eval runner,"* so the package brings cost without benefit. We load the dataset directly via HuggingFace `datasets` and map the fields ourselves. If we ever need something `swebench` offers (e.g., a parsing helper), reintroducing it then is cheap.
2. **No project-local cache file.** HuggingFace's `datasets` library already caches at `~/.cache/huggingface/datasets/`, and re-mapping ~500 Verified rows to `Task` objects takes microseconds. Adding a second cache layer would only have value if mapping became a bottleneck — which it is not. Revisit only if measurable.
3. **Added `pyyaml>=6.0`** because the filter file format remained YAML as the plan specified, and we needed a parser.
4. **Smoke task IDs are now locked, not tentative.** The plan listed the three IDs as "initial candidates to validate." All three exist in the Verified split, are pure-Python, pytest-based, and have small-to-medium patches — they pass the criteria. Final list: those three.

### Step 4 — Worktree manager

- **Goal:** Given a `Task`, the manager can prepare a clean worktree at `runs/<run-id>/<tool>/<task_id>/repo/` checked out at `task.base_sha`, and tear it down.
- **Deliverables:**
  - `harness/worktree.py` with `prepare(task, run_dir) -> Path` and `cleanup(path)`.
  - Local mirror of each repo cached under `~/.cache/coding-agent-compare/repos/<repo>.git` (bare clone, fetched once, reused via `git worktree add`).
  - Lock file to serialize worktree adds on the same mirror.
- **Verify:** Running `prepare()` for a smoke task yields a worktree at the right SHA; `git -C <path> rev-parse HEAD` matches `task.base_sha`.
- **Effort:** M.
- **Depends on:** 2.

### Step 5 — Tool wrappers (bash)

- **Goal:** Two scripts, identical contract, invoke each tool headlessly in a given worktree with a prompt and a wall-clock budget. They write `stdout.log`, `stderr.log`, `exit_code`, `wall_clock_seconds`, and a tool-specific `trace.raw` to a passed-in run dir.
- **Deliverables:**
  - `scripts/run_claude.sh` — wraps `claude -p "<prompt>" --output-format stream-json` with `timeout`-style wall-clock enforcement (Python supervisor delivers SIGTERM then SIGKILL; the bash script just exec's the binary).
  - `scripts/run_copilot.sh` — wraps `copilot -p "<prompt>" --allow-all-tools` (and `--model <model>` if provided).
  - Both scripts accept: `--workdir`, `--run-dir`, `--prompt-file`, optional `--model`.
- **Verify:** Manual: run each script against a worktree with a trivial prompt ("create a file called HELLO.txt"); both write logs and produce a non-empty diff. Document the exact `--version` of each tool you tested with in the run manifest.
- **Effort:** M (the long-tail is fighting headless flags).
- **Depends on:** 4.
- **Tool resolution note (PATH ordering).** `copilot` (and possibly `claude`) is commonly installed as a *project-local* npm dependency at `./node_modules/.bin/<tool>`. On developer machines, an unrelated `copilot` binary may live earlier in `PATH` — notably VS Code's GitHub Copilot Chat extension ships a `copilot` stub at `~/Library/Application Support/Code/.../copilotCli/copilot` that prints an install prompt and exits 0. A naive `exec copilot` from these wrappers will pick up the stub and silently corrupt every run. Each wrapper must therefore resolve the binary in npm order: project-local `./node_modules/.bin/<tool>` first, then `PATH`. Implement either by prepending `"$REPO_ROOT/node_modules/.bin"` to `PATH` at the top of each wrapper, or by resolving the absolute path once and invoking it directly. The prerequisite checker (`scripts/check_prereqs.{sh,ps1}`) already uses this resolution order; mirror that logic here. The resolved absolute path and the resolved tool version must both be recorded in the run manifest so a future reader can tell which binary actually ran.

#### Changes introduced during implementation of Step 5

Two deviations from the originally written deliverable were approved before coding (see `prompts/07-implement-step-5.md` for the conversation):

1. **Dropped the separate `trace.raw` file.** Both tools, when invoked with the structured-output flags the plan already specifies (`--output-format stream-json` for `claude`, `--output-format json` for `copilot`), stream the structured trace to stdout. Writing `stdout.log` *and* a byte-identical `trace.raw` would duplicate every run's payload with no upside; downstream parsers (Step 7) will read `stdout.log` directly. If a future tool moves its trace off stdout (separate log file, OTel exporter), reintroducing `trace.raw` is a one-line wrapper change at that time.
2. **Added `tool_info.json` to the per-run output dir.** The plan's note already requires the resolved binary path and tool version to land in the run manifest. Having the bash wrapper write a single-line `tool_info.json` (`{"tool", "binary", "version"}`) makes the manifest writer's job mechanical (merge a known file) and means manual / ad-hoc invocations of the wrapper produce the same metadata trail as supervised runs. Three lines of bash + a one-liner `python3 -c 'import json; ...'` for safe quoting.

Two flag-surface details locked in at implementation time against the live CLIs (claude 2.1.140, copilot 1.0.46):

- **Claude headless = `-p "<prompt>" --output-format stream-json --verbose --dangerously-skip-permissions`.** `--verbose` is required by claude when combining `-p` (print) with `--output-format=stream-json`; without it the tool errors out. `--dangerously-skip-permissions` is claude's equivalent of copilot's `--allow-all-tools` — required for any headless, non-interactive run.
- **Copilot headless = `-p "<prompt>" --allow-all-tools --output-format json --no-auto-update --no-color -C "<workdir>"`.** `--no-auto-update` prevents the CLI from silently downloading a newer version mid-run (which would invalidate the version recorded in `tool_info.json`); `--no-color` keeps stdout clean ANSI-free for parsers; `-C <dir>` is copilot's `cd`-equivalent and removes the need for a subshell in the wrapper.

Note on `--no-auto-update`: the locally-installed copilot was 1.0.45 before the first verify attempt and 1.0.46 after the user re-authenticated via `copilot /login`. The version bump happened during the interactive `/login` flow, not during a `-p` run — `--no-auto-update` only suppresses background updates during invocation, not user-initiated updates from interactive sessions. This is expected; the manifest captures whichever version was resolved at run time.

### Step 6 — Single-run executor

- **Goal:** One Python function runs one `(task, tool, seed)` end-to-end: prepare worktree, invoke wrapper, enforce wall-clock + retries, capture diff + trace + manifest.
- **Deliverables:**
  - `harness/runner.py::run_once(task, tool, seed, config) -> RunResult`.
  - Wall-clock enforcement: `subprocess.Popen` with `start_new_session=True`; on timeout, SIGTERM, 30s grace, SIGKILL.
  - Retry policy implemented per CLAUDE.md: 2 transient retries on non-zero-but-recognized exit codes / network errors / rate-limit signals; never on "produced a diff that fails tests".
  - Diff capture: `git -C <worktree> diff <base_sha> --` written to `diff.patch`.
- **Verify:** `uv run python -m harness run --task <id> --tool claude --seed 0` produces a `runs/<run-id>/claude/<task>/` dir containing `diff.patch`, `stdout.log`, `stderr.log`, `trace.raw`, and a manifest stub.
- **Effort:** M.
- **Depends on:** 3, 4, 5.

#### Changes introduced during implementation of Step 6

Two deviations from the originally written plan were approved before coding (see `prompts/08-implement-step-6.md` for the conversation):

1. **Retries deferred to Step 11.** The plan made retries a Step 6 deliverable, but on reflection retry orchestration belongs in the driver (Step 11) that owns multi-attempt state and decides whether to re-run a `(task, tool, seed)`. Keeping `run_once` single-attempt produces a clean contract: it does *exactly one* attempt and returns the outcome. The manifest still carries a `retries: {count, reasons}` field, currently always `{0, []}`, so Step 11 can populate it without a schema bump.
2. **Diff capture uses `git add -A` + `git diff --cached <base_sha>`, not bare `git diff <base_sha>`.** Agents typically *create* files (the wrapper-verify run produced a brand-new `HELLO.txt`); a tracked-only diff would silently lose every created file. Stage-all-then-diff captures created, modified, and deleted files in one canonical patch. The mutation to the worktree's index is harmless because worktrees are per-task and disposable.

Layout locked in at implementation time (compatible with the plan, more specific than it):

- Run-id is an ISO timestamp like `2026-05-13T11-45-00` (sortable, human-readable) when not user-supplied via `--run-id`.
- Per-run artifacts live at `runs/<run-id>/<tool>/<task_id>/seed-<N>/`, with the worktree as a subdirectory `repo/` (consumed from `WorktreeManager.prepare()`). All other artifacts — `prompt.txt`, `stdout.log`, `stderr.log`, `exit_code`, `wall_clock_seconds`, `tool_info.json`, `diff.patch`, `manifest.json` — sit next to `repo/`.
- Worktrees are *kept* by default after a run, so a human can inspect what the agent did. Opt-in cleanup via `--cleanup`.
- Manifest schema_version is `"step6-stub"`. Step 7 bumps this when it adds parser-derived fields (turn count, tool calls, etc.).

POSIX-only assumption: `runner.py` uses `start_new_session=True` and `os.killpg`. The repo is already bash-required (`scripts/run_*.sh`), so this constraint is consistent — Windows users go through Git Bash / WSL where these primitives work.

### Step 7 — Run manifest + trace normalization

- **Goal:** Every run dir contains a `manifest.json` capturing everything needed to reason about the run later; a `events.jsonl` provides a thin normalized view across tools.
- **Deliverables:**
  - `harness/manifest.py` writing: `task_id`, `tool`, `tool_version`, `model` (if known), `seed`, `started_at`, `ended_at`, `wall_clock_seconds`, `exit_code`, `retries` (count + reasons), `cli_args`, `host_info` (uname, python version), `framing` (product/harness).
  - `harness/parsers/claude.py` and `harness/parsers/copilot.py` translating each tool's raw trace into normalized events (`message`, `tool_call`, `tool_result`, `error`). Be conservative — only emit fields we're confident about; preserve raw alongside.
- **Verify:** Manifest validates against a Pydantic model; `events.jsonl` is parseable line-by-line; turn counts derivable.
- **Effort:** M.
- **Depends on:** 6.

### Step 8 — Mock grader (machinery-only)

- **Goal:** A grader that runs after every run and produces `grade.json` with a single field `produced_nonempty_diff: bool`. Enough to validate end-to-end plumbing without committing to the real test runner yet.
- **Deliverables:**
  - `harness/graders/mock.py`.
  - Wired into `run_once` as the default grader for now.
- **Verify:** `grade.json` written for every run; `false` for runs that produced no diff.
- **Effort:** S.
- **Depends on:** 6.

### Step 9 — Primary grader: host-venv test runner

- **Goal:** For tasks whose test commands run on the host, the grader replays the test patch, runs the test command, parses results against `FAIL_TO_PASS` / `PASS_TO_PASS`, and emits pass/fail.
- **Deliverables:**
  - `harness/graders/swebench_host.py`:
    - Creates per-task `uv venv` at `runs/<run-id>/<tool>/<task>/grade-venv/`.
    - Installs the repo per the instance's `install` commands (from SWE-bench metadata) into the venv.
    - Applies the test patch on top of the agent's diff.
    - Runs the test command, captures stdout/stderr.
    - Parses results; produces `grade.json` with `tests_passed`, `tests_failed`, `unresolved`, `pass`, `notes`.
  - Tagged smoke tasks with `host_runnable: true|false`; the grader refuses non-runnable ones with a clear "ungradeable on host" status.
- **Verify:** Running the grader against the gold patch for a smoke task yields `pass: true`. Running it against an empty diff yields `pass: false`. Running it against an agent diff produces a reasoned result.
- **Effort:** L. This is the riskiest step — most likely to surface dependency-isolation pain.
- **Depends on:** 8.

### Step 10 — Secondary graders

- **Goal:** Additional metrics emitted alongside the primary pass/fail.
- **Deliverables:**
  - `harness/graders/scope.py`: files-touched precision/recall vs. the human PR's `patch` field.
  - `harness/graders/size.py`: diff line count vs. human PR.
  - Both append to `grade.json` rather than producing separate files.
- **Verify:** Hand-check on one smoke task: precision/recall numbers match a manual diff of the file sets.
- **Effort:** S.
- **Depends on:** 9.

### Step 11 — Multi-mode driver (Product vs. Harness)

- **Goal:** A single command runs the full smoke list through both tools in either Product or Harness mode and produces a flat directory of completed runs.
- **Deliverables:**
  - `harness/driver.py::run_matrix(tasks, tools, framing, config)`.
  - Framing logic: in *Product* mode, each tool gets its default model. In *Harness* mode, both tools run with `--model <shared-claude-model>`; if the tool doesn't accept the flag, the run is marked ineligible for Harness comparison rather than silently downgraded.
  - CLI: `python -m harness run-matrix --tasks tasks/swebench_smoke.yaml --tools claude,copilot --framing product`.
- **Verify:** Single command produces `runs/<run-id>/{claude,copilot}/<task>/{...}` for every smoke task in both framings.
- **Effort:** M.
- **Depends on:** 7, 10.

### Step 12 — Comparison report

- **Goal:** A single markdown report per run aggregating both tools' results into a comparison table.
- **Deliverables:**
  - `harness/report.py` emitting `reports/<run-id>.md`:
    - Per-task table: tool × (pass, files-precision, files-recall, diff-size, wall-clock, turns, retries).
    - Aggregate row at the bottom.
    - Section listing every run that hit the wall-clock or had non-zero retries (for failure-mode triage).
- **Verify:** After step 11, `uv run python -m harness report --run-id <id>` produces a readable `reports/<run-id>.md`.
- **Effort:** S.
- **Depends on:** 11.

### Step 13 — Failure-mode trace tooling

- **Goal:** A helper that extracts traces from the N most informative failed runs and concatenates them with manifest context for human reading. No automated analysis; this is to make qualitative review fast.
- **Deliverables:**
  - `harness/failure_mode.py`: `python -m harness failures --run-id <id> --top 10` writes `reports/<run-id>-failures.md` with manifest + normalized events for each failure.
- **Verify:** Output is readable; failure cases jump out.
- **Effort:** S.
- **Depends on:** 12.

## Definition of done (smoke phase)

All of the following are true:

- `uv run python -m harness run-matrix --tasks tasks/swebench_smoke.yaml --tools claude,copilot --framing product` completes without harness errors on every task (agent may still fail the task; that's data).
- Same command works with `--framing harness --model <claude-model>`.
- Every run has `manifest.json`, `diff.patch`, `events.jsonl`, `grade.json`.
- `reports/<run-id>.md` is produced for both framings.
- The repository contains no Docker dependency.
- CLAUDE.md / AGENTS.md remain semantically equivalent.

## Out of scope (deliberately deferred)

- Docker isolation (agent or grader).
- Multi-seed runs (≥3 per task).
- LLM-as-judge tertiary grader.
- Promptfoo orchestration / UI.
- Own-repo PR `TaskProvider`.
- Synthetic task `TaskProvider`.
- CI workflows.
- Cost tracking.
- Codespaces / cloud deployment.
- MCP server parity (default: no MCP on either side).

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Copilot CLI headless flags change again | Medium | High | Pin tool version in manifest; isolate the flag surface inside `scripts/run_copilot.sh`. |
| Step 9 (host-venv grader) breaks on a smoke task's deps | High | Medium | Curate smoke list to host-runnable instances; fall back to mock grader for that task; escalate to Docker grader (option B) if it becomes a blocker. |
| Claude / Copilot auth expires mid-run | Medium | Medium | Document one-time auth as prerequisite; surface auth errors loudly in `errors.log`; the retry policy already handles transient auth blips. |
| Wall-clock SIGTERM corrupts a tool's trace | Low | Medium | Always preserve `stdout.log` + `stderr.log` raw; never depend solely on the tool's internal trace flushing. |
| SWE-bench dataset format changes | Low | High | Pin `swebench` and `datasets` versions; mapping is in one place (`providers/swebench.py`). |
| Slow first run (large dataset download, repo clones) | High | Low | Pre-warm the cache as a documented step 0; subsequent runs reuse. |

## Suggested order of work

Steps 1 → 7 form the spine of the machinery; 8 is the cheapest grader that proves end-to-end plumbing. Stop there, run it once, look at the output, *then* commit to step 9 (the real grader). Steps 10–13 follow naturally once 9 is reliable on the smoke list.
