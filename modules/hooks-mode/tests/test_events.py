"""Tests for event constants in the hooks-mode events module."""

from __future__ import annotations


def test_mode_transition_completed_constant_exists() -> None:
    """MODE_TRANSITION_COMPLETED must exist and equal 'mode:transition_completed'."""
    from amplifier_module_hooks_mode.events import MODE_TRANSITION_COMPLETED

    assert MODE_TRANSITION_COMPLETED == "mode:transition_completed"


def test_mode_activation_failed_constant_exists() -> None:
    """MODE_ACTIVATION_FAILED must exist and equal 'mode:activation_failed'."""
    from amplifier_module_hooks_mode.events import MODE_ACTIVATION_FAILED

    assert MODE_ACTIVATION_FAILED == "mode:activation_failed"


def test_all_events_includes_new_constants() -> None:
    """ALL_EVENTS must include both MODE_TRANSITION_COMPLETED and MODE_ACTIVATION_FAILED."""
    from amplifier_module_hooks_mode.events import (
        ALL_EVENTS,
        MODE_ACTIVATION_FAILED,
        MODE_TRANSITION_COMPLETED,
    )

    assert MODE_TRANSITION_COMPLETED in ALL_EVENTS
    assert MODE_ACTIVATION_FAILED in ALL_EVENTS
