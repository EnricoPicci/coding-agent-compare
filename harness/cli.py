"""Command-line interface for the harness."""

from __future__ import annotations

import argparse
import sys

from harness import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Evaluation harness comparing Claude Code and GitHub Copilot CLI.",
    )
    parser.add_argument("--version", action="version", version=f"harness {__version__}")

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    tasks = sub.add_parser("tasks", help="inspect and manage tasks")
    tasks_sub = tasks.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")
    tasks_list = tasks_sub.add_parser("list", help="list tasks from a provider")
    tasks_list.add_argument(
        "--provider",
        required=True,
        choices=["swebench"],
        help="task provider to load from",
    )
    tasks_list.add_argument(
        "--filter",
        dest="filter_path",
        help="YAML file with a 'task_ids' list to filter the provider's output",
    )

    run = sub.add_parser("run", help="run one (task, tool, seed) end-to-end")
    run.add_argument("--task", dest="task_id", required=True, help="task_id to run")
    run.add_argument("--tool", required=True, choices=["claude", "copilot"])
    run.add_argument("--seed", type=int, default=0)
    run.add_argument(
        "--provider",
        default="swebench",
        choices=["swebench"],
        help="task provider to load --task from",
    )
    run.add_argument(
        "--budget-seconds",
        type=int,
        default=900,
        help="wall-clock budget per attempt (default: 900s / 15min)",
    )
    run.add_argument(
        "--model",
        help=(
            "shared model to force this run onto (sets framing='harness' in the "
            "manifest). Omit to let the tool use its default model "
            "(framing='product')."
        ),
    )
    run.add_argument("--run-id", help="reuse an existing run-id instead of generating one")
    run.add_argument(
        "--runs-root",
        default="runs",
        help="output root (default: runs/)",
    )
    run.add_argument(
        "--cleanup",
        action="store_true",
        help="remove the worktree after the run (default: keep for inspection)",
    )

    matrix = sub.add_parser(
        "run-matrix",
        help="run (task × tool × seed) over a smoke list with retries",
    )
    matrix.add_argument(
        "--tasks", dest="tasks_yaml", required=True, help="YAML file with task_ids (smoke list)"
    )
    matrix.add_argument(
        "--tools", required=True, help="comma-separated tool list, e.g. claude,copilot"
    )
    matrix.add_argument(
        "--model",
        help=(
            "shared model to force on every cell (sets framing='harness'). "
            "Omit to let each tool use its default model (framing='product'). "
            "Per-tool overrides via --model-for take precedence over this default."
        ),
    )
    matrix.add_argument(
        "--model-for",
        dest="model_for",
        action="append",
        default=[],
        metavar="TOOL=NAME",
        help=(
            "Per-tool model override (repeatable). Use when the two CLIs use "
            "different names for the same underlying model — e.g. claude wants "
            "claude-sonnet-4-6 (dashes) while copilot wants claude-sonnet-4.6 "
            "(dots). Example: --model-for copilot=claude-sonnet-4.6"
        ),
    )
    matrix.add_argument("--seeds", default="0", help="comma-separated seed list")
    matrix.add_argument("--budget-seconds", type=int, default=900)
    matrix.add_argument(
        "--retries", type=int, default=2, help="transient-failure retries per cell (default: 2)"
    )
    matrix.add_argument("--run-id")
    matrix.add_argument("--runs-root", default="runs")
    matrix.add_argument("--cleanup", action="store_true")
    matrix.add_argument("--provider", default="swebench", choices=["swebench"])
    matrix.add_argument(
        "--output-json",
        help="write a matrix.json summary to this path after completion",
    )

    return parser


def _cmd_tasks_list(args: argparse.Namespace) -> int:
    from harness.providers.swebench import (
        SWEBenchVerifiedProvider,
        load_task_ids_from_yaml,
    )

    if args.provider != "swebench":
        # argparse 'choices' already enforces this, but be explicit.
        print(f"unknown provider: {args.provider}", file=sys.stderr)
        return 2

    task_ids = load_task_ids_from_yaml(args.filter_path) if args.filter_path else None
    provider = SWEBenchVerifiedProvider()
    tasks = provider.load(task_ids)

    for t in tasks:
        title = t.prompt.splitlines()[0] if t.prompt else ""
        print(f"{t.task_id}\t{t.metadata.get('repo', '')}\t{t.base_sha[:12]}\t{title[:80]}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from pathlib import Path

    from harness.providers.swebench import SWEBenchVerifiedProvider
    from harness.runner import RunConfig, run_once

    provider = SWEBenchVerifiedProvider()
    tasks = provider.load([args.task_id])
    if not tasks:
        print(f"task not found: {args.task_id}", file=sys.stderr)
        return 2
    task = tasks[0]

    cfg = RunConfig(
        runs_root=Path(args.runs_root),
        run_id=args.run_id,
        budget_seconds=args.budget_seconds,
        model=args.model,
        cleanup_worktree=args.cleanup,
    )
    result = run_once(task, args.tool, args.seed, cfg)

    print(f"run-id:    {result.run_id}")
    print(f"run-dir:   {result.run_dir}")
    print(f"exit:      {result.exit_code}{' (timed out)' if result.timed_out else ''}")
    print(f"wall:      {result.wall_clock_seconds:.1f}s")
    print(f"diff:      {result.diff_path}")
    print(f"manifest:  {result.manifest_path}")
    return 0 if result.exit_code == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "tasks":
        if args.subcommand == "list":
            return _cmd_tasks_list(args)
        parser.parse_args([args.command, "--help"])
        return 2
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "run-matrix":
        return _cmd_run_matrix(args)

    parser.print_help()
    return 1


def _cmd_run_matrix(args: argparse.Namespace) -> int:
    """Thin shim that forwards into harness.driver._cli_main."""
    from harness.driver import _cli_main

    forwarded = [
        "--tasks",
        args.tasks_yaml,
        "--tools",
        args.tools,
        "--seeds",
        args.seeds,
        "--budget-seconds",
        str(args.budget_seconds),
        "--retries",
        str(args.retries),
        "--runs-root",
        args.runs_root,
        "--provider",
        args.provider,
    ]
    if args.model:
        forwarded += ["--model", args.model]
    for entry in args.model_for or []:
        forwarded += ["--model-for", entry]
    if args.run_id:
        forwarded += ["--run-id", args.run_id]
    if args.cleanup:
        forwarded.append("--cleanup")
    if args.output_json:
        forwarded += ["--output-json", args.output_json]
    return _cli_main(forwarded)
