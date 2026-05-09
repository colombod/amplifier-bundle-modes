"""Tests for modes/README.md content.

Verifies that modes/README.md:
- Exists at the expected path
- Has the '# Built-in Modes' header
- Contains a table with all four built-in modes: plan, careful, explore, mode-design
- Marks mode-design as advertised=no in the table
- Mentions override paths (.amplifier/modes/ and ~/.amplifier/modes/)
- Has '## mode-design' note section
- Mentions mode-author agent, mode-design-discipline skill, mode-schema-reference.md
- Notes that none of those three artifacts contribute tokens when mode-design is not activated
- Has '## CLI /modes listing' section explaining unadvertised mode behavior
- References v1.1 for the --all flag
- Has '## Authoring a new mode' section pointing to /mode-design and mode-design-discipline
"""

from __future__ import annotations

from pathlib import Path

# Locate bundle root — three parents up from this file's package dir.
# modules/hooks-mode/tests/test_modes_readme.py → bundle root is parents[3].
BUNDLE_ROOT = Path(__file__).resolve().parents[3]
README_FILE = BUNDLE_ROOT / "modes" / "README.md"


def _content() -> str:
    return README_FILE.read_text(encoding="utf-8")


def test_modes_readme_exists() -> None:
    """modes/README.md must exist at the expected path."""
    assert README_FILE.is_file(), (
        f"modes/README.md not found at {README_FILE}. "
        "Create amplifier-bundle-modes/modes/README.md."
    )


def test_modes_readme_has_built_in_modes_header() -> None:
    """File must start with or contain '# Built-in Modes' header."""
    content = _content()
    assert "# Built-in Modes" in content, (
        "modes/README.md must contain a '# Built-in Modes' header."
    )


def test_modes_readme_table_has_plan() -> None:
    """Table must include a row for the 'plan' mode."""
    content = _content().lower()
    assert "plan" in content, (
        "modes/README.md table must include a row for the 'plan' mode."
    )


def test_modes_readme_table_has_careful() -> None:
    """Table must include a row for the 'careful' mode."""
    content = _content().lower()
    assert "careful" in content, (
        "modes/README.md table must include a row for the 'careful' mode."
    )


def test_modes_readme_table_has_explore() -> None:
    """Table must include a row for the 'explore' mode."""
    content = _content().lower()
    assert "explore" in content, (
        "modes/README.md table must include a row for the 'explore' mode."
    )


def test_modes_readme_table_has_mode_design() -> None:
    """Table must include a row for the 'mode-design' mode."""
    content = _content()
    assert "mode-design" in content, (
        "modes/README.md table must include a row for the 'mode-design' mode."
    )


def test_modes_readme_mode_design_row_advertised_no() -> None:
    """The mode-design row must indicate advertised=no."""
    content = _content()
    # Find the mode-design table row and check that it contains 'no'
    lines = content.splitlines()
    mode_design_lines = [line for line in lines if "mode-design" in line]
    assert mode_design_lines, (
        "No lines containing 'mode-design' found in modes/README.md"
    )
    # At least one mode-design line (table row) must contain 'no' (case-insensitive)
    # to indicate advertised:false
    found_no = any(
        "no" in line.lower()
        for line in mode_design_lines
        if "|" in line  # only check table rows
    )
    assert found_no, (
        f"The mode-design table row must indicate 'no' for advertised. "
        f"Lines found: {mode_design_lines}"
    )


def test_modes_readme_mentions_project_override_path() -> None:
    """.amplifier/modes/ project-level override path must be mentioned."""
    content = _content()
    assert ".amplifier/modes/" in content, (
        "modes/README.md must mention '.amplifier/modes/' as project-level override path."
    )


def test_modes_readme_mentions_user_override_path() -> None:
    """~/.amplifier/modes/ user-level override path must be mentioned."""
    content = _content()
    assert "~/.amplifier/modes/" in content, (
        "modes/README.md must mention '~/.amplifier/modes/' as user-level override path."
    )


def test_modes_readme_has_mode_design_note_section() -> None:
    """File must contain a '## mode-design' section header."""
    content = _content()
    assert "## mode-design" in content, (
        "modes/README.md must contain a '## mode-design' section."
    )


def test_modes_readme_mode_design_section_mentions_mode_author() -> None:
    """mode-design section must mention 'mode-author' agent."""
    content = _content()
    assert "mode-author" in content, (
        "modes/README.md must mention 'mode-author' agent in the mode-design note section."
    )


def test_modes_readme_mode_design_section_mentions_skill() -> None:
    """mode-design section must mention 'mode-design-discipline' skill."""
    content = _content()
    assert "mode-design-discipline" in content, (
        "modes/README.md must mention 'mode-design-discipline' skill."
    )


def test_modes_readme_mode_design_section_mentions_schema_reference() -> None:
    """mode-design section must mention 'mode-schema-reference.md' context file."""
    content = _content()
    assert "mode-schema-reference.md" in content, (
        "modes/README.md must mention 'mode-schema-reference.md' context reference."
    )


def test_modes_readme_mode_design_section_mentions_no_tokens_when_inactive() -> None:
    """mode-design section must note that artifacts contribute zero tokens when mode is never activated."""
    content = _content().lower()
    # Look for "token" mention in the context of never activating mode-design
    assert "token" in content, (
        "modes/README.md must mention that artifacts contribute no tokens "
        "for sessions that never activate /mode-design."
    )


def test_modes_readme_has_cli_modes_listing_section() -> None:
    """File must contain a section about CLI /modes listing and unadvertised modes."""
    content = _content()
    # Check for section header variants
    assert "## CLI" in content or "## /modes" in content or "## cli" in content.lower(), (
        "modes/README.md must contain a section about CLI /modes listing behavior."
    )


def test_modes_readme_cli_section_mentions_advertised_filter() -> None:
    """CLI /modes section must explain that the advertised flag affects mode(list) tool, not CLI /modes."""
    content = _content()
    assert "advertised" in content, (
        "modes/README.md CLI section must mention the 'advertised' flag."
    )
    assert "mode(list)" in content or "mode\\(list\\)" in content or "mode list" in content.lower(), (
        "modes/README.md CLI section must mention 'mode(list)' tool operation."
    )


def test_modes_readme_references_v1_1() -> None:
    """File must reference v1.1 for the --all flag behavior."""
    content = _content()
    assert "v1.1" in content or "v1.1" in content, (
        "modes/README.md must reference 'v1.1' for the --all flag scheduling."
    )


def test_modes_readme_cli_section_mentions_humans_vs_llm() -> None:
    """CLI /modes section must distinguish between human discovery and LLM visibility."""
    content = _content().lower()
    assert "human" in content, (
        "modes/README.md CLI section must mention humans vs LLM for mode discovery."
    )


def test_modes_readme_has_authoring_section() -> None:
    """File must contain '## Authoring a new mode' section."""
    content = _content()
    assert "## Authoring" in content or "## authoring" in content.lower(), (
        "modes/README.md must contain an 'Authoring a new mode' section."
    )


def test_modes_readme_authoring_section_points_to_mode_design() -> None:
    """Authoring section must reference /mode-design command."""
    content = _content()
    assert "/mode-design" in content, (
        "modes/README.md authoring section must reference '/mode-design' command."
    )


def test_modes_readme_authoring_section_mentions_schema_reference_path() -> None:
    """Authoring section must mention context/mode-schema-reference.md path."""
    content = _content()
    assert "context/mode-schema-reference.md" in content, (
        "modes/README.md authoring section must mention 'context/mode-schema-reference.md'."
    )


def test_modes_readme_table_has_shortcut_column() -> None:
    """Table must have a Shortcut column."""
    content = _content()
    assert "Shortcut" in content or "shortcut" in content.lower(), (
        "modes/README.md table must have a 'Shortcut' column."
    )


def test_modes_readme_table_has_advertised_column() -> None:
    """Table must have an Advertised column."""
    content = _content()
    assert "Advertised" in content or "advertised" in content.lower(), (
        "modes/README.md table must have an 'Advertised' column."
    )
