"""Tests for ModeDiscovery.list_modes() advertised filtering (task-6)."""

from __future__ import annotations

import textwrap
from pathlib import Path

from amplifier_module_hooks_mode import ModeDiscovery


def _write(path: Path, name: str, *, advertised: bool = True) -> Path:
    """Helper: create a mode .md file with frontmatter including advertised field."""
    mode_file = path / f"{name}.md"
    advertised_str = "true" if advertised else "false"
    mode_file.write_text(
        textwrap.dedent(f"""\
            ---
            mode:
              name: {name}
              description: "{name} mode"
              advertised: {advertised_str}
              tools:
                safe: [read_file]
              default_action: block
            ---
            # {name.title()} Mode
            You are in {name} mode.
        """),
        encoding="utf-8",
    )
    return mode_file


def test_default_hides_unadvertised(tmp_path: Path) -> None:
    """list_modes() with no args should hide modes with advertised=False."""
    _write(tmp_path, "public", advertised=True)
    _write(tmp_path, "secret", advertised=False)

    discovery = ModeDiscovery(search_paths=[tmp_path])
    names = {name for name, _desc, _source in discovery.list_modes()}

    assert "public" in names
    assert "secret" not in names


def test_include_unadvertised_true_shows_all(tmp_path: Path) -> None:
    """list_modes(include_unadvertised=True) should return all modes."""
    _write(tmp_path, "public", advertised=True)
    _write(tmp_path, "secret", advertised=False)

    discovery = ModeDiscovery(search_paths=[tmp_path])
    names = {
        name for name, _desc, _source in discovery.list_modes(include_unadvertised=True)
    }

    assert "public" in names
    assert "secret" in names


def test_legacy_mode_with_no_advertised_field_is_listed(tmp_path: Path) -> None:
    """A legacy mode file without 'advertised:' key defaults to advertised=True."""
    mode_file = tmp_path / "plan.md"
    mode_file.write_text(
        textwrap.dedent("""\
            ---
            mode:
              name: plan
              description: "Think and discuss"
              tools:
                safe: [read_file, grep]
              default_action: block
            ---
            # Plan Mode
            You are in plan mode.
        """),
        encoding="utf-8",
    )

    discovery = ModeDiscovery(search_paths=[tmp_path])
    names = {name for name, _desc, _source in discovery.list_modes()}

    assert "plan" in names


def test_tool_mode_list_default_hides_unadvertised(tmp_path: Path) -> None:
    """Regression: positional no-kwargs call hides unadvertised modes.

    Simulates tool-mode's usage of discovery.list_modes() without any arguments.
    The result should contain only advertised modes.
    """
    _write(tmp_path, "public", advertised=True)
    _write(tmp_path, "secret", advertised=False)

    discovery = ModeDiscovery(search_paths=[tmp_path])
    # Positional call with no kwargs — exactly how tool-mode calls it
    names = {name for name, _desc, _source in discovery.list_modes()}

    assert names == {"public"}
