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
        # Lazy-import the module that registers `name` on demand. Each
        # grader module calls `register(name, grade_fn)` at import time (when the module's top-level code runs),
        # so the *side effect* of these imports — not the imported name
        # itself — is what populates `_GRADERS`.
        #
        # The trailing `noqa: F401` marker on each import silences ruff's
        # "imported but unused" warning (rule F401). The local name
        # (`mock`, `swebench_host`, etc.) is genuinely never referenced
        # after the import — we just need the module's top-level code to
        # run. Without the marker ruff would flag every line here as a
        # lint error.
        if name == "mock":
            from harness.graders import mock  # noqa: F401
        elif name == "swebench_host":
            from harness.graders import swebench_host  # noqa: F401
        elif name == "scope":
            from harness.graders import scope  # noqa: F401
        elif name == "size":
            from harness.graders import size  # noqa: F401
        else:
            raise KeyError(f"no grader registered for {name!r}")
    return _GRADERS[name]


__all__ = ["GraderFn", "get_grader", "register"]
