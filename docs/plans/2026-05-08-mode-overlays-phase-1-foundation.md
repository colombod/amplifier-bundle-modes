# Mode Runtime Overlays — Phase 1: Foundation Infrastructure Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Land the foundation-layer primitives that Phases 2 and 3 will consume: a mode-frontmatter loader, a `Bundle.prepare()` modes-walk that validates `contributes` schema, and a `RuntimeOverlay` class with refcount-based atomic apply/revoke.

**Architecture:** This phase is a strict mirror of the agent-tool-spawn precedent (commits `96f45b0`, `9f129c2`, `39b970c`). The new `_load_mode_file_metadata()` mirrors `_load_agent_file_metadata()` (`_dataclass.py:678-735`) but reads from the `mode:` key. The `Bundle.prepare()` modes walk inserts after the agents walk (`_dataclass.py:404-430`). The new `RuntimeOverlay` class is a peer of `SessionConfigurator` — it lives in `amplifier_foundation/configurator/_overlay.py`, drives the same live `coordinator.mount/unmount` paths, and uses the existing `merge_module_lists`/`deep_merge` utilities. Phase 1 ships the file-path categories only: agents, context, skills. Tools and config overrides defer to v1.1.

**Tech Stack:** Python 3.11+, pytest with `asyncio_mode = "strict"`, PyYAML, `unittest.mock` (`MagicMock` + `AsyncMock`).

**Working directory for all commands:** `/home/bkrabach/dev/modes-updates/amplifier-foundation`

---

## Pre-flight: Branch and baseline

Before starting, create a working branch and confirm the existing test suite is green.

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
git checkout -b feat/mode-overlays-phase-1
uv run pytest tests/ -q --timeout=60 2>&1 | tail -5
```

Expected: existing tests all pass. If anything is red here, stop and report — Phase 1 must not paper over pre-existing breakage.

---

## Task 1: `_load_mode_file_metadata()` — happy path

**Files:**
- Test: `amplifier-foundation/tests/test_load_mode_metadata.py` (create)
- Modify: `amplifier-foundation/amplifier_foundation/bundle/_dataclass.py` (insert after line 735)

### Step 1: Write the failing test

Create `amplifier-foundation/tests/test_load_mode_metadata.py`:

```python
"""Tests for _load_mode_file_metadata in bundle/_dataclass.py."""

from pathlib import Path

import pytest

from amplifier_foundation.bundle._dataclass import _load_mode_file_metadata


@pytest.fixture
def mode_file(tmp_path: Path) -> Path:
    """A mode .md file with a full frontmatter block including contributes + advertised."""
    path = tmp_path / "demo-mode.md"
    path.write_text(
        """---
mode:
  name: demo-mode
  description: "A demo mode for tests"
  shortcut: demo
  advertised: false
  default_action: block
  tools:
    safe: [read_file, grep]
  contributes:
    agents:
      mode-author:
        source: "@modes:agents/mode-author"
    context:
      - "@modes:context/schema.md"
    skills:
      - "@modes:skills/mode-design-discipline"
---

# Demo Mode body

This is the system reminder text.
""",
        encoding="utf-8",
    )
    return path


def test_extracts_name_and_description(mode_file: Path) -> None:
    """Top-level mode: keys (name, description) flow through."""
    result = _load_mode_file_metadata(mode_file, fallback_name="fallback")
    assert result["name"] == "demo-mode"
    assert result["description"] == "A demo mode for tests"


def test_extracts_advertised_flag(mode_file: Path) -> None:
    """advertised: false is preserved (not coerced to default True)."""
    result = _load_mode_file_metadata(mode_file, fallback_name="fallback")
    assert result["advertised"] is False


def test_extracts_contributes_block(mode_file: Path) -> None:
    """contributes block is preserved as a dict with agents/context/skills keys."""
    result = _load_mode_file_metadata(mode_file, fallback_name="fallback")
    contrib = result["contributes"]
    assert isinstance(contrib, dict)
    assert "mode-author" in contrib["agents"]
    assert contrib["agents"]["mode-author"]["source"] == "@modes:agents/mode-author"
    assert contrib["context"] == ["@modes:context/schema.md"]
    assert contrib["skills"] == ["@modes:skills/mode-design-discipline"]


def test_includes_body_as_instruction(mode_file: Path) -> None:
    """Markdown body is captured as 'instruction' (mirrors agent loader pattern)."""
    result = _load_mode_file_metadata(mode_file, fallback_name="fallback")
    assert "instruction" in result
    assert "Demo Mode body" in result["instruction"]
    assert "system reminder text" in result["instruction"]
```

### Step 2: Run the test to verify it fails

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_load_mode_metadata.py -v
```

Expected: All four tests FAIL with `ImportError: cannot import name '_load_mode_file_metadata' from 'amplifier_foundation.bundle._dataclass'`.

### Step 3: Write the minimal implementation

In `amplifier-foundation/amplifier_foundation/bundle/_dataclass.py`, insert this function immediately after the existing `_load_agent_file_metadata` function (after line 735, before the next `def _parse_context(...)`):

```python
def _load_mode_file_metadata(path: Path, fallback_name: str) -> dict[str, Any]:
    """Load mode config from a .md file.

    Mirrors _load_agent_file_metadata but reads from the top-level ``mode:`` key
    (mode files use ``mode:`` where agent files use ``meta:``). Extracts mode
    metadata, the new ``advertised`` flag, and the new ``contributes`` block
    (agents, context, skills, tools, config) along with the markdown body as
    the instruction.

    Phase 1 of the mode runtime overlays work surfaces ``contributes`` and
    ``advertised`` for downstream consumption; ``contributes.tools`` and
    ``contributes.config`` are reserved for v1.1.

    Args:
        path: Path to mode .md file.
        fallback_name: Name to use if not specified in file.

    Returns:
        Dict with name, description, advertised, contributes, optionally
        shortcut, default_action, tools (policy), allowed_transitions,
        allow_clear, and instruction (markdown body).
    """
    from amplifier_foundation.io.frontmatter import parse_frontmatter

    text = path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(text)

    # Mode files use mode: section (not meta:, not bundle:)
    mode_section = frontmatter.get("mode", {})
    if not isinstance(mode_section, dict):
        mode_section = {}

    # Backward-compatible defaults: advertised=True (existing modes are visible),
    # contributes={} (existing modes contribute nothing).
    result: dict[str, Any] = {
        "name": mode_section.get("name", fallback_name),
        "description": mode_section.get("description", ""),
        "advertised": mode_section.get("advertised", True),
        "contributes": mode_section.get("contributes", {}) or {},
    }

    # Pass through the rest of the mode_section keys verbatim so tool-policy,
    # transitions, and shortcut land in the result without per-field plumbing.
    for k, v in mode_section.items():
        if k not in result:
            result[k] = v

    # Markdown body becomes the system-reminder instruction (same pattern as
    # the agent loader).
    if body and body.strip():
        result["instruction"] = body.strip()

    return result
```

### Step 4: Run the test to verify it passes

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_load_mode_metadata.py -v
```

Expected: All four tests PASS.

### Step 5: Commit

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
git add amplifier_foundation/bundle/_dataclass.py tests/test_load_mode_metadata.py
git commit -m "feat(bundle): add _load_mode_file_metadata for mode frontmatter

Mirrors _load_agent_file_metadata; reads mode: section, surfaces the new
advertised flag and contributes block (agents, context, skills) for the
mode-runtime-overlays Phase 1.

Refs: docs/designs/MODE_RUNTIME_OVERLAYS.md §5.2 step 1.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 2: `_load_mode_file_metadata()` — defaults for missing fields

**Files:**
- Modify: `amplifier-foundation/tests/test_load_mode_metadata.py`

### Step 1: Write the failing test

Append to `amplifier-foundation/tests/test_load_mode_metadata.py`:

```python
def test_minimal_mode_defaults(tmp_path: Path) -> None:
    """A mode file with only name/description gets safe backward-compatible defaults."""
    path = tmp_path / "minimal.md"
    path.write_text(
        """---
mode:
  name: minimal
  description: "Minimal mode"
---

body
""",
        encoding="utf-8",
    )

    result = _load_mode_file_metadata(path, fallback_name="fallback")

    # Backward compat: existing modes have no advertised/contributes keys.
    # Defaults must keep them visible and contribution-free.
    assert result["advertised"] is True
    assert result["contributes"] == {}


def test_fallback_name_when_no_mode_section(tmp_path: Path) -> None:
    """If frontmatter has no mode: key at all, fallback_name is used."""
    path = tmp_path / "noframe.md"
    path.write_text("just markdown body, no frontmatter\n", encoding="utf-8")

    result = _load_mode_file_metadata(path, fallback_name="noframe")

    assert result["name"] == "noframe"
    assert result["advertised"] is True
    assert result["contributes"] == {}


def test_contributes_explicit_null_yields_empty_dict(tmp_path: Path) -> None:
    """An explicit ``contributes: null`` (yaml: empty mapping) collapses to {}."""
    path = tmp_path / "nullcontrib.md"
    path.write_text(
        """---
mode:
  name: nullcontrib
  contributes:
---

body
""",
        encoding="utf-8",
    )

    result = _load_mode_file_metadata(path, fallback_name="nullcontrib")

    assert result["contributes"] == {}
```

### Step 2: Run the tests to verify failures

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_load_mode_metadata.py::test_minimal_mode_defaults tests/test_load_mode_metadata.py::test_fallback_name_when_no_mode_section tests/test_load_mode_metadata.py::test_contributes_explicit_null_yields_empty_dict -v
```

Expected: `test_contributes_explicit_null_yields_empty_dict` FAILS (because `mode_section.get("contributes", {})` returns `None` when the key is present-but-null, and `None or {}` evaluates to `{}` only because of the `or {}` guard already in the implementation — verify this expectation with the test). The other two should PASS already because of the defaults coded in Task 1.

### Step 3: Adjust the implementation if any test fails

If any of the three tests fail, the most likely reason is that the `or {}` fallback in the existing implementation already covers null. If `test_contributes_explicit_null_yields_empty_dict` passes, no edits are needed for this task. If it fails, ensure the line in `_load_mode_file_metadata`:

```python
"contributes": mode_section.get("contributes", {}) or {},
```

is exactly that — the `or {}` is what coerces `None` to `{}`.

### Step 4: Run the full test file again

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_load_mode_metadata.py -v
```

Expected: All seven tests PASS.

### Step 5: Commit

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
git add tests/test_load_mode_metadata.py
git commit -m "test(bundle): cover defaults and edge cases for _load_mode_file_metadata

Backward-compat defaults: advertised=True, contributes={}. Explicit null
contributes coerces to empty dict. No-frontmatter mode falls back to
caller-provided name.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 3: `_load_mode_file_metadata()` — malformed YAML

**Files:**
- Modify: `amplifier-foundation/tests/test_load_mode_metadata.py`

### Step 1: Write the failing test

Append to `amplifier-foundation/tests/test_load_mode_metadata.py`:

```python
def test_malformed_yaml_raises(tmp_path: Path) -> None:
    """Malformed frontmatter YAML propagates as yaml.YAMLError.

    Loader does NOT silently swallow YAML errors; the bundle prepare-walk is
    responsible for catching/logging. Centralising the catch in one place
    keeps observability consistent.
    """
    import yaml

    path = tmp_path / "broken.md"
    path.write_text(
        """---
mode:
  name: broken
  contributes: { not closed
---

body
""",
        encoding="utf-8",
    )

    with pytest.raises(yaml.YAMLError):
        _load_mode_file_metadata(path, fallback_name="broken")
```

### Step 2: Run the test to verify it fails

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_load_mode_metadata.py::test_malformed_yaml_raises -v
```

Expected: PASS already — `parse_frontmatter` calls `yaml.safe_load` which raises on malformed YAML. The test is documenting the contract, not driving an implementation change.

If the test FAILS unexpectedly, that means the loader is swallowing YAML errors somewhere — investigate before continuing.

### Step 3: No implementation change needed

This task locks in the contract that malformed YAML raises through the loader; the prepare-walk in Task 4 handles the catch.

### Step 4: Run the full test file

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_load_mode_metadata.py -v
```

Expected: All eight tests PASS.

### Step 5: Commit

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
git add tests/test_load_mode_metadata.py
git commit -m "test(bundle): document malformed-YAML contract for mode loader

YAMLError propagates from the loader; prepare-walk owns the log/skip policy.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 4: `Bundle.prepare()` modes walk — schema validation only

**Files:**
- Test: `amplifier-foundation/tests/test_bundle_prepare_modes_walk.py` (create)
- Modify: `amplifier-foundation/amplifier_foundation/bundle/_dataclass.py` (insert after line 430)

### Step 1: Write the failing test

Create `amplifier-foundation/tests/test_bundle_prepare_modes_walk.py`:

```python
"""Tests for the Bundle.prepare() modes-walk added in Phase 1.

The Phase 1 modes walk is schema-validation-only: it scans
``self.base_path / "modes"`` for ``.md`` files, parses each, and logs WARN
on a malformed ``contributes`` block. It does NOT call ModuleActivator —
that is reserved for v1.1 when ``contributes.tools`` joins.
"""

import logging
from pathlib import Path

import pytest

from amplifier_foundation.bundle import Bundle


def _write(p: Path, body: str) -> None:
    p.write_text(body, encoding="utf-8")


@pytest.fixture
def bundle_with_valid_mode(tmp_path: Path) -> Bundle:
    """Bundle pointing at a tmp dir containing a single well-formed mode file."""
    modes_dir = tmp_path / "modes"
    modes_dir.mkdir()
    _write(
        modes_dir / "demo.md",
        """---
mode:
  name: demo
  contributes:
    agents:
      mode-author:
        source: "@modes:agents/mode-author"
---

body
""",
    )
    bundle = Bundle(name="modes", base_path=tmp_path)
    return bundle


@pytest.fixture
def bundle_with_malformed_contributes(tmp_path: Path) -> Bundle:
    """Bundle with a mode whose contributes is not a dict (lint should warn)."""
    modes_dir = tmp_path / "modes"
    modes_dir.mkdir()
    _write(
        modes_dir / "bad.md",
        """---
mode:
  name: bad
  contributes:
    - this should be a dict not a list
---

body
""",
    )
    bundle = Bundle(name="modes", base_path=tmp_path)
    return bundle


@pytest.fixture
def bundle_with_no_modes_dir(tmp_path: Path) -> Bundle:
    """Bundle whose base_path has no modes/ directory at all (no-op walk)."""
    return Bundle(name="modes", base_path=tmp_path)


def test_validate_modes_returns_zero_warnings_for_valid_mode(
    bundle_with_valid_mode: Bundle,
) -> None:
    """A well-formed mode file produces no warnings."""
    warnings = bundle_with_valid_mode.validate_modes()
    assert warnings == []


def test_validate_modes_warns_on_non_dict_contributes(
    bundle_with_malformed_contributes: Bundle,
) -> None:
    """A non-dict contributes produces one warning naming the file."""
    warnings = bundle_with_malformed_contributes.validate_modes()
    assert len(warnings) == 1
    assert "bad.md" in warnings[0]
    assert "contributes" in warnings[0]


def test_validate_modes_no_modes_dir_is_noop(
    bundle_with_no_modes_dir: Bundle,
) -> None:
    """A bundle with no modes/ directory returns [] (clean no-op)."""
    warnings = bundle_with_no_modes_dir.validate_modes()
    assert warnings == []


def test_validate_modes_handles_yaml_error_as_warning(tmp_path: Path) -> None:
    """A mode with malformed YAML is logged as a warning, not a hard fail."""
    modes_dir = tmp_path / "modes"
    modes_dir.mkdir()
    _write(
        modes_dir / "broken.md",
        """---
mode:
  contributes: { not closed
---

body
""",
    )
    bundle = Bundle(name="modes", base_path=tmp_path)

    warnings = bundle.validate_modes()

    assert len(warnings) == 1
    assert "broken.md" in warnings[0]


def test_validate_modes_logs_warnings_via_logger(
    bundle_with_malformed_contributes: Bundle, caplog: pytest.LogCaptureFixture
) -> None:
    """validate_modes also emits via the module logger so prepare() observers see it."""
    with caplog.at_level(logging.WARNING, logger="amplifier_foundation.bundle._dataclass"):
        bundle_with_malformed_contributes.validate_modes()

    assert any("bad.md" in rec.message for rec in caplog.records)
```

### Step 2: Run the tests to verify failures

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_bundle_prepare_modes_walk.py -v
```

Expected: All five tests FAIL with `AttributeError: 'Bundle' object has no attribute 'validate_modes'`.

### Step 3: Add the `validate_modes()` method and wire into `prepare()`

In `amplifier-foundation/amplifier_foundation/bundle/_dataclass.py`:

**Edit 1 — add `validate_modes()` as a `Bundle` method.** Insert this method on the `Bundle` class. A good location is immediately after `load_agent_metadata()` (around line 645 — find the end of the `load_agent_metadata` method body, and add this method after it but inside the class):

```python
    def validate_modes(self) -> list[str]:
        """Scan ``self.base_path / "modes"`` and validate each mode's contributes block.

        Phase 1 of the mode runtime overlays work. This is schema-validation only:
        we parse every ``.md`` file under the modes/ directory and confirm that the
        ``contributes`` block (if present) is a dict. Malformed YAML, non-dict
        contributes, or unreadable files are logged as warnings and surfaced in
        the return list — they do NOT fail prepare(). Module activation for
        contributed sources is reserved for v1.1 when ``contributes.tools`` joins.

        Returns:
            List of human-readable warning strings; empty when every mode is
            well-formed or the bundle has no modes/ directory.
        """
        warnings: list[str] = []
        if not self.base_path:
            return warnings

        modes_dir = self.base_path / "modes"
        if not modes_dir.is_dir():
            return warnings

        for mode_path in sorted(modes_dir.glob("*.md")):
            try:
                meta = _load_mode_file_metadata(mode_path, fallback_name=mode_path.stem)
            except Exception as exc:  # noqa: BLE001
                msg = f"{mode_path.name}: failed to parse frontmatter: {exc}"
                logger.warning(msg)
                warnings.append(msg)
                continue

            contributes = meta.get("contributes", {})
            if not isinstance(contributes, dict):
                msg = (
                    f"{mode_path.name}: 'contributes' must be a dict; "
                    f"got {type(contributes).__name__}"
                )
                logger.warning(msg)
                warnings.append(msg)

        return warnings
```

**Edit 2 — call it from `prepare()`.** In `Bundle.prepare()`, immediately after the existing agents pre-activation walk (i.e., right after line 430's `if isinstance(mod_spec, dict) and "source" in mod_spec: modules_to_activate.append(resolve_source(mod_spec))` block exits, and before `# Activate all modules and get their paths` at line 432), insert:

```python
        # Phase 1: schema-only modes walk. Validates contributes structure;
        # actual module activation for contributed sources defers to v1.1
        # when contributes.tools joins. Warnings are logged but do not fail prepare.
        self.validate_modes()
```

The result around lines 430-433 should read:

```python
                    for mod_spec in agent_mods:
                        if isinstance(mod_spec, dict) and "source" in mod_spec:
                            modules_to_activate.append(resolve_source(mod_spec))

        # Phase 1: schema-only modes walk. Validates contributes structure;
        # actual module activation for contributed sources defers to v1.1
        # when contributes.tools joins. Warnings are logged but do not fail prepare.
        self.validate_modes()

        # Activate all modules and get their paths
        module_paths = await activator.activate_all(
            modules_to_activate, progress_callback=progress_callback
        )
```

### Step 4: Run the tests to verify they pass

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_bundle_prepare_modes_walk.py tests/test_load_mode_metadata.py -v
```

Expected: All thirteen tests PASS.

Also run the existing bundle-and-prepare suites to confirm no regressions:

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_bundle.py tests/test_agent_metadata.py -q --timeout=60
```

Expected: PASS.

### Step 5: Commit

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
git add amplifier_foundation/bundle/_dataclass.py tests/test_bundle_prepare_modes_walk.py
git commit -m "feat(bundle): schema-only modes walk in Bundle.prepare()

Adds Bundle.validate_modes() and wires it into prepare() right after the
agents pre-activation walk. Phase 1 only validates contributes shape; module
activation for contributed sources defers to v1.1 when contributes.tools
joins. Malformed entries are logged as warnings, never fatal.

Refs: docs/designs/MODE_RUNTIME_OVERLAYS.md §5.2 step 2.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 5: `RuntimeOverlay` scaffold and S2 agent path

**Files:**
- Test: `amplifier-foundation/tests/test_overlay.py` (create)
- Create: `amplifier-foundation/amplifier_foundation/configurator/_overlay.py`

### Step 1: Write the failing test

Create `amplifier-foundation/tests/test_overlay.py`:

```python
"""Tests for RuntimeOverlay (Phase 1).

Phase 1 covers S1 (overlap with session baseline) and S2 (mode-only) for the
agent / context / skill categories. S3 and S4 are exercised via integration
tests in Phase 3 with real modes.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_foundation.configurator._overlay import RuntimeOverlay


# ---------------------------------------------------------------------------
# Shared fixtures — match the test_configurator.py pattern
# ---------------------------------------------------------------------------


def _make_coordinator(
    initial_agents: dict[str, Any] | None = None,
    initial_capabilities: dict[str, Any] | None = None,
) -> MagicMock:
    """A MagicMock coordinator with the surfaces RuntimeOverlay touches."""
    coordinator = MagicMock()
    coordinator.config = {"agents": dict(initial_agents or {})}

    # Capability registry — backed by a real dict so register/get round-trip.
    capability_store: dict[str, Any] = dict(initial_capabilities or {})

    def _register_capability(name: str, value: Any) -> None:
        capability_store[name] = value

    def _get_capability(name: str) -> Any:
        return capability_store.get(name)

    coordinator.register_capability = MagicMock(side_effect=_register_capability)
    coordinator.get_capability = MagicMock(side_effect=_get_capability)

    # Hook bus — async emit.
    coordinator.hooks = MagicMock()
    coordinator.hooks.emit = AsyncMock()

    return coordinator


@pytest.fixture
def coordinator() -> MagicMock:
    return _make_coordinator()


@pytest.fixture
def overlay(coordinator: MagicMock) -> RuntimeOverlay:
    return RuntimeOverlay(
        coordinator,
        success_event="mode:transition_completed",
        failure_event="mode:activation_failed",
    )


# ---------------------------------------------------------------------------
# S2 — agent-only (no session baseline)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s2_agent_apply_mounts_into_coordinator_config(
    overlay: RuntimeOverlay, coordinator: MagicMock
) -> None:
    """S2 (mode-only): apply mounts an agent that wasn't in the session."""
    contributions = {
        "agents": {"mode-author": {"description": "A mode-author agent"}}
    }

    result = await overlay.apply("mode:demo", contributions)

    assert result.success is True
    assert "mode-author" in coordinator.config["agents"]
    assert coordinator.config["agents"]["mode-author"]["description"] == "A mode-author agent"


@pytest.mark.asyncio
async def test_s2_agent_revoke_unmounts(
    overlay: RuntimeOverlay, coordinator: MagicMock
) -> None:
    """S2: revoke removes the agent that apply added."""
    await overlay.apply(
        "mode:demo", {"agents": {"mode-author": {"description": "x"}}}
    )

    result = await overlay.revoke("mode:demo")

    assert result.success is True
    assert "mode-author" not in coordinator.config["agents"]


@pytest.mark.asyncio
async def test_revoke_unknown_scope_is_noop(overlay: RuntimeOverlay) -> None:
    """Revoking a scope that was never applied is a successful no-op."""
    result = await overlay.revoke("mode:never-applied")

    assert result.success is True
    assert result.unmounted == []
```

### Step 2: Run the tests to verify failures

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_overlay.py -v
```

Expected: All three tests FAIL with `ModuleNotFoundError: No module named 'amplifier_foundation.configurator._overlay'`.

### Step 3: Write the minimal implementation

Create `amplifier-foundation/amplifier_foundation/configurator/_overlay.py`:

```python
"""RuntimeOverlay — refcounted, atomic apply/revoke of mode contributions.

A ``RuntimeOverlay`` sits as a peer to ``SessionConfigurator`` and drives the
same live coordinator surfaces. Where ``SessionConfigurator`` toggles
session-level items via stash/unstash, ``RuntimeOverlay`` adds *additive*
contributions (agents, context, skills) under named scopes (typically
``"mode:<name>"``) with refcount semantics:

- Session baseline contributes +1 per existing item at construction.
- Each scope's apply() contributes +1 per declared item.
- Mount happens on 0→1; unmount happens on 1→0.

Phase 1 covers ``agents``, ``context``, ``skills``. ``tools`` and ``config``
overrides are reserved for v1.1.

Event names (success / failure) are caller-injected so this module remains
free of cross-bundle event-name coupling — the modes bundle in Phase 2 will
own the canonical names.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)


@dataclass
class TransitionResult:
    """Outcome of an ``apply`` or ``revoke`` call.

    ``success=True`` means the transition committed (or was a clean no-op).
    On a failed apply with rollback, ``success=False`` and ``error`` describes
    what went wrong; any items mounted before the failure are reflected in
    ``mounted`` followed by entries in ``rolled_back`` showing the reversal.
    """

    success: bool
    scope: str
    mounted: list[tuple[str, str]] = field(default_factory=list)
    unmounted: list[tuple[str, str]] = field(default_factory=list)
    rolled_back: list[tuple[str, str]] = field(default_factory=list)
    error: str | None = None


# ---------------------------------------------------------------------------
# Capability key constants — Phase 1 internal names.  Phase 2 may rename when
# wiring hooks-mode reads; if so, update both ends together.
# ---------------------------------------------------------------------------

_CAP_OVERLAY_CONTEXT = "mode_overlay_context"
_CAP_OVERLAY_SKILLS = "mode_overlay_skills"


class RuntimeOverlay:
    """Refcounted overlay over a live ``Coordinator``.

    Contributions are declared per-scope as a dict::

        {
            "agents":  {name: agent_config_dict, ...},
            "context": [path_or_mention, ...],
            "skills":  [path_or_mention, ...],
        }

    Internally we keep a refcount per ``(category, key)`` so two scopes that
    contribute the same agent/context/skill compose without churn (S3/S4) and
    overlap with the session baseline does not double-mount (S1).
    """

    def __init__(
        self,
        coordinator: Any,
        *,
        success_event: str,
        failure_event: str,
    ) -> None:
        self._coordinator = coordinator
        self._success_event = success_event
        self._failure_event = failure_event

        # (category, key) -> refcount.
        self._refcounts: dict[tuple[str, str], int] = {}

        # scope -> list of (category, key) it claims.
        self._scope_claims: dict[str, list[tuple[str, str]]] = {}

        # category -> dict[key, payload] for items this overlay is currently
        # responsible for. Agents store full config dicts; context/skills
        # store the original path/mention string. Used at unmount time to
        # remove the right entry without disturbing session state.
        self._owned: dict[str, dict[str, Any]] = {
            "agents": {},
            "context": {},
            "skills": {},
        }

        self._capture_baseline()

    # ------------------------------------------------------------------
    # Baseline
    # ------------------------------------------------------------------

    def _capture_baseline(self) -> None:
        """Record refcount=1 for every item the session already provides.

        Phase 1 baseline:
        - agents: keys of ``coordinator.config["agents"]``.
        - context: empty (session-level context flows through ``bundle.context``,
          not through the overlay capability).
        - skills: empty (session-level skills flow through tool-skills config).

        Modes that contribute the same agent name as a session-level agent
        therefore start at refcount 2 (S1) and never trigger a mount.
        """
        agents = self._coordinator.config.get("agents") or {}
        for name in agents:
            self._refcounts[("agents", name)] = 1

    # ------------------------------------------------------------------
    # apply / revoke
    # ------------------------------------------------------------------

    async def apply(
        self, scope: str, contributions: dict[str, Any]
    ) -> TransitionResult:
        """Atomically apply a scope's contributions. Rolls back on any failure."""
        if scope in self._scope_claims:
            # Already applied — treat as success no-op so callers don't have
            # to track scope state out-of-band.
            return TransitionResult(success=True, scope=scope)

        result = TransitionResult(success=True, scope=scope)
        applied_in_this_call: list[tuple[str, str]] = []

        try:
            for category, payload in contributions.items():
                if category == "agents":
                    items = self._normalise_agents(payload)
                elif category in ("context", "skills"):
                    items = self._normalise_path_list(payload)
                elif category in ("tools", "config"):
                    # v1.1 — silently skipped in Phase 1.
                    _log.debug(
                        "Skipping %r contribution for scope %r: deferred to v1.1",
                        category,
                        scope,
                    )
                    continue
                else:
                    _log.warning(
                        "Unknown contribution category %r in scope %r — skipping",
                        category,
                        scope,
                    )
                    continue

                for key, value in items:
                    self._increment(category, key, value)
                    applied_in_this_call.append((category, key))
                    result.mounted.append((category, key))

            self._scope_claims[scope] = list(applied_in_this_call)

        except Exception as exc:  # noqa: BLE001
            # Atomic rollback — reverse every increment from this call.
            for category, key in reversed(applied_in_this_call):
                try:
                    self._decrement(category, key)
                    result.rolled_back.append((category, key))
                except Exception as rb_exc:  # noqa: BLE001
                    _log.error(
                        "Rollback failure for (%s, %s) in scope %r: %s",
                        category,
                        key,
                        scope,
                        rb_exc,
                    )
            result.success = False
            result.error = str(exc)
            await self._emit(self._failure_event, scope, result)
            return result

        await self._emit(self._success_event, scope, result)
        return result

    async def revoke(self, scope: str) -> TransitionResult:
        """Atomically revoke a scope's contributions."""
        if scope not in self._scope_claims:
            return TransitionResult(success=True, scope=scope)

        claims = self._scope_claims.pop(scope)
        result = TransitionResult(success=True, scope=scope)

        for category, key in reversed(claims):
            try:
                self._decrement(category, key)
                result.unmounted.append((category, key))
            except Exception as exc:  # noqa: BLE001
                _log.error(
                    "revoke decrement failed for (%s, %s) in scope %r: %s",
                    category,
                    key,
                    scope,
                    exc,
                )
                # Continue best-effort; refcount integrity already breached
                # if this raises, but we want to drain.
                result.success = False
                result.error = str(exc)

        await self._emit(self._success_event, scope, result)
        return result

    # ------------------------------------------------------------------
    # Refcount + mount/unmount machinery
    # ------------------------------------------------------------------

    def _increment(self, category: str, key: str, value: Any) -> None:
        rc_key = (category, key)
        before = self._refcounts.get(rc_key, 0)
        self._refcounts[rc_key] = before + 1

        if before == 0:
            # 0 -> 1 transition: actually mount.
            self._mount(category, key, value)

    def _decrement(self, category: str, key: str) -> None:
        rc_key = (category, key)
        before = self._refcounts.get(rc_key, 0)
        if before <= 0:
            raise RuntimeError(
                f"refcount underflow for {category}:{key} (was {before})"
            )
        self._refcounts[rc_key] = before - 1

        if before == 1:
            # 1 -> 0 transition: actually unmount.
            self._unmount(category, key)
            del self._refcounts[rc_key]

    def _mount(self, category: str, key: str, value: Any) -> None:
        if category == "agents":
            agents = self._coordinator.config.setdefault("agents", {})
            agents[key] = value
            self._owned["agents"][key] = value
            return
        if category in ("context", "skills"):
            self._owned[category][key] = value
            self._refresh_capability(category)
            return
        raise ValueError(f"unknown category {category!r}")

    def _unmount(self, category: str, key: str) -> None:
        if category == "agents":
            agents = self._coordinator.config.get("agents") or {}
            agents.pop(key, None)
            self._owned["agents"].pop(key, None)
            return
        if category in ("context", "skills"):
            self._owned[category].pop(key, None)
            self._refresh_capability(category)
            return
        raise ValueError(f"unknown category {category!r}")

    def _refresh_capability(self, category: str) -> None:
        cap_name = (
            _CAP_OVERLAY_CONTEXT if category == "context" else _CAP_OVERLAY_SKILLS
        )
        # Stable order: insertion order from dict. Future cross-mode policy
        # may re-sort; not needed for v1.
        self._coordinator.register_capability(
            cap_name, list(self._owned[category].keys())
        )

    # ------------------------------------------------------------------
    # Normalisation
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_agents(payload: Any) -> list[tuple[str, dict[str, Any]]]:
        if not isinstance(payload, dict):
            raise ValueError(
                f"contributes.agents must be a dict; got {type(payload).__name__}"
            )
        out: list[tuple[str, dict[str, Any]]] = []
        for name, cfg in payload.items():
            if not isinstance(cfg, dict):
                raise ValueError(
                    f"contributes.agents[{name!r}] must be a dict; "
                    f"got {type(cfg).__name__}"
                )
            out.append((name, cfg))
        return out

    @staticmethod
    def _normalise_path_list(payload: Any) -> list[tuple[str, str]]:
        if not isinstance(payload, list):
            raise ValueError(
                f"context/skills contributions must be a list; "
                f"got {type(payload).__name__}"
            )
        out: list[tuple[str, str]] = []
        for entry in payload:
            if not isinstance(entry, str):
                raise ValueError(
                    f"context/skills entries must be strings; got {type(entry).__name__}"
                )
            out.append((entry, entry))
        return out

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def _emit(
        self, event_name: str, scope: str, result: TransitionResult
    ) -> None:
        try:
            await self._coordinator.hooks.emit(
                event_name,
                {
                    "scope": scope,
                    "success": result.success,
                    "mounted": result.mounted,
                    "unmounted": result.unmounted,
                    "rolled_back": result.rolled_back,
                    "error": result.error,
                },
            )
        except Exception as exc:  # noqa: BLE001
            _log.debug("Failed to emit %s for %r: %s", event_name, scope, exc)


__all__ = ["RuntimeOverlay", "TransitionResult"]
```

### Step 4: Run the tests to verify they pass

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_overlay.py -v
```

Expected: All three tests PASS.

### Step 5: Commit

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
git add amplifier_foundation/configurator/_overlay.py tests/test_overlay.py
git commit -m "feat(configurator): RuntimeOverlay with refcount + S2 agent path

Introduces RuntimeOverlay as a peer of SessionConfigurator. Phase 1 covers
agent/context/skill contributions; tools and config overrides defer to v1.1.
Event names are caller-injected to keep this module free of cross-bundle
event-name coupling.

Refs: docs/designs/MODE_RUNTIME_OVERLAYS.md §5.2 step 3.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 6: `RuntimeOverlay` — S1 agent overlap with session baseline

**Files:**
- Modify: `amplifier-foundation/tests/test_overlay.py`

### Step 1: Write the failing test

Append to `amplifier-foundation/tests/test_overlay.py`:

```python
# ---------------------------------------------------------------------------
# S1 — overlap with session baseline (agents only in v1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s1_agent_in_session_and_mode_no_unmount_on_revoke() -> None:
    """S1: agent in session AND in mode. Apply: refcount 1->2, no remount.
    Revoke: 2->1, agent stays in session."""
    coordinator = _make_coordinator(
        initial_agents={"mode-author": {"description": "session-level"}}
    )
    overlay = RuntimeOverlay(
        coordinator,
        success_event="mode:transition_completed",
        failure_event="mode:activation_failed",
    )

    await overlay.apply(
        "mode:demo",
        {"agents": {"mode-author": {"description": "mode-level"}}},
    )

    # Mode apply does NOT replace the session-level config (S1 invariant).
    assert coordinator.config["agents"]["mode-author"]["description"] == "session-level"

    await overlay.revoke("mode:demo")

    # Refcount went 2->1, agent must still be present.
    assert "mode-author" in coordinator.config["agents"]
    assert coordinator.config["agents"]["mode-author"]["description"] == "session-level"


@pytest.mark.asyncio
async def test_s1_baseline_agent_not_added_by_mode_apply_alone() -> None:
    """A mode that contributes nothing for an existing session agent leaves it alone."""
    coordinator = _make_coordinator(
        initial_agents={"baseline-agent": {"description": "session-level"}}
    )
    overlay = RuntimeOverlay(
        coordinator,
        success_event="mode:transition_completed",
        failure_event="mode:activation_failed",
    )

    await overlay.apply("mode:demo", {"agents": {}})
    await overlay.revoke("mode:demo")

    assert "baseline-agent" in coordinator.config["agents"]
```

### Step 2: Run the tests to verify they fail (or pass — verify behavior)

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_overlay.py::test_s1_agent_in_session_and_mode_no_unmount_on_revoke tests/test_overlay.py::test_s1_baseline_agent_not_added_by_mode_apply_alone -v
```

Expected: Both tests PASS already, because `_capture_baseline()` already sets refcount=1 for session-level agents and `_increment` only mounts on 0→1. This task is locking in the S1 contract; the implementation in Task 5 already handles it. If a test FAILS, there's a baseline-handling bug — fix it before moving on.

### Step 3: No implementation change expected

Verify by tracing:
- `coordinator.config["agents"] = {"mode-author": ...}` at construction.
- `_capture_baseline()` sets `_refcounts[("agents", "mode-author")] = 1`.
- `apply` calls `_increment` → `before=1`, `_refcounts → 2`, no `_mount` call (since `before != 0`).
- `revoke` calls `_decrement` → `before=2`, `_refcounts → 1`, no `_unmount` call (since `before != 1`).

If the trace doesn't match the test outcome, adjust `_increment`/`_decrement` accordingly.

### Step 4: Run the full overlay test file

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_overlay.py -v
```

Expected: All five tests PASS.

### Step 5: Commit

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
git add tests/test_overlay.py
git commit -m "test(configurator): cover S1 agent overlap with session baseline

S1: agent declared in both session and mode. Refcount 1->2 on apply (no
remount, no config replacement); 2->1 on revoke (no unmount, agent stays).

Refs: docs/designs/MODE_RUNTIME_OVERLAYS.md §7.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 7: `RuntimeOverlay` — context contributions

**Files:**
- Modify: `amplifier-foundation/tests/test_overlay.py`

### Step 1: Write the failing test

Append to `amplifier-foundation/tests/test_overlay.py`:

```python
# ---------------------------------------------------------------------------
# Context contributions (capability-based discovery)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_apply_registers_capability(
    overlay: RuntimeOverlay, coordinator: MagicMock
) -> None:
    """Apply with context: paths are exposed via the mode_overlay_context capability."""
    await overlay.apply(
        "mode:demo",
        {"context": ["@modes:context/schema.md", "@modes:context/anti-patterns.md"]},
    )

    cap = coordinator.get_capability("mode_overlay_context")
    assert cap == [
        "@modes:context/schema.md",
        "@modes:context/anti-patterns.md",
    ]


@pytest.mark.asyncio
async def test_context_revoke_clears_capability(
    overlay: RuntimeOverlay, coordinator: MagicMock
) -> None:
    """Revoke removes the entries this scope contributed."""
    await overlay.apply(
        "mode:demo", {"context": ["@modes:context/schema.md"]}
    )
    await overlay.revoke("mode:demo")

    cap = coordinator.get_capability("mode_overlay_context") or []
    assert cap == []


@pytest.mark.asyncio
async def test_context_revoke_keeps_paths_referenced_by_other_scope(
    overlay: RuntimeOverlay, coordinator: MagicMock
) -> None:
    """If two scopes contribute the same context path, revoking one leaves it."""
    await overlay.apply(
        "mode:m1", {"context": ["@modes:context/shared.md"]}
    )
    await overlay.apply(
        "mode:m2", {"context": ["@modes:context/shared.md"]}
    )

    await overlay.revoke("mode:m1")

    cap = coordinator.get_capability("mode_overlay_context") or []
    assert "@modes:context/shared.md" in cap
```

### Step 2: Run the tests to verify behavior

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_overlay.py -v -k "context"
```

Expected: All three context tests PASS already (the Task 5 implementation handles this case). If any fail, the most likely culprit is `_refresh_capability` not preserving the right keys after a partial revoke — fix the `_owned[category].pop(key, None)` pattern.

### Step 3: No implementation change expected

Confirmation only. The capability-refresh pattern is already in place.

### Step 4: Run the full overlay test file

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_overlay.py -v
```

Expected: All eight tests PASS.

### Step 5: Commit

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
git add tests/test_overlay.py
git commit -m "test(configurator): cover context contributions in RuntimeOverlay

Apply registers mode_overlay_context capability; revoke clears it; cross-
scope refcount keeps shared paths around when one scope drops.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 8: `RuntimeOverlay` — skills contributions

**Files:**
- Modify: `amplifier-foundation/tests/test_overlay.py`

### Step 1: Write the failing test

Append to `amplifier-foundation/tests/test_overlay.py`:

```python
# ---------------------------------------------------------------------------
# Skills contributions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skills_apply_registers_capability(
    overlay: RuntimeOverlay, coordinator: MagicMock
) -> None:
    """Apply with skills: paths exposed via mode_overlay_skills capability."""
    await overlay.apply(
        "mode:demo", {"skills": ["@modes:skills/mode-design-discipline"]}
    )

    cap = coordinator.get_capability("mode_overlay_skills")
    assert cap == ["@modes:skills/mode-design-discipline"]


@pytest.mark.asyncio
async def test_skills_revoke_clears_capability(
    overlay: RuntimeOverlay, coordinator: MagicMock
) -> None:
    await overlay.apply(
        "mode:demo", {"skills": ["@modes:skills/mode-design-discipline"]}
    )
    await overlay.revoke("mode:demo")

    cap = coordinator.get_capability("mode_overlay_skills") or []
    assert cap == []


@pytest.mark.asyncio
async def test_mixed_categories_in_one_apply(
    overlay: RuntimeOverlay, coordinator: MagicMock
) -> None:
    """A single apply can carry agents + context + skills together."""
    await overlay.apply(
        "mode:demo",
        {
            "agents": {"mode-author": {"description": "x"}},
            "context": ["@modes:context/schema.md"],
            "skills": ["@modes:skills/mode-design-discipline"],
        },
    )

    assert "mode-author" in coordinator.config["agents"]
    assert coordinator.get_capability("mode_overlay_context") == [
        "@modes:context/schema.md"
    ]
    assert coordinator.get_capability("mode_overlay_skills") == [
        "@modes:skills/mode-design-discipline"
    ]

    await overlay.revoke("mode:demo")

    assert "mode-author" not in coordinator.config["agents"]
    assert (coordinator.get_capability("mode_overlay_context") or []) == []
    assert (coordinator.get_capability("mode_overlay_skills") or []) == []
```

### Step 2: Run the tests

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_overlay.py -v -k "skills or mixed"
```

Expected: All three tests PASS.

### Step 3: No implementation change expected

The skills path mirrors context exactly. If anything fails, audit `_CAP_OVERLAY_SKILLS` wiring in `_refresh_capability`.

### Step 4: Run the full overlay test file

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_overlay.py -v
```

Expected: All eleven tests PASS.

### Step 5: Commit

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
git add tests/test_overlay.py
git commit -m "test(configurator): cover skills + mixed-category contributions

Skills mirror the context path through mode_overlay_skills capability. A
single apply can carry agents+context+skills; revoke unwinds all three
atomically.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 9: `RuntimeOverlay` — atomic rollback on apply failure

**Files:**
- Modify: `amplifier-foundation/tests/test_overlay.py`

### Step 1: Write the failing test

Append to `amplifier-foundation/tests/test_overlay.py`:

```python
# ---------------------------------------------------------------------------
# Atomic rollback on apply failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_rollback_on_invalid_agent_payload(
    overlay: RuntimeOverlay, coordinator: MagicMock
) -> None:
    """If validation fails partway through, every prior mount in this apply unwinds.

    Sequence: context first (succeeds), then agents with a malformed entry
    (raises). After rollback the context capability must be empty and no
    agent should be in coordinator.config['agents'].
    """
    bad_contributions = {
        "context": ["@modes:context/ok.md"],
        "agents": {"bad-agent": "not-a-dict"},  # validation will reject this
    }

    result = await overlay.apply("mode:bad", bad_contributions)

    assert result.success is False
    assert result.error is not None
    assert "bad-agent" in result.error or "dict" in result.error.lower()

    # context that was mounted before the failure must be rolled back.
    assert (coordinator.get_capability("mode_overlay_context") or []) == []
    assert "bad-agent" not in coordinator.config.get("agents", {})

    # The scope must NOT be marked as applied (so a later retry works).
    result2 = await overlay.apply(
        "mode:bad", {"agents": {"good-agent": {"description": "x"}}}
    )
    assert result2.success is True
    assert "good-agent" in coordinator.config["agents"]


@pytest.mark.asyncio
async def test_apply_rollback_emits_failure_event(
    coordinator: MagicMock,
) -> None:
    """A failed apply emits the failure_event (not the success_event)."""
    overlay = RuntimeOverlay(
        coordinator,
        success_event="mode:transition_completed",
        failure_event="mode:activation_failed",
    )

    await overlay.apply(
        "mode:bad", {"agents": {"x": "not-a-dict"}}
    )

    emitted_events = [call.args[0] for call in coordinator.hooks.emit.call_args_list]
    assert "mode:activation_failed" in emitted_events
    assert "mode:transition_completed" not in emitted_events
```

### Step 2: Run the tests to verify

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_overlay.py -v -k "rollback"
```

Expected: Both tests PASS — the rollback machinery in Task 5 already handles the unwind correctly because `apply()` catches the validation `ValueError`, walks `applied_in_this_call` in reverse, and decrements each.

If either test FAILS:
- Check that ordering of contribution categories is deterministic. Python 3.7+ dict iteration preserves insertion order, so context is processed before agents. Confirm by reading `apply()`.
- Confirm `_decrement` correctly drops `_owned["context"][key]` and refreshes the capability when refcount hits 0.

### Step 3: No new implementation expected

Audit only.

### Step 4: Run the full overlay suite

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_overlay.py -v
```

Expected: All thirteen tests PASS.

### Step 5: Commit

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
git add tests/test_overlay.py
git commit -m "test(configurator): cover atomic rollback on apply failure

Validation-time failure mid-apply unwinds prior mounts in reverse and emits
the failure event. Scope is not marked applied so caller can retry.

Refs: docs/designs/MODE_RUNTIME_OVERLAYS.md §6 step 9, §12.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 10: `RuntimeOverlay` — success-event emission contract

**Files:**
- Modify: `amplifier-foundation/tests/test_overlay.py`

### Step 1: Write the failing test

Append to `amplifier-foundation/tests/test_overlay.py`:

```python
# ---------------------------------------------------------------------------
# Event emission contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_emits_success_event_with_payload(
    overlay: RuntimeOverlay, coordinator: MagicMock
) -> None:
    """Successful apply emits the configured success event with delta payload."""
    await overlay.apply(
        "mode:demo", {"agents": {"a1": {"description": "x"}}}
    )

    success_calls = [
        c
        for c in coordinator.hooks.emit.call_args_list
        if c.args[0] == "mode:transition_completed"
    ]
    assert len(success_calls) == 1
    payload = success_calls[0].args[1]
    assert payload["scope"] == "mode:demo"
    assert payload["success"] is True
    assert ("agents", "a1") in payload["mounted"]


@pytest.mark.asyncio
async def test_revoke_emits_success_event_with_unmounted(
    overlay: RuntimeOverlay, coordinator: MagicMock
) -> None:
    await overlay.apply(
        "mode:demo", {"agents": {"a1": {"description": "x"}}}
    )
    coordinator.hooks.emit.reset_mock()

    await overlay.revoke("mode:demo")

    success_calls = [
        c
        for c in coordinator.hooks.emit.call_args_list
        if c.args[0] == "mode:transition_completed"
    ]
    assert len(success_calls) == 1
    payload = success_calls[0].args[1]
    assert payload["scope"] == "mode:demo"
    assert ("agents", "a1") in payload["unmounted"]


@pytest.mark.asyncio
async def test_event_emit_failure_does_not_break_apply(
    coordinator: MagicMock,
) -> None:
    """If hooks.emit raises, apply still succeeds — event emit is best-effort."""
    coordinator.hooks.emit.side_effect = RuntimeError("hook bus on fire")
    overlay = RuntimeOverlay(
        coordinator,
        success_event="mode:transition_completed",
        failure_event="mode:activation_failed",
    )

    result = await overlay.apply(
        "mode:demo", {"agents": {"a1": {"description": "x"}}}
    )

    assert result.success is True
    assert "a1" in coordinator.config["agents"]
```

### Step 2: Run the tests

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_overlay.py -v -k "event or emit"
```

Expected: All three tests PASS — the existing `_emit` already wraps in try/except and the success-event path already includes the payload fields the tests assert on.

### Step 3: No new implementation expected

If `test_revoke_emits_success_event_with_unmounted` fails, check that `revoke()` is calling `await self._emit(self._success_event, ...)` after the loop completes (Task 5 implementation does).

### Step 4: Run the full overlay suite

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_overlay.py -v
```

Expected: All sixteen tests PASS.

### Step 5: Commit

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
git add tests/test_overlay.py
git commit -m "test(configurator): lock event-emission contract for RuntimeOverlay

apply success -> success_event with mounted delta; revoke -> success_event
with unmounted delta; emit-side failures do not propagate (best-effort).

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 11: Export `RuntimeOverlay` from the configurator package

**Files:**
- Modify: `amplifier-foundation/amplifier_foundation/configurator/__init__.py`
- Modify: `amplifier-foundation/tests/test_overlay.py`

### Step 1: Write the failing test

Append to `amplifier-foundation/tests/test_overlay.py`:

```python
# ---------------------------------------------------------------------------
# Public export
# ---------------------------------------------------------------------------


def test_runtime_overlay_exported_from_configurator_package() -> None:
    """RuntimeOverlay and TransitionResult are importable from the package root."""
    from amplifier_foundation.configurator import RuntimeOverlay, TransitionResult

    assert RuntimeOverlay is not None
    assert TransitionResult is not None
```

### Step 2: Run the test to verify it fails

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_overlay.py::test_runtime_overlay_exported_from_configurator_package -v
```

Expected: FAIL with `ImportError: cannot import name 'RuntimeOverlay' from 'amplifier_foundation.configurator'`.

### Step 3: Add the export

In `amplifier-foundation/amplifier_foundation/configurator/__init__.py`, add the import near the other internal imports (after the `_state_manager` import line, around line 22):

```python
from amplifier_foundation.configurator._overlay import RuntimeOverlay
from amplifier_foundation.configurator._overlay import TransitionResult
```

And update the `__all__` block at the bottom of the file (around line 223) to include both names. The new `__all__` should read:

```python
__all__ = [
    "SessionConfigurator",
    "BundleStateManager",
    "BundleInspector",
    "RuntimeOverlay",
    "TransitionResult",
    "_PROV_CATEGORY_MAP",
    "_normalize_module_name",
    "_build_normalized_prov_lookup",
    "_lookup_prov_behavior",
]
```

### Step 4: Run the export test (and the full overlay suite)

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_overlay.py -v
```

Expected: All seventeen tests PASS.

### Step 5: Commit

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
git add amplifier_foundation/configurator/__init__.py tests/test_overlay.py
git commit -m "feat(configurator): export RuntimeOverlay and TransitionResult

Phase 2 (modes bundle) imports these directly:
    from amplifier_foundation.configurator import RuntimeOverlay

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 12: Smoke test — prepare runs cleanly on the existing modes bundle

**Files:**
- Test: `amplifier-foundation/tests/test_bundle_prepare_modes_walk.py` (modify)

### Step 1: Write the smoke test

Append to `amplifier-foundation/tests/test_bundle_prepare_modes_walk.py`:

```python
def test_validate_modes_clean_on_existing_modes_bundle(tmp_path: Path) -> None:
    """A bundle whose modes/ contains the canonical plan/careful/explore mode
    files (no contributes block, advertised default) produces zero warnings.

    This is the backward-compat smoke test: the new schema must not fault
    when the legacy modes that ship in microsoft/amplifier-bundle-modes are
    parsed by the new loader and walked by prepare()."""
    modes_dir = tmp_path / "modes"
    modes_dir.mkdir()

    # Mirror the shipped shape — no contributes, no advertised key.
    _write(
        modes_dir / "plan.md",
        """---
mode:
  name: plan
  description: "Plan only — no writes."
  shortcut: plan
  default_action: warn
  tools:
    safe: [read_file, glob, grep]
    warn: [bash]
---

You are in plan mode. Read-only.
""",
    )
    _write(
        modes_dir / "careful.md",
        """---
mode:
  name: careful
  description: "Confirm before writes."
  shortcut: careful
  default_action: allow
  tools:
    confirm: [write_file, edit_file, bash]
---

Careful mode body.
""",
    )
    _write(
        modes_dir / "explore.md",
        """---
mode:
  name: explore
  description: "Read-only exploration."
  shortcut: explore
  default_action: block
  tools:
    safe: [read_file, glob, grep]
---

Explore mode body.
""",
    )

    bundle = Bundle(name="modes", base_path=tmp_path)
    warnings = bundle.validate_modes()

    assert warnings == []
```

### Step 2: Run the smoke test

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_bundle_prepare_modes_walk.py::test_validate_modes_clean_on_existing_modes_bundle -v
```

Expected: PASS.

### Step 3: Run the full Phase 1 test surface

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/test_overlay.py tests/test_load_mode_metadata.py tests/test_bundle_prepare_modes_walk.py -v
```

Expected: All twenty-two tests PASS.

Then run the full foundation suite to confirm zero regressions:

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run pytest tests/ -q --timeout=60 2>&1 | tail -10
```

Expected: green.

### Step 4: Run linters / typecheckers

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
uv run python -m pyright amplifier_foundation/configurator/_overlay.py amplifier_foundation/bundle/_dataclass.py 2>&1 | tail -20
```

Expected: zero errors. (Warnings about untyped `MagicMock` returns in test files are fine — those are test-only.)

### Step 5: Commit

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
git add tests/test_bundle_prepare_modes_walk.py
git commit -m "test(bundle): smoke-test prepare modes-walk against legacy mode files

Confirms backward compatibility: plan.md/careful.md/explore.md (no
contributes, no advertised) parse cleanly through the new loader and
produce zero warnings from validate_modes().

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Phase 1 Complete — Checklist

Before declaring Phase 1 done, confirm:

- [ ] All 22 Phase-1 tests pass: `uv run pytest tests/test_overlay.py tests/test_load_mode_metadata.py tests/test_bundle_prepare_modes_walk.py -v`
- [ ] Full foundation suite stays green: `uv run pytest tests/ -q --timeout=60`
- [ ] `_load_mode_file_metadata` is callable from `amplifier_foundation.bundle._dataclass`
- [ ] `Bundle.validate_modes()` is a public method on `Bundle` and is invoked from `prepare()` between the agents pre-activation walk and `activate_all`
- [ ] `RuntimeOverlay` and `TransitionResult` are importable from `amplifier_foundation.configurator`
- [ ] The modes walk is a clean no-op on a bundle without a `modes/` directory
- [ ] The modes walk is a clean no-op on a bundle whose `modes/` contains only legacy `.md` files (no `contributes`, no `advertised`)
- [ ] Pyright reports zero errors on the new files
- [ ] All commits follow conventional-commit prefixes (`feat:`, `test:`) and include the Amplifier co-author trailer
- [ ] Branch `feat/mode-overlays-phase-1` exists with a clean linear history of the twelve task commits

When every box is ticked:

```bash
cd /home/bkrabach/dev/modes-updates/amplifier-foundation
git log --oneline -15
```

…and Phase 2 (`amplifier-bundle-modes` integration) and Phase 3 (`/mode-design` vertical slice) are unblocked.
