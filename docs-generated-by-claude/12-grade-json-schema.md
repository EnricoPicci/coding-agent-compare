# 12 — `grade.json` schema reference

Generated from `prompts/12-implement-step-10.md`.

> **See also:**
> - [`02-grader-role-explained.md`](02-grader-role-explained.md) — the conceptual companion: what a grader is, why it's separate from the runner, how the plan stages graders.
> - [`11-host-grader-pipeline.md`](11-host-grader-pipeline.md) — implementation deep-dive into the primary host-venv grader (Step 9), which contributes most of the fields documented here.

Every completed run produces a `grade.json` file at `<run_dir>/grade.json` containing the merged output of every grader that ran. This document is the per-field reference: what each field means, when it's `null` vs a real value, and which grader populates it.

The authoritative type definition lives in [`harness/graders/base.py::Grade`](../harness/graders/base.py) as a Pydantic v2 model. This doc covers semantics the Pydantic `Field(description=...)` strings can't express in one line — chiefly: *when does a field end up null, and what does that null mean?*

## Schema version

The current schema is `"1.0"`. Future additive changes (new optional fields) bump the minor version. Breaking changes (renames, removals, semantic redefinitions) bump the major. The schema is **strict on read** (`extra="forbid"`): any rogue field or typo in a `grade.json` causes `read_manifest`-style loaders to raise rather than silently swallowing the data.

## Field summary

| Field | Type | Contributor | Null when |
|---|---|---|---|
| `schema_version` | `str` | (metadata) | Never null. |
| `graders` | `list[str]` | (orchestrator) | Never null; may be empty. |
| `produced_nonempty_diff` | `bool \| null` | `mock` | `mock` grader didn't run, or it raised. |
| `pass` | `bool \| null` | `swebench_host` | `swebench_host` didn't run, or it returned `pass=null` (ungradeable / install crash / parser error). |
| `tests_passed` | `list[str] \| null` | `swebench_host` | Same as `pass`. |
| `tests_failed` | `list[str] \| null` | `swebench_host` | Same as `pass`. |
| `unresolved` | `list[str] \| null` | `swebench_host` | Same as `pass`. |
| `grader_notes` | `str \| null` | any grader | No grader contributed a note. |
| `files_touched_precision` | `float \| null` | `scope` | Agent produced no diff; no denominator. |
| `files_touched_recall` | `float \| null` | `scope` | Task's gold patch is empty; no denominator. |
| `diff_size_lines` | `int \| null` | `size` | `size` grader didn't run, or it raised. |
| `human_diff_size_lines` | `int \| null` | `size` | Same as `diff_size_lines`. |

## Field-by-field reference

### `schema_version`

**Type**: `str`. **Always populated.**

The schema version this `grade.json` was written against. Currently `"1.0"`. A loader that doesn't recognize the major version should refuse rather than guess. Bump the value in `harness/graders/base.py::SCHEMA_VERSION` when making a breaking change.

```json
"schema_version": "1.0"
```

### `graders`

**Type**: `list[str]`. **Always populated; may be empty.**

The names of the graders that successfully contributed fields to this document, in the order they ran. Graders that raised during their run are *not* included here — their error goes to `grader_notes` instead. This list is the way to distinguish "this field is null because the grader didn't run" from "this field is null because the grader ran and got a null result."

```json
"graders": ["mock", "swebench_host", "scope", "size"]
```

If you see `"graders": ["mock"]` and `"pass": null`, the `swebench_host` grader was never invoked (likely `RunConfig.graders` excluded it). If you see `"graders": ["mock", "swebench_host", ...]` and `"pass": null`, the host grader ran but couldn't reach a verdict — check `grader_notes` for the reason.

### `produced_nonempty_diff`

**Type**: `bool | null`. **Populated by the `mock` grader.**

`true` iff `<run_dir>/diff.patch` exists and has non-zero size. `false` iff the file is missing or empty. The cheapest possible signal that the run's plumbing worked end-to-end (the agent produced a diff, the runner captured it). Documented in detail in [`02-grader-role-explained.md`](02-grader-role-explained.md#how-the-plan-stages-graders).

`null` only when the `mock` grader didn't run (excluded from `RunConfig.graders`) or it crashed for some reason.

```json
"produced_nonempty_diff": true
```

### `pass`

**Type**: `bool | null`. **Populated by the `swebench_host` grader.** The JSON key is the spelling `"pass"`; the Pydantic field is named `pass_` because `pass` is a Python keyword (aliased via `Field(alias="pass")`).

The primary metric of the comparison. `true` iff every test the grader could run reported `PASSED`. `false` iff any test the grader ran reported `FAILED` or `ERROR`. `null` iff the grader couldn't reach a verdict — see `grader_notes` for which phase failed.

`null` cases the host grader produces (covered in detail in [`11-host-grader-pipeline.md`](11-host-grader-pipeline.md)):

- No spec for the task in `tasks/swebench_smoke_grade.yaml`.
- Spec marks `host_runnable: false`.
- `test_patch` failed to apply (can't grade without the bug-reproducing tests).
- Venv creation failed.
- An install command failed.
- Pytest exceeded the 5-minute timeout.

```json
"pass": true
```

The asymmetry with `produced_nonempty_diff` is intentional: a run can produce a non-empty diff (`mock` → true) and still grade `pass: null` (host grader couldn't run) or `pass: false` (tests failed). The two-axis split is the signal.

### `tests_passed`

**Type**: `list[str] | null`. **Populated by the `swebench_host` grader.**

The fully-qualified pytest names (e.g. `tests/test_foo.py::test_bar`) that pytest reported as `PASSED`, drawn from the union of the task's `FAIL_TO_PASS` and `PASS_TO_PASS` lists.

`null` for the same reasons as `pass`. An empty list `[]` means the grader ran but no tests passed — distinct from `null`.

```json
"tests_passed": [
  "testing/logging/test_fixture.py::test_clear_for_call_stage",
  "testing/logging/test_fixture.py::test_change_level"
]
```

### `tests_failed`

**Type**: `list[str] | null`. **Populated by the `swebench_host` grader.**

Tests pytest reported as `FAILED` or `ERROR`. Same null semantics as `tests_passed`. A non-empty list here is the direct evidence behind a `pass: false` verdict.

```json
"tests_failed": [
  "testing/logging/test_fixture.py::test_clear_for_call_stage"
]
```

### `unresolved`

**Type**: `list[str] | null`. **Populated by the `swebench_host` grader.**

Tests the grader couldn't get a verdict for, distinct from "failed." Three subcategories all land here:

1. **Data-corrupted target names** — SWE-bench Verified P2P entries with unbalanced parameter brackets (e.g. `test_X[a-b-Basic` with no closing `]`). The grader's `_looks_runnable()` filter routes these here before pytest sees them, because pytest aborts the whole batch with `rc=4` on any unknown target.
2. **Spec-marked environment-dependent tests** (`skip_tests` in the spec YAML) — e.g. `psf__requests-5414`'s `TestTimeout::test_connect_timeout` cases that need slow-network behavior to a TARPIT host.
3. **Tests that pytest collected but didn't report a verdict for** — rare; usually a sign of test-isolation issues or a collection error mid-batch.

`grader_notes` will tell you which subcategory applies. An entry here is *not* counted as a failure: `pass=true` can coexist with a non-empty `unresolved` list.

```json
"unresolved": [
  "tests/test_requests.py::TestRequests::test_basic_auth_str_is_always_native[test-test-Basic",
  "tests/test_requests.py::TestTimeout::test_connect_timeout[timeout0]"
]
```

### `grader_notes`

**Type**: `str | null`. **Any grader may contribute.**

A free-form, human-readable note string. Multiple graders' notes are joined with `"; "`. Typical contents:

- `"ungradeable on host: no grade spec for <task_id>"`
- `"venv create failed: <truncated stderr>"`
- `"install failed [<cmd>]: <truncated stderr>"`
- `"2 data-corrupted target name(s) dropped before pytest"`
- `"4 env-dependent test(s) skipped per grade spec"`
- `"<grader_name>: <ExceptionType>: <msg>"` when a grader raised

`null` when no grader had anything to report. Whenever `pass: null` or `produced_nonempty_diff: null` appears in a `grade.json`, this field is the place to look for "why."

```json
"grader_notes": "2 data-corrupted target name(s) dropped before pytest; 4 env-dependent test(s) skipped per grade spec"
```

### `files_touched_precision`

**Type**: `float | null` in `[0.0, 1.0]`. **Populated by the `scope` grader.**

`|agent ∩ human| / |agent|` — of the files the agent touched, what fraction also appear in the human PR's gold patch. Higher = more on-target editing.

`null` iff the agent's `diff.patch` is missing or empty: no denominator. *Not* 0.0 in that case — 0.0 means "we measured and the answer was zero," not "we couldn't measure." Step 12's report should display this as "—" and exclude the run from precision averages. See the design rationale in this session's transcript (`prompts/12-implement-step-10.md`).

Rename handling: the grader unions both the `a/` (old) and `b/` (new) paths from each `diff --git` header, so a rename counts as touching both names. This deliberately gives a precision penalty for renames the human didn't do, while keeping full recall for renames of the right file.

```json
"files_touched_precision": 0.5
```

### `files_touched_recall`

**Type**: `float | null` in `[0.0, 1.0]`. **Populated by the `scope` grader.**

`|agent ∩ human| / |human|` — of the files the human PR touched, what fraction did the agent also touch. Higher = wider coverage of the relevant code.

`null` iff the task's gold patch is empty (a malformed task). When the agent produced *nothing* but the human's patch is non-empty, this is **0.0** (a real, defined answer: "covered 0% of what was needed") — distinct from `null`. The asymmetry with precision is mathematically honest: `0 / |human|` is defined when `|human| > 0`, but `|agent ∩ human| / 0` never is.

```json
"files_touched_recall": 1.0
```

### `diff_size_lines`

**Type**: `int | null`. **Populated by the `size` grader.**

Count of added + deleted lines in the agent's `diff.patch`. Lines starting with `+` or `-` count; `+++` / `---` file headers and `@@` hunk headers don't. `0` for an empty / missing `diff.patch`. `null` only when the `size` grader didn't run.

```json
"diff_size_lines": 3
```

### `human_diff_size_lines`

**Type**: `int | null`. **Populated by the `size` grader.**

Same count, but for the task's gold patch (`task.metadata["patch"]`). Useful for comparing scope: a much larger agent diff than human diff often signals over-editing; a much smaller one often signals an under-scoped fix.

Step 12's report will likely compute the ratio inline rather than storing it; the schema deliberately stores the two raw numbers so future analyses can derive whatever ratio metric they need.

```json
"human_diff_size_lines": 3
```

## Two-axis split for failure-mode triage

Once `harness run` is invoked against real agents, the combination of `produced_nonempty_diff` and `pass` lets a reader classify each run quickly:

| `produced_nonempty_diff` | `pass` | Interpretation |
|---|---|---|
| `true` | `true` | Agent produced a diff, tests pass. Success. |
| `true` | `false` | Agent produced a diff, tests fail. The diff was wrong. |
| `true` | `null` | Agent produced a diff; grader couldn't verdict it. Check `grader_notes`. |
| `false` | `false` | Agent did nothing; tests fail (the F2P test still reproduces the bug). Expected failure mode for crashed / timed-out agents. |
| `false` | `null` | Agent did nothing AND the grader couldn't verdict. Both signals null — investigate. |
| `null` | anything | `mock` grader didn't run. Almost always a configuration error. |

Step 13's failure-mode tooling will use this matrix to bucket runs for human review.

## How to add a new field

When a new grader contributes a field that needs a real, typed slot in `grade.json`:

1. Add the field to `harness/graders/base.py::Grade` (type, default, optional `description=`).
2. Add a `### \`<field_name>\`` section to this doc with type, contributor, null semantics, and a JSON example.
3. Run `uv run pytest harness/tests/test_grade_doc_in_sync.py` — that test asserts the doc's field-section headings match the Pydantic model's field set exactly. If they diverge, the test fails loudly so the drift is caught at PR time, not at read time.
4. Bump `SCHEMA_VERSION` in `harness/graders/base.py` if the change is breaking. Additive optional fields keep the same major; renames / removals / type changes bump major.

## Related documents

- [`02-grader-role-explained.md`](02-grader-role-explained.md) — design rationale: why graders are separate from the runner, why `grade.json` is one accreting document.
- [`11-host-grader-pipeline.md`](11-host-grader-pipeline.md) — implementation deep-dive into `swebench_host`, which contributes most of the fields here.
- [`02-implementation-plan-step-by-step.md`](02-implementation-plan-step-by-step.md) — the broader plan, including each step's deviation log (Steps 8 / 9 / 10 each contributed fields and their semantics).
