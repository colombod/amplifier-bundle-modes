"""Regression test: hooks-mode consumes the renamed runtime_context_overlay capability.

Verifies that:
  1. handle_provider_request reads from 'runtime_context_overlay' (not 'mode_overlay_context')
     when injecting mode-contributed context files.
  2. The capability name constant RUNTIME_CONTEXT_OVERLAY_CAPABILITY is importable
     from amplifier_foundation and hooks-mode uses it consistently.

This test is RED when hooks-mode reads from the old 'mode_overlay_context' string
and GREEN after the rename is applied.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coordinator(active_mode: str | None = None) -> MagicMock:
    """Minimal coordinator mock for context-injection tests."""
    coordinator = MagicMock()
    coordinator.session_state = {
        "active_mode": active_mode,
        "require_approval_tools": set(),
    }
    coordinator.config = {"agents": {}}
    coordinator.hooks = MagicMock()
    coordinator.hooks.emit = AsyncMock()
    coordinator.hooks.register = MagicMock()
    coordinator.hooks.unregister = MagicMock()
    return coordinator


class TestHooksModeConsumesNewCapabilityName:
    """Verify hooks-mode reads contributed context from 'runtime_context_overlay'."""

    @pytest.mark.asyncio
    async def test_contributed_context_injected_via_new_cap_name(
        self, tmp_path: Path
    ) -> None:
        """handle_provider_request must inject content from runtime_context_overlay, not mode_overlay_context.

        This test simulates post-activation state by directly populating
        get_capability("runtime_context_overlay") with a path list. If hooks-mode
        reads from the old "mode_overlay_context" name, the context will NOT be
        injected and this test will fail.
        """
        from amplifier_foundation import RUNTIME_CONTEXT_OVERLAY_CAPABILITY
        from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks

        # Write a context file with a distinctive marker
        ctx_file = tmp_path / "contributed.md"
        ctx_file.write_text(
            "NEW-RUNTIME-CONTEXT-MARKER-123\n", encoding="utf-8"
        )

        # Write a minimal mode file so ModeDiscovery.find() returns a mode
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        (modes_dir / "ctx-test.md").write_text(
            textwrap.dedent("""\
                ---
                mode:
                  name: ctx-test
                  description: Context injection test
                  default_action: allow
                ---

                # Ctx Test Mode

                This body does not mention the contributed context.
            """),
            encoding="utf-8",
        )

        coord = _make_coordinator(active_mode="ctx-test")

        # Mention resolver: maps any mention to ctx_file
        resolver = MagicMock()
        resolver.resolve = MagicMock(return_value=str(ctx_file))

        contributed_paths = ["@test:context/contributed.md"]

        # ---- KEY ASSERTION ----
        # We ONLY mock get_capability("runtime_context_overlay"), NOT the old
        # "mode_overlay_context". If hooks-mode reads from the old name, the
        # context will be empty and the contributed marker won't appear.
        def _cap_side_effect(cap_name: str) -> Any:
            if cap_name == RUNTIME_CONTEXT_OVERLAY_CAPABILITY:
                return contributed_paths
            if cap_name == "mention_resolver":
                return resolver
            return None

        coord.get_capability = MagicMock(side_effect=_cap_side_effect)

        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coord, discovery)

        result = await hooks.handle_provider_request("provider:request", {})

        assert result.action == "inject_context", (
            f"Expected action='inject_context' but got {result.action!r}. "
            "The mode has a non-empty body, so context injection must occur."
        )

        injected: str = result.context_injection or ""
        assert "NEW-RUNTIME-CONTEXT-MARKER-123" in injected, (
            "The contributed context file's content must appear in the injected "
            "<system-reminder> when it is registered under 'runtime_context_overlay'. "
            f"Got: {injected[:300]!r}\n\n"
            "This test fails when hooks-mode reads from the OLD 'mode_overlay_context' "
            f"name instead of RUNTIME_CONTEXT_OVERLAY_CAPABILITY={RUNTIME_CONTEXT_OVERLAY_CAPABILITY!r}."
        )

    @pytest.mark.asyncio
    async def test_old_cap_name_not_consulted(self, tmp_path: Path) -> None:
        """When only 'mode_overlay_context' is populated, context must NOT be injected.

        This is the inverse test: if content is only in the old name but not
        the new name, hooks-mode must NOT inject it (i.e., it should not fall
        back to the old name after the rename).
        """
        from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks

        # Write a mode file
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        (modes_dir / "ctx-legacy.md").write_text(
            textwrap.dedent("""\
                ---
                mode:
                  name: ctx-legacy
                  description: Legacy context name test
                  default_action: allow
                ---

                # Ctx Legacy Mode

                Minimal body — only this text is injected.
            """),
            encoding="utf-8",
        )

        coord = _make_coordinator(active_mode="ctx-legacy")

        # Populate the OLD name only — new name returns None
        def _cap_side_effect(cap_name: str) -> Any:
            if cap_name == "mode_overlay_context":
                # Intentionally returning a path under the OLD name
                # hooks-mode must NOT read this after the rename
                return ["@test:context/should-not-be-injected.md"]
            return None

        coord.get_capability = MagicMock(side_effect=_cap_side_effect)

        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coord, discovery)

        result = await hooks.handle_provider_request("provider:request", {})

        # Either action is fine — this test just checks that the OLD cap name
        # content doesn't erroneously appear in the injected context.
        # (If the content was injected, hooks-mode is still reading the old name.)
        if result.action == "inject_context":
            injected: str = result.context_injection or ""
            assert "should-not-be-injected" not in injected, (
                "Content from 'mode_overlay_context' (old name) appeared in the "
                "injected context. After the rename, hooks-mode must read from "
                "'runtime_context_overlay' ONLY and must NOT fall back to the "
                "old 'mode_overlay_context' name. This means hooks-mode code is "
                "still using the old capability name string."
            )
