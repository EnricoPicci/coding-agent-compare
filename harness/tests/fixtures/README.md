# Test fixtures

Real captured traces from the harness's tool wrappers, used by `test_parsers.py`
to keep parser regression coverage independent of any live agent run.

## Files

- `claude_stream_json_sample.jsonl` — 6-event stream-json trace from a real
  `harness run --tool claude` against `psf__requests-1142` (Step 6 verify).
- `copilot_jsonl_sample.jsonl` — 297-event JSONL trace from a real
  `harness run --tool copilot` against the same task. Includes the chatty
  Copilot streaming intermediates (`assistant.message_delta`,
  `assistant.turn_start/end`, `session.*`) that the parser deliberately drops.

## When to refresh

Refresh these fixtures **only** when you intentionally bump the wrapper's
target tool to a new major version whose output format has changed. Steps:

1. Run `harness run --run-id parse-fixture-refresh --tool <claude|copilot> --task <smoke task>`
   against the new tool version.
2. Copy the resulting `stdout.log` over the corresponding fixture file.
3. Verify the parser still produces sensible output:
   `uv run pytest harness/tests/test_parsers.py -v`
4. Commit the new fixture and the tool-version bump in the same commit so the
   linkage is obvious in `git log`.

Otherwise leave them alone. The point is to detect parser regressions —
which only works if the input is frozen.
