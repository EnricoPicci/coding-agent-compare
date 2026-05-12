# coding-agent-compare

A small evaluation harness that compares **Claude Code** and **GitHub Copilot CLI** running in agent mode on the same software-engineering tasks.

This file is project memory for GitHub Copilot CLI. A mirror `CLAUDE.md` exists for Claude Code and **must be kept byte-equivalent in semantic content** — fairness of the comparison depends on it. When you edit one, edit the other.

## What this project is (and isn't)

- **Is**: the orchestrator, task definitions, graders, and reports for the comparison.
- **Is not**: the systems under test. Claude Code and Copilot CLI are external binaries invoked headlessly.

When working in this repo, you are building the harness. The agents being compared run inside isolated worktrees (`runs/<run-id>/<tool>/<task>/`), not in this directory.

## Methodology — three framings

We support all three; each is a separate run mode of the same harness.

1. **Product (default configs)** — each tool with its recommended defaults and default model. Answers "what should my team adopt?" Confounds model and harness.
2. **Harness (same model)** — both tools forced onto the same Claude model (via Copilot's `--model` flag). Isolates scaffolding differences.
3. **Failure-mode analysis** — qualitative read of traces from failed runs. Driven from the same outputs the quantitative runs produce; no separate execution path.

The delta between (1) and (2) tells us how much of any gap is harness vs. model.

## Conventions

- **Language**: Python 3.11+ for orchestration, parsing, grading; bash for CLI invocation wrappers. No Node/TypeScript, no promptfoo — keep dependencies minimal.
- **Isolation**: one fresh git worktree per `(task, tool, seed)`. No Docker for now. Worktrees go under `runs/`.
- **Pinned versions**: record the exact `claude --version` and `copilot --version` in every run manifest. Both CLIs' headless flags are in flux; reproducibility requires pins.
- **No global state**: every run writes to its own directory; nothing is appended to repo-tracked files at runtime.
- **Retries (`retries`, default `2`)**: configurable per run. Retries cover **transient infrastructure failures only** — process crash, network error, rate-limit, tool-CLI exit code indicating an internal error. A run whose agent produced a diff that failed the test suite is **not** retried; that is the signal we are measuring. Retry count and reason must be recorded in the run manifest so the data stays auditable.

## Task sources are pluggable

Tasks are loaded through a `TaskProvider` interface. The first implementation is `SWEBenchVerifiedProvider`; later we add `OwnRepoPRProvider` and `SyntheticTaskProvider`. A task exposes:

- `task_id`, `repo_url`, `base_sha` (pre-fix), `prompt`, `test_command`, `expected_changed_files` (optional, for precision/recall scoring).

Adding a new source means writing a new provider, **not** changing the orchestrator.

## Repository layout (target)

```
harness/                    Python package: providers, runner, graders, reporters
scripts/                    Bash entrypoints that invoke claude / copilot headlessly
tasks/                      Task manifests (yaml) + cached SWE-bench Verified slice
runs/                       Output: one dir per (run-id, tool, task, seed) — gitignored
reports/                    Generated comparison reports
prompts/                    Author-facing prompts driving this project's development
docs-generated-by-claude/   Documents authored by Claude in response to prompts
```

Don't create these eagerly — add a directory only when you have code that needs to live in it.

## Generated documents — NN- prefix convention

When a prompt file is named `prompts/NN-<slug>.md` (e.g., `prompts/02-plan-in-details.md`), any document generated as the direct result of that prompt **must** start with the same `NN-` prefix. So a plan produced from `02-plan-in-details.md` lives at `docs-generated-by-claude/02-<descriptive-name>.md`. The prefix links the artifact back to the prompt that produced it; without it, the lineage gets lost as the repo grows. This rule applies to every document type — plans, analyses, design notes, reports — placed under `docs-generated-by-claude/` or any sibling generated-doc folder.

## Invocation contract (must be identical across tools)

For each `(task, tool, seed)`:

1. Fresh worktree at the task's pre-fix SHA.
2. Same prompt: the issue body + a fixed suffix ("fix this; ensure tests pass").
3. Same wall-clock budget (default 15 min) and turn cap.
4. Headless mode, all tools allowed, no human input.
5. Capture: final `git diff`, full trace/log, wall-clock, turn count, tool version.

Any deviation breaks the comparison. If a tool needs a flag the other doesn't have, document the asymmetry in the run manifest.

## Graders

Primary metric is **test-pass on the original PR's test suite**. Secondary: files-touched precision/recall vs. the human PR, diff size vs. human PR. LLM-as-judge is a sampled tertiary signal, not a gate.

## What not to do

- Don't introduce promptfoo, Docker, or a web UI until the pragmatic-start phase produces signal.
- Don't normalize trace formats prematurely — keep raw tool output verbatim, write thin parsers per tool.
- Don't share state across the two tools' runs (no shared caches, no shared MCP servers unless explicitly listed in the run manifest).
- Don't auto-run anything destructive (`rm -rf runs/`, `git worktree remove --force`) without confirming with the user.

## When in doubt

The chat-conversation that motivated this project lives in `prompts/01-generate-claude-md.md`. Re-read it when a design choice is unclear; the rationale is there.
