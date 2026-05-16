"""Tests for the multi-mode driver (Step 11).

Uses the same stub-wrapper pattern as test_runner.py — the wrapper is a tiny
bash script that mimics scripts/run_*.sh and the WorktreeManager is pointed
at a local bare repo, so no real CLI is invoked and no network is touched.
The point is to verify the driver's orchestration (matrix shape, framing,
retries, manifest update) — not to re-test what run_once already covers.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

import pytest

from harness.driver import (
    DEFAULT_RETRIES,
    CellResult,
    DriverError,
    MatrixConfig,
    MatrixResult,
    matrix_result_to_dict,
    run_matrix,
)
from harness.task import Task
from harness.worktree import WorktreeManager


# ----- shared fixtures -----------------------------------------------------


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def local_bare(tmp_path: Path) -> tuple[Path, str]:
    src = tmp_path / "src"
    src.mkdir()
    _git("init", "--quiet", "--initial-branch=main", cwd=src)
    _git("config", "user.email", "t@e.com", cwd=src)
    _git("config", "user.name", "t", cwd=src)
    (src / "seed.txt").write_text("v1\n")
    _git("add", "seed.txt", cwd=src)
    _git("commit", "--quiet", "-m", "seed", cwd=src)
    sha = _git("rev-parse", "HEAD", cwd=src)
    bare = tmp_path / "repo.git"
    _git("clone", "--bare", "--quiet", str(src), str(bare))
    return bare, sha


@pytest.fixture
def tasks(local_bare) -> list[Task]:
    """Two distinct tasks pointing at the same bare repo — enough to verify
    matrix expansion without needing two real repos."""
    bare, sha = local_bare
    return [
        Task(
            task_id="owner__repo-1",
            repo_url=f"file://{bare}",
            base_sha=sha,
            prompt="p1",
            test_command="pytest",
            metadata={"patch": "", "test_patch": ""},
        ),
        Task(
            task_id="owner__repo-2",
            repo_url=f"file://{bare}",
            base_sha=sha,
            prompt="p2",
            test_command="pytest",
            metadata={"patch": "", "test_patch": ""},
        ),
    ]


def _make_stub_wrapper(
    tmp_path: Path,
    *,
    exit_code: int = 0,
    name: str = "run_stub.sh",
    record_args_to: Path | None = None,
) -> Path:
    """Stub wrapper — same contract as scripts/run_*.sh. If `record_args_to`
    is given, the wrapper appends its full argv to that file each time it
    runs (one line per invocation). Used to verify the driver passes the
    right flags per framing."""
    wrapper = tmp_path / name
    lines = [
        "#!/usr/bin/env bash",
        "set -uo pipefail",
        'WORKDIR=""; RUN_DIR=""; PROMPT_FILE=""; MODEL=""',
    ]
    if record_args_to is not None:
        lines.append(f'echo "$@" >> {shlex.quote(str(record_args_to))}')
    lines += [
        "while [[ $# -gt 0 ]]; do",
        '  case "$1" in',
        '    --workdir)     WORKDIR="$2"; shift 2 ;;',
        '    --run-dir)     RUN_DIR="$2"; shift 2 ;;',
        '    --prompt-file) PROMPT_FILE="$2"; shift 2 ;;',
        '    --model)       MODEL="$2"; shift 2 ;;',
        "    *) shift ;;",
        "  esac",
        "done",
        'mkdir -p "$RUN_DIR"',
        'echo "stub" > "$RUN_DIR/stdout.log"',
        'echo "" > "$RUN_DIR/stderr.log"',
        'echo \'{"tool":"stub","binary":"/stub","version":"0.0.0"}\' > "$RUN_DIR/tool_info.json"',
        f"exit {exit_code}",
    ]
    wrapper.write_text("\n".join(lines) + "\n")
    wrapper.chmod(0o755)
    return wrapper


def _make_flaky_wrapper(tmp_path: Path, fail_first_n: int) -> Path:
    """Stub wrapper that records its invocation count in a sidecar file and
    exits non-zero for the first N calls, zero thereafter. Used to verify
    retry orchestration."""
    counter = tmp_path / "attempt_count.txt"
    counter.write_text("0")
    wrapper = tmp_path / "run_flaky.sh"
    lines = [
        "#!/usr/bin/env bash",
        "set -uo pipefail",
        'WORKDIR=""; RUN_DIR=""; PROMPT_FILE=""; MODEL=""',
        "while [[ $# -gt 0 ]]; do",
        '  case "$1" in',
        '    --workdir)     WORKDIR="$2"; shift 2 ;;',
        '    --run-dir)     RUN_DIR="$2"; shift 2 ;;',
        '    --prompt-file) PROMPT_FILE="$2"; shift 2 ;;',
        '    --model)       MODEL="$2"; shift 2 ;;',
        "    *) shift ;;",
        "  esac",
        "done",
        'mkdir -p "$RUN_DIR"',
        'echo "" > "$RUN_DIR/stdout.log"',
        'echo "" > "$RUN_DIR/stderr.log"',
        'echo \'{"tool":"stub","binary":"/s","version":"0"}\' > "$RUN_DIR/tool_info.json"',
        f"COUNTER={shlex.quote(str(counter))}",
        'N=$(cat "$COUNTER")',
        'echo $((N + 1)) > "$COUNTER"',
        f"if (( N < {fail_first_n} )); then",
        "  exit 7",  # arbitrary non-zero, non-timeout exit
        "else",
        "  exit 0",
        "fi",
    ]
    wrapper.write_text("\n".join(lines) + "\n")
    wrapper.chmod(0o755)
    return wrapper


def _matrix_cfg(tmp_path: Path, wrapper: Path, **overrides) -> MatrixConfig:
    mgr = WorktreeManager(cache_root=tmp_path / "cache")
    # Push the WorktreeManager + wrapper through runner_kwargs so run_once
    # uses the stub instead of the real scripts/run_*.sh.
    defaults = {
        "run_id": "test-matrix",
        "runs_root": tmp_path / "runs",
        "retries": 0,
        "graders": ["mock"],  # keep tests focused; the full grader set is
        # exercised in their own dedicated test files.
        "runner_kwargs": {
            "wrapper_override": wrapper,
            "worktree_manager": mgr,
        },
    }
    defaults.update(overrides)
    return MatrixConfig(**defaults)


# ----- configuration validation --------------------------------------------


def test_unsupported_tool_raises(tmp_path, tasks):
    wrapper = _make_stub_wrapper(tmp_path)
    cfg = _matrix_cfg(tmp_path, wrapper)
    with pytest.raises(DriverError, match="unsupported tools"):
        run_matrix(tasks, ["claude", "bard"], cfg)


# ----- matrix shape --------------------------------------------------------


def test_matrix_visits_every_cell(tmp_path, tasks):
    """2 tasks × 2 tools × 2 seeds = 8 cells."""
    wrapper = _make_stub_wrapper(tmp_path)
    cfg = _matrix_cfg(tmp_path, wrapper, seeds=[0, 1])
    result = run_matrix(tasks, ["claude", "copilot"], cfg)
    assert len(result.cells) == 8
    keys = {(c.task_id, c.tool, c.seed) for c in result.cells}
    expected = {
        (t.task_id, tool, seed) for t in tasks for tool in ("claude", "copilot") for seed in (0, 1)
    }
    assert keys == expected


def test_run_id_shared_across_cells(tmp_path, tasks):
    wrapper = _make_stub_wrapper(tmp_path)
    cfg = _matrix_cfg(tmp_path, wrapper)
    result = run_matrix(tasks, ["claude"], cfg)
    # The driver's chosen run_id appears in every cell's manifest path.
    for cell in result.cells:
        assert f"/{result.run_id}/" in str(cell.result.manifest_path)


def test_run_id_auto_generated_when_none(tmp_path, tasks):
    wrapper = _make_stub_wrapper(tmp_path)
    cfg = _matrix_cfg(tmp_path, wrapper, run_id=None)
    result = run_matrix(tasks[:1], ["claude"], cfg)
    # ISO timestamp format: YYYY-MM-DDTHH-MM-SS
    assert len(result.run_id) == 19
    assert result.run_id[10] == "T"


# ----- framing (derived from model presence) -------------------------------


def test_no_model_means_product_framing_no_model_flag(tmp_path, tasks):
    """When `model` is None the driver runs each tool with its default
    (no `--model` flag passed to the wrapper) and records framing='product'
    in the manifest."""
    args_log = tmp_path / "args.log"
    wrapper = _make_stub_wrapper(tmp_path, record_args_to=args_log)
    cfg = _matrix_cfg(tmp_path, wrapper, model=None)
    result = run_matrix(tasks[:1], ["claude"], cfg)
    captured = args_log.read_text()
    assert "--model" not in captured
    assert result.framing == "product"
    # Manifest also records the derived framing.
    m = json.loads(result.cells[0].result.manifest_path.read_text())
    assert m["framing"] == "product"


def test_model_set_means_harness_framing_with_shared_model(tmp_path, tasks):
    """When `model` is set the driver forces it on every tool's invocation
    and records framing='harness' in the manifest."""
    args_log = tmp_path / "args.log"
    wrapper = _make_stub_wrapper(tmp_path, record_args_to=args_log)
    cfg = _matrix_cfg(tmp_path, wrapper, model="claude-sonnet-4-6")
    result = run_matrix(tasks[:1], ["claude", "copilot"], cfg)
    captured = args_log.read_text().splitlines()
    # Both tools' invocations should carry --model claude-sonnet-4-6.
    assert len(captured) == 2
    for line in captured:
        assert "--model claude-sonnet-4-6" in line
    assert result.framing == "harness"
    for cell in result.cells:
        m = json.loads(cell.result.manifest_path.read_text())
        assert m["framing"] == "harness"
        assert m["model"] == "claude-sonnet-4-6"


def test_model_overrides_take_precedence_per_tool(tmp_path, tasks):
    """Per-tool override (e.g. copilot's dotted model name) wins over the
    shared default for that tool only. The other tool still gets the
    default. Real-world case: claude wants `claude-sonnet-4-6`, copilot
    wants `claude-sonnet-4.6`."""
    args_log = tmp_path / "args.log"
    wrapper = _make_stub_wrapper(tmp_path, record_args_to=args_log)
    cfg = _matrix_cfg(
        tmp_path,
        wrapper,
        model="claude-sonnet-4-6",
        model_overrides={"copilot": "claude-sonnet-4.6"},
    )
    result = run_matrix(tasks[:1], ["claude", "copilot"], cfg)
    lines = args_log.read_text().splitlines()
    assert len(lines) == 2

    # Exactly one invocation should carry the dashed name (claude's),
    # exactly one the dotted name (copilot's). Different lines.
    dashed = [line for line in lines if "--model claude-sonnet-4-6" in line]
    dotted = [line for line in lines if "--model claude-sonnet-4.6" in line]
    assert len(dashed) == 1, f"expected exactly one dashed-name invocation, got: {dashed}"
    assert len(dotted) == 1, f"expected exactly one dotted-name invocation, got: {dotted}"
    # Framing remains harness; manifest records the per-tool model.
    assert result.framing == "harness"
    by_tool = {cell.tool: cell for cell in result.cells}
    assert (
        json.loads(by_tool["claude"].result.manifest_path.read_text())["model"]
        == "claude-sonnet-4-6"
    )
    assert (
        json.loads(by_tool["copilot"].result.manifest_path.read_text())["model"]
        == "claude-sonnet-4.6"
    )


def test_model_overrides_without_default_still_harness(tmp_path, tasks):
    """If only --model-for is used (no --model default), every tool listed
    in the overrides gets its name; the matrix is still in harness
    framing if any model is set."""
    args_log = tmp_path / "args.log"
    wrapper = _make_stub_wrapper(tmp_path, record_args_to=args_log)
    cfg = _matrix_cfg(
        tmp_path,
        wrapper,
        model=None,
        model_overrides={"claude": "x", "copilot": "y"},
    )
    result = run_matrix(tasks[:1], ["claude", "copilot"], cfg)
    lines = args_log.read_text().splitlines()
    assert any("--model x" in line for line in lines)
    assert any("--model y" in line for line in lines)
    assert result.framing == "harness"


# ----- retries -------------------------------------------------------------


def test_no_retries_on_success(tmp_path, tasks):
    wrapper = _make_stub_wrapper(tmp_path, exit_code=0)
    cfg = _matrix_cfg(tmp_path, wrapper, retries=2)
    result = run_matrix(tasks[:1], ["claude"], cfg)
    assert result.cells[0].attempts == 1
    assert result.cells[0].retry_reasons == []


def test_transient_failure_retries_then_succeeds(tmp_path, tasks):
    """Wrapper fails twice (exit 7) then succeeds — driver should attempt
    3 times total and end with exit_code=0."""
    wrapper = _make_flaky_wrapper(tmp_path, fail_first_n=2)
    cfg = _matrix_cfg(tmp_path, wrapper, retries=2)
    result = run_matrix(tasks[:1], ["claude"], cfg)
    cell = result.cells[0]
    assert cell.attempts == 3
    assert len(cell.retry_reasons) == 2
    assert all("exit 7" in r for r in cell.retry_reasons)
    assert cell.result.exit_code == 0


def test_exhausted_retries_returns_last_failure(tmp_path, tasks):
    """Wrapper always fails — driver should attempt retries+1 times and
    record every reason."""
    wrapper = _make_flaky_wrapper(tmp_path, fail_first_n=999)
    cfg = _matrix_cfg(tmp_path, wrapper, retries=2)
    result = run_matrix(tasks[:1], ["claude"], cfg)
    cell = result.cells[0]
    assert cell.attempts == 3  # 1 initial + 2 retries
    assert len(cell.retry_reasons) == 3
    assert cell.result.exit_code == 7


def test_manifest_retries_field_updated_after_retries(tmp_path, tasks):
    """After the retry loop, the cell's manifest.json must reflect the
    final retries count + reasons — not the {0, []} the runner wrote
    initially."""
    wrapper = _make_flaky_wrapper(tmp_path, fail_first_n=1)
    cfg = _matrix_cfg(tmp_path, wrapper, retries=2)
    result = run_matrix(tasks[:1], ["claude"], cfg)
    cell = result.cells[0]
    m = json.loads(cell.result.manifest_path.read_text())
    assert m["retries"]["count"] == 1
    assert len(m["retries"]["reasons"]) == 1


# ----- crash / timeout handling --------------------------------------------


def test_missing_wrapper_doesnt_abort_matrix(tmp_path, tasks):
    """A wrapper-not-found error for the first cell should be captured
    but not stop the second cell."""
    good_wrapper = _make_stub_wrapper(tmp_path)
    cfg = _matrix_cfg(tmp_path, good_wrapper, retries=0)
    # Mutate runner_kwargs to point at a non-existent wrapper.
    cfg.runner_kwargs = {**(cfg.runner_kwargs or {})}
    cfg.runner_kwargs["wrapper_override"] = tmp_path / "does-not-exist.sh"
    result = run_matrix(tasks, ["claude"], cfg)
    assert len(result.cells) == 2
    assert all(cell.result is None for cell in result.cells)
    assert all("wrapper script not found" in (cell.crashed_with or "") for cell in result.cells)


# ----- helpers -------------------------------------------------------------


def test_matrix_result_to_dict_is_json_serializable(tmp_path, tasks):
    wrapper = _make_stub_wrapper(tmp_path)
    result = run_matrix(tasks[:1], ["claude"], _matrix_cfg(tmp_path, wrapper))
    payload = matrix_result_to_dict(result)
    # Must round-trip through json.
    text = json.dumps(payload)
    back = json.loads(text)
    assert back["run_id"] == result.run_id
    assert len(back["cells"]) == 1


def test_default_retries_is_two():
    assert DEFAULT_RETRIES == 2
    assert MatrixConfig().retries == 2


def test_cell_result_dataclass_basic():
    c = CellResult(
        task_id="t",
        tool="claude",
        seed=0,
        attempts=1,
        retry_reasons=[],
        result=None,
        crashed_with="boom",
    )
    assert c.crashed_with == "boom"


def test_matrix_result_iterable():
    m = MatrixResult(run_id="r", framing="product", cells=[])
    assert list(m) == []
