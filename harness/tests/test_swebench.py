"""Tests for the SWE-bench Verified provider — no network access."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.providers.swebench import (
    SWEBenchVerifiedProvider,
    _parse_test_list,
    load_task_ids_from_yaml,
    row_to_task,
)


def _fake_row(instance_id: str = "owner__repo-1") -> dict:
    return {
        "instance_id": instance_id,
        "repo": "owner/repo",
        "base_commit": "abc123def456abc123def456abc123def456abc1",
        "problem_statement": "first line\n\nmore detail",
        "patch": "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n",
        "test_patch": "diff --git a/tests/test_x.py b/tests/test_x.py\n",
        "environment_setup_commit": "fff000",
        "version": "1.0",
        "created_at": "2024-01-01T00:00:00",
        "FAIL_TO_PASS": '["tests/test_x.py::test_a"]',
        "PASS_TO_PASS": '["tests/test_x.py::test_b", "tests/test_x.py::test_c"]',
    }


def test_row_to_task_maps_required_fields():
    task = row_to_task(_fake_row())
    assert task.task_id == "owner__repo-1"
    assert task.repo_url == "https://github.com/owner/repo"
    assert task.base_sha == "abc123def456abc123def456abc123def456abc1"
    assert task.prompt.startswith("first line")
    assert task.fail_to_pass == ["tests/test_x.py::test_a"]
    assert task.pass_to_pass == ["tests/test_x.py::test_b", "tests/test_x.py::test_c"]
    assert task.metadata["repo"] == "owner/repo"
    assert task.metadata["patch"].startswith("diff --git")


def test_parse_test_list_handles_json_strings():
    assert _parse_test_list('["a", "b"]') == ["a", "b"]


def test_parse_test_list_handles_lists():
    assert _parse_test_list(["a", "b"]) == ["a", "b"]


def test_parse_test_list_handles_empty():
    assert _parse_test_list(None) == []
    assert _parse_test_list("") == []


def test_provider_filters_by_task_ids(monkeypatch):
    rows = [_fake_row("a-1"), _fake_row("b-2"), _fake_row("c-3")]
    monkeypatch.setattr(
        "harness.providers.swebench.load_dataset", lambda *a, **kw: iter(rows), raising=False
    )
    # Patch the imported binding inside the load method.

    def fake_load_dataset(*args, **kwargs):
        return rows

    import datasets

    monkeypatch.setattr(datasets, "load_dataset", fake_load_dataset)

    provider = SWEBenchVerifiedProvider()
    got = provider.load(["a-1", "c-3"])
    assert sorted(t.task_id for t in got) == ["a-1", "c-3"]


def test_provider_raises_on_missing_task_ids(monkeypatch):
    rows = [_fake_row("a-1")]
    import datasets

    monkeypatch.setattr(datasets, "load_dataset", lambda *a, **kw: rows)

    provider = SWEBenchVerifiedProvider()
    with pytest.raises(LookupError, match="not found"):
        provider.load(["a-1", "missing-99"])


def test_load_task_ids_from_yaml(tmp_path: Path):
    f = tmp_path / "smoke.yaml"
    f.write_text("task_ids:\n  - one\n  - two\n  - three\n")
    assert load_task_ids_from_yaml(f) == ["one", "two", "three"]


def test_load_task_ids_from_yaml_rejects_non_strings(tmp_path: Path):
    f = tmp_path / "bad.yaml"
    f.write_text("task_ids:\n  - one\n  - 42\n")
    with pytest.raises(ValueError, match="list of strings"):
        load_task_ids_from_yaml(f)


def test_load_task_ids_from_yaml_handles_empty(tmp_path: Path):
    f = tmp_path / "empty.yaml"
    f.write_text("")
    assert load_task_ids_from_yaml(f) == []


# Marker 'integration': this test hits the real HF dataset and adds ~3s per run
# (the cost is the 'datasets' library import, not the iteration). Kept in the
# main suite for now because catching schema drift is worth the cost. To exclude
# it when speed matters, run:  uv run pytest harness/ -m "not integration"
# To exclude it permanently from default runs, add `addopts = "-m 'not integration'"`
# to [tool.pytest.ini_options] in pyproject.toml.
@pytest.mark.integration
def test_smoke_tasks_load_from_real_dataset():
    smoke_yaml = Path(__file__).parents[2] / "tasks" / "swebench_smoke.yaml"
    task_ids = load_task_ids_from_yaml(smoke_yaml)
    assert task_ids, "tasks/swebench_smoke.yaml is unexpectedly empty"

    tasks = SWEBenchVerifiedProvider().load(task_ids)
    assert len(tasks) == len(task_ids)
    by_id = {t.task_id: t for t in tasks}
    for tid in task_ids:
        t = by_id[tid]
        assert t.repo_url.startswith("https://github.com/")
        assert len(t.base_sha) == 40, f"{tid}: base_sha is not a full 40-char SHA"
        assert t.prompt, f"{tid}: problem_statement was empty"
        assert isinstance(t.fail_to_pass, list)
        assert isinstance(t.pass_to_pass, list)
        assert t.metadata.get("patch"), f"{tid}: gold patch was empty"
