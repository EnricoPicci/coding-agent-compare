"""Multi-mode driver — runs the matrix of (task × tool × seed) end-to-end.

Step 11 of the plan. Sits on top of `harness.runner.run_once` and adds:

  - Framing logic: in `product` mode each tool gets its default model;
    in `harness` mode both tools run with a shared `--model <name>` so
    scaffolding differences are isolated from the model variable.
  - Retry orchestration: a single (task, tool, seed) is retried up to N
    times on transient failures (non-zero exit that isn't a wall-clock
    timeout and isn't a runner crash with no result). Per CLAUDE.md,
    timeouts and "tests failed" are data, not transients — never retried.
    Retry count + reasons are written back into the cell's manifest.
  - Shared `run_id`: every cell of one matrix invocation lands under the
    same `runs/<run-id>/<tool>/<task>/seed-<N>/` tree, so Step 12's
    report can read one directory tree per matrix.

The driver is intentionally sequential. Parallelism is a later concern;
the smoke phase is small enough (a few tasks × two tools × one seed) that
sequential is fine and the failure modes are easier to reason about.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from harness.manifest import RetryInfo, read_manifest, write_manifest
from harness.runner import (
    DEFAULT_BUDGET_SECONDS,
    SUPPORTED_TOOLS,
    RunConfig,
    RunResult,
    RunnerError,
    framing_from_model,
    run_once,
)
from harness.task import Task

DEFAULT_RETRIES = 2


class DriverError(RuntimeError):
    """Raised for unrecoverable driver configuration errors (unsupported tool,
    etc.). Per-cell failures are recorded in `MatrixResult.cells`, not raised."""


@dataclass
class MatrixConfig:
    run_id: str | None = None
    runs_root: Path = Path("runs")
    # When `model` is set, every cell runs in "harness" framing (the shared
    # model is forced via the wrapper's --model flag). When `model` is None
    # AND `model_overrides` is empty, every cell runs in "product" framing
    # (each tool uses its default model). The framing label itself is
    # derived — see harness.runner.framing_from_model.
    model: str | None = None
    # Per-tool model overrides for the case where the two CLIs use
    # different names for the same underlying model. For example:
    #   model_overrides = {"copilot": "claude-sonnet-4.6"}
    # plus model="claude-sonnet-4-6" → claude gets the dashed name, copilot
    # gets the dotted one, both intended to address the same model.
    # When a tool appears in this dict, its entry wins over `model`.
    model_overrides: dict[str, str] = field(default_factory=dict)
    budget_seconds: int = DEFAULT_BUDGET_SECONDS
    seeds: list[int] = field(default_factory=lambda: [0])
    retries: int = DEFAULT_RETRIES
    cleanup_worktree: bool = False
    # Override hooks (tests use these).
    graders: list[str] | None = None
    runner_kwargs: dict | None = None


@dataclass
class CellResult:
    """The outcome of running one (task, tool, seed) cell. `result` is
    None iff every attempt crashed in the runner (e.g., wrapper not
    found, worktree prep failed) — in that case `crashed_with` carries
    the captured exception message."""

    task_id: str
    tool: str
    seed: int
    attempts: int
    retry_reasons: list[str]
    result: RunResult | None
    crashed_with: str | None


@dataclass
class MatrixResult:
    run_id: str
    framing: str
    cells: list[CellResult]

    def __iter__(self):
        return iter(self.cells)


# ----- public entry point ---------------------------------------------------


def run_matrix(
    tasks: list[Task], tools: list[str], config: MatrixConfig | None = None
) -> MatrixResult:
    """Run every (task, tool, seed) cell. See module docstring."""
    cfg = config or MatrixConfig()

    bad_tools = [t for t in tools if t not in SUPPORTED_TOOLS]
    if bad_tools:
        raise DriverError(
            f"unsupported tools: {bad_tools}; expected subset of {list(SUPPORTED_TOOLS)}"
        )

    run_id = cfg.run_id or _new_run_id()
    # Matrix-level framing summary: any model present anywhere (either the
    # uniform default or any per-tool override) puts the matrix in
    # "harness" intent. Individual cells' manifest.framing is still derived
    # cell-by-cell from the model that actually got passed to that cell.
    framing = "harness" if (cfg.model or cfg.model_overrides) else "product"
    cells: list[CellResult] = []

    for task in tasks:
        for tool in tools:
            for seed in cfg.seeds:
                cell = _run_one_cell(task, tool, seed, run_id, cfg)
                cells.append(cell)
                _print_cell_progress(cell)

    return MatrixResult(run_id=run_id, framing=framing, cells=cells)


# ----- internals ------------------------------------------------------------


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")


def _run_one_cell(task: Task, tool: str, seed: int, run_id: str, cfg: MatrixConfig) -> CellResult:
    """Drive a single (task, tool, seed) through up to `cfg.retries + 1`
    attempts, then update the final manifest's `retries` field. Catches
    runner crashes per attempt so one bad cell doesn't abort the matrix.
    """
    retry_reasons: list[str] = []
    last_result: RunResult | None = None
    crashed_with: str | None = None
    attempts = 0

    for attempt in range(cfg.retries + 1):
        attempts = attempt + 1
        run_cfg = _build_run_config(tool, run_id, cfg)
        try:
            last_result = run_once(task, tool, seed, run_cfg)
            crashed_with = None  # successful invocation supersedes prior crash
        except (RunnerError, Exception) as exc:  # noqa: BLE001 — crashes are data here
            crashed_with = f"{type(exc).__name__}: {exc}"
            retry_reasons.append(f"runner crash: {crashed_with}")
            continue

        if last_result.exit_code == 0:
            break  # success — done
        if last_result.timed_out:
            break  # timeout = the budget, not a transient — that's our data
        retry_reasons.append(f"non-zero exit {last_result.exit_code} (treated as transient)")

    if last_result is not None and retry_reasons:
        _update_manifest_retries(last_result.manifest_path, retry_reasons)

    return CellResult(
        task_id=task.task_id,
        tool=tool,
        seed=seed,
        attempts=attempts,
        retry_reasons=retry_reasons,
        result=last_result,
        crashed_with=crashed_with if last_result is None else None,
    )


def _build_run_config(tool: str, run_id: str, cfg: MatrixConfig) -> RunConfig:
    """Build a RunConfig for one cell.

    Per-cell model resolution: `cfg.model_overrides[tool]` wins over
    `cfg.model`. This lets the same logical model carry different names
    across tools — e.g. `claude-sonnet-4-6` for claude and
    `claude-sonnet-4.6` for copilot, which is a real-world Copilot vs
    Anthropic naming asymmetry.

    The framing label (`"product"` / `"harness"`) is derived from
    whichever model the cell ended up with: a set model means "harness",
    None means "product". The label is recorded in each cell's manifest.
    """
    model = cfg.model_overrides.get(tool, cfg.model)
    extra = dict(cfg.runner_kwargs or {})
    if cfg.graders is not None:
        extra["graders"] = cfg.graders

    return RunConfig(
        runs_root=cfg.runs_root,
        run_id=run_id,
        budget_seconds=cfg.budget_seconds,
        model=model,
        cleanup_worktree=cfg.cleanup_worktree,
        **extra,
    )


def _update_manifest_retries(manifest_path: Path, reasons: list[str]) -> None:
    """Re-read the cell's manifest, set its `retries` field, write back.

    The runner writes the manifest with retries={count: 0, reasons: []};
    we update it after the retry loop completes so the final manifest is
    auditable. Validated through Pydantic both ways, so a schema drift
    here surfaces immediately."""
    m = read_manifest(manifest_path)
    m.retries = RetryInfo(count=len(reasons), reasons=reasons)
    write_manifest(m, manifest_path)


def _print_cell_progress(cell: CellResult) -> None:
    """Stream one short line per cell as the matrix runs. Stdout, not
    stderr — the CLI's caller can pipe matrix output cleanly."""
    if cell.result is None:
        print(
            f"  {cell.tool:<8} {cell.task_id:<32} seed={cell.seed}  "
            f"CRASH  attempts={cell.attempts}  ({cell.crashed_with})",
            flush=True,
        )
        return
    r = cell.result
    status = "ok " if r.exit_code == 0 else ("TIMEOUT" if r.timed_out else f"exit={r.exit_code}")
    retries_str = f"  retries={len(cell.retry_reasons)}" if cell.retry_reasons else ""
    print(
        f"  {cell.tool:<8} {cell.task_id:<32} seed={cell.seed}  "
        f"{status:<10} wall={r.wall_clock_seconds:6.1f}s{retries_str}",
        flush=True,
    )


def matrix_result_to_dict(m: MatrixResult) -> dict:
    """Serialize a MatrixResult to a plain dict for JSON output. The
    nested RunResult / Path fields are stringified for portability."""
    out = {"run_id": m.run_id, "framing": m.framing, "cells": []}
    for c in m.cells:
        cell = asdict(c)
        if c.result is not None:
            cell["result"] = {
                **asdict(c.result),
                "run_dir": str(c.result.run_dir),
                "diff_path": str(c.result.diff_path),
                "manifest_path": str(c.result.manifest_path),
                "grade_path": str(c.result.grade_path) if c.result.grade_path else None,
            }
        out["cells"].append(cell)
    return out


def _cli_main(argv: list[str] | None = None) -> int:
    """Module-level helper invoked from `harness.cli` for the run-matrix
    subcommand. Returns 0 if every cell succeeded; 1 otherwise."""
    import argparse

    parser = argparse.ArgumentParser(prog="harness run-matrix")
    parser.add_argument("--tasks", dest="tasks_yaml", required=True)
    parser.add_argument("--tools", required=True, help="comma-separated list (e.g. claude,copilot)")
    parser.add_argument(
        "--model",
        help=(
            "shared model to force on every tool (sets framing='harness'). "
            "Omit to let each tool use its default model (framing='product'). "
            "Per-tool overrides via --model-for take precedence over this default."
        ),
    )
    parser.add_argument(
        "--model-for",
        dest="model_for",
        action="append",
        default=[],
        metavar="TOOL=NAME",
        help=(
            "Per-tool model override (repeatable). Takes precedence over "
            "--model for the named tool. Use this when the two CLIs use "
            "different names for the same underlying model. Example: "
            "--model-for copilot=claude-sonnet-4.6 paired with "
            "--model claude-sonnet-4-6 (claude wants dashes, copilot wants dots)."
        ),
    )
    parser.add_argument("--seeds", default="0", help="comma-separated seed list")
    parser.add_argument("--budget-seconds", type=int, default=DEFAULT_BUDGET_SECONDS)
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument("--run-id")
    parser.add_argument("--runs-root", default="runs")
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--provider", default="swebench", choices=["swebench"])
    parser.add_argument("--output-json", help="write a matrix.json summary to this path")
    args = parser.parse_args(argv)

    from harness.providers.swebench import (
        SWEBenchVerifiedProvider,
        load_task_ids_from_yaml,
    )

    task_ids = load_task_ids_from_yaml(args.tasks_yaml)
    tasks = SWEBenchVerifiedProvider().load(task_ids)
    tools = [t.strip() for t in args.tools.split(",") if t.strip()]
    seeds = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]

    model_overrides: dict[str, str] = {}
    for entry in args.model_for or []:
        if "=" not in entry:
            parser.error(f"--model-for needs TOOL=NAME format, got: {entry!r}")
        tool_key, model_name = entry.split("=", 1)
        tool_key, model_name = tool_key.strip(), model_name.strip()
        if not tool_key or not model_name:
            parser.error(f"--model-for: empty tool or model name in {entry!r}")
        model_overrides[tool_key] = model_name

    cfg = MatrixConfig(
        run_id=args.run_id,
        runs_root=Path(args.runs_root),
        model=args.model,
        model_overrides=model_overrides,
        budget_seconds=args.budget_seconds,
        seeds=seeds,
        retries=args.retries,
        cleanup_worktree=args.cleanup,
    )

    print(
        f"Matrix: {len(tasks)} task(s) × {len(tools)} tool(s) × {len(seeds)} seed(s) "
        f"= {len(tasks) * len(tools) * len(seeds)} cell(s)"
    )
    print(
        f"  run_id={cfg.run_id or '(auto)'}  "
        f"framing={framing_from_model(cfg.model)}  retries={cfg.retries}"
    )

    matrix = run_matrix(tasks, tools, cfg)

    print(f"\nMatrix complete. run_id={matrix.run_id}  framing={matrix.framing}")
    n_ok = sum(1 for c in matrix.cells if c.result and c.result.exit_code == 0)
    n_timeout = sum(1 for c in matrix.cells if c.result and c.result.timed_out)
    n_crash = sum(1 for c in matrix.cells if c.result is None)
    n_other = len(matrix.cells) - n_ok - n_timeout - n_crash
    print(f"  ok: {n_ok}   timeout: {n_timeout}   crashed: {n_crash}   other-nonzero: {n_other}")

    if args.output_json:
        Path(args.output_json).write_text(
            json.dumps(matrix_result_to_dict(matrix), indent=2) + "\n"
        )
        print(f"  wrote {args.output_json}")

    return 0 if n_ok == len(matrix.cells) else 1


if __name__ == "__main__":
    sys.exit(_cli_main())
