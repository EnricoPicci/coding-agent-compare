"""Per-grader plug-in registry, mirroring the parsers/ pattern.

Step 8 ships only the mock grader. Step 9 (host-venv test runner) and Step 10
(files-touched precision/recall, diff-size) will register themselves the same
way. The runner reads `RunConfig.graders` (a list of names) to decide which
graders to invoke after each run.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from harness.task import Task

GraderFn = Callable[[Path, Task], dict[str, Any]]

_GRADERS: dict[str, GraderFn] = {}


def register(name: str, fn: GraderFn) -> None:
    _GRADERS[name] = fn


def get_grader(name: str) -> GraderFn:
    if name not in _GRADERS:
        # Lazy-import the module that registers `name` on demand.
        if name == "mock":
            from harness.graders import mock  # noqa: F401
        elif name == "swebench_host":
            from harness.graders import swebench_host  # noqa: F401
        else:
            raise KeyError(f"no grader registered for {name!r}")
    return _GRADERS[name]


__all__ = ["GraderFn", "get_grader", "register"]
