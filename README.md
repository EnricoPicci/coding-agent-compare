# coding-agent-compare

A minimal harness for comparing **Claude Code** and **GitHub Copilot CLI** running in agent mode on the same software-engineering tasks.

The point isn't to crown a winner once. It's to have a reproducible setup so the question can be re-answered as both tools evolve.

## Why

Comparing agentic coding tools isn't a model-vs-model fight — it's a comparison of whole systems: prompts, planning loops, tool design, file-edit strategy, MCP integration. The model is one variable; the scaffolding around it is another. Both tools support headless invocation, so the same task can be driven through each and the results graded the same way.

## Methodology

Three framings, run as three modes of the same harness:

| Mode | What it isolates | Answers |
|---|---|---|
| **Product** (default configs) | Nothing — realistic deployment | "What should my team adopt?" |
| **Harness** (same Claude model on both) | Scaffolding only | "Which tool is better engineered?" |
| **Failure-mode analysis** | Qualitative read of traces | "How do they fail differently?" |

The delta between Product and Harness tells you how much of any gap is the model vs. the surrounding system.

### Invocation contract

For every `(task, tool, seed)`:

- Fresh git worktree at the task's pre-fix SHA
- Identical prompt (issue body + fixed suffix)
- Identical wall-clock budget and turn cap
- Headless mode, all tools allowed, no human input
- Capture: final diff, full trace, wall-clock, turn count, tool version

### Grading

- **Primary**: does the original PR's test suite pass on the agent's diff?
- **Secondary**: files-touched precision/recall vs. the human PR; diff size vs. human PR.
- **Tertiary** (sampled): LLM-as-judge on idiom fit and trajectory quality.

## Task sources

Pluggable behind a `TaskProvider` interface.

- **SWE-bench Verified** — starting point. Public, contamination-tolerant, ready-made test harnesses.
- **Own repo's closed PRs** — planned. Picks a closed PR, checks out its pre-fix SHA, replays the issue as the prompt, runs the PR's test changes as the grader.
- **Synthetic tasks** — planned. Hand-authored with known-good outcomes for controlled difficulty stratification.

Switching sources is a config change, not a code change.

## Status

Pragmatic-start phase. The repo currently contains the project brief (`prompts/`), the agent-memory files (`CLAUDE.md`, `AGENTS.md`), a step-by-step implementation plan (`docs-generated-by-claude/`), and a cross-platform prerequisite checker (`scripts/check_prereqs.{sh,ps1}`). The orchestrator, providers, and graders are being built incrementally per the plan — code lands as it's needed, not before.

## Supported platforms

Linux, macOS, and Windows. On Windows, the harness runs under Git Bash (bundled with Git for Windows) or WSL2 — both provide the POSIX-compatible bash that runner scripts need. Native-Windows PowerShell users can run the entry-point prerequisite checker (`check_prereqs.ps1`) but will need Git Bash or WSL for everything past that.

## Quickstart

```bash
# 1. Verify your machine has the tools the harness needs.
./scripts/check_prereqs.sh        # Linux, macOS, Git Bash, WSL
./scripts/check_prereqs.ps1       # native Windows PowerShell (or pwsh anywhere)

# 2. Verify the headless wrappers work end-to-end (real API calls; cents per run).
./scripts/verify_wrappers.sh                    # both tools
./scripts/verify_wrappers.sh --tool claude      # one at a time if you prefer
```

The prereq checker validates `git`, `uv`, `claude`, and `copilot` are on `PATH` and that each binary actually behaves like the tool it claims to be (it specifically detects the VS Code Copilot Chat stub that can shadow the real Copilot CLI). It does **not** verify CLI authentication — log into `claude` and `copilot` interactively at least once before running the harness.

`verify_wrappers.sh` then exercises `scripts/run_claude.sh` and `scripts/run_copilot.sh` against a throwaway git workdir with a trivial prompt ("create a file named HELLO.txt"). It exists for two reasons:

1. **Show, don't tell.** After it runs, `runs/wrapper-verify/` (gitignored) contains every artifact a real run produces — `stdout.log`, `stderr.log`, `exit_code`, `wall_clock_seconds`, `tool_info.json`, plus the diff the agent applied to the workdir. Browse it to understand the on-disk contract the rest of the harness consumes.
2. **Auth + flag-surface canary.** Both CLIs receive frequent updates, and `--help` flag inventories drift. Re-run this whenever a tool updates to catch breakage before it shows up in a real task run.

Costs real money (Claude) and seat usage (Copilot) — a few cents end-to-end. Skip it if you'd rather find out about a broken wrapper inside a real run.

Subsequent commands (running tasks, generating reports) will be added as the harness is implemented per `docs-generated-by-claude/02-implementation-plan-step-by-step.md`.

## Stack

- Python 3.11+ for orchestration, parsing, grading
- Bash for CLI invocation wrappers
- No promptfoo, no Docker, no Node — deliberately minimal until the small version proves the methodology works

## Caveats worth knowing up front

- **Cost tracking is directional, not exact.** Both CLIs roll into subscription/seat pricing rather than per-call API billing. Numbers come from each platform's usage dashboard.
- **Headless flags are moving targets.** Copilot CLI recently swapped `--headless --stdio` for `--acp --stdio`; Claude Code's `--output-format` is more stable but still evolving. Tool versions are pinned and recorded in every run manifest.
- **MCP parity matters.** If one tool has MCP servers the other doesn't, you're comparing surface area, not core capability. Default: no MCP on either side; opt in symmetrically when needed.
- **Agent runs are noisy.** Plan to run each task with multiple seeds per tool once we move past the pragmatic-start phase. One-shot results are misleading.

## Layout (target — built incrementally)

```
harness/                    Python: providers, runner, graders, reporters
scripts/                    Bash entrypoints invoking claude / copilot headlessly
                            (plus PowerShell mirrors for user-facing entry points only)
tasks/                      Task manifests + cached SWE-bench Verified slice
runs/                       Per-run outputs (gitignored)
reports/                    Generated comparison reports
prompts/                    Author-facing prompts driving this project's development
docs-generated-by-claude/   Documents Claude generates in response to prompts
                            (plan, design notes, explanations — see CLAUDE.md for the NN- prefix convention)
```

## License

TBD.
