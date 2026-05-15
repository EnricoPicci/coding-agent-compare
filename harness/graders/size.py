"""Secondary grader: diff line count vs the human PR (Step 10).

Counts added + deleted lines in the agent's diff and in the human PR's
gold patch and reports both numbers. The ratio of the two is left to the
consumer to compute — Step 12's report builds its own column from these
fields.

The metric is mainly an over-editing detector: if the agent's diff is
several times larger than the human's, the agent likely refactored more
than it needed to. A diff that's much *smaller* than the human's is often
a sign the fix is too narrow (e.g., touched only the most obvious file).
Neither extreme is automatically wrong; this number is one input among
several.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.graders import register
from harness.task import Task


def count_diff_lines(patch_text: str) -> int:
    """Count added + deleted lines in a unified diff.

    A line counts as an addition iff it starts with `+` but is not a `+++`
    file header; symmetric for `-` and `---`. Context lines (leading space)
    and hunk headers (`@@`) are ignored.
    """
    count = 0
    for line in patch_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") or line.startswith("-"):
            count += 1
    return count


def grade(run_dir: Path, task: Task) -> dict[str, Any]:
    agent_patch_path = run_dir / "diff.patch"
    agent_patch = agent_patch_path.read_text() if agent_patch_path.exists() else ""
    human_patch = task.metadata.get("patch") or ""

    return {
        "diff_size_lines": count_diff_lines(agent_patch),
        "human_diff_size_lines": count_diff_lines(human_patch),
    }


register("size", grade)
