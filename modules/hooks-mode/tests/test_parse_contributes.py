"""Tests for parsing `advertised` and `contributes` fields from mode YAML frontmatter.

These tests are INTENTIONALLY RED before Task 3 adds the new fields to ModeDefinition.
Expected failure: AttributeError: 'ModeDefinition' object has no attribute 'advertised'
"""

from __future__ import annotations

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
