"""Parse Claude Code's stream-json trace into normalized events.

The stream-json format emits one JSON event per line. Top-level `type` values
we care about:

  - `assistant`  — assistant turn; `message.content` is a list of blocks,
                   each either `{"type":"text","text":...}` or
                   `{"type":"tool_use","name":...,"id":..., ...}`.
  - `user`       — user message; content is a list of blocks, typically
                   `{"type":"tool_result","tool_use_id":...,"content":...}`
                   or plain text.
  - `result`     — final summary; carries `is_error` and `num_turns`.

We ignore `system/init`, `rate_limit_event`, and other infra events — they
are not part of the assistant↔user conversation that downstream graders care
about.
"""

from __future__ import annotations

import json
from pathlib import Path

from harness.parsers import register
from harness.parsers.base import NormalizedEvent


def parse_trace(stdout_log: Path) -> list[NormalizedEvent]:
    events: list[NormalizedEvent] = []
    for seq, line in enumerate(_iter_jsonl(stdout_log)):
        events.extend(_translate(seq, line))
    return events


def _iter_jsonl(path: Path):
    """Yield parsed JSON objects from a JSONL file. Tolerates blank lines and
    malformed lines (truncated trace from a SIGKILL'd process is common)."""
    if not path.exists():
        return
    with open(path) as fp:
        for raw in fp:
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                continue


def _translate(seq: int, e: dict) -> list[NormalizedEvent]:
    """Map one raw event to zero-or-more NormalizedEvents."""
    t = e.get("type")
    if t == "assistant":
        return _translate_assistant(seq, e)
    if t == "user":
        return _translate_user(seq, e)
    if t == "result":
        if e.get("is_error"):
            return [
                NormalizedEvent(
                    seq=seq,
                    kind="error",
                    raw_type="result",
                    text=str(e.get("result") or e.get("api_error_status") or ""),
                )
            ]
        return []  # successful result has no normalized event of its own
    return []


def _translate_assistant(seq: int, e: dict) -> list[NormalizedEvent]:
    msg = e.get("message", {})
    content = msg.get("content") or []
    out: list[NormalizedEvent] = []
    # An assistant turn can mix text and tool_use blocks; emit each as its own
    # normalized event so downstream consumers can iterate without re-walking.
    for block in content:
        btype = block.get("type")
        if btype == "text":
            text = block.get("text") or ""
            if text:
                out.append(
                    NormalizedEvent(
                        seq=seq,
                        kind="message",
                        role="assistant",
                        text=text,
                        raw_type="assistant",
                    )
                )
        elif btype == "tool_use":
            out.append(
                NormalizedEvent(
                    seq=seq,
                    kind="tool_call",
                    tool_name=block.get("name"),
                    raw_type="assistant",
                )
            )
    return out


def _translate_user(seq: int, e: dict) -> list[NormalizedEvent]:
    msg = e.get("message", {})
    content = msg.get("content")
    # Some user events have plain string content; treat that as user text.
    if isinstance(content, str):
        return [
            NormalizedEvent(
                seq=seq,
                kind="message",
                role="user",
                text=content,
                raw_type="user",
            )
        ]
    if not isinstance(content, list):
        return []
    out: list[NormalizedEvent] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "tool_result":
            out.append(
                NormalizedEvent(
                    seq=seq,
                    kind="tool_result",
                    raw_type="user",
                )
            )
        elif btype == "text":
            text = block.get("text") or ""
            if text:
                out.append(
                    NormalizedEvent(
                        seq=seq,
                        kind="message",
                        role="user",
                        text=text,
                        raw_type="user",
                    )
                )
    return out


register("claude", parse_trace)
