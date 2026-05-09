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


# ---------------------------------------------------------------------------
# advertised:false filtering — mode-design hidden from LLM, visible to humans
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_advertised_false_filtering() -> None:
    """mode-design is advertised:false — hidden from LLM listings, visible to humans.

    Scenario:
    - mode-design.md has ``advertised: false`` in its YAML frontmatter.
    - plan, careful, and explore are advertised (default: advertised: true).

    Expected behaviour:
    - ModeDiscovery.list_modes(include_unadvertised=False) must NOT include
      mode-design.  This is the LLM-facing listing — unadvertised modes are
      internal-only and must never be surfaced to the model.
    - ModeDiscovery.list_modes(include_unadvertised=True) MUST include
      mode-design.  Human-facing surfaces (e.g. ``/modes --all`` in the CLI)
      should expose every mode so operators can inspect the full catalogue.
    - The tool-mode mode(list) operation calls list_modes() with no kwargs
      (default: include_unadvertised=False), so its output must also exclude
      mode-design.  This is verified by comparing the no-args call to the
      explicit False call.
    - plan, careful, and explore must appear in BOTH listing variants — they
      are the canonical advertised modes and must always be reachable.

    Guard clause:
    - If list_modes() does not accept include_unadvertised, Phase 2 is not
      complete.  The TypeError from the unknown keyword argument will cause
      this test to error, signalling that the discovery filter must be
      implemented before this test can pass.
    """
    from amplifier_module_hooks_mode import ModeDiscovery

    # Point discovery at the real bundle modes directory.
    discovery = ModeDiscovery(search_paths=[MODES_DIR])

    # ------------------------------------------------------------------ #
    # LLM-facing listing: include_unadvertised=False (the default)        #
    # ------------------------------------------------------------------ #
    llm_visible = discovery.list_modes(include_unadvertised=False)
    llm_visible_names = {entry[0] for entry in llm_visible}

    assert "mode-design" not in llm_visible_names, (
        "advertised:false mode 'mode-design' must NOT appear in the LLM-facing "
        "listing (include_unadvertised=False).  The LLM must never see internal-only "
        "modes; they are surfaced only via human-facing /modes --all."
    )

    # ------------------------------------------------------------------ #
    # Human-facing listing: include_unadvertised=True                     #
    # ------------------------------------------------------------------ #
    human_visible = discovery.list_modes(include_unadvertised=True)
    human_visible_names = {entry[0] for entry in human_visible}

    assert "mode-design" in human_visible_names, (
        "advertised:false mode 'mode-design' MUST appear when include_unadvertised=True. "
        "Human-facing surfaces need full visibility into every mode in the catalogue, "
        "including internal-only ones."
    )

    # ------------------------------------------------------------------ #
    # tool-mode mode(list) operation uses list_modes() with no kwargs     #
    # Verify the no-args call matches include_unadvertised=False exactly. #
    # ------------------------------------------------------------------ #
    default_visible = discovery.list_modes()
    default_visible_names = {entry[0] for entry in default_visible}

    assert "mode-design" not in default_visible_names, (
        "tool-mode calls discovery.list_modes() with no args.  "
        "The default (include_unadvertised=False) must also hide mode-design, "
        "ensuring the tool-mode list operation never surfaces unadvertised modes."
    )

    # The two LLM-facing calls should agree
    assert default_visible_names == llm_visible_names, (
        "list_modes() with no args must produce the same set as "
        "list_modes(include_unadvertised=False).  "
        f"no-args={default_visible_names!r}, explicit-False={llm_visible_names!r}"
    )

    # ------------------------------------------------------------------ #
    # Canonical advertised modes: plan / careful / explore                #
    # Must appear in BOTH listings.                                       #
    # ------------------------------------------------------------------ #
    for mode_name in ("plan", "careful", "explore"):
        assert mode_name in llm_visible_names, (
            f"Advertised mode '{mode_name}' must appear in the LLM-facing listing "
            f"(include_unadvertised=False).  Found: {sorted(llm_visible_names)}"
        )
        assert mode_name in human_visible_names, (
            f"Advertised mode '{mode_name}' must appear in the human-facing listing "
            f"(include_unadvertised=True).  Found: {sorted(human_visible_names)}"
        )


# ---------------------------------------------------------------------------
# S2 — mode-only: item absent in session, contributed by mode only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_S2_mode_only() -> None:
    """S2 — mode-only contribution mounts on activate and unmounts on deactivate.

    Scenario:
    - The session has NO ``mode-author`` in its baseline agent registry.
    - ``/mode-design`` contributes ``mode-author`` via its ``contributes.agents`` block.

    Expected behaviour:
    - Before activation: ``mode-author`` must NOT be in the registry (refcount=0).
    - Activating ``/mode-design`` must MOUNT ``mode-author``.  The RuntimeOverlay
      sees refcount go 0→1, crossing the mount gate, and adds the agent to
      ``coordinator.config["agents"]``.
    - Deactivating ``/mode-design`` must UNMOUNT ``mode-author``.  The RuntimeOverlay
      decrements refcount 1→0, crossing the unmount gate, and removes the agent
      from the registry.  After deactivation the registry must be empty again.
    """
    from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks

    # Session baseline: no mode-author at session level (empty agent registry).
    coord = _make_coordinator(agents={})

    # Build discovery pointing at the real bundle modes directory.
    discovery = ModeDiscovery(search_paths=[MODES_DIR])
    hooks = ModeHooks(coord, discovery)

    # ------------------------------------------------------------------ #
    # Pre-activation: mode-author must NOT be in the registry             #
    # ------------------------------------------------------------------ #
    assert "mode-author" not in _agent_registry(coord), (
        "mode-author must be absent before /mode-design activation "
        "(session has no baseline entry for this agent)"
    )

    # ------------------------------------------------------------------ #
    # Activate /mode-design                                                #
    # ------------------------------------------------------------------ #
    coord.session_state["active_mode"] = "mode-design"
    await hooks.handle_mode_activated("mode:activated", {"mode": "mode-design"})

    reg = _agent_registry(coord)

    # Assertion 1: mode-author must appear in the registry after activation.
    assert "mode-author" in reg, (
        "mode-author must be in registry after /mode-design activation "
        "(S2: contribution must mount on activation, refcount 0→1)"
    )

    # ------------------------------------------------------------------ #
    # Deactivate /mode-design                                              #
    # ------------------------------------------------------------------ #
    coord.session_state["active_mode"] = None
    # NOTE: Phase 2 shipped handler is handle_mode_cleared, not handle_mode_deactivated.
    # Using the correct name here after wiring verification.
    await hooks.handle_mode_cleared("mode:cleared", {"name": "mode-design"})

    reg = _agent_registry(coord)

    # Assertion 2: mode-author must disappear from the registry after deactivation.
    assert "mode-author" not in reg, (
        "mode-author must be absent after /mode-design deactivation "
        "(S2: contribution must unmount on deactivation, refcount 1→0)"
    )


# ---------------------------------------------------------------------------
# S3 — two modes same item: both modes contribute mode-author; session has none
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_S3_two_modes_same_item() -> None:
    """S3 — two modes contribute the same item; end-state assertions only.

    Scenario:
    - The session has NO ``mode-author`` in its baseline agent registry.
    - Both ``/mode-design`` and ``test-overlap-mode`` contribute ``mode-author``
      via their ``contributes.agents`` blocks (same source:
      ``@modes:agents/mode-author``).

    Expected end-state behaviour (v1 unmount/remount churn is acceptable):
    - M1 active (mode-design):  ``mode-author`` IS in registry (mounted, refcount 0→1).
    - M2 active (test-overlap-mode), M1 cleared:
        During the switch, mode-author may briefly unmount (refcount 1→0) then
        remount (refcount 0→1) — this churn is acceptable in v1 and documented
        in design §7.  The test only asserts the END STATE: mode-author IS
        present after M2 is fully activated.
    - Both modes inactive (M2 cleared):  ``mode-author`` is NOT in registry
        (refcount back to 0, unmount gate crossed, removed from registry).
    """
    from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks

    # Session baseline: empty — mode-author not present at session level.
    coord = _make_coordinator(agents={})

    # Build discovery pointing at BOTH the real modes directory AND the test
    # fixtures directory so that test-overlap-mode.md is discoverable.
    discovery = ModeDiscovery(search_paths=[MODES_DIR, FIXTURES_DIR])
    hooks = ModeHooks(coord, discovery)

    # ------------------------------------------------------------------ #
    # Activate M1: /mode-design                                           #
    # ------------------------------------------------------------------ #
    coord.session_state["active_mode"] = "mode-design"
    await hooks.handle_mode_activated("mode:activated", {"mode": "mode-design"})

    reg = _agent_registry(coord)

    # Assertion 1 (S3: M1 active → mode-author mounted)
    assert "mode-author" in reg, (
        "S3: mode-author must be in registry after /mode-design activation "
        "(M1 active → mode-author mounted, refcount 0→1)"
    )

    # ------------------------------------------------------------------ #
    # Switch to M2: test-overlap-mode                                     #
    # Deactivate M1 (cleared), then activate M2.                          #
    # v1 may briefly unmount/remount mode-author during the transition;   #
    # the test only checks the end state after M2 is fully active.        #
    # ------------------------------------------------------------------ #
    await hooks.handle_mode_cleared("mode:cleared", {"name": "mode-design"})
    coord.session_state["active_mode"] = "test-overlap-mode"
    await hooks.handle_mode_activated("mode:activated", {"mode": "test-overlap-mode"})

    reg = _agent_registry(coord)

    # Assertion 2 (S3: M2 active → mode-author mounted, end-state check)
    assert "mode-author" in reg, (
        "S3: mode-author must be in registry after switching to test-overlap-mode "
        "(M2 active → mode-author mounted; v1 unmount/remount churn is acceptable, "
        "but end state must show agent present)"
    )

    # ------------------------------------------------------------------ #
    # Deactivate M2: both modes now inactive                              #
    # ------------------------------------------------------------------ #
    coord.session_state["active_mode"] = None
    await hooks.handle_mode_cleared("mode:cleared", {"name": "test-overlap-mode"})

    reg = _agent_registry(coord)

    # Assertion 3 (S3: both M1 and M2 inactive → mode-author unmounted)
    assert "mode-author" not in reg, (
        "S3: mode-author must be absent after both modes deactivated "
        "(both M1 and M2 inactive → mode-author unmounted, refcount 1→0)"
    )


# ---------------------------------------------------------------------------
# S4 — session + two modes: session has mode-author; both modes contribute it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_S4_session_plus_two_modes() -> None:
    """S4 — session + two modes contribute same item; refcount stays >=1 across all transitions.

    Scenario:
    - The session pre-populates ``mode-author`` in the agent registry (refcount=1
      from session baseline).
    - ``/mode-design`` ALSO contributes ``mode-author`` (refcount goes 1→2 on
      activation, 2→1 on deactivation — unmount gate never crossed).
    - ``test-overlap-mode`` ALSO contributes ``mode-author`` (same refcount
      semantics: 1→2 on activation, 2→1 on deactivation).

    Expected behaviour across every transition:
    - ``mode-author`` must ALWAYS remain in the registry.  The session's baseline
      contribution keeps the refcount at >=1 even when both modes are inactive.
    - The session's original agent *instance* must never be replaced.  Any mode
      activation that finds refcount>=1 must skip the mount call and leave the
      existing object in place.  Replacing the instance would break in-flight
      tool-calls holding a reference to the old dict.
    """
    from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks

    # Session baseline: mode-author already present with a session-specific marker.
    # The '_marker' key lets us verify object identity (is-check) after each transition.
    session_agent: dict = {"source": "session-fake-source", "_marker": "from-session"}

    # Build coordinator with mode-author pre-populated in the agent registry.
    coord = _make_coordinator(agents={"mode-author": session_agent})

    # Build discovery pointing at BOTH the real modes directory AND the test
    # fixtures directory so that test-overlap-mode.md is discoverable.
    discovery = ModeDiscovery(search_paths=[MODES_DIR, FIXTURES_DIR])
    hooks = ModeHooks(coord, discovery)

    # Helper closure: asserts the session instance is present and never replaced.
    def _assert_session_instance() -> None:
        reg = _agent_registry(coord)
        assert "mode-author" in reg, (
            "mode-author must remain in registry (S4: session holds refcount>=1 at all times)"
        )
        assert reg["mode-author"] is session_agent, (
            "S4: existing session instance must never be replaced by mode contributions. "
            f"Expected id={id(session_agent):#x}, got id={id(reg['mode-author']):#x}"
        )

    # ------------------------------------------------------------------ #
    # Pre-activation: session holds mode-author (refcount=1)              #
    # ------------------------------------------------------------------ #
    _assert_session_instance()

    # ------------------------------------------------------------------ #
    # Activate /mode-design (refcount: 1→2)                               #
    # mode-author must stay present and instance must be unchanged.       #
    # ------------------------------------------------------------------ #
    coord.session_state["active_mode"] = "mode-design"
    await hooks.handle_mode_activated("mode:activated", {"mode": "mode-design"})
    _assert_session_instance()

    # ------------------------------------------------------------------ #
    # Switch to test-overlap-mode:                                        #
    #   Deactivate mode-design (refcount: 2→1) — session still holds.    #
    #   Activate test-overlap-mode (refcount: 1→2).                      #
    # ------------------------------------------------------------------ #
    await hooks.handle_mode_cleared("mode:cleared", {"name": "mode-design"})
    coord.session_state["active_mode"] = "test-overlap-mode"
    await hooks.handle_mode_activated("mode:activated", {"mode": "test-overlap-mode"})
    _assert_session_instance()

    # ------------------------------------------------------------------ #
    # Deactivate test-overlap-mode (refcount: 2→1)                       #
    # Session still holds mode-author — unmount gate (1→0) never crossed. #
    # ------------------------------------------------------------------ #
    coord.session_state["active_mode"] = None
    await hooks.handle_mode_cleared("mode:cleared", {"name": "test-overlap-mode"})
    _assert_session_instance()


# ---------------------------------------------------------------------------
# Rollback — activation fails partway through; coordinator returns to
# pre-activation state atomically
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contribution_failure_rollback(tmp_path: Path) -> None:
    """Atomic rollback on contribution failure.

    Scenario:
    - A mode 'broken-overlap' contributes two agents:
      - mode-author: valid source ``@modes:agents/mode-author``
      - this-does-not-exist: deliberately broken (bare string value, not a
        nested dict), so ``RuntimeOverlay._normalise_agents`` raises a
        ``ValueError`` when it encounters the entry.

    Expected behaviour (Phase 1 atomic-apply guarantees):
    - The overlay must roll back every item it touched in that transition so
      that the coordinator is left in its pre-activation state.
    - handle_mode_activated must clear ``active_mode`` after a failed apply,
      preventing the session from being stuck in a half-activated mode.
    - MODE_ACTIVATION_FAILED (or an equivalent event whose name contains
      'activation_failed') must be emitted so that callers can observe the
      failure.

    Phase 1 gap note:
      If RuntimeOverlay does not implement atomic rollback, this is a
      Phase 1 gap — stop and fix in Phase 1, not Phase 3.
    """

    from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks

    # ------------------------------------------------------------------ #
    # Build the broken-overlap fixture in a temp directory                #
    # ------------------------------------------------------------------ #
    bad_mode_dir = tmp_path / "bad-modes"
    bad_mode_dir.mkdir()

    broken_mode_file = bad_mode_dir / "broken-overlap.md"
    broken_mode_file.write_text(
        textwrap.dedent("""\
            ---
            mode:
              name: broken-overlap
              shortcut: false
              advertised: false
              default_action: block
              tools:
                safe:
                  - delegate
                  - mode
              contributes:
                agents:
                  mode-author:
                    source: "@modes:agents/mode-author"
                  this-does-not-exist: "@modes:agents/this-does-not-exist"
            ---

            Broken on purpose.
        """),
        encoding="utf-8",
    )

    # ------------------------------------------------------------------ #
    # Build coordinator (empty baseline), discovery, hooks                #
    # ------------------------------------------------------------------ #
    coord = _make_coordinator(agents={})

    # Include both the shipped modes dir AND the broken fixture dir so that
    # both mode-author (from mode-design.md) and broken-overlap are visible.
    discovery = ModeDiscovery(search_paths=[MODES_DIR, bad_mode_dir])
    hooks = ModeHooks(coord, discovery)

    # ------------------------------------------------------------------ #
    # Trigger activation — expected to fail                               #
    # ------------------------------------------------------------------ #
    coord.session_state["active_mode"] = "broken-overlap"
    await hooks.handle_mode_activated("mode:activated", {"mode": "broken-overlap"})

    # ------------------------------------------------------------------ #
    # Assertion 1: failed activation must clear active_mode               #
    # ------------------------------------------------------------------ #
    active = coord.session_state.get("active_mode")
    assert active in (None, ""), (
        f"Failed activation must clear active_mode but got {active!r}. "
        "handle_mode_activated must set active_mode to None/'' when "
        "overlay.apply() returns success=False, so the session is not "
        "stuck in a half-activated mode state."
    )

    # ------------------------------------------------------------------ #
    # Assertion 2: atomic rollback — mode-author must NOT be in registry  #
    # ------------------------------------------------------------------ #
    assert "mode-author" not in _agent_registry(coord), (
        "'mode-author' must NOT be in the agent registry after a failed activation. "
        "Atomic rollback: every item mounted before the failure must be unmounted "
        "so the coordinator returns to its pre-activation baseline. "
        f"Registry contents: {list(_agent_registry(coord).keys())}"
    )

    # ------------------------------------------------------------------ #
    # Assertion 3: MODE_ACTIVATION_FAILED (or equivalent) must be emitted #
    # ------------------------------------------------------------------ #
    emit_calls = coord.hooks.emit.await_args_list
    failed_events = [
        call
        for call in emit_calls
        if call.args and "activation_failed" in str(call.args[0]).lower()
    ]
    all_events_seen = [
        call.args[0] if call.args else "<no-args>" for call in emit_calls
    ]
    assert failed_events, (
        "MODE_ACTIVATION_FAILED (or an event whose name contains "
        "'activation_failed') must be emitted when overlay.apply() fails "
        "and rolls back. All events seen in this test run: "
        f"{all_events_seen}"
    )
