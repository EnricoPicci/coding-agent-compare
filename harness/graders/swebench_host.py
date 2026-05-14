"""Primary grader — host-venv test runner (Step 9).

Given a completed run, replay the bug's tests on a fresh worktree with the
agent's diff applied, parse pytest output, and report pass/fail against
FAIL_TO_PASS + PASS_TO_PASS.

Pipeline per call:

  1. Look up the task in tasks/swebench_smoke_grade.yaml. If missing or
     `host_runnable: false`, return pass=null with a clear grader_notes.
  2. Prepare a fresh grade worktree at task.base_sha (separate from the
     agent's run worktree — never mutate the agent's working tree).
  3. Apply the agent's diff.patch on top of the worktree. If it doesn't
     apply, pass=false with a "patch did not apply" note.
  4. Apply the task's test_patch on top. If it doesn't apply, pass=null
     (we can't grade what we can't test).
  5. Create a per-seed `uv venv` at <run_dir>/grade-venv. Run install
     commands from the YAML inside the worktree.
  6. Run pytest with the FAIL_TO_PASS + PASS_TO_PASS test names as targets.
     Parse stdout line-by-line for `PASSED` / `FAILED` / `ERROR` markers.
  7. Cross-reference against the F2P+P2P lists. `pass=true` iff *every*
     listed test reports PASSED.

Fail-soft policy: any unrecoverable internal error (venv creation crash,
test runner exit on signal, etc.) goes to pass=null with grader_notes
containing the captured reason. The run is still considered complete.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from harness.graders import register
from harness.task import Task
from harness.worktree import WorktreeManager

DEFAULT_SPEC_PATH = Path(__file__).resolve().parents[2] / "tasks" / "swebench_smoke_grade.yaml"
TEST_RUN_TIMEOUT_SECONDS = 300  # 5 min per pytest invocation


@dataclass(frozen=True)
class GradeSpec:
    python_version: str
    host_runnable: bool
    install_cmds: list[str]
    # Per-task pytest argument extensions. Used when a project's own
    # pytest.ini interferes with targeted FAIL_TO_PASS/PASS_TO_PASS selection
    # (e.g. requests's --doctest-modules hijacks the collection phase).
    pytest_extra_args: list[str] = field(default_factory=list)
    # Tests we expect to be environment-dependent on the host and therefore
    # cannot grade reliably — e.g. tests that require slow-network access
    # to specific hosts. Removed from the F2P/P2P target lists before pytest
    # runs and reported in `unresolved` instead. Use sparingly.
    skip_tests: list[str] = field(default_factory=list)


# ----- public entry point ---------------------------------------------------


def grade(
    run_dir: Path,
    task: Task,
    *,
    spec_path: Path | None = None,
    worktree_manager: WorktreeManager | None = None,
) -> dict[str, Any]:
    """Run the host-venv grader for one run. See module docstring for the pipeline."""
    spec = _load_spec(spec_path or DEFAULT_SPEC_PATH, task.task_id)
    if spec is None:
        return {
            "pass": None,
            "grader_notes": f"ungradeable on host: no grade spec for {task.task_id}",
        }
    if not spec.host_runnable:
        return {
            "pass": None,
            "grader_notes": f"ungradeable on host: spec marks {task.task_id} as host_runnable=false",
        }

    grade_root = run_dir / "grade-work"
    grade_root.mkdir(parents=True, exist_ok=True)
    mgr = worktree_manager or WorktreeManager()
    worktree = mgr.prepare(task, grade_root)

    try:
        diff_patch = (
            (run_dir / "diff.patch").read_text() if (run_dir / "diff.patch").exists() else ""
        )
        if diff_patch.strip():
            err = _git_apply(worktree, diff_patch)
            if err is not None:
                return {
                    "pass": False,
                    "grader_notes": f"agent diff did not apply: {_truncate(err)}",
                }

        test_patch = task.metadata.get("test_patch") or ""
        if test_patch.strip():
            err = _git_apply(worktree, test_patch)
            if err is not None:
                return {
                    "pass": None,
                    "grader_notes": f"test_patch did not apply: {_truncate(err)}",
                }

        venv_dir = run_dir / "grade-venv"
        err = _create_venv(venv_dir, spec.python_version)
        if err is not None:
            return {"pass": None, "grader_notes": f"venv create failed: {_truncate(err)}"}

        for cmd in spec.install_cmds:
            err = _run_in_venv(venv_dir, cmd, cwd=worktree)
            if err is not None:
                return {
                    "pass": None,
                    "grader_notes": f"install failed [{cmd}]: {_truncate(err)}",
                }

        # FAIL_TO_PASS + PASS_TO_PASS use pytest's `path::testname` format.
        # SWE-bench Verified occasionally has data-corrupted parametrized
        # names with unbalanced brackets — pytest treats those as a CLI
        # usage error (rc=4) and refuses to run anything. Drop those names
        # into unresolved before calling pytest, then run with the rest.
        # Also drop any tests explicitly marked unrunnable in the spec.
        skip_set = set(spec.skip_tests)
        all_targets = list(task.fail_to_pass) + list(task.pass_to_pass)
        runnable = [t for t in all_targets if _looks_runnable(t) and t not in skip_set]
        unrunnable = [t for t in all_targets if not _looks_runnable(t)]
        skipped = [t for t in all_targets if t in skip_set]

        pytest_out, pytest_err = _run_pytest(
            venv_dir, worktree, runnable, extra_args=spec.pytest_extra_args
        )

        results = _parse_pytest_results(pytest_out + "\n" + pytest_err)
        passed_f2p = [t for t in task.fail_to_pass if _name_match(results, t) == "PASSED"]
        passed_p2p = [t for t in task.pass_to_pass if _name_match(results, t) == "PASSED"]
        # A test is "failed" only if pytest actually reported a non-pass for it.
        # Unrunnable + skipped names go to `unresolved`, not `failed`.
        excluded = set(unrunnable) | skip_set
        failed_f2p = [
            t
            for t in task.fail_to_pass
            if t not in excluded and _name_match(results, t) in {"FAILED", "ERROR"}
        ]
        failed_p2p = [
            t
            for t in task.pass_to_pass
            if t not in excluded and _name_match(results, t) in {"FAILED", "ERROR"}
        ]
        all_passed = not failed_f2p and not failed_p2p

        unresolved = (
            unrunnable
            + skipped
            + [t for t in runnable if _name_match(results, t) not in {"PASSED", "FAILED", "ERROR"}]
        )
        notes_parts: list[str] = []
        if unrunnable:
            notes_parts.append(
                f"{len(unrunnable)} data-corrupted target name(s) dropped before pytest"
            )
        if skipped:
            notes_parts.append(f"{len(skipped)} env-dependent test(s) skipped per grade spec")
        pytest_unresolved = len(unresolved) - len(unrunnable) - len(skipped)
        if pytest_unresolved:
            notes_parts.append(f"unresolved={pytest_unresolved}/{len(runnable)}")

        return {
            "pass": all_passed,
            "tests_passed": passed_f2p + passed_p2p,
            "tests_failed": failed_f2p + failed_p2p,
            "unresolved": unresolved,
            "grader_notes": "; ".join(notes_parts) if notes_parts else None,
        }
    finally:
        # The grade worktree is recreatable from cache. Removing it keeps the
        # run dir from doubling in size; users who want to inspect can re-run
        # the grader. Venv is preserved because that's the slow-to-recreate part.
        try:
            mgr.cleanup(worktree)
        except Exception:  # noqa: BLE001
            pass
        # Drop the now-empty parent dir so a successful cleanup leaves no
        # cosmetic stub next to grade.json. If grading crashed before
        # cleanup (so the worktree is still there), rmdir() raises OSError
        # and we silently leave the dir alone for inspection.
        try:
            grade_root.rmdir()
        except OSError:
            pass


# ----- internals ------------------------------------------------------------


def _load_spec(spec_path: Path, task_id: str) -> GradeSpec | None:
    if not spec_path.exists():
        return None
    raw = yaml.safe_load(spec_path.read_text()) or {}
    entries = raw.get("tasks") or {}
    entry = entries.get(task_id)
    if not entry:
        return None
    return GradeSpec(
        python_version=str(entry.get("python_version", "3.11")),
        host_runnable=bool(entry.get("host_runnable", False)),
        install_cmds=list(entry.get("install_cmds") or []),
        pytest_extra_args=list(entry.get("pytest_extra_args") or []),
        skip_tests=list(entry.get("skip_tests") or []),
    )


def _git_apply(worktree: Path, patch_text: str) -> str | None:
    """Apply a patch to the worktree via stdin. Returns stderr on failure, None on success."""
    result = subprocess.run(
        ["git", "-C", str(worktree), "apply", "--whitespace=nowarn", "-"],
        input=patch_text,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return result.stderr or result.stdout or f"exit {result.returncode}"
    return None


def _create_venv(venv_dir: Path, python_version: str) -> str | None:
    """Create a uv venv at venv_dir for the given Python version."""
    if venv_dir.exists():
        shutil.rmtree(venv_dir, ignore_errors=True)
    result = subprocess.run(
        ["uv", "venv", "--python", python_version, str(venv_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return result.stderr or result.stdout or f"exit {result.returncode}"
    return None


def _run_in_venv(venv_dir: Path, cmd: str, cwd: Path) -> str | None:
    """Run a shell command with the venv's VIRTUAL_ENV active. Returns stderr
    on failure, None on success. Uses bash -c so the command string can be
    a full pipeline if needed."""
    env = _venv_env(venv_dir)
    result = subprocess.run(
        ["bash", "-c", cmd],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        # uv pip's most useful diagnostic is usually in stderr.
        return result.stderr or result.stdout or f"exit {result.returncode}"
    return None


def _run_pytest(
    venv_dir: Path,
    worktree: Path,
    targets: list[str],
    extra_args: list[str] | tuple[str, ...] = (),
) -> tuple[str, str]:
    """Invoke pytest in the venv against the listed targets. Returns (stdout, stderr).
    A non-zero pytest exit (typical when tests fail) is *not* an error here —
    the parser inspects the output regardless. `extra_args` lets per-task
    grade specs inject things like `--override-ini=addopts=` when a project's
    pytest.ini interferes with targeted selection."""
    env = _venv_env(venv_dir)
    cmd = [
        "pytest",
        "-v",
        "--tb=short",
        "-p",
        "no:cacheprovider",
        "--no-header",
        *extra_args,
        *targets,
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(worktree),
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=TEST_RUN_TIMEOUT_SECONDS,
        )
        return result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        return (
            exc.stdout or ""
        ) if exc.stdout else "", f"pytest exceeded {TEST_RUN_TIMEOUT_SECONDS}s"


def _venv_env(venv_dir: Path) -> dict[str, str]:
    """Construct an os.environ-like dict that prepends the venv's bin to PATH
    and sets VIRTUAL_ENV. Mimics `source venv/bin/activate`."""
    import os

    bin_dir = venv_dir / "bin"
    env = dict(os.environ)
    env["VIRTUAL_ENV"] = str(venv_dir)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env.pop("PYTHONHOME", None)
    return env


# pytest -v emits lines like: `tests/test_foo.py::test_bar PASSED [50%]`
# or `tests/test_foo.py::test_bar FAILED`.  Capture the test name and outcome.
_PYTEST_LINE = re.compile(r"^(\S+::\S+)\s+(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b")


def _parse_pytest_results(output: str) -> dict[str, str]:
    """Parse pytest -v output. Returns {test_name: outcome}."""
    results: dict[str, str] = {}
    for line in output.splitlines():
        m = _PYTEST_LINE.match(line.strip())
        if m:
            results[m.group(1)] = m.group(2)
    return results


def _looks_runnable(name: str) -> bool:
    """A test target is runnable iff it looks like a pytest `path::test` name
    with balanced parameter brackets. SWE-bench Verified sometimes ships
    parametrized names where the closing `]` was lost during serialization;
    pytest rejects those as 'not found' and aborts the entire batch."""
    return "::" in name and name.count("[") == name.count("]")


def _name_match(results: dict[str, str], name: str) -> str | None:
    """Look up `name` in pytest results. Tolerates path-prefix variations
    (e.g., results may key by `tests/test_foo.py::test_bar` while the
    F2P list has it as `tests/test_foo.py::test_bar`)."""
    if name in results:
        return results[name]
    # Try matching by suffix — pytest sometimes normalizes paths.
    for k, v in results.items():
        if k.endswith(name) or name.endswith(k):
            return v
    return None


def _truncate(text: str, limit: int = 400) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"... (truncated, {len(text) - limit} more chars)"


register("swebench_host", grade)
