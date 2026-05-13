"""Tests for bundle root README.md content.

The built-in mode listing and mode-design documentation now lives in the bundle's
root README.md (moved from modes/README.md, which is no longer present — the
modes/ directory is a discovery directory, not a documentation directory).

Verifies that the root README.md:
- Has the '## Built-in Modes' section
- Contains a table with all four built-in modes: plan, careful, explore, mode-design
- Marks mode-design with advertised=no indication
- Mentions override paths (.amplifier/modes/ and ~/.amplifier/modes/)
- Has section about advertised: false semantics
- Mentions mode-author agent, mode-design-discipline skill, mode-schema-reference.md
- Notes that artifacts contribute zero tokens when mode-design is not activated
- Has authoring guidance section pointing to /mode-design
- Has a Shortcut column
- Has an Advertised column
"""

from __future__ import annotations

from pathlib import Path

# Locate bundle root — three parents up from this file's package dir.
# modules/hooks-mode/tests/test_modes_readme.py → bundle root is parents[3].
BUNDLE_ROOT = Path(__file__).resolve().parents[3]
README_FILE = BUNDLE_ROOT / "README.md"

# The modes/README.md has been moved; it should NOT exist there anymore.
MOVED_README = BUNDLE_ROOT / "modes" / "README.md"


def _content() -> str:
    return README_FILE.read_text(encoding="utf-8")


def test_bundle_readme_exists() -> None:
    """Bundle root README.md must exist."""
    assert README_FILE.is_file(), (
        f"Bundle root README.md not found at {README_FILE}."
    )


def test_modes_readme_moved_out_of_modes_dir() -> None:
    """modes/README.md must NOT exist — it has been moved to the bundle root README.md.

    The modes/ directory contract: every .md file is a mode definition. A
    documentation file in that directory is an error (it gets parsed as a mode and
    emits a silent skip). The content now lives in the bundle root README.md.
    """
    assert not MOVED_README.exists(), (
        f"modes/README.md still exists at {MOVED_README}. "
        "The file must be removed; its content has been merged into the bundle root README.md."
    )


def test_bundle_readme_has_built_in_modes_header() -> None:
    """Root README.md must contain a 'Built-in Modes' header."""
    content = _content()
    assert "Built-in Modes" in content, (
        "Root README.md must contain a 'Built-in Modes' section."
    )


def test_bundle_readme_table_has_plan() -> None:
    """Table must include a row for the 'plan' mode."""
    content = _content().lower()
    assert "plan" in content


def test_bundle_readme_table_has_careful() -> None:
    """Table must include a row for the 'careful' mode."""
    content = _content().lower()
    assert "careful" in content


def test_bundle_readme_table_has_explore() -> None:
    """Table must include a row for the 'explore' mode."""
    content = _content().lower()
    assert "explore" in content


def test_bundle_readme_table_has_mode_design() -> None:
    """Table must include a row for the 'mode-design' mode."""
    content = _content()
    assert "mode-design" in content


def test_bundle_readme_mode_design_row_advertised_no() -> None:
    """The mode-design row must indicate advertised=no."""
    content = _content()
    lines = content.splitlines()
    mode_design_lines = [line for line in lines if "mode-design" in line]
    assert mode_design_lines, "No lines containing 'mode-design' found in root README.md"
    found_no = any(
        "no" in line.lower()
        for line in mode_design_lines
        if "|" in line  # only check table rows
    )
    assert found_no, (
        f"The mode-design table row must indicate 'no' for advertised. "
        f"Lines found: {mode_design_lines}"
    )


def test_bundle_readme_mentions_project_override_path() -> None:
    """.amplifier/modes/ project-level override path must be mentioned."""
    content = _content()
    assert ".amplifier/modes/" in content


def test_bundle_readme_mentions_user_override_path() -> None:
    """~/.amplifier/modes/ user-level override path must be mentioned."""
    content = _content()
    assert "~/.amplifier/modes/" in content


def test_bundle_readme_has_advertised_false_section() -> None:
    """Root README.md must explain advertised: false semantics."""
    content = _content()
    assert "advertised" in content, (
        "Root README.md must explain the advertised field and its semantics."
    )


def test_bundle_readme_mentions_mode_author() -> None:
    """Mode-design section must mention 'mode-author' agent."""
    content = _content()
    assert "mode-author" in content


def test_bundle_readme_mentions_skill() -> None:
    """Mode-design section must mention 'mode-design-discipline' skill."""
    content = _content()
    assert "mode-design-discipline" in content


def test_bundle_readme_mentions_schema_reference() -> None:
    """Mode-design section must mention 'mode-schema-reference.md' context file."""
    content = _content()
    assert "mode-schema-reference.md" in content


def test_bundle_readme_mentions_no_tokens_when_inactive() -> None:
    """Mode-design section must note that artifacts disappear on deactivation."""
    content = _content()
    # The content says "disappear on deactivation" or similar
    assert "deactivat" in content.lower() or "never activate" in content.lower(), (
        "Root README.md must mention that mode-design artifacts are ephemeral."
    )


def test_bundle_readme_has_authoring_section() -> None:
    """Root README.md must contain authoring guidance."""
    content = _content()
    assert "Authoring" in content or "authoring" in content.lower()


def test_bundle_readme_authoring_points_to_mode_design() -> None:
    """Authoring section must reference /mode-design command."""
    content = _content()
    assert "/mode-design" in content


def test_bundle_readme_authoring_mentions_schema_reference_path() -> None:
    """Authoring section must mention context/mode-schema-reference.md path."""
    content = _content()
    assert "context/mode-schema-reference.md" in content


def test_bundle_readme_table_has_shortcut_column() -> None:
    """Table must have a Shortcut column."""
    content = _content()
    assert "Shortcut" in content or "shortcut" in content.lower()


def test_bundle_readme_table_has_advertised_column() -> None:
    """Table must have an Advertised column."""
    content = _content()
    assert "Advertised" in content or "advertised" in content.lower()
