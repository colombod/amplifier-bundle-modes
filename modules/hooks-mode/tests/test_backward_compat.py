"""Backward-compatibility regression tests for legacy mode file parsing.

These tests lock in the invariant that pre-Phase-2 mode files (no `advertised`,
no `contributes` fields) must still parse with sensible defaults.

Two of the three tests are intentionally RED until Task 3 adds the new fields
to ModeDefinition.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from amplifier_module_hooks_mode import ModeDefinition, parse_mode_file


def _write_legacy_mode(path: Path, name: str) -> Path:
    """Write a legacy (pre-Phase-2) mode file with no advertised/contributes fields."""
    mode_file = path / f"{name}.md"
    mode_file.write_text(
        textwrap.dedent(f"""\
            ---
            mode:
              name: {name}
              description: Legacy mode for backward-compat testing
              tools:
                safe: [read_file, grep]
                warn: [bash]
              default_action: block
            ---
            # {name.title()} Mode

            Legacy mode context.
        """),
        encoding="utf-8",
    )
    return mode_file


def test_legacy_mode_parses(tmp_path: Path) -> None:
    """Legacy mode files (no advertised/contributes) must parse without error."""
    mode_file = _write_legacy_mode(tmp_path, "plan")
    mode = parse_mode_file(mode_file)

    assert mode is not None
    assert mode.name == "plan"
    assert mode.safe_tools == ["read_file", "grep"]
    assert mode.warn_tools == ["bash"]
    assert mode.default_action == "block"


def test_legacy_mode_defaults_for_new_fields(tmp_path: Path) -> None:
    """Legacy mode files must produce sensible defaults for Phase-2 fields.

    INTENTIONALLY RED until Task 3 adds advertised/contributes to ModeDefinition.
    Expected failure: AttributeError: 'ModeDefinition' object has no attribute 'advertised'
    """
    mode_file = _write_legacy_mode(tmp_path, "plan")
    mode = parse_mode_file(mode_file)

    assert mode is not None
    assert mode.advertised is True
    assert mode.contributes == {}


def test_mode_definition_field_defaults() -> None:
    """ModeDefinition constructed with only name= must default new Phase-2 fields.

    INTENTIONALLY RED until Task 3 adds advertised/contributes to ModeDefinition.
    Expected failure: AttributeError: 'ModeDefinition' object has no attribute 'advertised'
    """
    md = ModeDefinition(name="x")

    assert md.advertised is True
    assert md.contributes == {}
