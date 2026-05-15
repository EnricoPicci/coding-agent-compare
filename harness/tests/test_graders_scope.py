"""Tests for the scope (files-touched precision/recall) grader."""

from __future__ import annotations

from pathlib import Path

from harness.graders import get_grader
from harness.graders.scope import files_touched, grade
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


def _write_diff(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "diff.patch"
    p.write_text(text)
    return p


# ----- files_touched parsing ------------------------------------------------


def test_files_touched_empty_returns_empty():
    assert files_touched("") == set()


def test_files_touched_single_modification():
    diff = "diff --git a/src/foo.py b/src/foo.py\n@@ -1 +1 @@\n-x\n+y\n"
    assert files_touched(diff) == {"src/foo.py"}


def test_files_touched_multiple_files():
    diff = "diff --git a/a.py b/a.py\n@@ @@\n+1\ndiff --git a/b.py b/b.py\n@@ @@\n+2\n"
    assert files_touched(diff) == {"a.py", "b.py"}


def test_files_touched_rename_includes_both_paths():
    """A rename should count both names — the agent (or human) interacted
    with the file under both identities."""
    diff = "diff --git a/old/path.py b/new/path.py\nsimilarity index 100%\nrename from old/path.py\nrename to new/path.py\n"
    assert files_touched(diff) == {"old/path.py", "new/path.py"}


def test_files_touched_new_file_single_path():
    """For created files, `a/` and `b/` paths in the diff --git line are
    identical (git syntax), so the set has one entry."""
    diff = (
        "diff --git a/newfile.py b/newfile.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/newfile.py\n"
        "@@ @@\n+content\n"
    )
    assert files_touched(diff) == {"newfile.py"}


# ----- grade() function --------------------------------------------------------


def test_grade_perfect_overlap(tmp_path):
    agent = "diff --git a/foo.py b/foo.py\n@@ @@\n+ change\n"
    human = "diff --git a/foo.py b/foo.py\n@@ @@\n+ different change\n"
    _write_diff(tmp_path, agent)
    result = grade(tmp_path, _task(human))
    assert result == {"files_touched_precision": 1.0, "files_touched_recall": 1.0}


def test_grade_partial_overlap(tmp_path):
    """Agent touched {a, b}, human touched {a, c}. Intersection = {a}.
    precision = 1/2; recall = 1/2."""
    agent = "diff --git a/a.py b/a.py\n@@ @@\n+1\ndiff --git a/b.py b/b.py\n@@ @@\n+2\n"
    human = "diff --git a/a.py b/a.py\n@@ @@\n+1\ndiff --git a/c.py b/c.py\n@@ @@\n+3\n"
    _write_diff(tmp_path, agent)
    result = grade(tmp_path, _task(human))
    assert result["files_touched_precision"] == 0.5
    assert result["files_touched_recall"] == 0.5


def test_grade_no_overlap(tmp_path):
    agent = "diff --git a/x.py b/x.py\n@@ @@\n+1\n"
    human = "diff --git a/y.py b/y.py\n@@ @@\n+1\n"
    _write_diff(tmp_path, agent)
    result = grade(tmp_path, _task(human))
    assert result == {"files_touched_precision": 0.0, "files_touched_recall": 0.0}


def test_grade_empty_agent_diff(tmp_path):
    """No agent diff → precision is undefined (None); recall is 0 (we
    covered none of the files the human touched)."""
    _write_diff(tmp_path, "")
    human = "diff --git a/y.py b/y.py\n@@ @@\n+1\n"
    result = grade(tmp_path, _task(human))
    assert result == {"files_touched_precision": None, "files_touched_recall": 0.0}


def test_grade_missing_agent_diff_file(tmp_path):
    """No `diff.patch` on disk at all — same as empty."""
    human = "diff --git a/y.py b/y.py\n@@ @@\n+1\n"
    result = grade(tmp_path, _task(human))
    assert result["files_touched_precision"] is None
    assert result["files_touched_recall"] == 0.0


def test_grade_empty_human_patch(tmp_path):
    """If the task has no gold patch (e.g. malformed), recall is None
    and precision is 0 (the agent touched files; none of them match any
    of zero human-touched files)."""
    _write_diff(tmp_path, "diff --git a/x.py b/x.py\n@@ @@\n+1\n")
    result = grade(tmp_path, _task(""))
    assert result["files_touched_precision"] == 0.0
    assert result["files_touched_recall"] is None


def test_registry_dispatch():
    assert get_grader("scope") is grade
