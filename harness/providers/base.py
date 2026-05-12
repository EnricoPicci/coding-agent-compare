"""Abstract TaskProvider protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from harness.task import Task


@runtime_checkable
class TaskProvider(Protocol):
    """Load Task instances, optionally filtered by task ID."""

    def load(self, task_ids: list[str] | None) -> list[Task]: ...
