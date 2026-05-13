"""Grade schema — the accreting document each grader contributes fields to.

One `grade.json` per run dir. Each grader returns a partial dict of fields;
the runner merges them all into a single Grade and writes it out. This keeps
the consumer (Step 12's report) reading from a single document rather than
hunting across N grader-specific files.

Schema policy: `extra="forbid"` — typos and rogue fields surface at read time.
Add a real field here when a new grader needs it; don't smuggle data through
arbitrary string keys.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"


class Grade(BaseModel):
    model_config = {"extra": "forbid"}

    schema_version: str = SCHEMA_VERSION
    graders: list[str] = Field(
        default_factory=list,
        description="names of graders that contributed to this Grade, in order run",
    )

    # ----- Step 8: mock grader -----
    produced_nonempty_diff: bool | None = Field(
        default=None,
        description="true iff diff.patch is non-empty (Step 8 mock signal)",
    )

    # ----- Step 9: swebench host-venv grader (placeholders) -----
    pass_: bool | None = Field(
        default=None,
        alias="pass",
        description="primary metric: did the original PR's test suite pass on the agent's diff?",
    )
    tests_passed: list[str] | None = None
    tests_failed: list[str] | None = None
    unresolved: list[str] | None = None
    grader_notes: str | None = None

    # ----- Step 10: scope + size graders (placeholders) -----
    files_touched_precision: float | None = None
    files_touched_recall: float | None = None
    diff_size_lines: int | None = None
    human_diff_size_lines: int | None = None
