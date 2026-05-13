"""Regression test: non-mode .md files in the modes directory are silently skipped.

After PR #14 added modes/README.md, parse_mode_file() was logging a WARNING for every
.md file that lacked a `mode:` frontmatter section. This test verifies that:

  1. Files with no frontmatter at all (e.g. README.md) are skipped at DEBUG level only.
  2. Files with frontmatter but no `mode:` section are skipped at DEBUG level only.
  3. Valid mode files still parse and appear in list_modes().
  4. No WARNING-or-above log records are emitted for non-mode files during discovery.
"""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path

import pytest

from amplifier_module_hooks_mode import ModeDiscovery, parse_mode_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_valid_mode(path: Path, name: str = "plan") -> Path:
    """Write a minimal but complete mode file."""
    f = path / f"{name}.md"
    f.write_text(
        textwrap.dedent(f"""\
            ---
            mode:
              name: {name}
              description: "{name} mode"
              tools:
                safe: [read_file, grep]
              default_action: block
            ---
            # {name.title()} Mode
            You are in {name} mode.
        """),
        encoding="utf-8",
    )
    return f


def _write_readme(path: Path) -> Path:
    """Write a README.md with no YAML frontmatter — not a mode file."""
    f = path / "README.md"
    f.write_text(
        textwrap.dedent("""\
            # Built-in Modes

            This directory contains the built-in mode definitions.

            - **plan.md** — think and discuss without writing code
        """),
        encoding="utf-8",
    )
    return f


def _write_misc_md(path: Path) -> Path:
    """Write a .md file that has frontmatter but no `mode:` section."""
    f = path / "misc.md"
    f.write_text(
        textwrap.dedent("""\
            ---
            title: Miscellaneous Notes
            author: tester
            ---
            # Misc

            This file has frontmatter but is not a mode definition.
        """),
        encoding="utf-8",
    )
    return f


# ---------------------------------------------------------------------------
# parse_mode_file unit tests (Part A)
# ---------------------------------------------------------------------------


class TestParseModeSilentSkip:
    """parse_mode_file() must return None *silently* for non-mode files."""

    def test_no_frontmatter_returns_none(self, tmp_path: Path) -> None:
        """README.md (no frontmatter) → None, no exception."""
        readme = _write_readme(tmp_path)
        result = parse_mode_file(readme)
        assert result is None

    def test_no_frontmatter_logs_debug_not_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No-frontmatter file must not produce a WARNING or ERROR log record."""
        readme = _write_readme(tmp_path)
        with caplog.at_level(logging.DEBUG, logger="amplifier_module_hooks_mode"):
            parse_mode_file(readme)

        # Gather all records for this file reference at WARNING+
        noisy = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING and str(readme) in r.getMessage()
        ]
        assert noisy == [], (
            f"Expected no WARNING/ERROR for README.md but got: "
            f"{[(r.levelname, r.getMessage()) for r in noisy]}"
        )

    def test_frontmatter_no_mode_section_returns_none(self, tmp_path: Path) -> None:
        """File with frontmatter but no `mode:` key → None."""
        misc = _write_misc_md(tmp_path)
        result = parse_mode_file(misc)
        assert result is None

    def test_frontmatter_no_mode_section_logs_debug_not_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Frontmatter-but-no-mode-section file must not produce WARNING/ERROR."""
        misc = _write_misc_md(tmp_path)
        with caplog.at_level(logging.DEBUG, logger="amplifier_module_hooks_mode"):
            parse_mode_file(misc)

        noisy = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING and str(misc) in r.getMessage()
        ]
        assert noisy == [], (
            f"Expected no WARNING/ERROR for misc.md but got: "
            f"{[(r.levelname, r.getMessage()) for r in noisy]}"
        )

    def test_valid_mode_still_parses(self, tmp_path: Path) -> None:
        """Valid mode file must still parse correctly — no regression."""
        mode_file = _write_valid_mode(tmp_path, "plan")
        result = parse_mode_file(mode_file)
        assert result is not None
        assert result.name == "plan"


# ---------------------------------------------------------------------------
# ModeDiscovery.list_modes integration test (Part B)
# ---------------------------------------------------------------------------


class TestModeDiscoverySkipsNonModes:
    """ModeDiscovery.list_modes() must exclude non-mode .md files silently."""

    def test_only_valid_modes_returned(self, tmp_path: Path) -> None:
        """list_modes() returns the real mode; README.md and misc.md are absent."""
        _write_valid_mode(tmp_path, "plan")
        _write_readme(tmp_path)
        _write_misc_md(tmp_path)

        discovery = ModeDiscovery(search_paths=[tmp_path])
        results = discovery.list_modes()

        names = [entry.name for entry in results]
        assert "plan" in names, "Valid mode 'plan' should appear in list_modes()"
        assert "README" not in names, "README.md must not appear as a mode"
        assert "misc" not in names, (
            "misc.md (no mode: section) must not appear as a mode"
        )

    def test_no_warning_logs_during_discovery(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """list_modes() must not emit WARNING or ERROR logs for non-mode files."""
        _write_valid_mode(tmp_path, "plan")
        _write_readme(tmp_path)
        _write_misc_md(tmp_path)

        discovery = ModeDiscovery(search_paths=[tmp_path])
        with caplog.at_level(logging.DEBUG, logger="amplifier_module_hooks_mode"):
            discovery.list_modes()

        # Only WARNING+ records that mention the non-mode files
        non_mode_files = {"README", "misc"}
        noisy = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING
            and any(stem in r.getMessage() for stem in non_mode_files)
        ]
        assert noisy == [], (
            f"Expected no WARNING/ERROR for non-mode files during discovery but got: "
            f"{[(r.levelname, r.getMessage()) for r in noisy]}"
        )

    def test_debug_log_emitted_for_no_frontmatter(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """parse_mode_file() emits at most a DEBUG record for no-frontmatter files."""
        readme = _write_readme(tmp_path)
        with caplog.at_level(logging.DEBUG, logger="amplifier_module_hooks_mode"):
            parse_mode_file(readme)

        readme_records = [r for r in caplog.records if str(readme) in r.getMessage()]
        for r in readme_records:
            assert r.levelno <= logging.DEBUG, (
                f"Expected at most DEBUG for README.md but got {r.levelname}: {r.getMessage()}"
            )
