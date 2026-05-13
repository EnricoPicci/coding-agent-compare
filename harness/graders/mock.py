"""Mock grader — Step 8.

The cheapest signal we can extract from a run: did the agent produce ANY
diff at all? `false` means the agent crashed, hit the wall-clock before
touching code, or returned a clean exit with no edits. `true` doesn't mean
the diff is correct — that's Step 9's job. It only means the plumbing
worked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.graders import register
from harness.task import Task


def grade(run_dir: Path, task: Task) -> dict[str, Any]:  # noqa: ARG001 — task unused
    diff_path = run_dir / "diff.patch"
    nonempty = diff_path.exists() and diff_path.stat().st_size > 0
    return {"produced_nonempty_diff": nonempty}


register("mock", grade)
