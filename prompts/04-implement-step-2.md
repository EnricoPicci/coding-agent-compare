# Prompt
Implement Step 2

# Claude response

Implements Step 2 of [`docs-generated-by-claude/02-implementation-plan-step-by-step.md`](../docs-generated-by-claude/02-implementation-plan-step-by-step.md) — *Task model & `TaskProvider` interface*.

## Verifications

```
$ uv run pytest harness/ -v     # → 5 passed in 0.01s ✓
$ uv run ruff check .           # → All checks passed ✓
$ uv run ruff format --check .  # → 8 files already formatted ✓
```

## Files created

- `harness/task.py` — frozen `Task` dataclass with `task_id`, `repo_url`, `base_sha`, `prompt`, `test_command`, `fail_to_pass`, `pass_to_pass`, `expected_changed_files`, `metadata`. `to_dict()` / `from_dict()` for round-tripping.
- `harness/providers/__init__.py` — re-exports `TaskProvider` so callers do `from harness.providers import TaskProvider`.
- `harness/providers/base.py` — `TaskProvider` as a `@runtime_checkable` `Protocol`; `load(task_ids: list[str] | None) -> list[Task]`.
- `harness/tests/__init__.py` — empty marker.
- `harness/tests/test_task.py` — round-trip test (full + minimal fields) plus a test that default-factory lists/dicts are independent per instance.
- `harness/tests/test_providers.py` — `isinstance` smoke tests for the Protocol (stub with `load` is accepted; class without is rejected).

## Files modified

- `pyproject.toml` — `pytest>=8` added to the dev dependency group.
- `.gitignore` — `.pytest_cache/` added (pytest created it on first run).

## Decisions worth flagging

- **Lists, not tuples**, for `fail_to_pass`, `pass_to_pass`, `expected_changed_files`. Round-trips cleanly through JSON without conversion. Side effect: `Task` is frozen but not hashable, so it can't live in a set. Won't need that for the harness.
- **`@runtime_checkable` on `TaskProvider`.** Lets `isinstance(x, TaskProvider)` actually do something — it checks for a `load` method. The structural check is shallow (doesn't verify signature), but catches "you forgot to implement the method" cases at runtime, not just at type-check time.
- **Tests live under `harness/tests/`**, matching the plan's literal `uv run pytest harness/` verification command. They'll ship in the wheel; a follow-up can exclude them via hatchling config if we ever publish.

## Step 2 → Step 3 readiness

Step 3 (`SWEBenchVerifiedProvider`) depends on Step 2 only. The `Task` model is the contract the SWE-bench provider needs to populate. Ready to proceed.
