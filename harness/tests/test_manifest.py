"""Tests for the manifest schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from harness.manifest import (
    SCHEMA_VERSION,
    HostInfo,
    Manifest,
    RetryInfo,
    ToolInfo,
    WrapperInvocation,
    read_manifest,
    write_manifest,
)


def _minimal_manifest(**overrides) -> Manifest:
    defaults = dict(
        run_id="r1",
        task_id="t1",
        tool="claude",
        seed=0,
        framing="product",
        base_sha="0" * 40,
        repo_url="https://example/repo",
        started_at="2026-05-13T12:00:00+00:00",
        ended_at="2026-05-13T12:00:10+00:00",
        wall_clock_seconds=10.0,
        budget_seconds=900,
        exit_code=0,
        timed_out=False,
        wrapper=WrapperInvocation(path="/scripts/run_claude.sh", args=[]),
        host=HostInfo(
            system="Darwin", release="25.3.0", python_version="3.11.15", harness_version="0.0.1"
        ),
    )
    defaults.update(overrides)
    return Manifest(**defaults)


def test_minimal_manifest_round_trips(tmp_path: Path):
    m = _minimal_manifest()
    path = write_manifest(m, tmp_path / "manifest.json")
    loaded = read_manifest(path)
    assert loaded == m


def test_default_schema_version():
    assert _minimal_manifest().schema_version == "1.0" == SCHEMA_VERSION


def test_extra_fields_rejected(tmp_path: Path):
    payload = json.loads(write_manifest(_minimal_manifest(), tmp_path / "m.json").read_text())
    payload["surprise"] = "boom"
    (tmp_path / "m.json").write_text(json.dumps(payload))
    with pytest.raises(ValidationError, match="surprise"):
        read_manifest(tmp_path / "m.json")


def test_missing_required_field_rejected(tmp_path: Path):
    payload = json.loads(write_manifest(_minimal_manifest(), tmp_path / "m.json").read_text())
    del payload["base_sha"]
    (tmp_path / "m.json").write_text(json.dumps(payload))
    with pytest.raises(ValidationError, match="base_sha"):
        read_manifest(tmp_path / "m.json")


def test_tool_info_optional():
    m = _minimal_manifest(tool_info=None)
    assert m.tool_info is None


def test_tool_info_accepts_extra_fields():
    """ToolInfo is intentionally permissive (extra='allow') so wrapper additions
    don't break the manifest contract."""
    m = _minimal_manifest(
        tool_info=ToolInfo(tool="claude", binary="/c", version="2", **{"build_id": "abc"})
    )
    assert m.tool_info.tool == "claude"


def test_retries_defaults_to_zero_count():
    assert _minimal_manifest().retries == RetryInfo()


def test_step7_fields_have_defaults():
    m = _minimal_manifest()
    assert m.turn_count == 0
    assert m.event_count == 0
    assert m.events_path is None
    assert m.parse_error is None
