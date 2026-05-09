# Mode Runtime Overlays — Phase 2 (Modes-Bundle Integration)

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Wire Phase 1's `RuntimeOverlay` and `_load_mode_file_metadata` primitives (in `amplifier-foundation`) into the `amplifier-bundle-modes` repo: extend the mode YAML schema (`advertised`, `contributes`), surface unadvertised filtering, and add transition handlers that apply/revoke contributions on mode lifecycle events.

**Architecture:** This phase is purely additive within the modes bundle. We extend `ModeDefinition`, `parse_mode_file`, and `ModeDiscovery.list_modes` with backward-compatible defaults; add three transition-handler methods on `ModeHooks` that delegate the actual mounting work to `RuntimeOverlay`; and register those handlers in `mount()` for the `mode:activated`, `mode:changed`, and `mode:cleared` kernel events emitted by `tool-mode`. No changes to `behaviors/modes.yaml`, no changes to `tool-mode/`, no changes to existing tool-policy or context-injection code paths.

**Tech Stack:** Python 3.11+, `pyyaml`, `pytest` + `pytest-asyncio`, `unittest.mock`. Hard dependency on `amplifier-foundation` (per design §R7).

---

## Prerequisite Check (Phase 1 must be merged)

**Run before starting Task 1:**

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes/modules/hooks-mode
python -c "from amplifier_foundation import RuntimeOverlay; print(RuntimeOverlay)"
python -c "from amplifier_foundation.bundle._dataclass import _load_mode_file_metadata; print(_load_mode_file_metadata)"
```

**Expected:** Both commands print a class/function repr without `ImportError`.

**If `ImportError`:** Phase 1 is not yet shipped. **STOP.** Do not start Phase 2. Verify Phase 1's PR is merged and `amplifier-foundation` is installed in this environment (`pip show amplifier-foundation`). If the import paths differ from what's shown above, ask the human which symbol path Phase 1 actually exports; the rest of this plan assumes `from amplifier_foundation import RuntimeOverlay`.

---

## Working Directory

All commands in this plan run from:

```
/home/bkrabach/dev/modes-updates/amplifier-bundle-modes/modules/hooks-mode
```

Unless otherwise stated. We refer to this as `$HOOKS_MODE` below.

---

## Task 1: Add `amplifier-foundation` dependency

**Files:**
- Modify: `modules/hooks-mode/pyproject.toml:12`

**Step 1: Edit `pyproject.toml`**

Change line 12 from:
```toml
dependencies = ["pyyaml>=6.0"]
```
to:
```toml
dependencies = ["pyyaml>=6.0", "amplifier-foundation"]
```

**Step 2: Reinstall the package so the dep is registered**

Run: `cd $HOOKS_MODE && pip install -e .`
Expected: `Successfully installed amplifier-module-hooks-mode-1.0.0` (and any foundation transitive installs). No errors.

**Step 3: Verify the import still works post-install**

Run: `cd $HOOKS_MODE && python -c "from amplifier_foundation import RuntimeOverlay; from amplifier_module_hooks_mode import ModeHooks; print('ok')"`
Expected: `ok`

**Step 4: Run the existing test suite to confirm nothing regressed**

Run: `cd $HOOKS_MODE && pytest tests/ -v`
Expected: all existing tests pass (the suite at `tests/test_hooks.py` should be green).

**Step 5: Commit**

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
git add modules/hooks-mode/pyproject.toml
git commit -m "chore(hooks-mode): add amplifier-foundation as direct dependency

Phase 2 of mode runtime overlays — hooks-mode now imports RuntimeOverlay
from amplifier-foundation. Per design §R7, the modes bundle is permitted
to depend on amplifier-foundation directly.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 2: Regression test — existing modes still parse

Before adding any new fields, lock in the backward-compat invariant with a regression test. This test will keep us honest as we extend `ModeDefinition` and `parse_mode_file`.

**Files:**
- Create: `modules/hooks-mode/tests/test_backward_compat.py`

**Step 1: Write the regression test**

Create the file with this content:

```python
"""Regression tests: existing modes (no contributes/advertised) must still parse identically."""

from __future__ import annotations

import textwrap
from pathlib import Path

from amplifier_module_hooks_mode import ModeDefinition, parse_mode_file


def _write_legacy_mode(path: Path, name: str) -> Path:
    """Write a mode file in the pre-Phase-2 schema (no `advertised`, no `contributes`)."""
    f = path / f"{name}.md"
    f.write_text(
        textwrap.dedent(f"""\
            ---
            mode:
              name: {name}
              description: "{name} mode"
              tools:
                safe: [read_file, grep]
                warn: [bash]
              default_action: block
            ---
            # {name.title()} Mode
            Body for {name}.
        """),
        encoding="utf-8",
    )
    return f


def test_legacy_mode_parses(tmp_path: Path) -> None:
    f = _write_legacy_mode(tmp_path, "plan")
    mode = parse_mode_file(f)
    assert mode is not None
    assert mode.name == "plan"
    assert mode.safe_tools == ["read_file", "grep"]
    assert mode.warn_tools == ["bash"]
    assert mode.default_action == "block"


def test_legacy_mode_defaults_for_new_fields(tmp_path: Path) -> None:
    """A pre-Phase-2 mode file (no advertised, no contributes) must default
    advertised=True and contributes={}."""
    f = _write_legacy_mode(tmp_path, "careful")
    mode = parse_mode_file(f)
    assert mode is not None
    assert mode.advertised is True, "advertised must default to True for legacy modes"
    assert mode.contributes == {}, "contributes must default to {} for legacy modes"


def test_mode_definition_field_defaults() -> None:
    """ModeDefinition constructed with only required fields has the new defaults."""
    md = ModeDefinition(name="x")
    assert md.advertised is True
    assert md.contributes == {}
```

**Step 2: Run to confirm it fails (the new fields don't exist yet)**

Run: `cd $HOOKS_MODE && pytest tests/test_backward_compat.py -v`
Expected: `test_legacy_mode_defaults_for_new_fields` and `test_mode_definition_field_defaults` FAIL with `AttributeError: 'ModeDefinition' object has no attribute 'advertised'`. The first test (`test_legacy_mode_parses`) passes — it only touches existing fields.

**Step 3: There is no implementation step — we’re intentionally leaving this red until Task 3 makes it green.**

Skip directly to commit (the red test is the deliverable for this task).

**Step 4: (no run)**

**Step 5: Commit (red — drives Task 3)**

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
git add modules/hooks-mode/tests/test_backward_compat.py
git commit -m "test(hooks-mode): add backward-compat regression for legacy mode parsing

Locks in the invariant that pre-Phase-2 mode files (no advertised,
no contributes) parse with sensible defaults. Two of three tests fail
intentionally — they drive Task 3 (ModeDefinition field extension).

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 3: Extend `ModeDefinition` and `parse_mode_file`

**Files:**
- Modify: `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py:46-61` (dataclass)
- Modify: `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py:168-180` (constructor call)

**Step 1: Write the new test for the new fields**

Create: `modules/hooks-mode/tests/test_parse_contributes.py`

```python
"""Tests for the new `advertised` and `contributes` fields on ModeDefinition."""

from __future__ import annotations

import textwrap
from pathlib import Path

from amplifier_module_hooks_mode import parse_mode_file


def _write_mode_with_extras(
    path: Path,
    name: str,
    *,
    advertised: bool | None = None,
    contributes: str | None = None,
) -> Path:
    """Write a mode file with optional `advertised` and `contributes` blocks."""
    advertised_line = (
        f"  advertised: {'true' if advertised else 'false'}\n"
        if advertised is not None
        else ""
    )
    contributes_block = f"  contributes:\n{contributes}\n" if contributes else ""
    f = path / f"{name}.md"
    f.write_text(
        textwrap.dedent(f"""\
            ---
            mode:
              name: {name}
              description: "{name} mode"
            {advertised_line}{contributes_block}  tools:
                safe: [read_file, grep, delegate, load_skill]
              default_action: block
            ---
            # {name.title()}
            body
        """),
        encoding="utf-8",
    )
    return f


def test_parses_advertised_true(tmp_path: Path) -> None:
    f = _write_mode_with_extras(tmp_path, "showy", advertised=True)
    mode = parse_mode_file(f)
    assert mode is not None
    assert mode.advertised is True


def test_parses_advertised_false(tmp_path: Path) -> None:
    f = _write_mode_with_extras(tmp_path, "hidden", advertised=False)
    mode = parse_mode_file(f)
    assert mode is not None
    assert mode.advertised is False


def test_parses_contributes_agents(tmp_path: Path) -> None:
    contributes = "    agents:\n      mode-author:\n        source: \"@modes:agents/mode-author\""
    f = _write_mode_with_extras(tmp_path, "design", contributes=contributes)
    mode = parse_mode_file(f)
    assert mode is not None
    assert "agents" in mode.contributes
    assert "mode-author" in mode.contributes["agents"]
    assert (
        mode.contributes["agents"]["mode-author"]["source"]
        == "@modes:agents/mode-author"
    )


def test_parses_contributes_context_and_skills(tmp_path: Path) -> None:
    contributes = (
        "    context:\n"
        "      - \"@modes:context/schema.md\"\n"
        "    skills:\n"
        "      - \"@modes:skills/mode-design-discipline\""
    )
    f = _write_mode_with_extras(tmp_path, "design", contributes=contributes)
    mode = parse_mode_file(f)
    assert mode is not None
    assert mode.contributes.get("context") == ["@modes:context/schema.md"]
    assert mode.contributes.get("skills") == ["@modes:skills/mode-design-discipline"]
```

**Step 2: Run to verify failures**

Run: `cd $HOOKS_MODE && pytest tests/test_parse_contributes.py tests/test_backward_compat.py -v`
Expected: All four new tests in `test_parse_contributes.py` and the two failing tests from `test_backward_compat.py` FAIL with `AttributeError: 'ModeDefinition' object has no attribute 'advertised'`.

**Step 3: Implement — add the two fields to the dataclass and parser**

In `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py`:

**Edit A** — extend the `ModeDefinition` dataclass. Replace the existing block at lines 45-60:

```python
@dataclass
class ModeDefinition:
    """Parsed mode definition from a mode file."""

    name: str
    description: str = ""
    source: str = ""
    shortcut: str | None = None
    context: str = ""  # Markdown body - injected when mode active
    safe_tools: list[str] = field(default_factory=list)
    warn_tools: list[str] = field(default_factory=list)
    confirm_tools: list[str] = field(default_factory=list)  # Require user approval
    block_tools: list[str] = field(default_factory=list)
    default_action: str = "block"  # "block" or "allow"
    allowed_transitions: list[str] | None = None  # None = any transition allowed
    allow_clear: bool = True  # False = mode(clear) denied
```

with:

```python
@dataclass
class ModeDefinition:
    """Parsed mode definition from a mode file."""

    name: str
    description: str = ""
    source: str = ""
    shortcut: str | None = None
    context: str = ""  # Markdown body - injected when mode active
    safe_tools: list[str] = field(default_factory=list)
    warn_tools: list[str] = field(default_factory=list)
    confirm_tools: list[str] = field(default_factory=list)  # Require user approval
    block_tools: list[str] = field(default_factory=list)
    default_action: str = "block"  # "block" or "allow"
    allowed_transitions: list[str] | None = None  # None = any transition allowed
    allow_clear: bool = True  # False = mode(clear) denied
    advertised: bool = True  # NEW (Phase 2): False hides the mode from LLM-facing listings
    contributes: dict[str, Any] = field(
        default_factory=dict
    )  # NEW (Phase 2): runtime overlay contributions
```

**Edit B** — extend the `ModeDefinition(...)` constructor call in `parse_mode_file()`. The existing call is at approximately lines 168-180. Replace it with:

```python
    return ModeDefinition(
        name=resolved_name,
        description=mode_config.get("description", ""),
        shortcut=shortcut,
        context=markdown_body,
        safe_tools=tools_config.get("safe", []),
        warn_tools=tools_config.get("warn", []),
        confirm_tools=tools_config.get("confirm", []),
        block_tools=tools_config.get("block", []),
        default_action=mode_config.get("default_action", "block"),
        allowed_transitions=mode_config.get("allowed_transitions"),
        allow_clear=mode_config.get("allow_clear", True),
        advertised=mode_config.get("advertised", True),
        contributes=mode_config.get("contributes", {}) or {},
    )
```

(`or {}` guards against an empty `contributes:` key in YAML deserializing to `None`.)

**Step 4: Run tests to confirm green**

Run: `cd $HOOKS_MODE && pytest tests/test_parse_contributes.py tests/test_backward_compat.py tests/test_hooks.py -v`
Expected: all tests pass.

**Step 5: Commit**

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
git add modules/hooks-mode/amplifier_module_hooks_mode/__init__.py modules/hooks-mode/tests/test_parse_contributes.py
git commit -m "feat(hooks-mode): add advertised + contributes fields to ModeDefinition

Extends the mode YAML schema with two new top-level keys:
  - advertised: bool (default True) — hides mode from LLM-facing listings
  - contributes: dict (default {}) — runtime overlay contributions

Backward-compat preserved: legacy mode files (no advertised, no
contributes) parse identically to before with sensible defaults.

Phase 2 of mode runtime overlays. See docs/designs/MODE_RUNTIME_OVERLAYS.md.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 4: Parse-time lints — referential integrity

A mode that contributes agents but doesn't allow `delegate` is broken (the LLM has no way to reach the contributed agents). Same for skills + `load_skill`. We emit `logging.warning` per design §5.3 — the parse still succeeds.

**Files:**
- Modify: `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py` — `parse_mode_file()` (insert before the `return ModeDefinition(...)`)

**Step 1: Write the lint tests**

Append to `modules/hooks-mode/tests/test_parse_contributes.py`:

```python


import logging


def _write_mode_lint_case(
    path: Path,
    name: str,
    *,
    contributes: str,
    safe_tools: str = "[read_file]",
    default_action: str = "block",
) -> Path:
    f = path / f"{name}.md"
    f.write_text(
        textwrap.dedent(f"""\
            ---
            mode:
              name: {name}
              contributes:
            {contributes}
              tools:
                safe: {safe_tools}
              default_action: {default_action}
            ---
            body
        """),
        encoding="utf-8",
    )
    return f


def test_lint_warns_when_agents_contributed_but_delegate_blocked(
    tmp_path: Path, caplog
) -> None:
    contributes = "    agents:\n      mode-author:\n        source: \"@modes:agents/mode-author\""
    f = _write_mode_lint_case(
        tmp_path, "design", contributes=contributes, safe_tools="[read_file]"
    )
    with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
        mode = parse_mode_file(f)
    assert mode is not None  # parse still succeeds (warning, not error)
    assert any(
        "contributes agents" in r.message and "delegate" in r.message
        for r in caplog.records
    ), f"expected lint warning about delegate; got {[r.message for r in caplog.records]}"


def test_lint_warns_when_skills_contributed_but_load_skill_blocked(
    tmp_path: Path, caplog
) -> None:
    contributes = "    skills:\n      - \"@modes:skills/foo\""
    f = _write_mode_lint_case(
        tmp_path, "design", contributes=contributes, safe_tools="[read_file]"
    )
    with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
        mode = parse_mode_file(f)
    assert mode is not None
    assert any(
        "contributes skills" in r.message and "load_skill" in r.message
        for r in caplog.records
    ), f"expected lint warning about load_skill; got {[r.message for r in caplog.records]}"


def test_lint_silent_when_delegate_in_safe_tools(tmp_path: Path, caplog) -> None:
    contributes = "    agents:\n      a:\n        source: \"@modes:agents/a\""
    f = _write_mode_lint_case(
        tmp_path,
        "ok-mode",
        contributes=contributes,
        safe_tools="[read_file, delegate]",
    )
    with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
        mode = parse_mode_file(f)
    assert mode is not None
    assert not any(
        "delegate" in r.message and "unreachable" in r.message
        for r in caplog.records
    )


def test_lint_silent_when_default_action_is_allow(tmp_path: Path, caplog) -> None:
    contributes = "    agents:\n      a:\n        source: \"@modes:agents/a\""
    f = _write_mode_lint_case(
        tmp_path,
        "permissive",
        contributes=contributes,
        safe_tools="[read_file]",
        default_action="allow",
    )
    with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
        mode = parse_mode_file(f)
    assert mode is not None
    assert not any(
        "unreachable" in r.message for r in caplog.records
    )
```

**Step 2: Run to verify failures**

Run: `cd $HOOKS_MODE && pytest tests/test_parse_contributes.py -v -k lint`
Expected: the two `_warns_*` tests FAIL because no warning is emitted yet. The two `_silent_*` tests pass.

**Step 3: Implement the lints**

In `parse_mode_file()`, immediately before the `return ModeDefinition(...)` line, add:

```python
    # Phase 2: Parse-time referential-integrity lints.
    # Modes that contribute agents/skills but block the access tool will silently
    # produce unreachable capabilities. Warn (don't fail) so the parse still loads.
    contributes_block = mode_config.get("contributes", {}) or {}
    safe_list = list(tools_config.get("safe", []) or [])
    default_action_value = mode_config.get("default_action", "block")
    if (
        contributes_block.get("agents")
        and "delegate" not in safe_list
        and default_action_value != "allow"
    ):
        logger.warning(
            "Mode '%s' contributes agents but does not allow `delegate` in tools.safe "
            "(and default_action is not 'allow') — contributed agents will be unreachable "
            "by the LLM while this mode is active.",
            resolved_name,
        )
    if (
        contributes_block.get("skills")
        and "load_skill" not in safe_list
        and default_action_value != "allow"
    ):
        logger.warning(
            "Mode '%s' contributes skills but does not allow `load_skill` in tools.safe "
            "(and default_action is not 'allow') — contributed skills will be undiscoverable "
            "by the LLM while this mode is active.",
            resolved_name,
        )
```

**Step 4: Run all tests**

Run: `cd $HOOKS_MODE && pytest tests/ -v`
Expected: all tests pass.

**Step 5: Commit**

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
git add modules/hooks-mode/amplifier_module_hooks_mode/__init__.py modules/hooks-mode/tests/test_parse_contributes.py
git commit -m "feat(hooks-mode): warn at parse time on broken contributes/tools combos

Adds two referential-integrity lints that emit logger.warning (parse
still succeeds, mode still loads):

  - contributes.agents non-empty but delegate blocked → warn
  - contributes.skills non-empty but load_skill blocked → warn

Skipped when default_action='allow'. Tool-name lint deferred to v1.1
(when contributes.tools is in scope). Per design §5.3.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 5: Add new event constants

**Files:**
- Modify: `modules/hooks-mode/amplifier_module_hooks_mode/events.py`

**Step 1: Write the event-presence test**

Create: `modules/hooks-mode/tests/test_events.py`

```python
"""Tests for the Phase-2 event constants."""

from __future__ import annotations


def test_mode_transition_completed_constant_exists() -> None:
    from amplifier_module_hooks_mode.events import MODE_TRANSITION_COMPLETED
    assert MODE_TRANSITION_COMPLETED == "mode:transition_completed"


def test_mode_activation_failed_constant_exists() -> None:
    from amplifier_module_hooks_mode.events import MODE_ACTIVATION_FAILED
    assert MODE_ACTIVATION_FAILED == "mode:activation_failed"


def test_all_events_includes_new_constants() -> None:
    from amplifier_module_hooks_mode.events import (
        ALL_EVENTS,
        MODE_ACTIVATION_FAILED,
        MODE_TRANSITION_COMPLETED,
    )
    assert MODE_TRANSITION_COMPLETED in ALL_EVENTS
    assert MODE_ACTIVATION_FAILED in ALL_EVENTS
```

**Step 2: Verify failure**

Run: `cd $HOOKS_MODE && pytest tests/test_events.py -v`
Expected: all three tests FAIL with `ImportError: cannot import name 'MODE_TRANSITION_COMPLETED'`.

**Step 3: Implement**

Replace the entire contents of `modules/hooks-mode/amplifier_module_hooks_mode/events.py` with:

```python
"""Event constants for the hooks-mode module.

Defines the string event identifiers emitted by hooks-mode during
tool moderation, context injection, and mode-transition lifecycle.
"""

from __future__ import annotations

MODE_TOOL_BLOCKED: str = "mode:tool_blocked"
MODE_TOOL_WARNED: str = "mode:tool_warned"
MODE_CONTEXT_INJECTED: str = "mode:context_injected"
MODE_TRANSITION_COMPLETED: str = "mode:transition_completed"
MODE_ACTIVATION_FAILED: str = "mode:activation_failed"

ALL_EVENTS: list[str] = [
    MODE_TOOL_BLOCKED,
    MODE_TOOL_WARNED,
    MODE_CONTEXT_INJECTED,
    MODE_TRANSITION_COMPLETED,
    MODE_ACTIVATION_FAILED,
]
```

**Step 4: Run tests**

Run: `cd $HOOKS_MODE && pytest tests/test_events.py tests/test_hooks.py -v`
Expected: all tests pass (including `TestEventsContributorRegistration::test_mount_registers_observability_events_contributor`, which checks `supplier() == ALL_EVENTS` — the longer list is fine, it's `==`-comparing the supplier output, which now includes the two new events).

**Step 5: Commit**

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
git add modules/hooks-mode/amplifier_module_hooks_mode/events.py modules/hooks-mode/tests/test_events.py
git commit -m "feat(hooks-mode): add MODE_TRANSITION_COMPLETED and MODE_ACTIVATION_FAILED events

These will be emitted by the Phase 2 transition handlers (Tasks 7-9).
Adding them now so the event catalog is complete and contributed to
observability.events at mount time.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 6: `ModeDiscovery.list_modes` — `include_unadvertised` filter

**Files:**
- Modify: `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py:395-412` (`list_modes` method)

**Step 1: Write the filter tests**

Create: `modules/hooks-mode/tests/test_list_modes_filter.py`

```python
"""Tests for ModeDiscovery.list_modes(include_unadvertised=...)."""

from __future__ import annotations

import textwrap
from pathlib import Path

from amplifier_module_hooks_mode import ModeDiscovery


def _write(path: Path, name: str, *, advertised: bool = True) -> None:
    (path / f"{name}.md").write_text(
        textwrap.dedent(f"""\
            ---
            mode:
              name: {name}
              description: "{name} mode"
              advertised: {'true' if advertised else 'false'}
              tools:
                safe: [read_file]
              default_action: block
            ---
            body
        """),
        encoding="utf-8",
    )


def test_default_hides_unadvertised(tmp_path: Path) -> None:
    _write(tmp_path, "public", advertised=True)
    _write(tmp_path, "secret", advertised=False)
    discovery = ModeDiscovery(search_paths=[tmp_path])
    names = [n for (n, _d, _s) in discovery.list_modes()]
    assert "public" in names
    assert "secret" not in names


def test_include_unadvertised_true_shows_all(tmp_path: Path) -> None:
    _write(tmp_path, "public", advertised=True)
    _write(tmp_path, "secret", advertised=False)
    discovery = ModeDiscovery(search_paths=[tmp_path])
    names = [n for (n, _d, _s) in discovery.list_modes(include_unadvertised=True)]
    assert "public" in names
    assert "secret" in names


def test_legacy_mode_with_no_advertised_field_is_listed(tmp_path: Path) -> None:
    """Pre-Phase-2 mode files (no `advertised:` key) default to advertised=True
    and must appear in the default listing."""
    legacy_file = tmp_path / "plan.md"
    legacy_file.write_text(
        textwrap.dedent("""\
            ---
            mode:
              name: plan
              description: "plan"
              tools:
                safe: [read_file]
              default_action: block
            ---
            body
        """),
        encoding="utf-8",
    )
    discovery = ModeDiscovery(search_paths=[tmp_path])
    names = [n for (n, _d, _s) in discovery.list_modes()]
    assert "plan" in names


def test_tool_mode_list_default_hides_unadvertised(tmp_path: Path) -> None:
    """Regression: tool-mode's list operation calls discovery.list_modes() with no
    args; with our new default (include_unadvertised=False), unadvertised modes
    are hidden from the LLM-facing list."""
    _write(tmp_path, "public", advertised=True)
    _write(tmp_path, "secret", advertised=False)
    discovery = ModeDiscovery(search_paths=[tmp_path])
    # Simulate tool-mode's call site: positional, no kwargs.
    listed = discovery.list_modes()
    names = {n for (n, _d, _s) in listed}
    assert names == {"public"}
```

**Step 2: Verify failure**

Run: `cd $HOOKS_MODE && pytest tests/test_list_modes_filter.py -v`
Expected: `test_default_hides_unadvertised`, `test_include_unadvertised_true_shows_all`, `test_tool_mode_list_default_hides_unadvertised` all FAIL (currently `secret` is included). `test_legacy_mode_with_no_advertised_field_is_listed` passes.

**Step 3: Implement the filter**

In `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py`, replace the existing `list_modes` method (around lines 395-412):

```python
    def list_modes(self) -> list[tuple[str, str, str]]:
        """List all available modes as (name, description, source) tuples."""
        self._ensure_bundle_discovery()
        modes: dict[str, tuple[str, str]] = {}

        for base_path, source_label in self._search_paths:
            if not base_path.exists():
                continue
            for mode_file in base_path.glob("*.md"):
                name = mode_file.stem
                if name not in modes:  # First match wins (precedence)
                    mode_def = parse_mode_file(mode_file)
                    if mode_def:
                        mode_def.source = source_label
                        modes[name] = (mode_def.description, source_label)
                        self._cache[name] = mode_def

        return sorted((name, desc, source) for name, (desc, source) in modes.items())
```

with:

```python
    def list_modes(
        self, include_unadvertised: bool = False
    ) -> list[tuple[str, str, str]]:
        """List available modes as (name, description, source) tuples.

        Args:
            include_unadvertised: If False (default), modes with `advertised: false`
                are excluded from the result — this is the LLM-facing listing.
                If True, all modes are returned — used by human-facing surfaces
                (e.g. the CLI's `/modes --all`).
        """
        self._ensure_bundle_discovery()
        modes: dict[str, tuple[str, str]] = {}

        for base_path, source_label in self._search_paths:
            if not base_path.exists():
                continue
            for mode_file in base_path.glob("*.md"):
                name = mode_file.stem
                if name not in modes:  # First match wins (precedence)
                    mode_def = parse_mode_file(mode_file)
                    if mode_def:
                        if not include_unadvertised and not mode_def.advertised:
                            continue
                        mode_def.source = source_label
                        modes[name] = (mode_def.description, source_label)
                        self._cache[name] = mode_def

        return sorted((name, desc, source) for name, (desc, source) in modes.items())
```

**Step 4: Run tests**

Run: `cd $HOOKS_MODE && pytest tests/ -v`
Expected: all tests pass.

**Step 5: Commit**

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
git add modules/hooks-mode/amplifier_module_hooks_mode/__init__.py modules/hooks-mode/tests/test_list_modes_filter.py
git commit -m "feat(hooks-mode): list_modes() hides advertised=false modes by default

Adds include_unadvertised parameter to ModeDiscovery.list_modes (default
False). The LLM-facing tool-mode.list operation calls with no args and
therefore hides unadvertised modes; the CLI can call with True for the
human-facing /modes --all listing.

Backward-compatible: existing callers see no behavior change for modes
without advertised: false.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 7: `handle_mode_activated` transition handler

This is where Phase 2 connects to Phase 1's `RuntimeOverlay`. The handler is called when `tool-mode` emits `mode:activated`. It looks up the active mode, calls `RuntimeOverlay.apply(scope, contributes)`, and emits a single `mode:transition_completed` (or `mode:activation_failed` on error).

**Important — singleton overlay storage.** We use `coordinator.session_state["mode_runtime_overlay"]` as the storage slot for the singleton `RuntimeOverlay`. We instantiate it lazily on first activation and reuse it for all later transitions. This keeps refcounts coherent across activations.

**Files:**
- Modify: `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py` — add method to `ModeHooks` class (around line 692, before `reset_warnings`).

**Step 1: Write the test**

Create: `modules/hooks-mode/tests/test_transition_handlers.py`

```python
"""Tests for ModeHooks transition handlers (mode:activated/changed/cleared)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks


def _make_coordinator(active_mode: str | None = None) -> MagicMock:
    coordinator = MagicMock()
    coordinator.session_state = {
        "active_mode": active_mode,
        "require_approval_tools": set(),
    }
    coordinator.hooks = MagicMock()
    coordinator.hooks.emit = AsyncMock()
    coordinator.get_capability = MagicMock(return_value=None)
    return coordinator


def _write_mode(
    path: Path, name: str, *, contributes: dict | None = None
) -> None:
    contrib_block = ""
    if contributes:
        import yaml

        contrib_yaml = yaml.safe_dump({"contributes": contributes}, default_flow_style=False)
        contrib_block = textwrap.indent(contrib_yaml, "  ")
    (path / f"{name}.md").write_text(
        f"""---
mode:
  name: {name}
  description: "{name} mode"
{contrib_block}  tools:
    safe: [read_file, delegate, load_skill]
  default_action: block
---
body
""",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_activated_handler_calls_overlay_apply(tmp_path: Path) -> None:
    """On mode:activated, the handler must call RuntimeOverlay.apply with the
    correct scope name and the mode's contributes block."""
    from amplifier_module_hooks_mode.events import MODE_TRANSITION_COMPLETED

    contributes = {"agents": {"a": {"source": "@modes:agents/a"}}}
    _write_mode(tmp_path, "design", contributes=contributes)

    coordinator = _make_coordinator(active_mode="design")
    discovery = ModeDiscovery(search_paths=[tmp_path])
    hooks = ModeHooks(coordinator, discovery)

    fake_overlay = MagicMock()
    fake_overlay.apply = MagicMock(return_value=MagicMock(success=True))
    coordinator.session_state["mode_runtime_overlay"] = fake_overlay

    result = await hooks.handle_mode_activated("mode:activated", {"name": "design"})

    fake_overlay.apply.assert_called_once()
    call_args = fake_overlay.apply.call_args
    scope = call_args.args[0] if call_args.args else call_args.kwargs.get("scope_name")
    contribs = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("contributions")
    assert scope == "mode:design"
    assert contribs == contributes
    coordinator.hooks.emit.assert_any_await(
        MODE_TRANSITION_COMPLETED, {"mode": "design", "phase": "activated"}
    )
    assert result.action == "continue"


@pytest.mark.asyncio
async def test_activated_handler_emits_failure_event_on_apply_failure(
    tmp_path: Path,
) -> None:
    """If RuntimeOverlay.apply raises or returns a failure result, the handler
    must emit mode:activation_failed and still return action='continue'."""
    from amplifier_module_hooks_mode.events import MODE_ACTIVATION_FAILED

    contributes = {"agents": {"a": {"source": "@modes:agents/a"}}}
    _write_mode(tmp_path, "design", contributes=contributes)

    coordinator = _make_coordinator(active_mode="design")
    discovery = ModeDiscovery(search_paths=[tmp_path])
    hooks = ModeHooks(coordinator, discovery)

    fake_overlay = MagicMock()
    fake_overlay.apply = MagicMock(side_effect=RuntimeError("boom"))
    coordinator.session_state["mode_runtime_overlay"] = fake_overlay

    result = await hooks.handle_mode_activated("mode:activated", {"name": "design"})

    coordinator.hooks.emit.assert_any_await(
        MODE_ACTIVATION_FAILED,
        {"mode": "design", "error": "boom"},
    )
    assert result.action == "continue"


@pytest.mark.asyncio
async def test_activated_handler_no_contributes_is_noop(tmp_path: Path) -> None:
    """If the activated mode has no contributes block, the handler must NOT call
    RuntimeOverlay.apply but should still emit MODE_TRANSITION_COMPLETED."""
    from amplifier_module_hooks_mode.events import MODE_TRANSITION_COMPLETED

    _write_mode(tmp_path, "plain")
    coordinator = _make_coordinator(active_mode="plain")
    discovery = ModeDiscovery(search_paths=[tmp_path])
    hooks = ModeHooks(coordinator, discovery)

    fake_overlay = MagicMock()
    fake_overlay.apply = MagicMock(return_value=MagicMock(success=True))
    coordinator.session_state["mode_runtime_overlay"] = fake_overlay

    result = await hooks.handle_mode_activated("mode:activated", {"name": "plain"})

    fake_overlay.apply.assert_not_called()
    coordinator.hooks.emit.assert_any_await(
        MODE_TRANSITION_COMPLETED, {"mode": "plain", "phase": "activated"}
    )
    assert result.action == "continue"
```

**Step 2: Verify failure**

Run: `cd $HOOKS_MODE && pytest tests/test_transition_handlers.py -v`
Expected: all three tests FAIL with `AttributeError: 'ModeHooks' object has no attribute 'handle_mode_activated'`.

**Step 3: Implement `handle_mode_activated`**

In `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py`, find the `reset_warnings` method on `ModeHooks` (currently around line 692). **Insert before it** (so the new methods sit at the end of the class body before `reset_warnings`):

```python
    def _get_or_create_overlay(self) -> Any:
        """Get the singleton RuntimeOverlay for this session, creating it lazily.

        Stored in session_state so it survives across activations and
        deactivations within a single session, keeping refcounts coherent.
        """
        overlay = self.coordinator.session_state.get("mode_runtime_overlay")
        if overlay is None:
            from amplifier_foundation import RuntimeOverlay

            overlay = RuntimeOverlay(self.coordinator)
            self.coordinator.session_state["mode_runtime_overlay"] = overlay
        return overlay

    async def handle_mode_activated(
        self, _event: str, data: dict
    ) -> "HookResult":
        """Apply the activated mode's contributions via RuntimeOverlay.

        On any failure: emit mode:activation_failed with the error message and
        return continue (the mode is still active for context-injection
        purposes; only the contributions failed). The RuntimeOverlay primitive
        is responsible for atomic rollback within itself; the handler's job is
        to dispatch and report.
        """
        from amplifier_core.models import HookResult
        from .events import MODE_ACTIVATION_FAILED, MODE_TRANSITION_COMPLETED

        mode_name = data.get("name") or self.coordinator.session_state.get(
            "active_mode"
        )
        if not mode_name:
            return HookResult(action="continue")

        try:
            mode_def = self.discovery.find(mode_name)
            if mode_def and mode_def.contributes:
                overlay = self._get_or_create_overlay()
                overlay.apply(f"mode:{mode_name}", mode_def.contributes)

            await self.coordinator.hooks.emit(
                MODE_TRANSITION_COMPLETED,
                {"mode": mode_name, "phase": "activated"},
            )
        except Exception as exc:
            logger.warning(
                "handle_mode_activated: overlay apply failed for mode '%s': %s",
                mode_name,
                exc,
                exc_info=True,
            )
            await self.coordinator.hooks.emit(
                MODE_ACTIVATION_FAILED,
                {"mode": mode_name, "error": str(exc)},
            )

        return HookResult(action="continue")
```

**Step 4: Run tests**

Run: `cd $HOOKS_MODE && pytest tests/test_transition_handlers.py -v`
Expected: all three tests pass.

**Step 5: Commit**

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
git add modules/hooks-mode/amplifier_module_hooks_mode/__init__.py modules/hooks-mode/tests/test_transition_handlers.py
git commit -m "feat(hooks-mode): add handle_mode_activated transition handler

On mode:activated, look up the activated mode, get/create a singleton
RuntimeOverlay (stored in session_state), and call apply(scope_name,
contributions). Emits mode:transition_completed on success, or
mode:activation_failed on apply failure (handler is non-fatal — the
mode is still active for context-injection purposes).

Phase 2 of mode runtime overlays.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 8: `handle_mode_changed` transition handler

`mode:changed` is emitted by `tool-mode` when one mode is replaced by another in a single transition. Payload: `{"old": old_name, "new": new_name}`. We revoke the old scope, then apply the new one.

**Files:**
- Modify: `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py` — add to `ModeHooks` after `handle_mode_activated`.

**Step 1: Write the test**

Append to `modules/hooks-mode/tests/test_transition_handlers.py`:

```python


@pytest.mark.asyncio
async def test_changed_handler_revokes_old_then_applies_new(tmp_path: Path) -> None:
    """On mode:changed, the handler must revoke the old mode's scope and apply
    the new mode's contributions, in that order."""
    from amplifier_module_hooks_mode.events import MODE_TRANSITION_COMPLETED

    _write_mode(tmp_path, "old-mode", contributes={"context": ["@a:b.md"]})
    _write_mode(tmp_path, "new-mode", contributes={"agents": {"x": {"source": "@y:z"}}})

    coordinator = _make_coordinator(active_mode="new-mode")
    discovery = ModeDiscovery(search_paths=[tmp_path])
    hooks = ModeHooks(coordinator, discovery)

    fake_overlay = MagicMock()
    call_log: list[tuple[str, str]] = []
    fake_overlay.revoke = MagicMock(
        side_effect=lambda scope: call_log.append(("revoke", scope))
        or MagicMock(success=True)
    )
    fake_overlay.apply = MagicMock(
        side_effect=lambda scope, contribs: call_log.append(("apply", scope))
        or MagicMock(success=True)
    )
    coordinator.session_state["mode_runtime_overlay"] = fake_overlay

    result = await hooks.handle_mode_changed(
        "mode:changed", {"old": "old-mode", "new": "new-mode"}
    )

    assert call_log == [("revoke", "mode:old-mode"), ("apply", "mode:new-mode")]
    coordinator.hooks.emit.assert_any_await(
        MODE_TRANSITION_COMPLETED, {"mode": "new-mode", "phase": "changed"}
    )
    assert result.action == "continue"


@pytest.mark.asyncio
async def test_changed_handler_emits_failure_on_apply_error(tmp_path: Path) -> None:
    """If apply of the new mode fails, the handler must emit
    mode:activation_failed (the revoke of the old mode already succeeded)."""
    from amplifier_module_hooks_mode.events import MODE_ACTIVATION_FAILED

    _write_mode(tmp_path, "old-mode", contributes={"context": ["@a:b.md"]})
    _write_mode(tmp_path, "new-mode", contributes={"agents": {"x": {"source": "@y:z"}}})

    coordinator = _make_coordinator(active_mode="new-mode")
    discovery = ModeDiscovery(search_paths=[tmp_path])
    hooks = ModeHooks(coordinator, discovery)

    fake_overlay = MagicMock()
    fake_overlay.revoke = MagicMock(return_value=MagicMock(success=True))
    fake_overlay.apply = MagicMock(side_effect=RuntimeError("apply failed"))
    coordinator.session_state["mode_runtime_overlay"] = fake_overlay

    result = await hooks.handle_mode_changed(
        "mode:changed", {"old": "old-mode", "new": "new-mode"}
    )

    coordinator.hooks.emit.assert_any_await(
        MODE_ACTIVATION_FAILED,
        {"mode": "new-mode", "error": "apply failed"},
    )
    assert result.action == "continue"
```

**Step 2: Verify failure**

Run: `cd $HOOKS_MODE && pytest tests/test_transition_handlers.py -v -k changed`
Expected: both new tests FAIL with `AttributeError: 'ModeHooks' object has no attribute 'handle_mode_changed'`.

**Step 3: Implement**

Insert immediately after `handle_mode_activated` in `ModeHooks`:

```python
    async def handle_mode_changed(self, _event: str, data: dict) -> "HookResult":
        """Revoke old mode's scope, then apply new mode's scope.

        Payload: {"old": <old_name>, "new": <new_name>}. Either may be falsy
        (in practice tool-mode always emits both, but defensive code costs
        nothing here). On any error, emit mode:activation_failed and continue.
        """
        from amplifier_core.models import HookResult
        from .events import MODE_ACTIVATION_FAILED, MODE_TRANSITION_COMPLETED

        old_name = data.get("old")
        new_name = data.get("new")

        try:
            overlay = self._get_or_create_overlay()
            if old_name:
                overlay.revoke(f"mode:{old_name}")
            if new_name:
                new_def = self.discovery.find(new_name)
                if new_def and new_def.contributes:
                    overlay.apply(f"mode:{new_name}", new_def.contributes)

            await self.coordinator.hooks.emit(
                MODE_TRANSITION_COMPLETED,
                {"mode": new_name, "phase": "changed"},
            )
        except Exception as exc:
            logger.warning(
                "handle_mode_changed: overlay transition failed (old=%s, new=%s): %s",
                old_name,
                new_name,
                exc,
                exc_info=True,
            )
            await self.coordinator.hooks.emit(
                MODE_ACTIVATION_FAILED,
                {"mode": new_name, "error": str(exc)},
            )

        return HookResult(action="continue")
```

**Step 4: Run tests**

Run: `cd $HOOKS_MODE && pytest tests/test_transition_handlers.py -v`
Expected: all five tests pass.

**Step 5: Commit**

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
git add modules/hooks-mode/amplifier_module_hooks_mode/__init__.py modules/hooks-mode/tests/test_transition_handlers.py
git commit -m "feat(hooks-mode): add handle_mode_changed transition handler

On mode:changed, revoke the old mode's scope then apply the new mode's
contributions. Emits mode:transition_completed on success or
mode:activation_failed on error.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 9: `handle_mode_cleared` transition handler

`mode:cleared` payload from tool-mode: `{"name": <cleared_name>}`. Just revoke.

**Files:**
- Modify: `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py` — add to `ModeHooks` after `handle_mode_changed`.

**Step 1: Write the test**

Append to `modules/hooks-mode/tests/test_transition_handlers.py`:

```python


@pytest.mark.asyncio
async def test_cleared_handler_revokes_scope(tmp_path: Path) -> None:
    from amplifier_module_hooks_mode.events import MODE_TRANSITION_COMPLETED

    _write_mode(tmp_path, "design", contributes={"context": ["@a:b.md"]})

    coordinator = _make_coordinator(active_mode=None)
    discovery = ModeDiscovery(search_paths=[tmp_path])
    hooks = ModeHooks(coordinator, discovery)

    fake_overlay = MagicMock()
    fake_overlay.revoke = MagicMock(return_value=MagicMock(success=True))
    coordinator.session_state["mode_runtime_overlay"] = fake_overlay

    result = await hooks.handle_mode_cleared("mode:cleared", {"name": "design"})

    fake_overlay.revoke.assert_called_once_with("mode:design")
    coordinator.hooks.emit.assert_any_await(
        MODE_TRANSITION_COMPLETED, {"mode": "design", "phase": "cleared"}
    )
    assert result.action == "continue"


@pytest.mark.asyncio
async def test_cleared_handler_handles_revoke_error(tmp_path: Path) -> None:
    from amplifier_module_hooks_mode.events import MODE_ACTIVATION_FAILED

    _write_mode(tmp_path, "design", contributes={"context": ["@a:b.md"]})

    coordinator = _make_coordinator(active_mode=None)
    discovery = ModeDiscovery(search_paths=[tmp_path])
    hooks = ModeHooks(coordinator, discovery)

    fake_overlay = MagicMock()
    fake_overlay.revoke = MagicMock(side_effect=RuntimeError("nope"))
    coordinator.session_state["mode_runtime_overlay"] = fake_overlay

    result = await hooks.handle_mode_cleared("mode:cleared", {"name": "design"})

    coordinator.hooks.emit.assert_any_await(
        MODE_ACTIVATION_FAILED, {"mode": "design", "error": "nope"}
    )
    assert result.action == "continue"
```

**Step 2: Verify failure**

Run: `cd $HOOKS_MODE && pytest tests/test_transition_handlers.py -v -k cleared`
Expected: both new tests FAIL with `AttributeError: 'ModeHooks' object has no attribute 'handle_mode_cleared'`.

**Step 3: Implement**

Insert immediately after `handle_mode_changed`:

```python
    async def handle_mode_cleared(self, _event: str, data: dict) -> "HookResult":
        """Revoke the cleared mode's scope.

        Payload: {"name": <cleared_name>}. On any error, emit
        mode:activation_failed and continue (revocation should be best-effort
        — leftover state is far better than a broken transition).
        """
        from amplifier_core.models import HookResult
        from .events import MODE_ACTIVATION_FAILED, MODE_TRANSITION_COMPLETED

        mode_name = data.get("name")
        if not mode_name:
            return HookResult(action="continue")

        try:
            overlay = self._get_or_create_overlay()
            overlay.revoke(f"mode:{mode_name}")
            await self.coordinator.hooks.emit(
                MODE_TRANSITION_COMPLETED,
                {"mode": mode_name, "phase": "cleared"},
            )
        except Exception as exc:
            logger.warning(
                "handle_mode_cleared: overlay revoke failed for mode '%s': %s",
                mode_name,
                exc,
                exc_info=True,
            )
            await self.coordinator.hooks.emit(
                MODE_ACTIVATION_FAILED,
                {"mode": mode_name, "error": str(exc)},
            )

        return HookResult(action="continue")
```

**Step 4: Run tests**

Run: `cd $HOOKS_MODE && pytest tests/test_transition_handlers.py -v`
Expected: all seven tests pass.

**Step 5: Commit**

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
git add modules/hooks-mode/amplifier_module_hooks_mode/__init__.py modules/hooks-mode/tests/test_transition_handlers.py
git commit -m "feat(hooks-mode): add handle_mode_cleared transition handler

On mode:cleared, revoke the cleared mode's scope. Emits
mode:transition_completed on success or mode:activation_failed on error.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 10: Wire the three handlers in `mount()`

The transition handlers exist on `ModeHooks` but are not yet registered with the coordinator. Register them in `mount()` after the existing `tool:pre` registration (around line 810).

**Files:**
- Modify: `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py:805-810` — add three new `coordinator.hooks.register(...)` calls.

**Step 1: Write the registration test**

Append to `modules/hooks-mode/tests/test_transition_handlers.py`:

```python


@pytest.mark.asyncio
async def test_mount_registers_three_transition_handlers(tmp_path: Path) -> None:
    """mount() must register handle_mode_activated, handle_mode_changed,
    and handle_mode_cleared on their respective kernel events."""
    from amplifier_module_hooks_mode import mount

    modes_dir = tmp_path / "modes"
    modes_dir.mkdir()
    (modes_dir / "x.md").write_text(
        textwrap.dedent("""\
            ---
            mode:
              name: x
              tools:
                safe: [read_file]
              default_action: block
            ---
            body
        """),
        encoding="utf-8",
    )

    coordinator = _make_coordinator()
    coordinator.register_contributor = MagicMock()

    await mount(coordinator, {"search_paths": [str(modes_dir)]})

    registered_events: dict[str, str] = {}
    for call in coordinator.hooks.register.call_args_list:
        args, kwargs = call
        event = args[0]
        name = kwargs.get("name")
        if name:
            registered_events[name] = event

    assert registered_events.get("mode-overlay-activate") == "mode:activated"
    assert registered_events.get("mode-overlay-change") == "mode:changed"
    assert registered_events.get("mode-overlay-clear") == "mode:cleared"
```

**Step 2: Verify failure**

Run: `cd $HOOKS_MODE && pytest tests/test_transition_handlers.py -v -k mount_registers`
Expected: FAIL with `assert None == 'mode:activated'` (the new register names don't exist).

**Step 3: Implement — add registrations in `mount()`**

In `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py`, find the existing `tool:pre` registration (around line 805-810):

```python
    coordinator.hooks.register(
        "tool:pre",
        hooks.handle_tool_pre,
        priority=-20,
        name="mode-tools",
    )
```

**Insert immediately after that block** (still inside `mount()`, before the `coordinator.register_contributor(...)` call):

```python
    # Phase 2: register mode-transition handlers that drive RuntimeOverlay
    # apply/revoke on the lifecycle events emitted by tool-mode.
    coordinator.hooks.register(
        "mode:activated",
        hooks.handle_mode_activated,
        name="mode-overlay-activate",
    )
    coordinator.hooks.register(
        "mode:changed",
        hooks.handle_mode_changed,
        name="mode-overlay-change",
    )
    coordinator.hooks.register(
        "mode:cleared",
        hooks.handle_mode_cleared,
        name="mode-overlay-clear",
    )
```

**Step 4: Run all tests**

Run: `cd $HOOKS_MODE && pytest tests/ -v`
Expected: all tests pass.

**Step 5: Commit**

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
git add modules/hooks-mode/amplifier_module_hooks_mode/__init__.py modules/hooks-mode/tests/test_transition_handlers.py
git commit -m "feat(hooks-mode): wire transition handlers in mount()

Registers handle_mode_activated/changed/cleared on the corresponding
mode:* kernel events emitted by tool-mode. Names: mode-overlay-activate,
mode-overlay-change, mode-overlay-clear.

This completes the Phase 2 modes-bundle integration. Activation now
drives RuntimeOverlay.apply via the kernel hook bus.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 11: Final regression sweep + Phase 2 sign-off

**Files:**
- No code changes — verification only.

**Step 1: Run the full test suite**

Run: `cd $HOOKS_MODE && pytest tests/ -v`
Expected: every test passes. Take note of the count.

**Step 2: Sanity-check existing built-in modes still parse**

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
python -c "
from pathlib import Path
from amplifier_module_hooks_mode import parse_mode_file
for p in sorted(Path('modes').glob('*.md')):
    md = parse_mode_file(p)
    assert md is not None, f'failed to parse {p}'
    assert md.advertised is True, f'{p}: advertised default broken'
    assert md.contributes == {}, f'{p}: contributes default broken'
    print(f'OK {md.name}: advertised={md.advertised} contributes={md.contributes}')
"
```
Expected: prints `OK plan: ...`, `OK careful: ...`, `OK explore: ...` (or whatever the bundle's modes are) — all advertised, all empty contributes. No assertion errors.

**Step 3: Verify the Phase 1 → Phase 2 connection point still resolves**

Run: `cd $HOOKS_MODE && python -c "from amplifier_module_hooks_mode import ModeHooks; from amplifier_foundation import RuntimeOverlay; print('ModeHooks methods:', sorted(m for m in dir(ModeHooks) if m.startswith('handle_')))"`
Expected:
```
ModeHooks methods: ['handle_mode_activated', 'handle_mode_changed', 'handle_mode_cleared', 'handle_provider_request', 'handle_tool_pre']
```

**Step 4: (no run)**

**Step 5: Tag the phase complete**

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
git log --oneline -n 11
```

Expected: a clean ladder of 11 commits (one per task) all on the current branch. Optionally tag:

```bash
git tag phase-2-modes-bundle-complete
```

---

## Phase 2 Complete — Checklist

Before declaring Phase 2 done and unblocking Phase 3, confirm all of:

- [ ] **All Phase 2 tests pass.** `pytest tests/ -v` is fully green in `$HOOKS_MODE`.
- [ ] **Existing modes still parse and behave identically.** Step 2 of Task 11 prints all bundled modes parsing with `advertised=True` and `contributes={}`. Existing tests in `test_hooks.py` remain green throughout.
- [ ] **`RuntimeOverlay` from Phase 1 is being called from `handle_mode_activated`.** Confirmed by `test_activated_handler_calls_overlay_apply` and the import-path check in Task 11 Step 3.
- [ ] **Three new hooks are registered.** Confirmed by `test_mount_registers_three_transition_handlers`: `mode:activated → mode-overlay-activate`, `mode:changed → mode-overlay-change`, `mode:cleared → mode-overlay-clear`.
- [ ] **`advertised: false` modes are hidden by default.** Confirmed by `test_default_hides_unadvertised` and `test_tool_mode_list_default_hides_unadvertised`.
- [ ] **Parse-time lints fire on broken combos.** Confirmed by the four lint tests in `test_parse_contributes.py`.
- [ ] **Two new event constants are in `ALL_EVENTS`.** Confirmed by `test_events.py` and the existing `test_mount_registers_observability_events_contributor` test continues to pass with the longer list.
- [ ] **No changes to `behaviors/modes.yaml`, `modules/tool-mode/`, or any non-Phase-2 code path.** `git diff main..HEAD --stat` should only touch `modules/hooks-mode/**`.

**Phase 3 (vertical slice — `/mode-design` mode + integration tests for S1–S4) is now unblocked.** Phase 3 will:
1. Add the `/mode-design` mode YAML under `modes/`.
2. Add the `mode-author` agent under `agents/`.
3. Add the `mode-schema-reference.md` context file.
4. Add the `mode-design-discipline` skill.
5. Add integration tests that activate `/mode-design` against a real `RuntimeOverlay` and verify S1–S4 overlap behavior end-to-end.
