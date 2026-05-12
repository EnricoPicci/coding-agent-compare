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

Pragmatic-start phase. The repo currently contains only the project brief (`prompts/`) and these two memory files. The orchestrator, providers, and graders are being built incrementally — code lands as it's needed, not before.

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
harness/    Python: providers, runner, graders, reporters
scripts/    Bash entrypoints invoking claude / copilot headlessly
tasks/      Task manifests + cached SWE-bench Verified slice
runs/       Per-run outputs (gitignored)
reports/    Generated comparison reports
prompts/    Author-facing prompts driving this project's development
```

## License

TBD.
