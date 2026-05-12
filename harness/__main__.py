"""Entry point for `python -m harness`."""

import argparse
import sys

from harness import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Evaluation harness comparing Claude Code and GitHub Copilot CLI.",
    )
    parser.add_argument("--version", action="version", version=f"harness {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    # No subcommands yet — subsequent plan steps wire up tasks, run, report, etc.
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
