"""Per-tool trace parsers that translate raw stdout.log into a normalized
events.jsonl. Each tool has its own parser because the trace formats differ
substantially; the shared `NormalizedEvent` shape (see `base.py`) is what
downstream graders and reports consume.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from harness.parsers.event import NormalizedEvent

_PARSERS: dict[str, Callable[[Path], list[NormalizedEvent]]] = {}


def register(tool: str, fn: Callable[[Path], list[NormalizedEvent]]) -> None:
    _PARSERS[tool] = fn


def get_parser(tool: str) -> Callable[[Path], list[NormalizedEvent]]:
    if tool not in _PARSERS:
        # Lazy-import so the package boots cheap even when only one parser is used.
        if tool == "claude":
            from harness.parsers import claude  # noqa: F401
        elif tool == "copilot":
            from harness.parsers import copilot  # noqa: F401
        else:
            raise KeyError(f"no parser registered for tool {tool!r}")
    return _PARSERS[tool]


__all__ = ["NormalizedEvent", "get_parser", "register"]
