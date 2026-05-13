"""Tests for the per-tool trace parsers.

Each parser is fed a tiny handcrafted JSONL fixture mimicking the shape of
the real tool's output, then we assert the normalized events come out the
way downstream graders expect. The shapes are derived from real step6-verify
traces, with the obvious cruft (rate_limit_event, session.skills_loaded, ...)
dropped.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.parsers import get_parser
from harness.parsers.base import NormalizedEvent
from harness.parsers.claude import parse_trace as parse_claude
from harness.parsers.copilot import parse_trace as parse_copilot


def _write_jsonl(path: Path, events: list[dict]) -> Path:
    with open(path, "w") as fp:
        for e in events:
            fp.write(json.dumps(e) + "\n")
    return path


# ----- Claude --------------------------------------------------------------


def test_claude_parses_text_message(tmp_path: Path):
    log = _write_jsonl(
        tmp_path / "stdout.log",
        [
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Reading the code now."}]},
            },
        ],
    )
    events = parse_claude(log)
    assert len(events) == 1
    assert events[0].kind == "message"
    assert events[0].role == "assistant"
    assert events[0].text == "Reading the code now."
    assert events[0].raw_type == "assistant"


def test_claude_parses_tool_call(tmp_path: Path):
    log = _write_jsonl(
        tmp_path / "stdout.log",
        [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Bash", "id": "tu_1", "input": {"cmd": "ls"}}
                    ]
                },
            },
        ],
    )
    events = parse_claude(log)
    assert len(events) == 1
    assert events[0].kind == "tool_call"
    assert events[0].tool_name == "Bash"


def test_claude_parses_tool_result(tmp_path: Path):
    log = _write_jsonl(
        tmp_path / "stdout.log",
        [
            {
                "type": "user",
                "message": {
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tu_1", "content": "stdout..."}
                    ]
                },
            },
        ],
    )
    events = parse_claude(log)
    assert len(events) == 1
    assert events[0].kind == "tool_result"


def test_claude_mixed_assistant_block_splits_into_two_events(tmp_path: Path):
    """An assistant turn that says 'I'll run this' and then issues a tool call
    should produce one message + one tool_call event, in order."""
    log = _write_jsonl(
        tmp_path / "stdout.log",
        [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "I'll run the tests."},
                        {"type": "tool_use", "name": "Bash", "id": "tu_2", "input": {}},
                    ]
                },
            },
        ],
    )
    events = parse_claude(log)
    assert [e.kind for e in events] == ["message", "tool_call"]
    assert events[0].text == "I'll run the tests."
    assert events[1].tool_name == "Bash"


def test_claude_ignores_system_and_rate_limit_events(tmp_path: Path):
    log = _write_jsonl(
        tmp_path / "stdout.log",
        [
            {"type": "system", "subtype": "init", "tools": ["Bash"]},
            {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed"}},
        ],
    )
    assert parse_claude(log) == []


def test_claude_result_error_becomes_error_event(tmp_path: Path):
    log = _write_jsonl(
        tmp_path / "stdout.log",
        [
            {"type": "result", "is_error": True, "result": "boom", "num_turns": 0},
        ],
    )
    events = parse_claude(log)
    assert len(events) == 1
    assert events[0].kind == "error"
    assert "boom" in (events[0].text or "")


def test_claude_skips_malformed_lines(tmp_path: Path):
    log = tmp_path / "stdout.log"
    log.write_text(
        '{"type": "assistant", "message": {"content": [{"type":"text","text":"ok"}]}}\n'
        "not-json\n"
        "\n"  # blank line
        '{"type":"assistant","message":{"content":[{"type":"text","text":"two"}]}}\n'
    )
    events = parse_claude(log)
    assert [e.text for e in events] == ["ok", "two"]


def test_claude_missing_file_returns_empty(tmp_path: Path):
    assert parse_claude(tmp_path / "does-not-exist.log") == []


# ----- Copilot -------------------------------------------------------------


def test_copilot_parses_assistant_message(tmp_path: Path):
    log = _write_jsonl(
        tmp_path / "stdout.log",
        [
            {"type": "assistant.message", "data": {"text": "Let me look."}},
        ],
    )
    events = parse_copilot(log)
    assert len(events) == 1
    assert events[0].kind == "message"
    assert events[0].role == "assistant"
    assert events[0].text == "Let me look."


def test_copilot_parses_user_message(tmp_path: Path):
    log = _write_jsonl(
        tmp_path / "stdout.log",
        [
            {"type": "user.message", "data": {"text": "fix the bug"}},
        ],
    )
    events = parse_copilot(log)
    assert events[0].kind == "message"
    assert events[0].role == "user"


def test_copilot_parses_tool_call_and_result(tmp_path: Path):
    log = _write_jsonl(
        tmp_path / "stdout.log",
        [
            {"type": "tool.execution_start", "data": {"toolName": "shell"}},
            {"type": "tool.execution_complete", "data": {"toolName": "shell"}},
        ],
    )
    events = parse_copilot(log)
    assert [e.kind for e in events] == ["tool_call", "tool_result"]
    assert all(e.tool_name == "shell" for e in events)


def test_copilot_drops_deltas_and_session_events(tmp_path: Path):
    log = _write_jsonl(
        tmp_path / "stdout.log",
        [
            {"type": "session.mcp_servers_loaded", "data": {}},
            {"type": "session.skills_loaded", "data": {}},
            {"type": "assistant.turn_start", "data": {}},
            {"type": "assistant.message_delta", "data": {"text": "chunk1"}},
            {"type": "assistant.message_delta", "data": {"text": "chunk2"}},
            {"type": "assistant.reasoning", "data": {"text": "thinking..."}},
            {"type": "assistant.message", "data": {"text": "final answer"}},
            {"type": "assistant.turn_end", "data": {}},
        ],
    )
    events = parse_copilot(log)
    # Only the final assistant.message survives normalization.
    assert len(events) == 1
    assert events[0].kind == "message"
    assert events[0].text == "final answer"


def test_copilot_abort_becomes_error(tmp_path: Path):
    log = _write_jsonl(
        tmp_path / "stdout.log",
        [
            {"type": "abort", "data": {"reason": "wall-clock exceeded"}},
        ],
    )
    events = parse_copilot(log)
    assert events[0].kind == "error"
    assert "wall-clock" in (events[0].text or "")


def test_copilot_text_extraction_handles_content_list(tmp_path: Path):
    """Some Copilot releases emit `data.content = [{type, text}, ...]`."""
    log = _write_jsonl(
        tmp_path / "stdout.log",
        [
            {
                "type": "assistant.message",
                "data": {
                    "content": [
                        {"type": "text", "text": "part one"},
                        {"type": "text", "text": "part two"},
                    ]
                },
            },
        ],
    )
    events = parse_copilot(log)
    assert events[0].text == "part one\npart two"


def test_copilot_skips_malformed_lines(tmp_path: Path):
    log = tmp_path / "stdout.log"
    log.write_text(
        '{"type":"assistant.message","data":{"text":"ok"}}\n'
        "garbage\n"
        '{"type":"assistant.message","data":{"text":"two"}}\n'
    )
    events = parse_copilot(log)
    assert [e.text for e in events] == ["ok", "two"]


# ----- registry ------------------------------------------------------------


def test_get_parser_dispatches_by_tool():
    assert get_parser("claude") is parse_claude
    assert get_parser("copilot") is parse_copilot


def test_get_parser_unknown_tool_raises():
    with pytest.raises(KeyError, match="bard"):
        get_parser("bard")


# ----- end-to-end against real step6-verify traces -------------------------


@pytest.mark.parametrize("tool", ["claude", "copilot"])
def test_real_step6_trace_parses_without_error(tool: str):
    """If step6-verify artifacts are present on disk, the parsers should
    handle them without raising. Skip otherwise so this isn't a CI dependency."""
    log = (
        Path(__file__).parents[2]
        / "runs"
        / "step6-verify"
        / tool
        / "psf__requests-1142"
        / "seed-0"
        / "stdout.log"
    )
    if not log.exists():
        pytest.skip(f"no live trace at {log}")
    events = get_parser(tool)(log)
    assert all(isinstance(e, NormalizedEvent) for e in events)
