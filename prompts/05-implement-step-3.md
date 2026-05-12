# Prompt
Implement Step 3

# Claude Response
Risky step — check-in first. Re-reading Step 3 surfaces four choices that should be locked in before I write code, plus one decision
that requires loading the actual dataset.
Choices to confirm
1. Dependency: swebench vs datasets only.
The plan literally says "add swebench + datasets". But the swebench PyPI package is heavy — it pulls in Docker SDKs and their evaluation
 harness — and the plan's architectural decisions explicitly say "we do not reuse their Docker eval runner." We only need task metadata
for Step 3. Recommend datasets + pyyaml only; defer swebench until/unless we need something it offers. This is a deviation from the
plan's literal dep list but consistent with its intent.
2. Filter file format: keep YAML.
The plan says tasks/swebench_smoke.yaml. Sticking with YAML means adding pyyaml. Alternative would be a plain .txt (one ID per line) —
fewer deps. Recommend YAML so we can later attach per-task notes (e.g., host_runnable: true|false flagged in Step 9).
3. Cache: rely on HuggingFace's built-in cache.
The plan says cache to ~/.cache/coding-agent-compare/swebench/. HuggingFace's datasets library already caches at
~/.cache/huggingface/datasets/, and re-mapping ~500 rows to Task objects is microseconds. Recommend skipping a custom cache layer;
revisit only if it ever becomes a perf issue. This is also a deviation from the plan's literal text.
4. CLI structure.
Step 3's verify command is python -m harness tasks list --provider swebench --filter tasks/swebench_smoke.yaml. This forces me to switch
 the CLI from "always print help" to a real subparser layout. I'll add a tasks list subcommand. Future subcommands (run, report, etc.)
plug in alongside.
One decision I can't lock in without the dataset
Smoke task IDs. The plan offers three candidates as tentative — sympy__sympy-20154, pylint-dev__pylint-7080, psf__requests-1142 — with
"final list confirmed at implementation time after spot-checking each." I have no way to verify those IDs are even in the Verified
subset (~500 curated instances) without loading the data. My plan: write the provider code, load the dataset locally, filter for
criteria (pytest-based, Python ≥3.9, smallish repo, no native deps), curate 3–5 IDs, write them to swebench_smoke.yaml, then run the
verify command. If the plan's candidates clear the criteria they go in; otherwise I pick replacements and note what changed.
Network requirement
First load downloads ~tens of MB from HuggingFace, no auth needed for the public Verified split. Subsequent loads hit the local HF
cache.
Effort estimate
The plan tagged this M (~½ day). I think that's right: code is small, but the curation + verification round will surface dataset quirks
worth handling cleanly.
OK to proceed with these four choices as stated, or want to override any? Specifically: pushing back on dropping the swebench package
dep, or on skipping the custom cache?

# Prompt
Ok to proceed

# Claude response

Implements Step 3 of [`docs-generated-by-claude/02-implementation-plan-step-by-step.md`](../docs-generated-by-claude/02-implementation-plan-step-by-step.md) — *`SWEBenchVerifiedProvider`*.

## Verifications

```
$ uv run python -m harness tasks list \
    --provider swebench --filter tasks/swebench_smoke.yaml
psf__requests-1142       psf/requests        22623bd8c265  requests.get is ALWAYS sending content length
pylint-dev__pylint-7080  pylint-dev/pylint   3c5eca2ded3d  `--recursive=y` ignores `ignore-paths`
sympy__sympy-20154       sympy/sympy         bdb49c4abfb3  partitions() reusing the output dictionaries

$ uv run pytest harness/ -q       # → 18 passed in 0.72s ✓
$ uv run ruff check .             # → All checks passed ✓
$ uv run ruff format --check .    # → 12 files already formatted ✓
```

## Files created

- `harness/providers/swebench.py` — `SWEBenchVerifiedProvider`, `row_to_task`, `_parse_test_list`, `load_task_ids_from_yaml`. Imports `datasets` lazily inside `load()` so tests that don't exercise the network path don't pay for the import.
- `harness/cli.py` — argparse layout with `tasks list --provider <name> [--filter <yaml>]`. Built to extend cleanly for `run`, `report`, etc. in later steps.
- `tasks/swebench_smoke.yaml` — three curated IDs with inline difficulty/version/title comments.
- `harness/tests/test_swebench.py` — 9 tests covering mapping, JSON-list parsing, filtering, missing-ID errors, YAML loading.
- `harness/tests/test_cli.py` — 4 tests covering parser construction, no-args help, required `--provider`, and end-to-end CLI dispatch with a stubbed provider.

## Files modified

- `harness/__main__.py` — slimmed to just call `harness.cli.main`.
- `pyproject.toml` — added `datasets>=3.0` and `pyyaml>=6.0` to runtime deps. `uv.lock` updated.

## Curation findings

- All three plan candidates exist in Verified (`sympy__sympy-20154`, `pylint-dev__pylint-7080`, `psf__requests-1142`).
- They span easy/medium difficulty, three different repos, and three different test patch sizes (17/31/44 test-patch lines).
- Verified contains 500 instances total; top repos by count are django (231), sympy (75), sphinx (44), matplotlib (34). The smoke list deliberately avoids django/sphinx for now — too many instances and heavier setup. Easy to widen later by appending to `swebench_smoke.yaml`.

## Decisions worth flagging

- **No `swebench` package dep** — only `datasets` + `pyyaml`. Plan deviation, approved before starting.
- **No custom cache file** — HuggingFace's `datasets` cache at `~/.cache/huggingface/` is the only cache layer. Re-mapping 500 rows is microseconds. Plan deviation, approved.
- **`test_command = "python -m pytest"` as placeholder** in every mapped Task. The real per-task command is derived from `FAIL_TO_PASS` / `PASS_TO_PASS` and that's the Step-9 grader's job, not the provider's.
- **HF unauthenticated rate-limit warning** appears on every dataset load. Harmless for our volume; we'd only set `HF_TOKEN` if we hit rate limits.

## Step 4 readiness

Step 4 (worktree manager) depends only on Step 2 (Task model) — independent of Step 3. Ready to proceed.
