"""Normalized event shape shared across tool parsers.

Conservative on purpose: four kinds (message, tool_call, tool_result, error),
each with the smallest field set the downstream graders need. The raw event
type tag is preserved so a reader can see what we mapped from without
consulting stdout.log; the full raw payload stays in stdout.log itself.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EventKind = Literal["message", "tool_call", "tool_result", "error"]


class NormalizedEvent(BaseModel):
    """One normalized trace event. Order is preserved by `seq`."""

    model_config = {"extra": "forbid"}

    seq: int = Field(description="0-based index in the original stdout.log")
    kind: EventKind
    role: str | None = Field(
        default=None,
        description='for kind="message": "assistant" | "user" | "system"',
    )
    tool_name: str | None = Field(
        default=None,
        description='for kind in ("tool_call", "tool_result")',
    )
    text: str | None = Field(
        default=None,
        description="for kind=message: assistant/user text content",
    )
    raw_type: str = Field(
        description="the original event's type tag from the tool's trace",
    )
