"""Tests for list_modes() returning all modes with advertised metadata (mechanism/policy split).

After the refactor:
  - list_modes() always returns ALL modes (advertised + unadvertised)
  - Each entry has an .advertised field (ModeListing NamedTuple)
  - The include_unadvertised kwarg is still accepted but emits DeprecationWarning
  - tool-mode's _handle_list filters for advertised=True before returning to LLM
"""

from __future__ import annotations

import textwrap
import warnings
from pathlib import Path

from amplifier_module_hooks_mode import ModeDiscovery


def _write(path: Path, name: str, *, advertised: bool = True) -> Path:
    """Helper: create a mode .md file."""
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


def test_list_modes_returns_all_modes(tmp_path: Path) -> None:
    """list_modes() must return both advertised and unadvertised modes."""
    _write(tmp_path, "public", advertised=True)
    _write(tmp_path, "secret", advertised=False)

    discovery = ModeDiscovery(search_paths=[tmp_path])
    entries = discovery.list_modes()
    names = {e.name for e in entries}

    assert "public" in names, "Advertised mode should be returned"
    assert "secret" in names, "Unadvertised mode should also be returned"


def test_list_modes_entries_have_advertised_field(tmp_path: Path) -> None:
    """Each ModeListing entry must expose .advertised accurately."""
    _write(tmp_path, "visible", advertised=True)
    _write(tmp_path, "hidden", advertised=False)

    discovery = ModeDiscovery(search_paths=[tmp_path])
    entries = {e.name: e for e in discovery.list_modes()}

    assert entries["visible"].advertised is True
    assert entries["hidden"].advertised is False


def test_list_modes_entries_have_name_description_source(tmp_path: Path) -> None:
    """Each ModeListing entry must expose .name, .description, and .source."""
    _write(tmp_path, "plan", advertised=True)

    discovery = ModeDiscovery(search_paths=[tmp_path])
    entries = discovery.list_modes()

    assert len(entries) == 1
    entry = entries[0]
    assert entry.name == "plan"
    assert entry.description == "plan mode"
    assert isinstance(entry.source, str)


def test_list_modes_deprecation_warning_on_include_unadvertised_false(
    tmp_path: Path,
) -> None:
    """Passing include_unadvertised=False must emit DeprecationWarning."""
    _write(tmp_path, "plan", advertised=True)

    discovery = ModeDiscovery(search_paths=[tmp_path])
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        discovery.list_modes(include_unadvertised=False)

    deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
    assert len(deprecation_warnings) == 1, (
        "Passing include_unadvertised kwarg should emit exactly one DeprecationWarning"
    )
    assert "include_unadvertised" in str(deprecation_warnings[0].message)


def test_list_modes_deprecation_warning_on_include_unadvertised_true(
    tmp_path: Path,
) -> None:
    """Passing include_unadvertised=True must emit DeprecationWarning."""
    _write(tmp_path, "plan", advertised=True)

    discovery = ModeDiscovery(search_paths=[tmp_path])
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        discovery.list_modes(include_unadvertised=True)

    deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
    assert len(deprecation_warnings) == 1
    assert "include_unadvertised" in str(deprecation_warnings[0].message)


def test_list_modes_no_deprecation_without_kwarg(tmp_path: Path) -> None:
    """Calling list_modes() with no kwargs must NOT emit any DeprecationWarning."""
    _write(tmp_path, "plan", advertised=True)

    discovery = ModeDiscovery(search_paths=[tmp_path])
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        discovery.list_modes()

    deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
    assert deprecation_warnings == [], (
        "No DeprecationWarning should be emitted when include_unadvertised is not passed"
    )


def test_list_modes_ignored_kwarg_still_returns_all(tmp_path: Path) -> None:
    """include_unadvertised=False is accepted but ignored; all modes still returned."""
    _write(tmp_path, "public", advertised=True)
    _write(tmp_path, "secret", advertised=False)

    discovery = ModeDiscovery(search_paths=[tmp_path])
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        entries = discovery.list_modes(include_unadvertised=False)

    names = {e.name for e in entries}
    assert "public" in names
    assert "secret" in names, (
        "include_unadvertised=False is deprecated/ignored; all modes should still be returned"
    )


# ---------------------------------------------------------------------------
# tool-mode consumer-side filter tests
# ---------------------------------------------------------------------------


def test_tool_mode_handle_list_filters_to_advertised_only(tmp_path: Path) -> None:
    """tool-mode's _handle_list must return only advertised modes to the LLM.

    This test instantiates ModeTool directly and verifies that the 'list'
    operation output does NOT include modes with advertised=False.
    """
    import asyncio
    from unittest.mock import MagicMock

    # Create a mixed directory: one advertised, one unadvertised
    _write(tmp_path, "plan", advertised=True)
    _write(tmp_path, "mode-design", advertised=False)

    discovery = ModeDiscovery(search_paths=[tmp_path])

    coordinator = MagicMock()
    coordinator.session_state = {
        "active_mode": None,
        "mode_discovery": discovery,
    }

    from amplifier_module_tool_mode import ModeTool

    tool = ModeTool(config={}, coordinator=coordinator)
    result = asyncio.run(tool.execute({"operation": "list"}))

    assert result.success is True
    names = [m["name"] for m in result.output["modes"]]

    assert "plan" in names, "Advertised mode 'plan' must be in LLM-facing list"
    assert "mode-design" not in names, (
        "Unadvertised mode 'mode-design' must NOT be in LLM-facing list; "
        "tool-mode must filter on .advertised before returning to the LLM."
    )
