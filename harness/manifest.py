"""Run manifest schema + serialization.

Step 7. Replaces the inline manifest dict that Step 6 produced (`schema_version
= "step6-stub"`); bumps to `"1.0"` with parser-derived fields included
(`turn_count`, `event_count`, normalized event paths).

Pydantic v2 is the chosen validator (deviation from "pragmatic-start minimize
deps" — flagged in the plan). Strict on read (`model_validate`), permissive
on write (we control the writers). `extra="forbid"` catches typos that would
otherwise silently land in JSON.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"


class ToolInfo(BaseModel):
    model_config = {"extra": "allow"}  # forward-compat with new wrapper fields
    tool: str
    binary: str
    version: str


class RetryInfo(BaseModel):
    model_config = {"extra": "forbid"}
    count: int = 0
    reasons: list[str] = Field(default_factory=list)


class HostInfo(BaseModel):
    model_config = {"extra": "forbid"}
    system: str
    release: str
    python_version: str
    harness_version: str


class WrapperInvocation(BaseModel):
    model_config = {"extra": "forbid"}
    path: str
    args: list[str]


class Manifest(BaseModel):
    """The full per-run manifest. Schema version 1.0."""

    model_config = {"extra": "forbid"}

    schema_version: str = SCHEMA_VERSION
    run_id: str
    task_id: str
    tool: str
    tool_info: ToolInfo | None = None
    seed: int
    model: str | None = None
    framing: str  # "product" | "harness"
    base_sha: str
    repo_url: str

    started_at: str
    ended_at: str
    wall_clock_seconds: float
    budget_seconds: int

    exit_code: int
    timed_out: bool
    retries: RetryInfo = Field(default_factory=RetryInfo)

    # Step 7 additions:
    turn_count: int = Field(
        default=0,
        description='count of normalized "message" events with role="assistant"',
    )
    event_count: int = Field(
        default=0,
        description="total normalized events in events.jsonl",
    )
    events_path: str | None = Field(
        default=None,
        description="run-dir-relative path to events.jsonl, or null if parse failed",
    )
    parse_error: str | None = Field(
        default=None,
        description="captured stringified parser error, if any; null on success",
    )

    wrapper: WrapperInvocation
    host: HostInfo


def write_manifest(manifest: Manifest, path: Path) -> Path:
    """Serialize a Manifest to JSON. The caller picks the path so tests can
    redirect; the runner writes to `<run_dir>/manifest.json`."""
    path.write_text(manifest.model_dump_json(indent=2) + "\n")
    return path


def read_manifest(path: Path) -> Manifest:
    """Load a manifest and validate it strictly. Raises ValidationError on
    schema drift — that is the contract."""
    return Manifest.model_validate_json(path.read_text())


def manifest_from_dict(d: dict[str, Any]) -> Manifest:
    """Construct a Manifest from a dict (for callers that build the payload
    field-by-field). Same strict validation as `read_manifest`."""
    return Manifest.model_validate(d)
