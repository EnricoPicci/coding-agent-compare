"""Secondary grader: files-touched precision/recall vs the human PR (Step 10).

For each completed run, compare the set of files the agent's diff touches
against the set the human PR's gold patch touches. Report:

  - precision = |agent ∩ human| / |agent|   (how much of what the agent
                                              did was on-target)
  - recall    = |agent ∩ human| / |human|   (how much of what the human
                                              changed did the agent cover)

Both are appended to the run's `grade.json` alongside the primary grader's
verdict. They are advisory — a high precision/recall does not imply the
fix is correct (that's the primary grader's job), and a low one doesn't
imply it's wrong (an agent can solve a bug with a tighter or wider scope
than the human did). They surface a real qualitative difference between
the two tools the harness compares.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from harness.graders import register
from harness.task import Task

# `diff --git a/<path> b/<path>` is the canonical file-change header in a
# unified diff produced by `git diff`. We capture both sides so renames
# count as touching both paths.
_DIFF_FILE_RE = re.compile(r"^diff --git a/(\S+) b/(\S+)$", re.MULTILINE)


def files_touched(patch_text: str) -> set[str]:
    """Return the set of file paths touched by a unified diff.

    Includes both the `a/` (old) and `b/` (new) paths from each
    `diff --git` header, so renames count as touching both names. For
    modifications, deletions, and new files the two paths are identical
    so the set contains just one entry per file.
    """
    if not patch_text:
        return set()
    files: set[str] = set()
    for m in _DIFF_FILE_RE.finditer(patch_text):
        files.add(m.group(1))
        files.add(m.group(2))
    return files


def grade(run_dir: Path, task: Task) -> dict[str, Any]:
    agent_patch_path = run_dir / "diff.patch"
    agent_patch = agent_patch_path.read_text() if agent_patch_path.exists() else ""
    human_patch = task.metadata.get("patch") or ""

    agent_files = files_touched(agent_patch)
    human_files = files_touched(human_patch)

    # Defined-zero conventions:
    #   precision is None if the agent produced no diff (denominator zero
    #     and "what fraction of nothing was correct" is meaningless).
    #   recall is None if the human PR has no patch (a malformed task);
    #     otherwise it's 0 when the agent produced nothing.
    if not agent_files:
        precision: float | None = None
    else:
        precision = len(agent_files & human_files) / len(agent_files)

    if not human_files:
        recall: float | None = None
    elif not agent_files:
        recall = 0.0
    else:
        recall = len(agent_files & human_files) / len(human_files)

    return {
        "files_touched_precision": precision,
        "files_touched_recall": recall,
    }


register("scope", grade)
