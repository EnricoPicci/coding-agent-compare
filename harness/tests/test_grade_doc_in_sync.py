"""Mechanical drift catch between `Grade` and its schema doc.

The Pydantic model in `harness/graders/base.py::Grade` and the reference doc
at `docs-generated-by-claude/12-grade-json-schema.md` are paired:
they have to list the same field set. If a future grader adds a field to
`Grade` but forgets to document it (or vice versa), this test fails loudly
at PR time rather than letting the doc go silently stale.

What this test does NOT catch:
- Semantic drift (the field exists in both, but its meaning changed).
- Type changes that don't change the field name.
- Wrong section ordering in the doc.

Those still need a human reviewer. This test only protects against the
most common drift mode: someone adds a field on one side and forgets the
other.
"""

from __future__ import annotations

import re
from pathlib import Path

from harness.graders.base import Grade

# Field section headings look like:  ### `field_name`
# (one backtick-quoted identifier on a level-3 heading)
_FIELD_HEADING_RE = re.compile(r"^###\s+`([a-zA-Z_][a-zA-Z_0-9]*)`\s*$", re.MULTILINE)

DOC_PATH = Path(__file__).parents[2] / "docs-generated-by-claude" / "12-grade-json-schema.md"


def _model_field_names_as_serialized() -> set[str]:
    """Return the set of field names as they appear in serialized JSON,
    honoring Pydantic aliases (so `pass_` is reported as `pass`)."""
    names: set[str] = set()
    for name, info in Grade.model_fields.items():
        names.add(info.alias if info.alias else name)
    return names


def test_grade_doc_lists_every_model_field():
    assert DOC_PATH.exists(), f"missing doc at {DOC_PATH}"
    headings = set(_FIELD_HEADING_RE.findall(DOC_PATH.read_text()))
    model_fields = _model_field_names_as_serialized()

    missing_in_doc = model_fields - headings
    extra_in_doc = headings - model_fields

    assert not missing_in_doc and not extra_in_doc, (
        "Grade model and 12-grade-json-schema.md have drifted:\n"
        f"  fields in model but missing from doc: {sorted(missing_in_doc) or 'none'}\n"
        f"  headings in doc but not in model:    {sorted(extra_in_doc) or 'none'}\n"
        "Update one side or the other; see the NOTE in harness/graders/base.py."
    )
