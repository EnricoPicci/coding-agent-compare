#!/usr/bin/env python3
"""Grade smoke task gold patches without invoking any LLM.

Smoke check that exercises the grader pipeline end-to-end against known-good
inputs (the human's PR fix for each smoke task). Useful after any change to
the grader, the providers, or the per-task install specs.

For each task in tasks/swebench_smoke.yaml (or one task if --task is given):

  1. Stage `task.metadata["patch"]` (the human's gold patch) as `diff.patch`
     in `runs/<run-id>/<task_id>/`.
  2. Run the configured graders (default: mock + swebench_host) by calling
     them directly. Each grader contributes a partial dict; we merge them
     the same way the runner's `_run_graders` does.
  3. Write a schema-valid `grade.json` next to `diff.patch`.
  4. Print a per-task summary line + a final table.

Costs nothing per run (no LLM, no API budget). The first run downloads the
flask + pytest + requests bare mirrors and creates a uv venv per task
(~150 MB under runs/<run-id>/). Subsequent runs reuse both.

Usage:
  uv run python scripts/grade_smoke_tasks.py
  uv run python scripts/grade_smoke_tasks.py --task pytest-dev__pytest-10051
  uv run python scripts/grade_smoke_tasks.py --run-id my-test

Exit code: 0 if every task graded pass=True; 1 otherwise.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make `harness` importable when this script is run from anywhere.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from harness.graders import get_grader  # noqa: E402  (post-path-insert imports)
from harness.graders.base import Grade  # noqa: E402
from harness.providers.swebench import (  # noqa: E402
    SWEBenchVerifiedProvider,
    load_task_ids_from_yaml,
)

DEFAULT_GRADERS = ("mock", "swebench_host", "scope", "size")
DEFAULT_RUN_ID = "gold-smoke"
DEFAULT_RUNS_ROOT = REPO_ROOT / "runs"
SMOKE_YAML = REPO_ROOT / "tasks" / "swebench_smoke.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="grade_smoke_tasks.py",
        description="Grade smoke task gold patches without invoking any LLM.",
    )
    parser.add_argument(
        "--task",
        dest="task_id",
        help="Grade only this single task id; default grades the whole smoke set.",
    )
    parser.add_argument(
        "--run-id",
        default=DEFAULT_RUN_ID,
        help=f"Run-id under runs/ (default: {DEFAULT_RUN_ID})",
    )
    parser.add_argument(
        "--runs-root",
        default=str(DEFAULT_RUNS_ROOT),
        help=f"Output root (default: {DEFAULT_RUNS_ROOT})",
    )
    parser.add_argument(
        "--graders",
        default=",".join(DEFAULT_GRADERS),
        help=f"Comma-separated grader names (default: {','.join(DEFAULT_GRADERS)})",
    )
    args = parser.parse_args(argv)

    smoke_ids = load_task_ids_from_yaml(SMOKE_YAML)
    if args.task_id:
        if args.task_id not in smoke_ids:
            print(
                f"task {args.task_id!r} is not in {SMOKE_YAML.name}; available: {smoke_ids}",
                file=sys.stderr,
            )
            return 2
        smoke_ids = [args.task_id]

    run_root = Path(args.runs_root) / args.run_id
    grader_names = [g.strip() for g in args.graders.split(",") if g.strip()]
    print(f"Grading {len(smoke_ids)} task(s) into {run_root}/ with graders={grader_names}")

    tasks = SWEBenchVerifiedProvider().load(smoke_ids)
    results: list[tuple[str, Grade]] = []

    for task in tasks:
        run_dir = run_root / task.task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "diff.patch").write_text(task.metadata["patch"])

        print(f"\n=== {task.task_id} ===")
        print(f"  run-dir: {run_dir.relative_to(REPO_ROOT)}")

        merged: dict = {"graders": []}
        for name in grader_names:
            try:
                fields = get_grader(name)(run_dir, task)
                merged.update(fields)
                merged["graders"].append(name)
                print(f"  {name}: ok")
            except Exception as exc:  # noqa: BLE001 — grader surface is uncontrolled
                msg = f"{name}: {type(exc).__name__}: {exc}"
                print(f"  {msg}")
                prior = merged.get("grader_notes")
                merged["grader_notes"] = "; ".join([*([prior] if prior else []), msg])

        grade = Grade.model_validate(merged)
        (run_dir / "grade.json").write_text(grade.model_dump_json(indent=2, by_alias=True) + "\n")
        print(
            f"  → pass={grade.pass_}  passed={len(grade.tests_passed or [])}  "
            f"failed={len(grade.tests_failed or [])}  unres={len(grade.unresolved or [])}"
        )
        results.append((task.task_id, grade))

    # Final side-by-side summary.
    print("\n=== Summary ===")
    header = f"  {'task_id':<32}  {'pass':>5}  {'#pass':>5}  {'#fail':>5}  {'#unr':>4}  notes"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for task_id, grade in results:
        notes = grade.grader_notes or "—"
        if len(notes) > 50:
            notes = notes[:47] + "..."
        print(
            f"  {task_id:<32}  {str(grade.pass_):>5}  "
            f"{len(grade.tests_passed or []):>5}  "
            f"{len(grade.tests_failed or []):>5}  "
            f"{len(grade.unresolved or []):>4}  {notes}"
        )
    print(f"\nArtifacts: {run_root}/<task>/{{diff.patch, grade.json, grade-venv/}}")

    overall_pass = all(g.pass_ is True for _, g in results)
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
