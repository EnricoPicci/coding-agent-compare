"""Tests for the size (diff line count) grader."""

from __future__ import annotations


from harness.graders import get_grader
from harness.graders.size import count_diff_lines, grade
from harness.task import Task


def _task(human_patch: str = "") -> Task:
    return Task(
        task_id="t1",
        repo_url="https://example/repo",
        base_sha="0" * 40,
        prompt="p",
        test_command="pytest",
        metadata={"patch": human_patch},
    )


# ----- count_diff_lines -----------------------------------------------------


def test_count_empty():
    assert count_diff_lines("") == 0


def test_count_only_additions():
    diff = "diff --git a/x b/x\n@@ -0,0 +1,3 @@\n+a\n+b\n+c\n"
    assert count_diff_lines(diff) == 3


def test_count_only_deletions():
    diff = "diff --git a/x b/x\n@@ -1,3 +0,0 @@\n-a\n-b\n-c\n"
    assert count_diff_lines(diff) == 3


def test_count_mixed_additions_and_deletions():
    diff = (
        "diff --git a/x b/x\n"
        "--- a/x\n"
        "+++ b/x\n"
        "@@ -1,3 +1,3 @@\n"
        "-old1\n"
        "+new1\n"
        " context\n"
        "-old2\n"
        "+new2\n"
    )
    # 2 deletions + 2 additions = 4. The file-header `---` and `+++` and
    # the context line all don't count.
    assert count_diff_lines(diff) == 4


def test_count_ignores_file_headers():
    """`---` and `+++` look like deletions and additions but are file
    headers — must not be counted."""
    diff = "--- a/x.py\n+++ b/x.py\n@@ -0,0 +1,1 @@\n+actual\n"
    assert count_diff_lines(diff) == 1


def test_count_ignores_context_and_hunk_headers():
    diff = "@@ -1,2 +1,2 @@\n unchanged1\n unchanged2\n"
    assert count_diff_lines(diff) == 0


def test_count_multiple_hunks():
    diff = "diff --git a/x b/x\n@@ -1 +1 @@\n-old\n+new\n@@ -10 +10 @@\n-old2\n+new2\n"
    assert count_diff_lines(diff) == 4


# ----- grade() function -------------------------------------------------------


def test_grade_returns_both_counts(tmp_path):
    agent = "diff --git a/x b/x\n@@ @@\n+a\n+b\n"
    human = "diff --git a/x b/x\n@@ @@\n+a\n+b\n+c\n-d\n"
    (tmp_path / "diff.patch").write_text(agent)
    result = grade(tmp_path, _task(human))
    assert result == {"diff_size_lines": 2, "human_diff_size_lines": 4}


def test_grade_empty_agent_diff(tmp_path):
    (tmp_path / "diff.patch").write_text("")
    human = "diff --git a/x b/x\n@@ @@\n+a\n"
    result = grade(tmp_path, _task(human))
    assert result == {"diff_size_lines": 0, "human_diff_size_lines": 1}


def test_grade_missing_diff_file(tmp_path):
    """No diff.patch on disk — counts as 0 lines."""
    result = grade(tmp_path, _task("diff --git a/x b/x\n@@ @@\n+a\n"))
    assert result == {"diff_size_lines": 0, "human_diff_size_lines": 1}


def test_registry_dispatch():
    assert get_grader("size") is grade
