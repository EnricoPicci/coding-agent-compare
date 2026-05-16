# 02 — The grader role explained

The **grader** is the component that turns "the agent finished and produced a diff" into "did the agent actually succeed?" It is the scoring function of the experiment.

> **See also:**
> - [`11-host-grader-pipeline.md`](11-host-grader-pipeline.md) — implementation deep-dive into the Step 9 host-venv grader: the directory layout it produces on disk, the step-by-step pipeline inside `swebench_host.grade()`, and how the workspace (`grade-work/`) and toolchain (`grade-venv/`) are bridged via `pip install -e .`. Read that document when you need to understand *how* a real run grades, not just *what* a grader is for.
> - [`12-grade-json-schema.md`](12-grade-json-schema.md) — per-field reference for the `grade.json` artifact every grader contributes to. Use it when you're inspecting a real `grade.json` and need to know what a specific field means or when it's null.
> - [`13-product-vs-harness-modes.md`](13-product-vs-harness-modes.md) — explains the two run modes (Product vs Harness) the driver supports. Grading runs identically regardless of mode, but the *interpretation* of `pass` / `precision` / `recall` numbers depends on which mode produced them.

## What it does

After every run, the runner has captured an artifact: `diff.patch` — the agent's proposed code change. That artifact is just text. By itself it tells you nothing about whether the agent solved the task. The grader answers that question and writes the answer to `grade.json`.

## Why it's a separate component from the runner

Three reasons:

1. **Separation of concerns.** The runner is "execute the agent under controlled conditions." The grader is "judge the output." Different code, different failure modes, different upgrade paths.
2. **You can swap graders without re-running agents.** Agent runs are expensive (15-min wall-clock, paid API calls). Grading is cheap. If you decide later your scoring was wrong, you re-grade the saved diffs — you don't re-run the agents.
3. **Multiple graders, one run.** The plan layers them: a primary grader (pass/fail), secondary graders (scope, size), and eventually a tertiary one (LLM-as-judge). Each reads the same `diff.patch` and appends its judgment to `grade.json`.

## For SWE-bench specifically

A SWE-bench task ships with three things relevant to grading:

- A **test patch** — the new tests the human added in the original PR (i.e., the tests that reproduce the bug being fixed).
- **FAIL_TO_PASS** — names of tests that *should now pass* with a correct fix (typically the new tests).
- **PASS_TO_PASS** — names of tests that *must still pass* (regression check — the fix shouldn't break existing behavior).

A real grader does this:

1. Take the agent's `diff.patch`, apply it to the repo at the task's `base_sha`.
2. Apply the SWE-bench test patch on top (so the bug-reproducing tests now exist in the worktree).
3. Run the test command in an appropriate Python env.
4. Parse the test output. If every FAIL_TO_PASS test passes *and* every PASS_TO_PASS test still passes → `pass: true`. Otherwise `pass: false`, with a breakdown.

That's the **primary** metric — the headline pass/fail number.

## How the plan stages graders

| Step | Grader | What it answers |
|---|---|---|
| 8 | **Mock grader** | "Did the agent produce a non-empty diff?" Validates plumbing; no real judgment. |
| 9 | **[Host-venv grader](11-host-grader-pipeline.md)** (primary) | "Do FAIL_TO_PASS / PASS_TO_PASS tests behave correctly?" The real signal. |
| 10 | **Scope grader** (secondary) | "Did the agent touch roughly the same files the human did?" (precision/recall) |
| 10 | **Size grader** (secondary) | "How does the agent's diff size compare to the human's?" (over-editing detector) |

The mock grader exists so steps 1–8 of the plan can be wired end-to-end *before* you commit to the harder work of step 9. You see the full machinery run with stand-in scores, fix any plumbing issues, *then* invest in real test execution.

## Why step 9 is risky

Step 9 needs to actually execute the test suite at the right Python version with the right deps for a historical state of an external repo. That's the dependency-isolation problem — exactly why SWE-bench's official harness uses Docker. Our plan tries to dodge Docker by carefully picking smoke tasks that run cleanly in a `uv` venv on the host. If that breaks on a task we care about, the escape hatch is using SWE-bench's prebuilt Docker images for grading only (option B in the plan's open-questions section) — Docker scoped to the grader, not to the agent's runtime.

How Step 9 actually solves the dep-isolation problem on the host — workspace/toolchain separation, the editable-install bridge, the per-task install spec — is documented in detail in [`11-host-grader-pipeline.md`](11-host-grader-pipeline.md).

## One-line summary

The **runner** says "the agent did its work"; the **grader** says "and here's how well." They are intentionally decoupled so we can re-score saved runs without re-paying for them.
