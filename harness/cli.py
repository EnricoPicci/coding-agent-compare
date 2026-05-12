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

    parser.print_help()
    return 1
