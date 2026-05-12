With this project I want to create a mechanism to compare Claude Code and GitHub Copilot in agent mode.

I ask Claude Chat for suggestions and I got the following answer:

<claude-chat-answer>
This comparison is more interesting than Opus-vs-Sonnet because you're now comparing whole agentic systems, not just models. The scaffolding (prompts, planning loop, tool design, file-edit strategy, MCP integration) matters as much as the model. Good news: both tools have headless modes, so the methodology still works — you just need to handle the new variables.
Key methodological choice up front
Decide what you're actually measuring. There are two valid framings, and you probably want both:

Harness comparison (same model). GitHub Copilot CLI lets you pick the underlying model with the --model option, including Claude variants. Force both tools to run on the same Claude model. This isolates the agent scaffolding — planning, prompts, tool loop — from model capability. Cleanest answer to "which tool is better engineered." GitHub
Product comparison (default config). Let each tool use its recommended defaults. This is the realistic "what should my team adopt" answer, but it confounds model and harness.

Run both. The delta between them tells you how much is harness vs. model.
The mechanics work out cleanly
Both tools support headless programmatic invocation:
bash# Claude Code
claude -p "Fix issue #1234 per the description below: ..." \
       --output-format json

# GitHub Copilot CLI
copilot -p "Fix issue #1234 per the description below: ..." \
        --allow-all-tools --model claude-sonnet-4-5
copilot --allow-all-tools -p "..." runs Copilot headlessly in a way that's directly analogous to claude -p. So you can drive both from a script the same way you'd drive mini-swe-agent in the SWE-bench setup. GitHub
Concrete plan

Set up isolation. Per-task Docker container or fresh git worktree. Critical — these agents modify state and you need a clean baseline per run.
Normalize project memory. Create identical content in CLAUDE.md (Claude Code) and AGENTS.md (Copilot CLI). Both tools read their respective file as project memory. Same conventions, same instructions, same MCP servers configured if you use any.
Pick 15–25 tasks stratified by difficulty, same as Phase 1 before. Start with SWE-bench Verified for contamination-tolerant smoke testing, then your own repo's closed PRs.
Define the invocation contract — identical for both:

Fresh checkout at pre-fix SHA
Same prompt (the GitHub issue body + "fix this; ensure tests pass")
Same wall-clock budget (e.g., 15 min) or turn cap
Headless mode, all tools allowed, no human input
Capture: final diff, full trace/log, wall-clock, turn count


Grade the diff the same way:

Run the original PR's test suite — pass/fail (your primary metric)
Files-touched precision/recall vs. the human PR (scope discipline)
Diff size vs. human PR (over-editing)
LLM-as-judge on a sample for idiom fit and trajectory quality


Orchestrate with promptfoo using a custom "exec" provider for each tool — promptfoo invokes the CLI, captures the output, runs your grader script, and gives you the side-by-side matrix.
Run each task ≥3 seeds per tool. Agent variance is large; one-shot is misleading.

What's harder than the model-vs-model case

Cost tracking is messier. API-level comparison gives you exact token costs; CLI tools roll into subscription/seat pricing. You'll get a directional number from each platform's usage dashboard, not per-task precision.
Trace formats differ. Claude Code emits JSON with --output-format json; Copilot has its own format. You'll write small parsers for each to normalize turn counts and tool-call sequences.
MCP parity matters. If one tool has access to MCP servers the other doesn't (or different versions), you're comparing surface area, not core capability. Either give both the same MCP set or disable MCP entirely for the comparison.
API surface is moving fast. Copilot CLI recently removed --headless --stdio in favor of --acp --stdio, breaking downstream SDK integrations — meaning headless invocation patterns are in flux. Pin tool versions during your eval and document them. GitHub

What you'll learn that matters
Three things, ordered by usefulness:

Default-config win rate — directly informs adoption.
Same-model win rate — tells you whether differences are durable (harness) or temporary (model choice).
Failure-mode differences — often more decisive than the score. One tool may over-edit aggressively while the other gives up on hard tasks. Pull 10 failures each and read the traces; this drives the qualitative recommendation.

One pragmatic note
Before building the full pipeline, run one task manually through each tool and read both traces end-to-end. You'll learn more in 30 minutes than the first 5 hours of harness work — and you'll catch normalization issues (e.g., one tool aggressively reads files the other doesn't, one auto-runs tests the other waits to be told) before they pollute the eval.
</claude-chat-answer>

Does this make sense to you?
If not ask me any question to clarify my intent.
If it makes sense but you have something not really clear, ask me any questions.
If it makes sense to you and you have everything clear write a CLAUDE.md file and a README.md file for such a project.