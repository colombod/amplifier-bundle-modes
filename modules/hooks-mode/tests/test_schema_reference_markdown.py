"""Markdown heading-hierarchy tests for context/mode-schema-reference.md.

The schema reference is injected as LLM context on every provider request while
mode-design is active.  A broken heading structure (e.g. H1 inside a section that
is a child of an H3) confuses models that interpret the raw markdown and creates
visual noise when rendered.

These tests use a *regex-only* approach intentionally — the same way a naive LLM
or markdown renderer will see the document.  Code fences are NOT treated specially:
any line that starts with one or more ``#`` followed by whitespace and text is
counted as a heading.  This means heading-like content inside code blocks must
also be well-formed (or avoided).
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Three levels up from tests/ brings us to the bundle root
# (tests/ → hooks-mode/ → modules/ → amplifier-bundle-modes/)
BUNDLE_ROOT: Path = Path(__file__).resolve().parents[3]

SCHEMA_REF: Path = BUNDLE_ROOT / "context" / "mode-schema-reference.md"

_HEADING_RE = re.compile(r"^(#+)\s+(.+)$", re.MULTILINE)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _parse_headings(text: str) -> list[tuple[int, str]]:
    """Return list of (depth, title) pairs from all heading-like lines."""
    return [(len(hashes), title) for hashes, title in _HEADING_RE.findall(text)]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_schema_reference_exists() -> None:
    """Sanity-check: the schema reference file must be present in the bundle."""
    assert SCHEMA_REF.exists(), (
        f"context/mode-schema-reference.md not found at {SCHEMA_REF}. "
        "This file is required for the mode-design mode to function."
    )


def test_no_heading_level_jump_greater_than_one() -> None:
    """No consecutive heading pair may jump by more than 1 level in either direction.

    Well-formed markdown requires:
    - Going *deeper*: never skip a level (H2 → H4 is forbidden; H2 → H3 is fine).
    - Going *shallower*: never jump by more than one level at a time
      (H4 → H2 is forbidden; H4 → H3 is fine).

    This rule applies even to heading-like lines inside code fences, because the
    document is injected as raw text into the LLM context where the model sees the
    raw ``#`` markers without understanding fence boundaries.
    """
    text = SCHEMA_REF.read_text(encoding="utf-8")
    headings = _parse_headings(text)

    violations: list[str] = []
    for i in range(1, len(headings)):
        prev_depth, prev_title = headings[i - 1]
        curr_depth, curr_title = headings[i]
        jump = curr_depth - prev_depth
        if abs(jump) > 1:
            violations.append(
                f"  index {i}: H{prev_depth} '{prev_title}' → H{curr_depth} '{curr_title}'"
                f" (jump={jump:+d})"
            )

    assert not violations, (
        "Heading level jumps > 1 found in context/mode-schema-reference.md.\n"
        "Each pair of consecutive headings must differ by at most 1 level.\n"
        "Violations:\n" + "\n".join(violations)
    )
