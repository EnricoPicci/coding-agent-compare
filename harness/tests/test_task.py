"""Tests for the Task dataclass."""

from harness.task import Task


def make_task() -> Task:
    return Task(
        task_id="x__y-1",
        repo_url="https://github.com/x/y",
        base_sha="abc123",
        prompt="fix the thing",
        test_command="pytest -q tests/",
        fail_to_pass=["tests/test_a.py::test_one"],
        pass_to_pass=["tests/test_b.py::test_two"],
        expected_changed_files=["src/x.py"],
        metadata={"environment": "py311"},
    )


def test_round_trip_via_dict():
    task = make_task()
    assert Task.from_dict(task.to_dict()) == task


def test_round_trip_minimal_fields():
    minimal = Task(
        task_id="x__y-1",
        repo_url="https://github.com/x/y",
        base_sha="abc123",
        prompt="fix",
        test_command="pytest",
    )
    assert Task.from_dict(minimal.to_dict()) == minimal


def test_defaults_are_independent():
    a = Task(task_id="a", repo_url="", base_sha="", prompt="", test_command="")
    b = Task(task_id="b", repo_url="", base_sha="", prompt="", test_command="")
    a.fail_to_pass.append("x")
    assert b.fail_to_pass == []
