"""Single-run executor: drives one (task, tool, seed) end-to-end.

Step 6 of the plan. Prepares a fresh worktree, invokes the tool wrapper with
a wall-clock budget enforced via SIGTERM → grace → SIGKILL on the wrapper's
process group, captures the agent's diff, and writes a manifest stub. Step 7
fleshes out the manifest with parsed trace fields; Step 11's driver owns
retry orchestration. This module is single-attempt.

POSIX-only: signals + start_new_session. The repo is bash-required anyway
(scripts/run_*.sh), so this constraint is consistent with the rest of the
harness. Windows users go through Git Bash / WSL.
"""

from __future__ import annotations

import json
import os
import platform
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from harness import __version__
from harness.manifest import (
    HostInfo,
    Manifest,
    RetryInfo,
    ToolInfo,
    WrapperInvocation,
    write_manifest,
)
from harness.parsers import NormalizedEvent, get_parser
from harness.task import Task
from harness.worktree import WorktreeManager

SUPPORTED_TOOLS = ("claude", "copilot")
DEFAULT_PROMPT_SUFFIX = "\n\nFix this; ensure tests pass."
DEFAULT_BUDGET_SECONDS = 15 * 60  # 15 min, matches plan
DEFAULT_SIGTERM_GRACE_SECONDS = 30


class RunnerError(RuntimeError):
    """Raised for any unrecoverable failure inside run_once."""


@dataclass
class RunConfig:
    runs_root: Path = Path("runs")
    run_id: str | None = None
    budget_seconds: int = DEFAULT_BUDGET_SECONDS
    sigterm_grace_seconds: int = DEFAULT_SIGTERM_GRACE_SECONDS
    model: str | None = None
    framing: str = "product"  # "product" | "harness"
    prompt_suffix: str = DEFAULT_PROMPT_SUFFIX
    cleanup_worktree: bool = False
    # Optional override for the wrapper script path (tests use this).
    wrapper_override: Path | None = None
    # Optional override for the WorktreeManager (tests use this).
    worktree_manager: WorktreeManager | None = None


@dataclass
class RunResult:
    run_id: str
    run_dir: Path
    task_id: str
    tool: str
    seed: int
    exit_code: int
    wall_clock_seconds: float
    timed_out: bool
    started_at: str
    ended_at: str
    diff_path: Path
    manifest_path: Path


def run_once(task: Task, tool: str, seed: int, config: RunConfig | None = None) -> RunResult:
    """Run one (task, tool, seed) end-to-end. See module docstring."""
    if tool not in SUPPORTED_TOOLS:
        raise RunnerError(f"unsupported tool {tool!r}; expected one of {SUPPORTED_TOOLS}")
    cfg = config or RunConfig()

    run_id = cfg.run_id or _new_run_id()
    run_dir = Path(cfg.runs_root) / run_id / tool / task.task_id / f"seed-{seed}"
    run_dir.mkdir(parents=True, exist_ok=True)

    wrapper = cfg.wrapper_override or _wrapper_path(tool)
    if not wrapper.exists():
        raise RunnerError(f"wrapper script not found: {wrapper}")

    mgr = cfg.worktree_manager or WorktreeManager()
    worktree = mgr.prepare(task, run_dir)

    prompt_text = task.prompt + cfg.prompt_suffix
    prompt_file = run_dir / "prompt.txt"
    prompt_file.write_text(prompt_text)

    cli_args: list[str] = [
        str(wrapper),
        "--workdir",
        str(worktree),
        "--run-dir",
        str(run_dir),
        "--prompt-file",
        str(prompt_file),
    ]
    if cfg.model:
        cli_args += ["--model", cfg.model]

    started_at = _utc_now_iso()
    t0 = time.monotonic()
    exit_code, timed_out = _spawn_with_deadline(
        cli_args, cfg.budget_seconds, cfg.sigterm_grace_seconds
    )
    wall_clock = time.monotonic() - t0
    ended_at = _utc_now_iso()

    diff_path = _capture_diff(worktree, task.base_sha, run_dir)
    events, parse_error = _parse_trace_safe(tool, run_dir / "stdout.log")
    events_path = _write_events_jsonl(run_dir, events) if events else None
    manifest_path = _write_run_manifest(
        run_dir=run_dir,
        run_id=run_id,
        task=task,
        tool=tool,
        seed=seed,
        cfg=cfg,
        cli_args=cli_args,
        started_at=started_at,
        ended_at=ended_at,
        wall_clock_seconds=wall_clock,
        exit_code=exit_code,
        timed_out=timed_out,
        wrapper_path=wrapper,
        events=events,
        events_path=events_path,
        parse_error=parse_error,
    )

    if cfg.cleanup_worktree:
        mgr.cleanup(worktree)

    return RunResult(
        run_id=run_id,
        run_dir=run_dir,
        task_id=task.task_id,
        tool=tool,
        seed=seed,
        exit_code=exit_code,
        wall_clock_seconds=wall_clock,
        timed_out=timed_out,
        started_at=started_at,
        ended_at=ended_at,
        diff_path=diff_path,
        manifest_path=manifest_path,
    )


# ----- internals -----------------------------------------------------------


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _wrapper_path(tool: str) -> Path:
    # harness/runner.py → harness/ → repo root → scripts/run_<tool>.sh
    return Path(__file__).resolve().parents[1] / "scripts" / f"run_{tool}.sh"


def _spawn_with_deadline(
    cli_args: list[str], budget_seconds: int, sigterm_grace_seconds: int
) -> tuple[int, bool]:
    """Run the wrapper as its own process group; enforce wall-clock budget.

    Returns (exit_code, timed_out). On timeout, sends SIGTERM to the whole
    process group, waits `sigterm_grace_seconds`, then SIGKILL if still alive.
    """
    proc = subprocess.Popen(cli_args, start_new_session=True)
    try:
        return proc.wait(timeout=budget_seconds), False
    except subprocess.TimeoutExpired:
        pgid = os.getpgid(proc.pid)
        _signal_group_safe(pgid, signal.SIGTERM)
        try:
            return proc.wait(timeout=sigterm_grace_seconds), True
        except subprocess.TimeoutExpired:
            _signal_group_safe(pgid, signal.SIGKILL)
            return proc.wait(), True


def _signal_group_safe(pgid: int, sig: signal.Signals) -> None:
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass  # process group already gone


def _capture_diff(worktree: Path, base_sha: str, run_dir: Path) -> Path:
    """Stage everything in the worktree, then diff against base into diff.patch.

    Stage-all (`git add -A`) is what makes new files the agent created visible
    in the diff. `git diff --cached <base>` is the canonical patch form.
    """
    diff_path = run_dir / "diff.patch"
    subprocess.run(
        ["git", "-C", str(worktree), "add", "-A"],
        check=False,
        capture_output=True,
    )
    with open(diff_path, "wb") as fp:
        subprocess.run(
            ["git", "-C", str(worktree), "diff", "--cached", base_sha, "--"],
            stdout=fp,
            stderr=subprocess.PIPE,
            check=False,
        )
    return diff_path


def _parse_trace_safe(tool: str, stdout_log: Path) -> tuple[list[NormalizedEvent], str | None]:
    """Run the per-tool parser. Tolerant — a parser bug or trace drift records
    the error in the manifest instead of failing the whole run."""
    try:
        parser = get_parser(tool)
        events = parser(stdout_log)
        return events, None
    except Exception as exc:  # noqa: BLE001 — parser surface is uncontrolled
        return [], f"{type(exc).__name__}: {exc}"


def _write_events_jsonl(run_dir: Path, events: list[NormalizedEvent]) -> Path:
    """Write one JSON object per line. Stable schema = NormalizedEvent."""
    path = run_dir / "events.jsonl"
    with open(path, "w") as fp:
        for e in events:
            fp.write(e.model_dump_json() + "\n")
    return path


def _write_run_manifest(
    *,
    run_dir: Path,
    run_id: str,
    task: Task,
    tool: str,
    seed: int,
    cfg: RunConfig,
    cli_args: list[str],
    started_at: str,
    ended_at: str,
    wall_clock_seconds: float,
    exit_code: int,
    timed_out: bool,
    wrapper_path: Path,
    events: list[NormalizedEvent],
    events_path: Path | None,
    parse_error: str | None,
) -> Path:
    """Build a validated Manifest and write it to <run_dir>/manifest.json."""
    tool_info_dict = _read_tool_info(run_dir)
    tool_info = ToolInfo.model_validate(tool_info_dict) if tool_info_dict else None

    turn_count = sum(1 for e in events if e.kind == "message" and e.role == "assistant")

    manifest = Manifest(
        run_id=run_id,
        task_id=task.task_id,
        tool=tool,
        tool_info=tool_info,
        seed=seed,
        model=cfg.model,
        framing=cfg.framing,
        base_sha=task.base_sha,
        repo_url=task.repo_url,
        started_at=started_at,
        ended_at=ended_at,
        wall_clock_seconds=round(wall_clock_seconds, 3),
        budget_seconds=cfg.budget_seconds,
        exit_code=exit_code,
        timed_out=timed_out,
        retries=RetryInfo(),  # Step 11 will populate
        turn_count=turn_count,
        event_count=len(events),
        events_path=events_path.name if events_path else None,
        parse_error=parse_error,
        wrapper=WrapperInvocation(path=str(wrapper_path), args=cli_args),
        host=HostInfo(
            system=platform.system(),
            release=platform.release(),
            python_version=sys.version.split()[0],
            harness_version=__version__,
        ),
    )
    return write_manifest(manifest, run_dir / "manifest.json")


def _read_tool_info(run_dir: Path) -> dict | None:
    """Read the wrapper's tool_info.json if present. Tolerant — missing or
    malformed payloads return None rather than failing the whole run."""
    info_path = run_dir / "tool_info.json"
    if not info_path.exists():
        return None
    try:
        return json.loads(info_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


# Make RunResult JSON-friendly for callers that want to log it.
def run_result_to_dict(r: RunResult) -> dict:
    d = asdict(r)
    d["run_dir"] = str(r.run_dir)
    d["diff_path"] = str(r.diff_path)
    d["manifest_path"] = str(r.manifest_path)
    return d
