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

import textwrap
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
    """mode-design is advertised:false — carries the flag for consumer-side filtering.

    After the mechanism/policy split, list_modes() always returns ALL modes.
    The .advertised field carries the metadata; consumers (tool-mode, CLI) decide
    what to show based on that field.

    Scenario:
    - mode-design.md has ``advertised: false`` in its YAML frontmatter.
    - plan, careful, and explore are advertised (default: advertised: true).

    Expected behaviour:
    - list_modes() ALWAYS includes mode-design; no filtering at the discovery layer.
    - mode-design has ModeListing.advertised == False.
    - plan/careful/explore have ModeListing.advertised == True.
    - Consumer-side LLM filter (filter(lambda e: e.advertised, ...)) excludes
      mode-design — demonstrating the policy lives in the consumer, not the mechanism.
    - Passing include_unadvertised kwarg still works (for backward compat) but emits
      DeprecationWarning.
    """
    import warnings

    from amplifier_module_hooks_mode import ModeDiscovery

    # Point discovery at the real bundle modes directory.
    discovery = ModeDiscovery(search_paths=[MODES_DIR])

    # ------------------------------------------------------------------ #
    # list_modes() returns ALL modes including unadvertised               #
    # ------------------------------------------------------------------ #
    all_modes = discovery.list_modes()
    all_names = {entry.name for entry in all_modes}

    assert "mode-design" in all_names, (
        "list_modes() must return ALL modes including unadvertised ones. "
        "mode-design (advertised:false) must be in the full listing."
    )

    # ------------------------------------------------------------------ #
    # .advertised field accurately reflects frontmatter                  #
    # ------------------------------------------------------------------ #
    entries_by_name = {entry.name: entry for entry in all_modes}

    assert entries_by_name["mode-design"].advertised is False, (
        "mode-design must have .advertised == False in its ModeListing entry."
    )

    # Canonical advertised modes must be present with advertised=True
    for mode_name in ("plan", "careful", "explore"):
        assert mode_name in entries_by_name, (
            f"Canonical mode '{mode_name}' must appear in list_modes()."
        )
        assert entries_by_name[mode_name].advertised is True, (
            f"Mode '{mode_name}' must have .advertised == True."
        )

    # ------------------------------------------------------------------ #
    # Consumer-side LLM filter excludes mode-design                      #
    # ------------------------------------------------------------------ #
    llm_visible_names = {entry.name for entry in all_modes if entry.advertised}

    assert "mode-design" not in llm_visible_names, (
        "Consumer-side filter on .advertised must exclude mode-design from "
        "LLM-facing listings."
    )
    for mode_name in ("plan", "careful", "explore"):
        assert mode_name in llm_visible_names, (
            f"Advertised mode '{mode_name}' must survive the consumer filter."
        )

    # ------------------------------------------------------------------ #
    # Deprecated include_unadvertised kwarg emits DeprecationWarning     #
    # ------------------------------------------------------------------ #
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        discovery.list_modes(include_unadvertised=False)

    deprecations = [x for x in w if issubclass(x.category, DeprecationWarning)]
    assert len(deprecations) == 1, (
        "Passing include_unadvertised kwarg must emit exactly one DeprecationWarning."
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


# ---------------------------------------------------------------------------
# End-to-end — full /mode-design activation: agent + context + skill all live
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mode_design_end_to_end() -> None:
    """Full activation of /mode-design: agent + context + skill all live;
    deactivation: all three gone.

    Scenario:
    - The session starts with an empty agent registry.
    - /mode-design is activated via handle_mode_activated.

    After activation:
    1. ``mode-author`` is reachable in the agent registry (proxy for delegate).
    2. The body of ``mode-schema-reference.md`` (specifically the string
       "Amplifier Mode Schema Reference") ends up in the injected system-reminder
       context when handle_provider_request fires.
    3. The skill ``mode-design-discipline`` is discoverable via the overlay's
       registered capability (mode_overlay_skills).

    After deactivation:
    - All three are gone: agent removed, schema reference absent from context,
      skill removed from capability.

    Notes on implementation details:
    - Phase 2 shipped ``handle_mode_cleared`` (not ``handle_mode_deactivated``);
      the test uses the actual handler name.
    - Phase 2 stores skills via ``coordinator.register_capability('mode_overlay_skills', [...])``.
      The skills check below reads from ``register_capability`` mock call log, not
      ``coordinator.config['skills']``.  The spec allows updating only these lines.
    """
    from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks

    # Session baseline: empty agent registry.
    coord = _make_coordinator(agents={})
    discovery = ModeDiscovery(search_paths=[MODES_DIR])
    hooks = ModeHooks(coord, discovery)

    # ------------------------------------------------------------------ #
    # ACTIVATE /mode-design                                                #
    # ------------------------------------------------------------------ #
    coord.session_state["active_mode"] = "mode-design"
    await hooks.handle_mode_activated("mode:activated", {"mode": "mode-design"})

    # ---- 1. Agent: mode-author must be reachable in the registry ----
    reg = _agent_registry(coord)
    assert "mode-author" in reg, (
        "mode-author agent must be reachable in the agent registry "
        "after /mode-design activation (the contributed agent was not mounted)"
    )

    # ---- 2. Context: schema reference body in injected system-reminder ----
    result = await hooks.handle_provider_request("provider:request", {})
    assert result.action == "inject_context", (
        f"Expected action='inject_context', got {result.action!r}. "
        "handle_provider_request must inject the mode body while mode-design is active."
    )
    injected: str = result.context_injection or ""
    # 'Amplifier Mode Schema Reference' is the signature line in mode-schema-reference.md;
    # it must be present in the injected mode body (either directly or via the mode body
    # referencing it).
    assert "Amplifier Mode Schema Reference" in injected, (
        "The string 'Amplifier Mode Schema Reference' must appear in the injected context "
        "when /mode-design is active. This signature line is present in "
        "context/mode-schema-reference.md and must be referenced in the mode body. "
        f"Injected context (first 500 chars): {injected[:500]!r}"
    )

    # ---- 3. Skill discoverability: mode_overlay_skills capability ----
    # Phase 2 stores skills via register_capability('mode_overlay_skills', [paths...]).
    # Read from the mock's call log since coord.config['skills'] is not updated by Phase 2.
    # (If Phase 2 chose a different storage slot, update only these lines.)
    _skills_cap_calls: list[Any] = [
        call.args[1]
        for call in coord.register_capability.call_args_list
        if call.args and call.args[0] == "mode_overlay_skills"
    ]
    skills_in_play: list[str] = _skills_cap_calls[-1] if _skills_cap_calls else []
    assert any("mode-design-discipline" in str(s) for s in skills_in_play), (
        "mode-design-discipline skill must be discoverable via mode_overlay_skills capability "
        "while /mode-design is active. "
        f"Skills registered: {skills_in_play!r}"
    )

    # ------------------------------------------------------------------ #
    # DEACTIVATE /mode-design                                              #
    # Phase 2 shipped handle_mode_cleared, not handle_mode_deactivated.   #
    # ------------------------------------------------------------------ #
    coord.session_state["active_mode"] = None
    await hooks.handle_mode_cleared("mode:cleared", {"name": "mode-design"})

    # ---- 1. Agent gone ----
    assert "mode-author" not in _agent_registry(coord), (
        "mode-author must be removed from the agent registry after "
        "/mode-design deactivation (the contributed agent was not unmounted)"
    )

    # ---- 2. Context gone: provider request must not inject the schema ref ----
    result_after = await hooks.handle_provider_request("provider:request", {})
    if result_after.action == "inject_context":
        injected_after: str = result_after.context_injection or ""
        assert "Amplifier Mode Schema Reference" not in injected_after, (
            "The schema reference must NOT be injected once /mode-design is inactive. "
            f"Context after deactivation (first 500 chars): {injected_after[:500]!r}"
        )

    # ---- 3. Skill gone: mode_overlay_skills capability must be empty ----
    _skills_after_calls: list[Any] = [
        call.args[1]
        for call in coord.register_capability.call_args_list
        if call.args and call.args[0] == "mode_overlay_skills"
    ]
    skills_after: list[str] = _skills_after_calls[-1] if _skills_after_calls else []
    if skills_after:
        assert not any("mode-design-discipline" in str(s) for s in skills_after), (
            "mode-design-discipline must be removed from the mode_overlay_skills capability "
            "after /mode-design deactivation. "
            f"Skills still registered: {skills_after!r}"
        )


# ---------------------------------------------------------------------------
# M3 — contributes.context auto-injection via mode_overlay_context consumer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contributes_context_auto_injected(tmp_path: Path) -> None:
    """handle_provider_request must inject contributes.context files even when
    the mode body does NOT @-mention them.

    Scenario:
    - A mode is active with body text that does NOT reference the contributed
      context file.
    - The coordinator's ``mode_overlay_context`` capability holds the path to
      that file (set by RuntimeOverlay.apply during activation).
    - ``handle_provider_request`` is called.

    Expected behaviour:
    - The contributed context file's content appears in the injected
      ``<system-reminder>`` block, prepended before the mode body.
    - This proves that ``handle_provider_request`` consumes
      ``mode_overlay_context`` directly rather than relying solely on inline
      ``@``-mentions in the mode body.
    """
    from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks

    # ------------------------------------------------------------------ #
    # Build a contributed context file with a unique content marker       #
    # ------------------------------------------------------------------ #
    ctx_file = tmp_path / "contributed.md"
    ctx_file.write_text(
        "CONTRIBUTED-CONTEXT-MARKER\n\nThis content comes from contributes.context.",
        encoding="utf-8",
    )

    # ------------------------------------------------------------------ #
    # Build a mode whose body does NOT mention the contributed file at all #
    # ------------------------------------------------------------------ #
    modes_dir = tmp_path / "modes"
    modes_dir.mkdir()
    (modes_dir / "ctx-test-mode.md").write_text(
        textwrap.dedent("""\
            ---
            mode:
              name: ctx-test-mode
              description: Test mode for contributes.context auto-injection
              tools:
                safe: [read_file]
              default_action: block
              contributes:
                context:
                  - "@test:context/contributed.md"
            ---

            # Ctx Test Mode

            This body does NOT @-mention the contributed context file.
            The file should be injected via contributes.context auto-injection.
        """),
        encoding="utf-8",
    )

    # ------------------------------------------------------------------ #
    # Build coordinator with capabilities set as RuntimeOverlay would after
    # activation: mode_overlay_context holds the path list, and a mention
    # resolver knows how to read the file.
    # ------------------------------------------------------------------ #
    coord = _make_coordinator(active_mode="ctx-test-mode", agents={})

    # Mention resolver: maps any @-mention to ctx_file for this test
    resolver = MagicMock()
    resolver.resolve = MagicMock(return_value=str(ctx_file))

    contributed_paths = ["@test:context/contributed.md"]

    def _cap_side_effect(cap_name: str) -> Any:
        if cap_name == "mode_overlay_context":
            return contributed_paths
        if cap_name == "mention_resolver":
            return resolver
        return None

    coord.get_capability = MagicMock(side_effect=_cap_side_effect)

    discovery = ModeDiscovery(search_paths=[modes_dir])
    hooks = ModeHooks(coord, discovery)

    # ------------------------------------------------------------------ #
    # Call handle_provider_request and inspect the injected context        #
    # ------------------------------------------------------------------ #
    result = await hooks.handle_provider_request("provider:request", {})

    assert result.action == "inject_context", (
        f"Expected action='inject_context' but got {result.action!r}. "
        "The mode has a non-empty body so injection must always occur."
    )

    injected: str = result.context_injection or ""
    assert "CONTRIBUTED-CONTEXT-MARKER" in injected, (
        "The contributed context file's content must appear in the injected "
        "<system-reminder> even when the mode body does not @-mention it. "
        "handle_provider_request must consume mode_overlay_context and prepend "
        "the resolved file contents before the mode body. "
        f"Injected context (first 500 chars): {injected[:500]!r}"
    )
