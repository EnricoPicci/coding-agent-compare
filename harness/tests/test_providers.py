"""Smoke tests for the TaskProvider protocol."""

from harness.providers import TaskProvider
from harness.task import Task


class _StubProvider:
    def load(self, task_ids: list[str] | None) -> list[Task]:
        return []


def test_stub_is_recognized_as_task_provider():
    assert isinstance(_StubProvider(), TaskProvider)


def test_non_provider_is_rejected():
    class _NotAProvider:
        pass

    assert not isinstance(_NotAProvider(), TaskProvider)
