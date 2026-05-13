"""Tests for ModeDiscovery.list_modes() advertised metadata (updated for mechanism/policy split).

After the refactor list_modes() always returns ALL modes. The .advertised field carries
the policy metadata so that each consumer (tool-mode, CLI) can apply its own filter.
"""

from __future__ import annotations

import textwrap
import warnings
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


def test_list_modes_returns_all_including_unadvertised(tmp_path: Path) -> None:
    """list_modes() returns both advertised and unadvertised modes.

    Previously the default hid unadvertised modes. After the mechanism/policy
    split, list_modes() is the mechanism (returns everything) and consumers
    apply the policy (filter on .advertised if needed).
    """
    _write(tmp_path, "public", advertised=True)
    _write(tmp_path, "secret", advertised=False)

    discovery = ModeDiscovery(search_paths=[tmp_path])
    entries = discovery.list_modes()
    names = {e.name for e in entries}

    assert "public" in names
    assert "secret" in names, (
        "list_modes() should return unadvertised modes; consumers filter on .advertised"
    )


def test_advertised_field_accurate(tmp_path: Path) -> None:
    """The .advertised field in each ModeListing accurately reflects the mode's config."""
    _write(tmp_path, "public", advertised=True)
    _write(tmp_path, "secret", advertised=False)

    discovery = ModeDiscovery(search_paths=[tmp_path])
    entries = {e.name: e for e in discovery.list_modes()}

    assert entries["public"].advertised is True
    assert entries["secret"].advertised is False


def test_include_unadvertised_kwarg_emits_deprecation_warning(tmp_path: Path) -> None:
    """list_modes(include_unadvertised=True) emits DeprecationWarning but still works."""
    _write(tmp_path, "public", advertised=True)
    _write(tmp_path, "secret", advertised=False)

    discovery = ModeDiscovery(search_paths=[tmp_path])
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        names = {e.name for e in discovery.list_modes(include_unadvertised=True)}

    deprecations = [x for x in w if issubclass(x.category, DeprecationWarning)]
    assert len(deprecations) == 1
    assert "include_unadvertised" in str(deprecations[0].message)

    # Still returns all modes
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
    entries = {e.name: e for e in discovery.list_modes()}

    assert "plan" in entries
    assert entries["plan"].advertised is True


def test_consumer_can_filter_to_advertised_only(tmp_path: Path) -> None:
    """Illustrates the consumer-side filter pattern for LLM-facing listings.

    This is how tool-mode (and any LLM-facing consumer) should filter the
    full list to only advertised modes. The discovery mechanism itself does
    not filter; consumers apply policy.
    """
    _write(tmp_path, "public", advertised=True)
    _write(tmp_path, "secret", advertised=False)

    discovery = ModeDiscovery(search_paths=[tmp_path])
    advertised_names = {e.name for e in discovery.list_modes() if e.advertised}

    assert advertised_names == {"public"}
    # 'secret' excluded by the consumer-side filter on .advertised
