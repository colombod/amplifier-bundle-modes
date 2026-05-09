"""Tests for parsing `advertised` and `contributes` fields from mode YAML frontmatter.

These tests are INTENTIONALLY RED before Task 3 adds the new fields to ModeDefinition.
Expected failure: AttributeError: 'ModeDefinition' object has no attribute 'advertised'
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from amplifier_module_hooks_mode import parse_mode_file


def _write_mode_with_extras(
    path: Path,
    name: str,
    *,
    advertised: bool | None = None,
    contributes: dict[str, Any] | None = None,
) -> Path:
    """Write a mode file, conditionally including advertised: and contributes: keys."""
    lines = [
        "---",
        "mode:",
        f"  name: {name}",
        "  description: Test mode",
        "  tools:",
        "    safe: [read_file]",
        "  default_action: block",
    ]

    if advertised is not None:
        advertised_str = "true" if advertised else "false"
        lines.append(f"  advertised: {advertised_str}")

    if contributes is not None:
        import yaml

        # Render contributes as indented YAML block under `mode:`
        contributes_yaml = yaml.dump(
            {"contributes": contributes}, default_flow_style=False
        )
        for contrib_line in contributes_yaml.splitlines():
            lines.append(f"  {contrib_line}")

    lines.extend(
        [
            "---",
            f"# {name.title()} Mode",
            "",
            "Test mode context.",
        ]
    )

    mode_file = path / f"{name}.md"
    mode_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return mode_file


def test_parses_advertised_true(tmp_path: Path) -> None:
    """Mode file with `advertised: true` parses to mode.advertised is True."""
    mode_file = _write_mode_with_extras(tmp_path, "plan", advertised=True)
    mode = parse_mode_file(mode_file)

    assert mode is not None
    assert mode.advertised is True


def test_parses_advertised_false(tmp_path: Path) -> None:
    """Mode file with `advertised: false` parses to mode.advertised is False."""
    mode_file = _write_mode_with_extras(tmp_path, "internal", advertised=False)
    mode = parse_mode_file(mode_file)

    assert mode is not None
    assert mode.advertised is False


def test_parses_contributes_agents(tmp_path: Path) -> None:
    """Mode file with contributes.agents block parses correctly."""
    contributes = {
        "agents": {
            "mode-author": {
                "source": "@modes:agents/mode-author",
            }
        }
    }
    mode_file = _write_mode_with_extras(tmp_path, "design", contributes=contributes)
    mode = parse_mode_file(mode_file)

    assert mode is not None
    assert "agents" in mode.contributes
    assert "mode-author" in mode.contributes["agents"]
    assert (
        mode.contributes["agents"]["mode-author"]["source"]
        == "@modes:agents/mode-author"
    )


def test_parses_contributes_context_and_skills(tmp_path: Path) -> None:
    """Mode file with contributes.context and contributes.skills parses correctly."""
    contributes = {
        "context": ["@modes:context/schema.md"],
        "skills": ["@modes:skills/mode-design-discipline"],
    }
    mode_file = _write_mode_with_extras(tmp_path, "author", contributes=contributes)
    mode = parse_mode_file(mode_file)

    assert mode is not None
    assert mode.contributes["context"] == ["@modes:context/schema.md"]
    assert mode.contributes["skills"] == ["@modes:skills/mode-design-discipline"]


# ---------------------------------------------------------------------------
# Parse-time referential-integrity lint tests (Task 4)
# ---------------------------------------------------------------------------


def _write_mode_lint_case(
    path: Path,
    name: str,
    *,
    contributes: dict[str, Any],
    safe_tools: str = "[read_file]",
    default_action: str = "block",
) -> Path:
    """Write a mode file for lint testing with configurable contributes/tools/action."""
    import yaml

    lines = [
        "---",
        "mode:",
        f"  name: {name}",
        "  description: Lint test mode",
        "  tools:",
        f"    safe: {safe_tools}",
        f"  default_action: {default_action}",
    ]

    # Render contributes as indented YAML block under `mode:`
    contributes_yaml = yaml.dump({"contributes": contributes}, default_flow_style=False)
    for contrib_line in contributes_yaml.splitlines():
        lines.append(f"  {contrib_line}")

    lines.extend(
        [
            "---",
            f"# {name.title()} Mode",
            "",
            "Lint test mode context.",
        ]
    )

    mode_file = path / f"{name}.md"
    mode_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return mode_file


def test_lint_warns_when_agents_contributed_but_delegate_blocked(
    tmp_path: Path, caplog: Any
) -> None:
    """Mode contributes agents but delegate not in safe_tools and default_action=block.

    Parse must succeed (mode is not None) and a WARNING record must contain
    both 'contributes agents' and 'delegate'.
    """
    with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
        mode_file = _write_mode_lint_case(
            tmp_path,
            "focus",
            contributes={"agents": {"foo": {"source": "@modes:agents/foo"}}},
        )
        mode = parse_mode_file(mode_file)

    assert mode is not None  # parse still succeeds
    assert any(
        "contributes agents" in r.message and "delegate" in r.message
        for r in caplog.records
    ), (
        "Expected a warning about contributed agents being unreachable (delegate blocked)"
    )


def test_lint_warns_when_skills_contributed_but_load_skill_blocked(
    tmp_path: Path, caplog: Any
) -> None:
    """Mode contributes skills but load_skill not in safe_tools and default_action=block.

    Parse must succeed and a WARNING record must contain both 'contributes skills'
    and 'load_skill'.
    """
    with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
        mode_file = _write_mode_lint_case(
            tmp_path,
            "skills-mode",
            contributes={"skills": ["@modes:skills/foo"]},
        )
        mode = parse_mode_file(mode_file)

    assert mode is not None
    assert any(
        "contributes skills" in r.message and "load_skill" in r.message
        for r in caplog.records
    ), (
        "Expected a warning about contributed skills being undiscoverable (load_skill blocked)"
    )


def test_lint_silent_when_delegate_in_safe_tools(tmp_path: Path, caplog: Any) -> None:
    """Mode contributes agents and delegate IS in safe_tools — no lint warning expected."""
    with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
        mode_file = _write_mode_lint_case(
            tmp_path,
            "focus",
            contributes={"agents": {"foo": {"source": "@modes:agents/foo"}}},
            safe_tools="[read_file, delegate]",
        )
        mode = parse_mode_file(mode_file)

    assert mode is not None
    assert not any(
        "delegate" in r.message and "unreachable" in r.message for r in caplog.records
    ), "Expected no warning when delegate is in safe_tools"


def test_lint_silent_when_default_action_is_allow(tmp_path: Path, caplog: Any) -> None:
    """Mode contributes agents but default_action=allow — lints are suppressed."""
    with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
        mode_file = _write_mode_lint_case(
            tmp_path,
            "focus",
            contributes={"agents": {"foo": {"source": "@modes:agents/foo"}}},
            default_action="allow",
        )
        mode = parse_mode_file(mode_file)

    assert mode is not None
    assert not any("unreachable" in r.message for r in caplog.records), (
        "Expected no lint warning when default_action is 'allow'"
    )
