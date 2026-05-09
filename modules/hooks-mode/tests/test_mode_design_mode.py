"""Tests for the modes/mode-design.md file.

Verifies that modes/mode-design.md:
- Exists at the expected path
- Parses cleanly via parse_mode_file
- Has the correct name, advertised=False, contributes block
- Has delegate and load_skill in safe_tools
- Has write_file in confirm_tools

Expected output when all checks pass: 'OK: mode-design.md parses correctly'
"""

from __future__ import annotations

from pathlib import Path

from amplifier_module_hooks_mode import parse_mode_file

# Locate bundle root — three parents up from this file's package dir.
# modules/hooks-mode/tests/test_mode_design_mode.py → bundle root is parents[3].
BUNDLE_ROOT = Path(__file__).resolve().parents[3]
MODE_FILE = BUNDLE_ROOT / "modes" / "mode-design.md"


def test_mode_design_file_exists() -> None:
    """modes/mode-design.md must exist at the expected path."""
    assert MODE_FILE.is_file(), (
        f"Mode file not found at {MODE_FILE}. "
        "Create amplifier-bundle-modes/modes/mode-design.md."
    )


def test_mode_design_parses_cleanly() -> None:
    """parse_mode_file must return a ModeDefinition (not None) for mode-design.md."""
    mode = parse_mode_file(MODE_FILE)
    assert mode is not None, (
        f"parse_mode_file({MODE_FILE}) returned None — "
        "check that the file has valid YAML frontmatter with a 'mode:' key."
    )


def test_mode_design_name() -> None:
    """Parsed mode must have name='mode-design'."""
    mode = parse_mode_file(MODE_FILE)
    assert mode is not None
    assert mode.name == "mode-design", (
        f"Expected mode.name == 'mode-design', got {mode.name!r}"
    )


def test_mode_design_advertised_false() -> None:
    """Parsed mode must have advertised=False (hidden from LLM-facing listings)."""
    mode = parse_mode_file(MODE_FILE)
    assert mode is not None
    assert mode.advertised is False, (
        f"Expected mode.advertised is False, got {mode.advertised!r}"
    )


def test_mode_design_contributes_agents_mode_author() -> None:
    """contributes must contain 'agents' with 'mode-author' entry."""
    mode = parse_mode_file(MODE_FILE)
    assert mode is not None
    assert mode.contributes is not None, "mode.contributes must not be None"
    assert "agents" in mode.contributes, (
        f"mode.contributes must contain 'agents', got keys: {list(mode.contributes.keys())}"
    )
    assert "mode-author" in mode.contributes["agents"], (
        f"mode.contributes['agents'] must contain 'mode-author', "
        f"got: {list(mode.contributes['agents'].keys())}"
    )


def test_mode_design_contributes_context() -> None:
    """contributes must contain 'context' list."""
    mode = parse_mode_file(MODE_FILE)
    assert mode is not None
    assert "context" in mode.contributes, (
        f"mode.contributes must contain 'context', got keys: {list(mode.contributes.keys())}"
    )
    assert isinstance(mode.contributes["context"], list), (
        f"mode.contributes['context'] must be a list, "
        f"got {type(mode.contributes['context'])!r}"
    )
    assert len(mode.contributes["context"]) > 0, (
        "mode.contributes['context'] must have at least one entry"
    )


def test_mode_design_contributes_skills() -> None:
    """contributes must contain 'skills' list."""
    mode = parse_mode_file(MODE_FILE)
    assert mode is not None
    assert "skills" in mode.contributes, (
        f"mode.contributes must contain 'skills', got keys: {list(mode.contributes.keys())}"
    )
    assert isinstance(mode.contributes["skills"], list), (
        f"mode.contributes['skills'] must be a list, "
        f"got {type(mode.contributes['skills'])!r}"
    )
    assert len(mode.contributes["skills"]) > 0, (
        "mode.contributes['skills'] must have at least one entry"
    )


def test_mode_design_delegate_in_safe_tools() -> None:
    """'delegate' must be in safe_tools (allows using mode-author agent)."""
    mode = parse_mode_file(MODE_FILE)
    assert mode is not None
    assert "delegate" in mode.safe_tools, (
        f"'delegate' must be in mode.safe_tools, got: {mode.safe_tools}"
    )


def test_mode_design_load_skill_in_safe_tools() -> None:
    """'load_skill' must be in safe_tools (allows discovering contributed skill)."""
    mode = parse_mode_file(MODE_FILE)
    assert mode is not None
    assert "load_skill" in mode.safe_tools, (
        f"'load_skill' must be in mode.safe_tools, got: {mode.safe_tools}"
    )


def test_mode_design_write_file_in_confirm_tools() -> None:
    """'write_file' must be in confirm_tools (requires approval before writing)."""
    mode = parse_mode_file(MODE_FILE)
    assert mode is not None
    assert "write_file" in mode.confirm_tools, (
        f"'write_file' must be in mode.confirm_tools, got: {mode.confirm_tools}"
    )


def test_mode_design_full_validation_prints_ok(capsys) -> None:
    """Full validation: parses correctly with all required attributes.

    This test produces the expected output: 'OK: mode-design.md parses correctly'
    """
    mode = parse_mode_file(MODE_FILE)

    assert mode is not None
    assert mode.name == "mode-design"
    assert mode.advertised is False
    assert mode.contributes is not None
    assert "agents" in mode.contributes
    assert "mode-author" in mode.contributes["agents"]
    assert "context" in mode.contributes
    assert "skills" in mode.contributes
    assert "delegate" in mode.safe_tools
    assert "load_skill" in mode.safe_tools
    assert "write_file" in mode.confirm_tools

    print("OK: mode-design.md parses correctly")
    captured = capsys.readouterr()
    assert "OK: mode-design.md parses correctly" in captured.out
