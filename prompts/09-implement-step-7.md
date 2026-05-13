# Prompt
Implement Step 7

# Claude Response

Implements Step 7 of [`docs-generated-by-claude/02-implementation-plan-step-by-step.md`](../docs-generated-by-claude/02-implementation-plan-step-by-step.md) — *Run manifest + trace normalization*.

## Verifications

```
$ uv run pytest harness/ -q -m "not integration"
  → 69 passed in 11.29s ✓
$ uv run ruff check . && uv run ruff format --check .  → clean ✓

# Live re-parse of the existing step6-verify traces (no API cost):
=== claude  (30 raw lines → 23 normalized events)
   by kind: {tool_call: 10, tool_result: 10, message: 3}
   turn_count: 3
=== copilot (297 raw lines → 66 normalized events)
   by kind: {message: 13, tool_call: 26, tool_result: 26, error: 1}
   turn_count: 12
```

The reduction ratios reflect how chatty each tool's raw trace is: claude
drops `system/init` + `rate_limit_event` (≈ 7 lines), copilot drops ~166
`*_delta` chunks, ~12 `turn_start/end` markers, ~3 `session.*` events,
~12 `reasoning` blocks (≈ 231 lines).

## Files created

- `harness/manifest.py` — Pydantic v2 models: `Manifest`, `ToolInfo`,
  `RetryInfo`, `HostInfo`, `WrapperInvocation`. `write_manifest` /
  `read_manifest` / `manifest_from_dict` helpers. Schema version is the
  string `"1.0"`.
- `harness/parsers/__init__.py` — `register(tool, fn)` + `get_parser(tool)`
  with lazy import per tool so the package boots cheap.
- `harness/parsers/base.py` — `NormalizedEvent` Pydantic model. Four kinds:
  `message`, `tool_call`, `tool_result`, `error`. Carries `seq`, optional
  `role`, `tool_name`, `text`, plus the original event's `raw_type` tag.
- `harness/parsers/claude.py` — translates `assistant`, `user`, and
  error-`result` events. Splits mixed `assistant` turns (text + tool_use)
  into separate normalized events.
- `harness/parsers/copilot.py` — translates `assistant.message`,
  `user.message`, `tool.execution_start/complete`, and `abort`. Drops
  every `*_delta`, `*_start`/`*_end`, `session.*`, and `reasoning` event.
  Text extraction is best-effort across three known content shapes
  (`text`, `content` as str, `content` as list of `{type, text}`).
- `harness/tests/test_manifest.py` — 8 tests: round-trip, default schema
  version, extra-field rejection, missing-field rejection, optional
  `tool_info`, permissive `ToolInfo`, default `retries`, default Step 7
  fields.
- `harness/tests/test_parsers.py` — 17 tests: per-parser coverage of each
  event kind + edge cases (mixed blocks, ignored infra events, malformed
  JSON, missing file), parser registry dispatch, plus a parametrized
  "real trace parses without error" test that skips when the
  step6-verify artifacts aren't present.
- 2 new tests in `harness/tests/test_runner.py` — integration via a
  stub wrapper that writes a claude-shaped stdout.log: confirms
  `events.jsonl` is emitted, `turn_count` is derived, and parser
  exceptions are captured as `manifest.parse_error` without failing
  the run.

## Files modified

- `harness/runner.py` — replaces the inline manifest dict with Pydantic
  model construction. Adds `_parse_trace_safe`, `_write_events_jsonl`,
  `_write_run_manifest` internals. Calls the parser after the wrapper
  returns, derives `turn_count`, embeds parser-derived counts in the
  manifest, captures parser exceptions as `parse_error`.
- `pyproject.toml` — adds `pydantic>=2` to runtime dependencies.

## Plan deviations / decisions locked in

The Pydantic question (the only real plan-vs-pragmatic-start tension)
was resolved in favor of the plan: Pydantic v2 is now a runtime dep.
Six implementation-time decisions are logged in
[the plan's Step 7 change-log](../docs-generated-by-claude/02-implementation-plan-step-by-step.md#changes-introduced-during-implementation-of-step-7):

1. Schema version is `"1.0"` (bumped from `"step6-stub"`).
2. "Preserve raw alongside" = stdout.log + `raw_type` tag, not duplicated
   payloads.
3. Parser tolerance is explicit and load-bearing — skip malformed
   lines; record parser exceptions in `manifest.parse_error` rather than
   failing the run.
4. `assistant.message_delta` is dropped (Copilot streaming chunks).
5. `turn_count` is defined as "count of normalized `message` events with
   `role=assistant`", not API round-trips or tool invocations.
6. `ToolInfo` is `extra="allow"`; every other model is `extra="forbid"`.

## Design decisions worth flagging

- **NormalizedEvent carries `raw_type`, not the full raw event.** stdout.log
  already preserves raw; duplicating it in events.jsonl would 3–5× the
  file size with no readable benefit. `seq` is the bridge if anyone wants
  to look up the full raw payload.
- **Parsers are registered, not switched on by `if/elif`.** `register()`
  in `harness/parsers/__init__.py` lets `claude.py` and `copilot.py`
  declare themselves at import time; `get_parser("claude")` lazily
  imports the module on first use. Cheaper boot, easier to add a third
  tool later.
- **Parser failures don't fail the run.** A run that produced a real
  diff and a stdout.log is data we want to keep. If the parser breaks
  on schema drift, the manifest records the error string and the run
  is otherwise complete — Step 12's report can flag runs with non-null
  `parse_error` for triage.
- **Mixed assistant blocks split into multiple normalized events.**
  Claude often emits `[{type:text}, {type:tool_use}]` in a single
  `assistant` event — we split that into one `message` + one `tool_call`
  in `events.jsonl` so downstream consumers can iterate without
  re-walking the structure.

## Side effects on this machine

- New runtime dependency `pydantic==2.13.4` (+ `pydantic-core`,
  `annotated-types`, `typing-inspection`).
- The existing step6-verify manifest files in `runs/` still have
  `schema_version: "step6-stub"`. They'll be rejected by the new
  `read_manifest()` because the schema is strict. Re-running them
  through `harness run` will regenerate manifests at schema 1.0; or
  delete the dirs and they'll be recreated on the next live run.

## Step 8 readiness

Step 8 (mock grader) depends on Step 6 — done. Step 7 unblocks Steps 11
(driver) and 12 (report), both of which read `manifest.json` and care
about `turn_count` / `event_count`. Step 13 (failure-mode tooling) reads
both manifests and `events.jsonl` directly.
