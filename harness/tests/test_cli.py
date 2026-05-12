"""Tests for the CLI parser — no provider work, no network."""

from __future__ import annotations

import pytest

from harness.cli import build_parser, main


def test_parser_help_does_not_raise():
    parser = build_parser()
    # SystemExit is what argparse raises after printing help with --help.
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["--help"])
    assert excinfo.value.code == 0


def test_parser_no_args_returns_zero(capsys):
    rc = main([])
    assert rc == 0
    captured = capsys.readouterr()
    assert "usage" in captured.out.lower()


def test_tasks_list_requires_provider():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["tasks", "list"])


def test_tasks_list_accepts_swebench(monkeypatch):
    # Stub the provider so we don't hit the network.
    import harness.providers.swebench as swb

    class _StubProvider:
        def __init__(self, *a, **kw):
            pass

        def load(self, task_ids):
            return []

    monkeypatch.setattr(swb, "SWEBenchVerifiedProvider", _StubProvider)
    rc = main(["tasks", "list", "--provider", "swebench"])
    assert rc == 0
