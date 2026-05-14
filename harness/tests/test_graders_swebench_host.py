"""Tests for the swebench_host grader (Step 9).

Unit tests cover the pure-function pieces (pytest output parsing, spec
loading, name matching). The full end-to-end install + test run is gated
behind @pytest.mark.integration since it creates a real venv and pip-installs
a real repo — that's the verify-clause-of-the-plan smoke check, not a
unit test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.graders.swebench_host import (
    GradeSpec,
    _load_spec,
    _name_match,
    _parse_pytest_results,
    _truncate,
    grade,
)
from harness.task import Task


# ----- pure-function unit tests --------------------------------------------


def test_parse_pytest_results_picks_up_passed_failed_error():
    out = """
tests/test_a.py::test_one PASSED                                         [ 25%]
tests/test_a.py::test_two FAILED                                         [ 50%]
tests/test_a.py::test_three ERROR                                        [ 75%]
tests/test_b.py::test_four SKIPPED                                       [100%]
"""
    results = _parse_pytest_results(out)
    assert results["tests/test_a.py::test_one"] == "PASSED"
    assert results["tests/test_a.py::test_two"] == "FAILED"
    assert results["tests/test_a.py::test_three"] == "ERROR"
    assert results["tests/test_b.py::test_four"] == "SKIPPED"


def test_parse_pytest_results_handles_xfail_xpass():
    out = "tests/test_x.py::test_y XFAIL\ntests/test_x.py::test_z XPASS\n"
    results = _parse_pytest_results(out)
    assert results["tests/test_x.py::test_y"] == "XFAIL"
    assert results["tests/test_x.py::test_z"] == "XPASS"


def test_parse_pytest_results_ignores_non_matching_lines():
    out = "============== test session starts ==============\nsome random log\n"
    assert _parse_pytest_results(out) == {}


def test_name_match_exact():
    results = {"tests/t.py::test_x": "PASSED"}
    assert _name_match(results, "tests/t.py::test_x") == "PASSED"


def test_name_match_returns_none_when_not_found():
    assert _name_match({}, "tests/t.py::test_x") is None


def test_name_match_handles_path_normalization():
    """pytest sometimes prefixes test paths differently — name_match tolerates
    'src/tests/t.py::test_x' vs 'tests/t.py::test_x'."""
    results = {"src/tests/t.py::test_x": "PASSED"}
    assert _name_match(results, "tests/t.py::test_x") == "PASSED"


def test_truncate_under_limit():
    assert _truncate("short") == "short"


def test_truncate_over_limit():
    out = _truncate("x" * 1000, limit=50)
    assert out.startswith("x" * 50)
    assert "truncated" in out


# ----- spec loading --------------------------------------------------------


def test_load_spec_reads_known_task(tmp_path: Path):
    yaml_text = """
tasks:
  my_task:
    python_version: "3.10"
    host_runnable: true
    install_cmds:
      - "uv pip install -e ."
"""
    p = tmp_path / "spec.yaml"
    p.write_text(yaml_text)
    spec = _load_spec(p, "my_task")
    assert spec == GradeSpec(
        python_version="3.10", host_runnable=True, install_cmds=["uv pip install -e ."]
    )


def test_load_spec_returns_none_for_unknown_task(tmp_path: Path):
    p = tmp_path / "spec.yaml"
    p.write_text("tasks: {a: {python_version: '3.11', host_runnable: true}}")
    assert _load_spec(p, "missing") is None


def test_load_spec_returns_none_for_missing_file(tmp_path: Path):
    assert _load_spec(tmp_path / "no.yaml", "x") is None


def test_smoke_grade_yaml_has_entries_for_every_smoke_task():
    """The grade spec YAML must stay in sync with the smoke task YAML —
    every entry in swebench_smoke.yaml needs a matching grade spec, or the
    grader will silently report 'no grade spec' for it."""
    from harness.providers.swebench import load_task_ids_from_yaml

    root = Path(__file__).parents[2]
    smoke_ids = set(load_task_ids_from_yaml(root / "tasks" / "swebench_smoke.yaml"))
    grade_yaml = root / "tasks" / "swebench_smoke_grade.yaml"
    assert grade_yaml.exists(), "tasks/swebench_smoke_grade.yaml is missing"

    import yaml as yaml_mod

    grade_spec = yaml_mod.safe_load(grade_yaml.read_text())
    grade_ids = set((grade_spec or {}).get("tasks", {}).keys())
    missing = smoke_ids - grade_ids
    assert not missing, f"smoke tasks without grade specs: {missing}"


# ----- ungradeable paths ---------------------------------------------------


def _task(task_id: str = "unknown_task") -> Task:
    return Task(
        task_id=task_id,
        repo_url="file:///nowhere",
        base_sha="0" * 40,
        prompt="p",
        test_command="pytest",
    )


def test_grade_reports_ungradeable_when_no_spec(tmp_path: Path):
    spec = tmp_path / "empty.yaml"
    spec.write_text("tasks: {}")
    out = grade(tmp_path, _task("not_in_yaml"), spec_path=spec)
    assert out["pass"] is None
    assert "no grade spec" in out["grader_notes"]


def test_grade_reports_ungradeable_when_host_runnable_false(tmp_path: Path):
    spec = tmp_path / "spec.yaml"
    spec.write_text("tasks: {x: {python_version: '3.11', host_runnable: false, install_cmds: []}}")
    out = grade(tmp_path, _task("x"), spec_path=spec)
    assert out["pass"] is None
    assert "host_runnable=false" in out["grader_notes"]


# ----- integration test (real venv + pip install + pytest) ------------------


@pytest.mark.integration
def test_gold_patch_grades_pass_on_smoke_task(tmp_path: Path):
    """Verify clause of the plan: applying the human's gold patch to the
    base SHA and grading should yield pass=true. Picks the lightest smoke
    task (pytest-dev__pytest-10051, 16 tests total). Real install + pytest;
    ~30-90s the first time the bare clone is fetched.
    """
    from harness.providers.swebench import (
        SWEBenchVerifiedProvider,
        load_task_ids_from_yaml,
    )

    root = Path(__file__).parents[2]
    smoke_yaml = root / "tasks" / "swebench_smoke.yaml"
    ids = load_task_ids_from_yaml(smoke_yaml)
    task = next(
        t for t in SWEBenchVerifiedProvider().load(ids) if t.task_id == "pytest-dev__pytest-10051"
    )

    # Stage a "run dir" with diff.patch = gold patch.
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    gold_patch = task.metadata["patch"]
    (run_dir / "diff.patch").write_text(gold_patch)

    result = grade(run_dir, task)
    # Print full result so a failure here is debuggable from CI.
    print(json.dumps(result, indent=2, default=str))
    assert result["pass"] is True, f"gold patch failed to grade as pass: {result}"
    assert not result["tests_failed"]


@pytest.mark.integration
def test_empty_diff_grades_pass_false_on_smoke_task(tmp_path: Path):
    """Verify clause: with no agent diff, the bug-reproducing tests
    (FAIL_TO_PASS) should fail, so pass=false. Uses the same lightest
    smoke task as the gold-patch test above."""
    from harness.providers.swebench import (
        SWEBenchVerifiedProvider,
        load_task_ids_from_yaml,
    )

    root = Path(__file__).parents[2]
    ids = load_task_ids_from_yaml(root / "tasks" / "swebench_smoke.yaml")
    task = next(
        t for t in SWEBenchVerifiedProvider().load(ids) if t.task_id == "pytest-dev__pytest-10051"
    )

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "diff.patch").write_text("")  # explicit empty diff

    result = grade(run_dir, task)
    print(json.dumps(result, indent=2, default=str))
    # pass must be False (or possibly null if test_patch couldn't apply, but
    # the gold patch already verified the test_patch applies cleanly).
    assert result["pass"] is False, f"empty diff should not grade as pass: {result}"
    # At least one FAIL_TO_PASS test must be in tests_failed.
    assert any(t in result["tests_failed"] for t in task.fail_to_pass)
