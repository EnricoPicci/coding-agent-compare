"""Tests for the single-run executor.

Uses a stub bash wrapper that mimics the scripts/run_*.sh contract so we
exercise the whole runner — worktree prep, subprocess spawn, signal cascade,
diff capture, manifest write — without touching the real CLIs.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

import pytest

from harness.runner import (
    DEFAULT_PROMPT_SUFFIX,
    RunConfig,
    RunnerError,
    run_once,
)
from harness.task import Task
from harness.worktree import WorktreeManager


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
    """A tiny bare repo to use as Task.repo_url. Returns (bare_path, sha)."""
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
def task(local_bare) -> Task:
    bare, sha = local_bare
    return Task(
        task_id="owner__repo-1",
        repo_url=f"file://{bare}",
        base_sha=sha,
        prompt="Solve the thing.",
        test_command="pytest",
    )


def _make_stub_wrapper(
    tmp_path: Path,
    *,
    exit_code: int = 0,
    sleep_seconds: float = 0.0,
    create_file: tuple[str, str] | None = ("HELLO.txt", "hi from stub\n"),
    name: str = "run_stub.sh",
) -> Path:
    """Write a stub wrapper that honors the same arg contract as run_*.sh.

    Optionally sleeps (to exercise the timeout path) and optionally creates a
    file in the workdir (to give the diff something to capture).

    Built as a list of lines (no dedent / heredoc) so that user-supplied
    payloads containing newlines can't perturb Python's indentation parsing.
    """
    wrapper = tmp_path / name
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
        '    *) echo "unknown arg: $1" >&2; exit 2 ;;',
        "  esac",
        "done",
        'mkdir -p "$RUN_DIR"',
        'echo "stub stdout" > "$RUN_DIR/stdout.log"',
        'echo "stub stderr" > "$RUN_DIR/stderr.log"',
        'echo \'{"tool":"stub","binary":"/stub","version":"0.0.0"}\' > "$RUN_DIR/tool_info.json"',
    ]
    if create_file is not None:
        fname, content = create_file
        # Content is shlex-quoted (arbitrary payload); the path must stay
        # double-quoted so the shell expands $WORKDIR. fname is test-controlled,
        # so direct interpolation is safe here.
        lines.append(f'printf "%b" {shlex.quote(content)} > "$WORKDIR/{fname}"')
    if sleep_seconds:
        lines.append(f"sleep {sleep_seconds}")
    lines += [
        f'printf "%d\\n" {exit_code} > "$RUN_DIR/exit_code"',
        'printf "%d\\n" 0 > "$RUN_DIR/wall_clock_seconds"',
        f"exit {exit_code}",
    ]
    wrapper.write_text("\n".join(lines) + "\n")
    wrapper.chmod(0o755)
    return wrapper


def _cfg(tmp_path: Path, wrapper: Path, **overrides) -> RunConfig:
    """Build a RunConfig that points at tmp dirs and the stub wrapper."""
    mgr = WorktreeManager(cache_root=tmp_path / "cache")
    return RunConfig(
        runs_root=tmp_path / "runs",
        run_id="test-run",
        wrapper_override=wrapper,
        worktree_manager=mgr,
        **overrides,
    )


def test_happy_path_produces_all_artifacts(tmp_path, task):
    wrapper = _make_stub_wrapper(tmp_path)
    result = run_once(task, "claude", 0, _cfg(tmp_path, wrapper))

    assert result.exit_code == 0
    assert not result.timed_out
    assert result.run_dir.exists()
    # All artifacts the contract promises:
    for name in [
        "prompt.txt",
        "stdout.log",
        "stderr.log",
        "exit_code",
        "wall_clock_seconds",
        "tool_info.json",
        "diff.patch",
        "manifest.json",
    ]:
        assert (result.run_dir / name).exists(), f"missing {name}"


def test_prompt_file_has_task_prompt_plus_suffix(tmp_path, task):
    wrapper = _make_stub_wrapper(tmp_path)
    result = run_once(task, "claude", 0, _cfg(tmp_path, wrapper))
    prompt = (result.run_dir / "prompt.txt").read_text()
    assert prompt.startswith(task.prompt)
    assert prompt.endswith(DEFAULT_PROMPT_SUFFIX)


def test_diff_captures_created_files(tmp_path, task):
    """The agent creating a new file must show up in diff.patch (stage-all)."""
    wrapper = _make_stub_wrapper(tmp_path, create_file=("NEW.txt", "agent created\n"))
    result = run_once(task, "claude", 0, _cfg(tmp_path, wrapper))
    diff = result.diff_path.read_text()
    assert "NEW.txt" in diff
    assert "agent created" in diff


def test_diff_is_empty_when_agent_does_nothing(tmp_path, task):
    wrapper = _make_stub_wrapper(tmp_path, create_file=None)
    result = run_once(task, "claude", 0, _cfg(tmp_path, wrapper))
    assert result.diff_path.read_text() == ""


def test_manifest_has_expected_fields(tmp_path, task):
    wrapper = _make_stub_wrapper(tmp_path)
    cfg = _cfg(tmp_path, wrapper, model="some-model", framing="harness")
    result = run_once(task, "claude", 7, cfg)
    m = json.loads(result.manifest_path.read_text())

    assert m["schema_version"] == "1.0"
    assert m["run_id"] == "test-run"
    assert m["task_id"] == task.task_id
    assert m["tool"] == "claude"
    assert m["seed"] == 7
    assert m["model"] == "some-model"
    assert m["framing"] == "harness"
    assert m["base_sha"] == task.base_sha
    assert m["exit_code"] == 0
    assert m["timed_out"] is False
    assert m["retries"] == {"count": 0, "reasons": []}
    assert m["tool_info"] == {"tool": "stub", "binary": "/stub", "version": "0.0.0"}
    assert "harness_version" in m["host"]
    assert m["wrapper"]["args"][0].endswith("run_stub.sh")


def test_non_zero_exit_is_propagated_not_retried(tmp_path, task):
    """Step 6 is single-attempt by design (retries deferred to Step 11)."""
    wrapper = _make_stub_wrapper(tmp_path, exit_code=3)
    result = run_once(task, "claude", 0, _cfg(tmp_path, wrapper))
    assert result.exit_code == 3
    assert not result.timed_out
    m = json.loads(result.manifest_path.read_text())
    assert m["exit_code"] == 3
    assert m["retries"] == {"count": 0, "reasons": []}


def test_timeout_triggers_sigterm_then_kill(tmp_path, task):
    """Sleep longer than the budget; expect timed_out=True and a short grace."""
    wrapper = _make_stub_wrapper(tmp_path, sleep_seconds=10)
    cfg = _cfg(tmp_path, wrapper, budget_seconds=1, sigterm_grace_seconds=1)
    result = run_once(task, "claude", 0, cfg)
    assert result.timed_out is True
    assert result.wall_clock_seconds < 5  # quickly killed, not waiting 10s
    m = json.loads(result.manifest_path.read_text())
    assert m["timed_out"] is True


def test_unknown_tool_raises(tmp_path, task):
    wrapper = _make_stub_wrapper(tmp_path)
    with pytest.raises(RunnerError, match="unsupported tool"):
        run_once(task, "bard", 0, _cfg(tmp_path, wrapper))


def test_missing_wrapper_raises(tmp_path, task):
    cfg = RunConfig(
        runs_root=tmp_path / "runs",
        run_id="test-run",
        wrapper_override=tmp_path / "does-not-exist.sh",
        worktree_manager=WorktreeManager(cache_root=tmp_path / "cache"),
    )
    with pytest.raises(RunnerError, match="wrapper script not found"):
        run_once(task, "claude", 0, cfg)


def test_run_dir_layout(tmp_path, task):
    """runs/<run-id>/<tool>/<task_id>/seed-<N>/ — locked-in convention."""
    wrapper = _make_stub_wrapper(tmp_path)
    result = run_once(task, "copilot", 2, _cfg(tmp_path, wrapper))
    expected = tmp_path / "runs" / "test-run" / "copilot" / task.task_id / "seed-2"
    assert result.run_dir == expected


def test_cleanup_removes_worktree(tmp_path, task):
    wrapper = _make_stub_wrapper(tmp_path)
    cfg = _cfg(tmp_path, wrapper, cleanup_worktree=True)
    result = run_once(task, "claude", 0, cfg)
    assert not (result.run_dir / "repo").exists()


def test_default_keep_preserves_worktree(tmp_path, task):
    wrapper = _make_stub_wrapper(tmp_path)
    result = run_once(task, "claude", 0, _cfg(tmp_path, wrapper))
    assert (result.run_dir / "repo").is_dir()


# ----- Step 7 integration: parser → events.jsonl → manifest fields ----------


def _make_claude_trace_wrapper(tmp_path: Path) -> Path:
    """Stub wrapper that writes a stdout.log matching claude's stream-json shape,
    so the runner exercises the parser path end-to-end."""
    events = [
        '{"type":"system","subtype":"init"}',
        '{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}',
        '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","id":"t1"}]}}',
        '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"t1"}]}}',
        '{"type":"assistant","message":{"content":[{"type":"text","text":"done"}]}}',
    ]
    wrapper = tmp_path / "run_claude_trace.sh"
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
        "    *) exit 2 ;;",
        "  esac",
        "done",
        'mkdir -p "$RUN_DIR"',
        "cat > \"$RUN_DIR/stdout.log\" <<'EOF'\n" + "\n".join(events) + "\nEOF",
        'echo "" > "$RUN_DIR/stderr.log"',
        'echo \'{"tool":"claude","binary":"/c","version":"x"}\' > "$RUN_DIR/tool_info.json"',
        "exit 0",
    ]
    wrapper.write_text("\n".join(lines) + "\n")
    wrapper.chmod(0o755)
    return wrapper


def test_run_once_emits_events_jsonl_and_derives_turn_count(tmp_path, task):
    """run_once should run the parser, write events.jsonl, and populate
    turn_count / event_count / events_path in the manifest."""
    wrapper = _make_claude_trace_wrapper(tmp_path)
    result = run_once(task, "claude", 0, _cfg(tmp_path, wrapper))

    events_jsonl = result.run_dir / "events.jsonl"
    assert events_jsonl.exists()
    lines = events_jsonl.read_text().splitlines()
    assert len(lines) == 4  # 2 messages + 1 tool_call + 1 tool_result

    m = json.loads(result.manifest_path.read_text())
    assert m["schema_version"] == "1.0"
    assert m["turn_count"] == 2  # two assistant text messages
    assert m["event_count"] == 4
    assert m["events_path"] == "events.jsonl"
    assert m["parse_error"] is None


def test_run_once_records_parse_error_without_failing(tmp_path, task, monkeypatch):
    """A parser exception should be captured in manifest.parse_error rather
    than failing the whole run."""
    import harness.parsers as parsers_mod

    def boom(_path):
        raise RuntimeError("synthetic parser failure")

    monkeypatch.setitem(parsers_mod._PARSERS, "claude", boom)

    wrapper = _make_stub_wrapper(tmp_path)
    result = run_once(task, "claude", 0, _cfg(tmp_path, wrapper))

    m = json.loads(result.manifest_path.read_text())
    assert m["parse_error"] is not None
    assert "synthetic parser failure" in m["parse_error"]
    assert m["events_path"] is None
    assert m["event_count"] == 0
