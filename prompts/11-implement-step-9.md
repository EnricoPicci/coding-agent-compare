# Prompt
Implement Step 9

# Claude Response

Implements Step 9 of [`docs-generated-by-claude/02-implementation-plan-step-by-step.md`](../docs-generated-by-claude/02-implementation-plan-step-by-step.md) — *Primary grader: host-venv test runner*. Flagged as the riskiest step in the plan; full verify-clause satisfaction on all 3 (re-curated) smoke tasks.

## Verifications

```
$ uv run pytest harness/ -q -m "not integration"
  → 91 passed in 12.37s ✓
$ uv run pytest harness/tests/test_graders_swebench_host.py -q -m integration
  → 2 passed in 8.27s ✓
$ uv run ruff check . && uv run ruff format --check .  → clean ✓

# Gold-patch grading on all 3 smoke tasks (real venv + pip install + pytest) - (see below for a detailed explanation of what this test proves):
  pallets__flask-5014:        pass=True  | 60 passed | 0 failed | 0 unresolved
  pytest-dev__pytest-10051:   pass=True  | 16 passed | 0 failed | 0 unresolved
  psf__requests-5414:         pass=True  | 125 passed | 0 failed | 6 unresolved
    (2 data-corrupted target names; 4 env-dependent tests skipped per spec)
```

The empty-diff verification (via the integration test on pytest-10051) yields `pass=False` with the F2P test correctly identified as failing. Verify clause satisfied (see below for an explanation of this verification).

### What "Gold-patch grading on all 3 smoke tasks (real venv + pip install + pytest)" proves

  "Gold-patch grading on all 3 smoke tasks" — for each smoke task, I took the human's fix to the bug (task.metadata["patch"],
  called the "gold patch" because it's the canonical correct answer) and fed it to the grader as if it were the agent's diff.patch.
   This is the experimental control: if the grader can't recognize the human's known-good fix as passing, then it can't be trusted
  to judge an agent's fix either.

  "(real venv + pip install + pytest)" — not mocked anywhere in this run. For each of the three smoke tasks, the grader:
  1. Created a fresh uv venv at Python 3.11 in a tmp dir.
  2. Did real pip install calls — installed flask + werkzeug<3, installed pytest itself in editable mode, installed requests with
  -e . plus pytest. Each of these is a real network + dependency-resolution round-trip.
  3. Ran real pytest against the worktree.
  
  The whole loop is the slow, expensive, dep-isolation-prone path the plan flagged as the riskiest step.

  The columns:

  - pass=True/False — the primary metric. True iff every test the grader could run reported PASSED. False iff any reported FAILED
  or ERROR. null would mean the grader couldn't reach a verdict (e.g., install crashed).
  - passed — count of tests the grader ran AND pytest reported PASSED for.
  - failed — count where pytest reported FAILED or ERROR.
  - unresolved — count where the grader couldn't get a verdict for that specific test name. Splits into two reasons (both shown for
   the requests row).

  Why the requests row has 6 unresolved (and pass is still True):

  - 2 data-corrupted target names (see below for a detailed explanation of why these tests are considered unresolved): SWE-bench Verified's PASS_TO_PASS field for this task contains entries like
  test_basic_auth_str_is_always_native[test-test-Basic — that [ has no matching ] because the serializer split on whitespace and
  lost the closing fragment. The grader's _looks_runnable filter catches these and routes them to unresolved rather than handing
  them to pytest (which would abort the entire batch with rc=4 over even one bad name).
  - 4 env-dependent tests skipped per spec: requests's TestTimeout::test_connect_timeout[...] and test_total_timeout_connect[...]
  connect to a TARPIT host and expect the connection to time out slowly. On a network that refuses fast, the timeout never fires
  and the test wrongly fails — a property of the host's network, not the code. The grader's spec YAML marks them with skip_tests so
   they're routed to unresolved with a clear note rather than treated as real failures.

  The pass=True next to those 6 unresolved is the important detail: pass only counts tests we could actually grade. If the grader
  couldn't reach a verdict on a test, the test doesn't count for or against the pass status — it's reported in unresolved with a
  reason, and a human can decide whether that's acceptable. The alternative (treating unresolved as failure) would have made
  requests grade as pass=False for environmental reasons that have nothing to do with the agent's code.

  The deeper meaning — this is the verify clause of the plan: "Running the grader against the gold patch for a smoke task yields
  pass: true." For all 3 smoke tasks, the grader correctly recognizes a known-correct fix. When Step 11's driver later runs real
  agents and Step 12 builds the comparison report, any pass=False result will be a real signal about the agent's code, not noise
  from the grader.

#### Explanation of the "2 data-corrupted target names"
In short: it is a problem of the data taken from SWE-bench_Verified curated task list.

⏺ The two corrupted entries are in PASS_TO_PASS for psf__requests-5414. Let me show what's actually there and walk through what
  went wrong.

  What the dataset contains for these tests (verbatim from SWE-bench_Verified):

  index 59 in P2P list:
    "tests/test_requests.py::TestRequests::test_basic_auth_str_is_always_native[test-test-Basic"

  index 60 in P2P list:
    "tests/test_requests.py::TestRequests::test_basic_auth_str_is_always_native[\xd0\xb8\xd0\xbc\xd1\x8f-\xd0\xbf\xd0\xb0\xd1\x80\x
  d0\xbe\xd0\xbb\xd1\x8c-Basic"

  index 61 in P2P list:
    "tests/test_requests.py::TestRequests::test_proxy_auth"   ← unrelated next test

  What the strings SHOULD have been (what pytest actually has when you --collect-only the file):

  "...test_basic_auth_str_is_always_native[test-test-Basic dGVzdDp0ZXN0]"
  "...test_basic_auth_str_is_always_native[\xd0\xb8\xd0\xbc\xd1\x8f-\xd0\xbf\xd0\xb0\xd1\x80\xd0\xbe\xd0\xbb\xd1\x8c-Basic
  0LjQvNGPOtC/0LDRgNC+0LvRjA==]"

  What went wrong (in the dataset's lineage, not our code):

  This is a parametrized pytest test. The fixture in requests' test file looks roughly like:

  @pytest.mark.parametrize(
      'username, password, auth_string',
      [
          ('test', 'test', 'Basic dGVzdDp0ZXN0'),
          ('имя', 'пароль', 'Basic 0LjQvNGPOtC/0LDRgNC+0LvRjA=='),
      ],
  )
  def test_basic_auth_str_is_always_native(self, username, password, auth_string):
      ...

  Pytest names the parametrized cases by joining the parameter values with -, giving e.g.
  test_basic_auth_str_is_always_native[test-test-Basic dGVzdDp0ZXN0] — note the literal space between Basic and the base64 token,
  because the parameter value "Basic dGVzdDp0ZXN0" itself contains a space.

  Somewhere in the SWE-bench Verified curation pipeline that built FAIL_TO_PASS / PASS_TO_PASS, a step tokenized test names on 
  whitespace before JSON-serializing them. The original full name got split into two strings:

  "...test_basic_auth_str_is_always_native[test-test-Basic"   ← first half (no closing ])
  "dGVzdDp0ZXN0]"                                              ← second half (orphaned)

  For some tasks (we saw this earlier in this very session for the simpler split cases), the orphaned b] and dGVzdDp0ZXN0]
  fragments DO remain in the serialized list as their own entries. For those cases, _stitch_parametrized in
  harness/providers/swebench.py reassembles them by detecting an unbalanced [ count and consuming the following item.

  But for these two specific entries, the second half is completely missing from the JSON list. There's nothing in the dataset to
  recover from. After index 59's broken-bracket name, index 60 is another full test name (also broken in the same way), and index
  61 is a different test entirely. We have no record of what came after Basic — neither the dGVzdDp0ZXN0] nor the 0LjQvNGPOtC/...]
  is anywhere in the file. They were dropped at curation.

  Why my code marks them as unresolved rather than failed:

  The grader's _looks_runnable(name) check requires both :: (so it's a test name) and balanced brackets (so it's a complete test
  name):

  def _looks_runnable(name: str) -> bool:
      return "::" in name and name.count("[") == name.count("]")

  These two entries fail the bracket check. There are exactly three options for what to do with them:

  1. Pass them to pytest anyway. Pytest sees tests/.../test_basic_auth_str_is_always_native[test-test-Basic with no closing ],
  can't find a matching test in its collection (the real test has the full parameter), reports ERROR: not found, and — critically —
   exits the whole batch with rc=4 having run zero tests. One broken target name in the list of 131 would invalidate the run for
  the other 129 tests too. Wrong.
  2. Count them as failed. But we never actually ran them. We never even attempted them. Calling them "failed" would conflate "the
  code is broken" with "the dataset entry was unrecoverable" — exactly the kind of category error that erodes trust in the
  comparison.
  3. Mark them as unresolved with a grader_notes field explaining "2 data-corrupted target name(s) dropped before pytest." This is
  what we do. The grader honestly admits it could not reach a verdict on those specific test names, and a human reading the result
  can see why.

  The same rationale (don't conflate "we couldn't grade it" with "the code failed") is why pass=True even with these 6 unresolved
  entries. The 125 tests we could run all passed. Six were genuinely ungradeable for reasons that have nothing to do with the
  agent's (or human's) code. Reporting that honestly is more useful than picking a binary verdict at the cost of accuracy.

### Explanation of "empty-diff verification"
  The plan's verify clause has two halves — it's quoted at the top of Step 9 in the plan doc:

  ▎ "Running the grader against the gold patch for a smoke task yields pass: true. Running it against an empty diff yields pass: 
  ▎ false."

  The gold-patch half is what the table above the line demonstrates. The empty-diff half is what this line is about — and together
  they're the experimental control needed to trust the grader.

  Why both halves matter — a grader that only returns pass=true on a known-good fix isn't enough. You also have to prove it returns
   pass=false on a known-bad input. Without that, the grader could be returning true for the wrong reasons (e.g., running zero
  tests, treating skips as passes, misparsing the output) — and your verification would never catch it. The empty-diff check is the
   "negative control": when the agent did literally nothing, the grader must say pass=false.

  What "empty diff" simulates — diff.patch exists but is zero bytes. This is the on-disk state of a run where the agent invoked
  tools, generated traces, and exited cleanly but didn't actually modify any file. (It's also what the runner produces if the agent
   crashed before writing or hit the wall-clock before its first edit.)

  Why pytest-10051 specifically — it's the lightest of the three smoke tasks (1 F2P + 15 P2P = 16 tests total). The integration
  test runs in ~5 seconds with the bare clone already cached. Picking the heaviest task would slow the test suite without adding
  signal.

  What the grader does for this case — same pipeline as gold-patch, but the agent's diff contributes nothing:

  1. Prepare a fresh worktree at task.base_sha.
  2. Try to apply diff.patch. It's empty after .strip(), so we skip that step entirely — worktree stays at base.
  3. Apply the task's test_patch (which adds the bug-reproducing test test_clear_for_call_stage).
  4. Create the venv, install pytest in editable mode.
  5. Run pytest against all 16 F2P + P2P tests.
  6. Parse the output.

  Because the worktree is at the unfixed base SHA + the new failing test, the FAIL_TO_PASS test (test_clear_for_call_stage) reports
   FAILED. The 15 PASS_TO_PASS tests still report PASSED (they're regression coverage — they pass whether or not the bug is fixed,
  that's why they're in P2P). The grader cross-references and produces pass=False.

  "F2P test correctly identified as failing" — F2P stands for FAIL_TO_PASS, the list of test names that the human's bug fix is
  supposed to make pass. For pytest-10051 that list has exactly one entry:

  tests/testing/logging/test_fixture.py::test_clear_for_call_stage

  This is the new test the human added in the original PR to reproduce the bug — the test that fails against the unfixed code and
  passes once the fix is applied. The empty-diff run leaves the code unfixed, so this test must fail.

  The integration test (test_empty_diff_grades_pass_false_on_smoke_task in harness/tests/test_graders_swebench_host.py) asserts
  exactly two things to confirm this:

```
  assert result["pass"] is False  # primary metric is False
  assert any(t in result["tests_failed"] for t in task.fail_to_pass)
  # i.e., the failure is specifically the F2P test, not some other test
```

  That second assertion is the load-bearing one. pass=False alone could come from any random test failing — e.g., a flaky test in
  P2P, a broken install, a timeout. But if the exact test the bug should fix shows up in tests_failed, we know the grader is
  correctly attributing the failure to the right reason. That's what closes the loop: the grader recognizes a known-good fix as
  pass=true and attributes a missing fix to the right pass=false.

  "Verify clause satisfied" — together with the gold-patch table above the line, both halves of the plan's verify clause now have
  empirical evidence on this machine. The grader passes when it should pass, fails when it should fail, and the failure is for the
  right reason. Step 9 — the riskiest step in the plan — is genuinely done, not just compiled-and-tested.

## Smoke task list re-curation (prerequisite)

Before writing the grader, the Step 3 smoke set was swapped for safer
candidates. The original `sympy / pylint / requests-1142` set was chosen
without yet thinking about how grading would actually work — the packages "sympy" and
"pylint" are heavy / native-dep prone, the package "requests-1142" is from 2013 with EOL-era old style
packaging. Therefore these packages pose risks to raise issues during the installation on a modern host machine that has to run the smoke tests against them.

Therefore it has been decided to select a new set of packages to run the smoke tests against. 
The new set is made of all post-2020 pure-Python packages with modern packaging:

  - `pallets__flask-5014` (2023-03, 60 tests, "Require non-empty Blueprint name")
  - `pytest-dev__pytest-10051` (2022-06, 16 tests, "caplog.get_records/clear conflict")
  - `psf__requests-5414` (2020-04, 131 tests, "Getting http://.example.com raises UnicodeError")

## Files created

- `tasks/swebench_smoke_grade.yaml` — per-task install + test specs.
  Schema: `python_version`, `host_runnable`, `install_cmds[]`,
  `pytest_extra_args[]`, `skip_tests[]`. Three entries for the smoke set.
- `harness/graders/swebench_host.py` — the grader. ~300 lines covering:
  prepare a fresh grade-worktree, apply agent's `diff.patch` + the task's
  `test_patch`, create a `uv venv`, run the YAML-specified install commands,
  run pytest with FAIL_TO_PASS + PASS_TO_PASS as targets, parse line-by-line
  for PASSED/FAILED/ERROR, cross-reference against the F2P/P2P lists.
  Fail-soft: every step returns `pass=null` with a `grader_notes` string
  rather than raising.
- `harness/tests/test_graders_swebench_host.py` — 14 unit tests
  (pytest-output parsing, spec loading, ungradeable paths, smoke YAML
  sync) + 2 integration tests (real install + pytest for gold patch and
  empty diff against pytest-10051).

## Files modified

- `harness/graders/__init__.py` — adds `swebench_host` to the lazy-import
  registry.
- `harness/providers/swebench.py` — `_parse_test_list` now calls
  `_stitch_parametrized` to re-join SWE-bench Verified parametrized test
  names that were split on whitespace during serialization.
- `tasks/swebench_smoke.yaml` — replaced with the new smoke set.
- `harness/tests/test_worktree.py` — comment updated; the test logic
  still picks "the requests task" so the new requests-5414 is exercised
  automatically.
- `harness/tests/test_parsers.py` — the live-trace smoke test now
  globs `step6-verify/<tool>/*/seed-0/stdout.log` instead of hardcoding
  the old `psf__requests-1142` task ID.

## Real-world wrinkles discovered (and handled)

1. **flask 5014 + werkzeug 3.** Werkzeug 3.0 (Sept 2023) removed
   `werkzeug.__version__`, which flask's `testing.__init__` reads. Plain
   `pip install -e .` resolves the latest werkzeug and breaks every test.
   The install command pins `werkzeug<3`.
2. **requests + --doctest-modules.** requests's own `pytest.ini` sets
   `addopts = --doctest-modules`, which turns every Python file into a
   DoctestModule and refuses targeted F2P/P2P selection. Fixed via per-task
   `pytest_extra_args: ["--override-ini=addopts="]` in the spec.
3. **pytest needs `-p pytester` in its addopts.** Initial attempt blanket-
   applied `--override-ini=addopts=` to all tasks; this broke the pytest
   task because the project's own addopts (`-rfEX -p pytester
   --strict-markers`) are legitimate. Made it per-task.
4. **TARPIT timeouts in requests.** 4 of requests-5414's PASS_TO_PASS tests
   connect to a TARPIT host and expect a slow timeout; on networks that
   refuse the connection fast, they wrongly fail. Per-task `skip_tests`
   in the spec marks them environment-dependent and routes them to
   `unresolved`.
5. **SWE-bench Verified parametrized-name splits.** F2P/P2P sometimes
   serialize `test_X[a b]` as two separate strings `"test_X[a"` and
   `"b]"`. Fixed at the provider via `_stitch_parametrized` (uses
   unbalanced-bracket detection, refuses to merge across two items that
   both contain `::` since those are distinct tests).
6. **Pytest aborts on any unknown target.** If even one F2P/P2P name isn't
   collected, pytest exits rc=4 and "no tests ran" — a single broken name
   kills the whole batch. `_looks_runnable` pre-filters target names; bad
   ones go straight to `unresolved`.
7. **`text_patch.strip()` reassignment bug.** First grader version called
   `test_patch = (... or "").strip()` and passed the stripped value to
   `git apply` — stripping the trailing newline made `git apply` report
   "corrupt patch at line 28". Fixed by separating the strip-check from
   the value passed to git.

## Plan deviations recorded

Detailed in the
[plan's Step 9 change-log](../docs-generated-by-claude/02-implementation-plan-step-by-step.md#changes-introduced-during-implementation-of-step-9). Summary:

- Smoke task list re-curated (prerequisite change, documented in its own
  plan section).
- Two new per-task spec fields (`pytest_extra_args`, `skip_tests`) on top
  of the plan's `python_version`/`host_runnable`/`install_cmds`.
- Provider-level patch for SWE-bench parametrized-name corruption.
- Grader pre-filters target names to avoid pytest's all-or-nothing rc=4.
- Fail-soft policy applied to every grader step.

## Design decisions worth flagging

- **Each grader step is fail-soft.** A failure at any phase (apply patch,
  install, pytest, parse) returns `pass=null` with a `grader_notes` string
  rather than raising. The run is still considered complete. This is what
  keeps an expensive agent run useful even when grading hits an
  environmental snag.
- **The grade worktree is separate from the agent's run worktree.** The
  grader prepares its own worktree under `<run_dir>/grade-work/` so
  applying patches doesn't mutate the agent's `repo/`. The grade worktree
  is cleaned up after the grader returns; the venv at
  `<run_dir>/grade-venv/` is *kept* because it's the slow-to-recreate part
  and useful for re-grading or debugging.
- **Pytest output is parsed by regex, not by JSON plugin.** A simple
  line-based regex over `PASSED/FAILED/ERROR/SKIPPED/XFAIL/XPASS` markers
  works across pytest versions and avoids adding the pytest-json-report
  dep. `_name_match` tolerates path prefix variations (e.g., `src/` in
  some projects).
- **`uv` is used for venv creation + install.** `uv venv --python 3.11`
  fetches the interpreter if absent and the install resolves much faster
  than plain pip. Same `uv` we use for the harness itself.

## Side effects on this machine

- New caches:
  - `~/.cache/coding-agent-compare/repos/pallets__flask.git` (~30 MB)
  - `~/.cache/coding-agent-compare/repos/pytest-dev__pytest.git` (~10 MB)
  - `~/.cache/coding-agent-compare/repos/psf__requests.git` was reused
    from Step 4 (different SHA but same bare mirror).
- The existing step6-verify run dirs (`psf__requests-1142`) are stale
  relative to the new smoke set; safe to delete or ignore.
- `uv` will have fetched Python 3.11 if it wasn't already present
  (`uv venv --python 3.11`).

## Step 10 readiness

Step 10 (secondary graders: files-touched precision/recall, diff size)
depends on Step 9 — done. The `Grade` schema already has the placeholder
fields (`files_touched_precision`, `files_touched_recall`,
`diff_size_lines`, `human_diff_size_lines`); Step 10's graders register
themselves with the same `register("scope", ...)` / `register("size", ...)`
pattern and return those fields.
