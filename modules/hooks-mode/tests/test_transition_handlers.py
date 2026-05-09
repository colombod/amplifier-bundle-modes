"""Tests for ModeHooks transition handlers (handle_mode_activated).

Three tests — all expected RED before the implementation is added:
    AttributeError: 'ModeHooks' object has no attribute 'handle_mode_activated'
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks


def _make_coordinator(active_mode=None):
    """Build a MagicMock coordinator suitable for ModeHooks tests."""
    coordinator = MagicMock()
    coordinator.session_state = {
        "active_mode": active_mode,
        "require_approval_tools": set(),
    }
    coordinator.hooks = MagicMock()
    coordinator.hooks.emit = AsyncMock()
    coordinator.get_capability = MagicMock(return_value=None)
    return coordinator


def _write_mode(path: Path, name: str, *, contributes=None) -> Path:
    """Write a mode .md file with optional contributes block.

    The mode policy includes safe_tools=[read_file, delegate, load_skill] and
    default_action=block so that parse-time lint checks don't fire warnings
    when agents are contributed.
    """
    lines = [
        "---",
        "mode:",
        f"  name: {name}",
        f"  description: {name} mode",
        "  tools:",
        "    safe: [read_file, delegate, load_skill]",
        "  default_action: block",
    ]

    if contributes is not None:
        # Render contributes as indented YAML block nested under `mode:`
        contributes_yaml = yaml.safe_dump(
            {"contributes": contributes}, default_flow_style=False
        )
        for contrib_line in contributes_yaml.splitlines():
            lines.append(f"  {contrib_line}")

    lines.extend(
        [
            "---",
            f"# {name.title()} Mode",
            "",
            f"You are in {name} mode.",
        ]
    )

    mode_file = path / f"{name}.md"
    mode_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return mode_file


@pytest.mark.asyncio
async def test_activated_handler_calls_overlay_apply(tmp_path: Path) -> None:
    """handle_mode_activated calls overlay.apply with scope and contributes dict."""
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
    pos_args = call_args.args
    kw_args = call_args.kwargs

    # First arg: scope_name (positional or kwarg)
    scope_arg = (
        pos_args[0] if pos_args else kw_args.get("scope_name") or kw_args.get("scope")
    )
    # Second arg: contributions (positional or kwarg)
    contributions_arg = (
        pos_args[1] if len(pos_args) > 1 else kw_args.get("contributions")
    )

    assert scope_arg == "mode:design"
    assert contributions_arg == contributes

    coordinator.hooks.emit.assert_any_await(
        MODE_TRANSITION_COMPLETED,
        {"mode": "design", "phase": "activated"},
    )
    assert result.action == "continue"


@pytest.mark.asyncio
async def test_activated_handler_emits_failure_event_on_apply_failure(
    tmp_path: Path,
) -> None:
    """handle_mode_activated emits MODE_ACTIVATION_FAILED when overlay.apply raises."""
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
    """handle_mode_activated skips overlay.apply when mode has no contributes."""
    from amplifier_module_hooks_mode.events import MODE_TRANSITION_COMPLETED

    _write_mode(tmp_path, "plain")  # no contributes kwarg → no contributes block

    coordinator = _make_coordinator(active_mode="plain")
    discovery = ModeDiscovery(search_paths=[tmp_path])
    hooks = ModeHooks(coordinator, discovery)

    fake_overlay = MagicMock()
    fake_overlay.apply = MagicMock(return_value=MagicMock(success=True))
    coordinator.session_state["mode_runtime_overlay"] = fake_overlay

    result = await hooks.handle_mode_activated("mode:activated", {"name": "plain"})

    fake_overlay.apply.assert_not_called()
    coordinator.hooks.emit.assert_any_await(
        MODE_TRANSITION_COMPLETED,
        {"mode": "plain", "phase": "activated"},
    )
    assert result.action == "continue"


@pytest.mark.asyncio
async def test_changed_handler_revokes_old_then_applies_new(tmp_path: Path) -> None:
    """handle_mode_changed revokes the old scope then applies the new scope (order matters)."""
    from amplifier_module_hooks_mode.events import MODE_TRANSITION_COMPLETED

    _write_mode(tmp_path, "old-mode", contributes={"context": ["@a:b.md"]})
    _write_mode(
        tmp_path,
        "new-mode",
        contributes={"agents": {"x": {"source": "@y:z"}}},
    )

    coordinator = _make_coordinator()
    discovery = ModeDiscovery(search_paths=[tmp_path])
    hooks = ModeHooks(coordinator, discovery)

    call_log: list[tuple[str, str]] = []

    fake_overlay = MagicMock()
    fake_overlay.revoke = MagicMock(
        side_effect=lambda scope: (
            call_log.append(("revoke", scope)) or MagicMock(success=True)
        )
    )
    fake_overlay.apply = MagicMock(
        side_effect=lambda scope, contrib: (
            call_log.append(("apply", scope)) or MagicMock(success=True)
        )
    )
    coordinator.session_state["mode_runtime_overlay"] = fake_overlay

    result = await hooks.handle_mode_changed(
        "mode:changed", {"old": "old-mode", "new": "new-mode"}
    )

    assert call_log == [("revoke", "mode:old-mode"), ("apply", "mode:new-mode")]
    coordinator.hooks.emit.assert_any_await(
        MODE_TRANSITION_COMPLETED,
        {"mode": "new-mode", "phase": "changed"},
    )
    assert result.action == "continue"


@pytest.mark.asyncio
async def test_changed_handler_emits_failure_on_apply_error(tmp_path: Path) -> None:
    """handle_mode_changed emits MODE_ACTIVATION_FAILED when overlay.apply raises."""
    from amplifier_module_hooks_mode.events import MODE_ACTIVATION_FAILED

    _write_mode(tmp_path, "old-mode", contributes={"context": ["@a:b.md"]})
    _write_mode(
        tmp_path,
        "new-mode",
        contributes={"agents": {"x": {"source": "@y:z"}}},
    )

    coordinator = _make_coordinator()
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
