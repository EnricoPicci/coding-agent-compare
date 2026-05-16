"""Parse GitHub Copilot CLI's --output-format=json trace into normalized events.

Copilot's trace is much chattier than Claude's — for a single agent turn it
emits a `turn_start`, dozens of `message_delta` chunks, a final `message`,
plus `reasoning` blocks and per-tool `execution_start` / `execution_complete`
events. We deliberately keep only the *finalized* views to match Claude's
shape and the plan's "be conservative" guidance:

  - `assistant.message`          → message (role="assistant")
  - `user.message`               → message (role="user")
  - `tool.execution_start`       → tool_call
  - `tool.execution_complete`    → tool_result
  - `abort`                      → error
  - everything else (deltas, session.*, reasoning, turn boundaries) is dropped.

If event-shape drift makes any of the above unrecognizable, the parser skips
that line and continues — partial traces are common (SIGKILL during timeout).
"""

from __future__ import annotations

import json
from pathlib import Path

from harness.parsers import register
from harness.parsers.event import NormalizedEvent


def parse_trace(stdout_log: Path) -> list[NormalizedEvent]:
    events: list[NormalizedEvent] = []
    for seq, line in enumerate(_iter_jsonl(stdout_log)):
        evt = _translate(seq, line)
        if evt is not None:
            events.append(evt)
    return events


def _iter_jsonl(path: Path):
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


def _translate(seq: int, e: dict) -> NormalizedEvent | None:
    t = e.get("type")
    data = e.get("data") or {}

    if t == "assistant.message":
        return NormalizedEvent(
            seq=seq,
            kind="message",
            role="assistant",
            text=_extract_text(data),
            raw_type=t,
        )
    if t == "user.message":
        return NormalizedEvent(
            seq=seq,
            kind="message",
            role="user",
            text=_extract_text(data),
            raw_type=t,
        )
    if t == "tool.execution_start":
        return NormalizedEvent(
            seq=seq,
            kind="tool_call",
            tool_name=data.get("toolName") or data.get("tool") or data.get("name"),
            raw_type=t,
        )
    if t == "tool.execution_complete":
        return NormalizedEvent(
            seq=seq,
            kind="tool_result",
            tool_name=data.get("toolName") or data.get("tool") or data.get("name"),
            raw_type=t,
        )
    if t == "abort":
        return NormalizedEvent(
            seq=seq,
            kind="error",
            raw_type=t,
            text=str(data.get("reason") or "aborted"),
        )
    return None


def _extract_text(data: dict) -> str | None:
    """Best-effort text extraction from a message payload. Copilot's exact
    shape has evolved across releases — try several known shapes before
    giving up."""
    # Direct text field
    if isinstance(data.get("text"), str):
        return data["text"]
    # content as string
    content = data.get("content")
    if isinstance(content, str):
        return content
    # content as list of {type, text} blocks
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        if parts:
            return "\n".join(parts)
    # message.text nested
    msg = data.get("message")
    if isinstance(msg, dict) and isinstance(msg.get("text"), str):
        return msg["text"]
    return None


register("copilot", parse_trace)
