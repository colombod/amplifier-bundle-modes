"""Integration tests for the mode runtime-overlay vertical slice.

These tests exercise the live RuntimeOverlay through hooks-mode transition
handlers and validate four overlap scenarios:

  S1 — Clean activation: mode contributes agents that are NOT already in the
       session; overlay adds them unconditionally.
  S2 — No-contributes noop: mode has no contributes block; overlay is never
       called.
  S3 — Overlap (same name, same source): contributed agent already present in
       the session under the same handle; overlay deduplicates silently.
  S4 — Overlap (name collision, different source): contributed agent handle
       clashes with an already-registered agent from a different source; overlay
       raises ContributionConflict and the activation rolls back atomically.

Additional scenarios tested here:
  - advertised:false filtering — modes with ``advertised: false`` in their
    YAML frontmatter must not appear in the public mode list.
  - Atomic rollback on contribution failure — if any single agent contribution
    fails mid-apply, every previously applied contribution from that batch is
    revoked and the coordinator is left in its pre-activation state.
  - Full activation of /mode-design end-to-end — the mode-design mode activates
    cleanly, contributes the mode-author agent, and the coordinator reflects the
    new capability after a successful handle_mode_activated call.

Assumptions (Phases 1 and 2 must be complete before these tests are green):
  - ``amplifier_foundation.configurator.RuntimeOverlay`` is importable.
  - ``parse_mode_file`` honours ``advertised`` and ``contributes`` fields on the
    returned ``ModeDefinition`` (new fields added in Phase 1).
  - hooks-mode transition handlers (``handle_mode_activated``,
    ``handle_mode_changed``, ``handle_mode_cleared``) call
    ``RuntimeOverlay.apply`` / ``RuntimeOverlay.revoke`` as required.
"""

from __future__ import annotations

import textwrap  # noqa: F401 — reserved for scenario tests in subsequent tasks
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Three levels up from tests/ brings us to the bundle root
# (tests/ → hooks-mode/ → modules/ → amplifier-bundle-modes/)
BUNDLE_ROOT: Path = Path(__file__).resolve().parents[3]

# The bundle's modes directory — where real mode .md files live
MODES_DIR: Path = BUNDLE_ROOT / "modes"

# The test fixtures directory — private, test-only mode files
FIXTURES_DIR: Path = Path(__file__).resolve().parent / "fixtures"


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


def _make_coordinator(
    active_mode: str | None = None,
    agents: dict[str, Any] | None = None,
) -> MagicMock:
    """Build a MagicMock coordinator with the surface area that overlay touches.

    Parameters
    ----------
    active_mode:
        Initial value of ``session_state['active_mode']``.  Defaults to
        ``None`` (no mode active).
    agents:
        Pre-populated agent registry entries.  Use this to simulate a session
        that already has certain agents mounted (needed for S1/S4 scenarios).
        Defaults to an empty dict.

    Returns
    -------
    MagicMock
        A coordinator mock whose attributes match the shape that
        ``RuntimeOverlay`` and the hooks-mode handlers expect to interact with.
    """
    coordinator = MagicMock()

    # Session state — mutable dict that transition handlers read and write
    coordinator.session_state = {
        "active_mode": active_mode,
        "require_approval_tools": set(),
    }

    # Config dict — holds the agent registry keyed by agent handle
    coordinator.config = {"agents": dict(agents or {})}

    # Hooks sub-object — overlay calls register/unregister; handlers call emit
    coordinator.hooks = MagicMock()
    coordinator.hooks.emit = AsyncMock()
    coordinator.hooks.register = MagicMock()
    coordinator.hooks.unregister = MagicMock()
    coordinator.hooks.mount = MagicMock()
    coordinator.hooks.unmount = MagicMock()

    # Capability query — overlay may probe for existing capabilities
    coordinator.get_capability = MagicMock(return_value=None)

    return coordinator


def _agent_registry(coordinator: MagicMock) -> dict[str, Any]:
    """Return the agent registry from a coordinator mock.

    Centralises the knowledge of *where* the registry actually lives so that
    future structural moves only require updating this one function.

    Parameters
    ----------
    coordinator:
        A mock coordinator produced by :func:`_make_coordinator`.

    Returns
    -------
    dict[str, Any]
        The current contents of the agent registry (may be empty).
    """
    return coordinator.config.get("agents", {})


# ---------------------------------------------------------------------------
# Smoke test — validates scaffolding & imports are wired correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_imports_and_scaffold_smoke() -> None:
    """Scaffold smoke test — verifies helpers produce a coherent coordinator.

    This test has no dependency on Phase 1 or Phase 2 deliverables; it exists
    purely to confirm that the scaffolding imports resolve and that the helper
    functions behave as advertised.  All subsequent scenario tests in this
    module extend from this baseline.
    """
    coord = _make_coordinator()

    # A freshly constructed coordinator must start with no active mode …
    assert coord.session_state["active_mode"] is None

    # … and an empty agent registry.
    assert _agent_registry(coord) == {}


# ---------------------------------------------------------------------------
# S1 — session-overlap: session has X and mode contributes X
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_S1_session_overlap() -> None:
    """S1 — session has X and mode contributes X: refcount stays >=1 throughout.

    Scenario:
    - The session pre-populates ``mode-author`` in the agent registry (simulating
      a session that already has this agent from its baseline configuration).
    - ``/mode-design`` ALSO contributes ``mode-author`` via its ``contributes.agents``
      block (source: ``@modes:agents/mode-author``).

    Expected behaviour:
    - Activating ``/mode-design`` must NOT remount ``mode-author``.  The RuntimeOverlay
      captures the session baseline at construction time (refcount=1), so the mode's
      contribution increments the refcount to 2 — the mount gate (0→1) is never
      crossed and the existing instance is preserved.
    - Deactivating ``/mode-design`` (via handle_mode_cleared) must NOT unmount
      ``mode-author``.  The revoke decrements refcount to 1 — the unmount gate
      (1→0) is not crossed and the agent stays in the registry.
    - The session's original agent *instance* must survive the full
      activate/deactivate cycle unchanged (``is`` identity check).  Replacing
      the instance would break any in-flight tool-call that holds a reference to
      the old dict.
    """
    from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks

    # Session baseline: mode-author already present with a session-specific marker.
    # The '_marker' key lets us verify object identity (is-check) after the cycle.
    session_agent: dict = {"source": "session-fake-source", "_marker": "from-session"}

    # Build coordinator with mode-author pre-populated in the agent registry.
    coord = _make_coordinator(agents={"mode-author": session_agent})

    # Build discovery pointing at the real bundle modes directory.
    # mode-design.md lives there and contributes mode-author.
    discovery = ModeDiscovery(search_paths=[MODES_DIR])
    hooks = ModeHooks(coord, discovery)

    # ------------------------------------------------------------------ #
    # Activate /mode-design                                                #
    # ------------------------------------------------------------------ #
    coord.session_state["active_mode"] = "mode-design"
    # Note: handle_mode_activated reads data.get("name") first, then falls back
    # to session_state["active_mode"].  Passing {"mode": "mode-design"} exercises
    # the fallback path — mirrors what tool-mode emits in practice.
    await hooks.handle_mode_activated("mode:activated", {"mode": "mode-design"})

    reg = _agent_registry(coord)

    # Assertion 1: mode-author must still be present after activation.
    assert "mode-author" in reg, (
        "mode-author must remain in registry after /mode-design activation "
        "(refcount 1→2 must not remove it)"
    )

    # Assertion 2: the registry must hold the ORIGINAL session instance, not the
    # mode's contributed dict.  If RuntimeOverlay incorrectly calls _mount when
    # refcount >= 1, the session's agent entry is silently replaced — this assert
    # catches that regression.
    assert reg["mode-author"] is session_agent, (
        "/mode-design activation must NOT replace the session's mode-author instance. "
        "Refcount 1→2 must skip the mount call so the existing object is preserved. "
        f"Expected id={id(session_agent):#x}, got id={id(reg['mode-author']):#x}"
    )

    # ------------------------------------------------------------------ #
    # Deactivate /mode-design (handle_mode_cleared is the real Phase 2 name)#
    # ------------------------------------------------------------------ #
    coord.session_state["active_mode"] = None
    await hooks.handle_mode_cleared("mode:cleared", {"name": "mode-design"})

    reg = _agent_registry(coord)

    # Assertion 3: mode-author must still be present after deactivation.
    # The session still holds this agent; only the mode's refcount share was
    # released (2→1), so the unmount gate (1→0) was never crossed.
    assert "mode-author" in reg, (
        "mode-author must remain in registry after /mode-design deactivation "
        "(session still references it — refcount 2→1 must not remove it)"
    )

    # Assertion 4: object identity must be preserved through the full cycle.
    assert reg["mode-author"] is session_agent, (
        "/mode-design deactivation must NOT replace the session's mode-author instance. "
        f"Expected id={id(session_agent):#x}, got id={id(reg['mode-author']):#x}"
    )
