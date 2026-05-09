"""Tests for modules/hooks-mode/tests/fixtures/test-overlap-mode.md.

Verifies that the test fixture mode file:
- Exists at the expected path
- Parses cleanly via parse_mode_file
- Has name=test-overlap-mode
- Has description matching the spec
- Has shortcut disabled (shortcut: false → ModeDefinition.shortcut is None)
- Has advertised=False
- Has default_action=block
- Has allow_clear=True
- Has safe tools: [read_file, todo, mode, delegate]
- Has contributes.agents.mode-author with source='@modes:agents/mode-author'
- Body explains purpose, mentions S3/S4, 'Do not ship this mode', and fixture location
"""

from __future__ import annotations

from pathlib import Path

from amplifier_module_hooks_mode import parse_mode_file

# The fixture lives inside the tests/fixtures/ dir:
# modules/hooks-mode/tests/fixtures/test-overlap-mode.md
# This test file is at:
# modules/hooks-mode/tests/test_overlap_fixture.py
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURE_FILE = FIXTURES_DIR / "test-overlap-mode.md"


def test_fixture_file_exists() -> None:
    """tests/fixtures/test-overlap-mode.md must exist."""
    assert FIXTURE_FILE.is_file(), (
        f"Fixture file not found at {FIXTURE_FILE}. "
        "Create modules/hooks-mode/tests/fixtures/test-overlap-mode.md."
    )


def test_fixture_parses_cleanly() -> None:
    """parse_mode_file must return a ModeDefinition (not None)."""
    mode = parse_mode_file(FIXTURE_FILE)
    assert mode is not None, (
        f"parse_mode_file({FIXTURE_FILE}) returned None — "
        "check YAML frontmatter has a valid 'mode:' key."
    )


def test_fixture_name() -> None:
    """Parsed mode must have name='test-overlap-mode'."""
    mode = parse_mode_file(FIXTURE_FILE)
    assert mode is not None
    assert mode.name == "test-overlap-mode", (
        f"Expected mode.name == 'test-overlap-mode', got {mode.name!r}"
    )


def test_fixture_description() -> None:
    """Parsed mode must have the exact fixture description."""
    mode = parse_mode_file(FIXTURE_FILE)
    assert mode is not None
    expected = (
        "Test fixture — declares mode-author for S3/S4 testing. NOT for end users."
    )
    assert mode.description == expected, (
        f"Expected description {expected!r}, got {mode.description!r}"
    )


def test_fixture_shortcut_disabled() -> None:
    """shortcut: false must result in ModeDefinition.shortcut being None."""
    mode = parse_mode_file(FIXTURE_FILE)
    assert mode is not None
    assert mode.shortcut is None, (
        f"Expected mode.shortcut is None (shortcut: false in YAML), got {mode.shortcut!r}"
    )


def test_fixture_advertised_false() -> None:
    """Parsed mode must have advertised=False."""
    mode = parse_mode_file(FIXTURE_FILE)
    assert mode is not None
    assert mode.advertised is False, (
        f"Expected mode.advertised is False, got {mode.advertised!r}"
    )


def test_fixture_default_action_block() -> None:
    """Parsed mode must have default_action='block'."""
    mode = parse_mode_file(FIXTURE_FILE)
    assert mode is not None
    assert mode.default_action == "block", (
        f"Expected mode.default_action == 'block', got {mode.default_action!r}"
    )


def test_fixture_allow_clear_true() -> None:
    """Parsed mode must have allow_clear=True."""
    mode = parse_mode_file(FIXTURE_FILE)
    assert mode is not None
    assert mode.allow_clear is True, (
        f"Expected mode.allow_clear is True, got {mode.allow_clear!r}"
    )


def test_fixture_safe_tools() -> None:
    """safe tools must be exactly [read_file, todo, mode, delegate]."""
    mode = parse_mode_file(FIXTURE_FILE)
    assert mode is not None
    expected_safe = ["read_file", "todo", "mode", "delegate"]
    assert mode.safe_tools == expected_safe, (
        f"Expected safe_tools == {expected_safe}, got {mode.safe_tools}"
    )


def test_fixture_contributes_agents_mode_author() -> None:
    """contributes must contain agents.mode-author."""
    mode = parse_mode_file(FIXTURE_FILE)
    assert mode is not None
    assert mode.contributes is not None, "mode.contributes must not be None"
    assert "agents" in mode.contributes, (
        f"mode.contributes must contain 'agents', got keys: {list(mode.contributes.keys())}"
    )
    assert "mode-author" in mode.contributes["agents"], (
        f"mode.contributes['agents'] must contain 'mode-author', "
        f"got: {list(mode.contributes['agents'].keys())}"
    )


def test_fixture_mode_author_source() -> None:
    """contributes.agents.mode-author must have source='@modes:agents/mode-author'."""
    mode = parse_mode_file(FIXTURE_FILE)
    assert mode is not None
    agent_entry = mode.contributes.get("agents", {}).get("mode-author", {})
    source = agent_entry.get("source") if isinstance(agent_entry, dict) else None
    assert source == "@modes:agents/mode-author", (
        f"Expected source == '@modes:agents/mode-author', got {source!r}"
    )


def test_fixture_body_explains_purpose() -> None:
    """Body must contain a 'Test Overlap Mode' heading."""
    mode = parse_mode_file(FIXTURE_FILE)
    assert mode is not None
    assert "Test Overlap Mode" in mode.context, (
        "Body must contain '# Test Overlap Mode' heading"
    )


def test_fixture_body_mentions_s3_s4() -> None:
    """Body must mention S3 and S4 scenarios."""
    mode = parse_mode_file(FIXTURE_FILE)
    assert mode is not None
    assert "S3" in mode.context, "Body must mention S3 scenario"
    assert "S4" in mode.context, "Body must mention S4 scenario"


def test_fixture_body_do_not_ship() -> None:
    """Body must contain 'Do not ship this mode' note."""
    mode = parse_mode_file(FIXTURE_FILE)
    assert mode is not None
    assert "Do not ship this mode" in mode.context, (
        "Body must contain 'Do not ship this mode' note"
    )


def test_fixture_body_references_fixture_location() -> None:
    """Body must mention tests/fixtures/ as the fixture location."""
    mode = parse_mode_file(FIXTURE_FILE)
    assert mode is not None
    assert "tests/fixtures/" in mode.context, (
        "Body must mention 'tests/fixtures/' as the fixture location"
    )


def test_fixture_body_mentions_integration_test() -> None:
    """Body must mention that it is loaded only by integration test module."""
    mode = parse_mode_file(FIXTURE_FILE)
    assert mode is not None
    assert "integration test" in mode.context.lower(), (
        "Body must mention that the fixture is loaded only by integration test module"
    )
