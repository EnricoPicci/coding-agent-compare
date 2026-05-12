"""SWE-bench Verified task provider.

Loads task metadata from the public 'princeton-nlp/SWE-bench_Verified' HuggingFace
dataset and maps each row to a harness Task. We deliberately do NOT use the
official 'swebench' package: its evaluation runner is Docker-based and the
project's architectural decision is to keep the agent runtime Docker-free.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from harness.task import Task

DATASET_NAME = "princeton-nlp/SWE-bench_Verified"
DATASET_SPLIT = "test"


def load_task_ids_from_yaml(path: str | Path) -> list[str]:
    """Read a smoke-list YAML and return its `task_ids` array."""
    with Path(path).open() as f:
        data = yaml.safe_load(f) or {}
    task_ids = data.get("task_ids", [])
    if not isinstance(task_ids, list) or not all(isinstance(x, str) for x in task_ids):
        raise ValueError(f"{path}: 'task_ids' must be a list of strings")
    return task_ids


def _parse_test_list(raw: Any) -> list[str]:
    """SWE-bench encodes FAIL_TO_PASS / PASS_TO_PASS as JSON strings."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if isinstance(raw, str):
        return [str(x) for x in json.loads(raw)]
    raise TypeError(f"unexpected test-list type: {type(raw).__name__}")


def row_to_task(row: dict[str, Any]) -> Task:
    """Map a SWE-bench Verified row to a harness Task."""
    repo = row["repo"]
    return Task(
        task_id=row["instance_id"],
        repo_url=f"https://github.com/{repo}",
        base_sha=row["base_commit"],
        prompt=row["problem_statement"],
        # Step-9 grader will refine this using FAIL_TO_PASS / PASS_TO_PASS.
        test_command="python -m pytest",
        fail_to_pass=_parse_test_list(row.get("FAIL_TO_PASS")),
        pass_to_pass=_parse_test_list(row.get("PASS_TO_PASS")),
        expected_changed_files=None,
        metadata={
            "repo": repo,
            "patch": row.get("patch", ""),
            "test_patch": row.get("test_patch", ""),
            "environment_setup_commit": row.get("environment_setup_commit", ""),
            "version": row.get("version", ""),
            "created_at": row.get("created_at", ""),
        },
    )


class SWEBenchVerifiedProvider:
    """Provider that yields SWE-bench Verified instances as Task objects."""

    def __init__(self, dataset_name: str = DATASET_NAME, split: str = DATASET_SPLIT) -> None:
        self.dataset_name = dataset_name
        self.split = split

    def load(self, task_ids: list[str] | None) -> list[Task]:
        # Import inside the method so unit tests that don't exercise this path
        # can run without the heavy 'datasets' import.
        from datasets import load_dataset

        ds = load_dataset(self.dataset_name, split=self.split)

        wanted: set[str] | None = set(task_ids) if task_ids else None
        tasks: list[Task] = []
        for row in ds:
            if wanted is not None and row["instance_id"] not in wanted:
                continue
            tasks.append(row_to_task(row))

        if wanted is not None:
            found = {t.task_id for t in tasks}
            missing = wanted - found
            if missing:
                raise LookupError(f"task IDs not found in {self.dataset_name}: {sorted(missing)}")
        return tasks
