"""Tests for the mock grader (Step 8) — machinery-only signal."""

from __future__ import annotations

from pathlib import Path

from harness.graders import get_grader
from harness.graders.mock import grade as mock_grade
from harness.task import Task


def _task() -> Task:
    return Task(
        task_id="t1",
        repo_url="https://example/repo",
        base_sha="0" * 40,
        prompt="p",
        test_command="pytest",
    )


def test_mock_reports_true_on_nonempty_diff(tmp_path: Path):
    (tmp_path / "diff.patch").write_text("diff --git a/x b/x\n+content\n")
    assert mock_grade(tmp_path, _task()) == {"produced_nonempty_diff": True}


def test_mock_reports_false_on_empty_diff(tmp_path: Path):
    (tmp_path / "diff.patch").write_text("")
    assert mock_grade(tmp_path, _task()) == {"produced_nonempty_diff": False}


def test_mock_reports_false_on_missing_diff(tmp_path: Path):
    # No diff.patch at all.
    assert mock_grade(tmp_path, _task()) == {"produced_nonempty_diff": False}


def test_registry_returns_mock_grader():
    assert get_grader("mock") is mock_grade
