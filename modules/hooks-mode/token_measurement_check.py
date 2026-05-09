#!/usr/bin/env python
"""
Token-cost-when-inactive measurement script.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks

# BUNDLE_ROOT: three levels up from the hooks-mode directory
# hooks-mode/ -> modules/ -> amplifier-bundle-modes/
BUNDLE_ROOT = Path(__file__).resolve().parent.parent.parent


def _make_coordinator(active_mode=None, agents=None):
    """Build a MagicMock coordinator with active_mode and agents."""
    coordinator = MagicMock()
    coordinator.session_state = {
        "active_mode": active_mode,
        "require_approval_tools": set(),
    }
    coordinator.config = {"agents": dict(agents or {})}
    coordinator.hooks = MagicMock()
    coordinator.hooks.emit = AsyncMock()
    coordinator.hooks.register = MagicMock()
    coordinator.hooks.unregister = MagicMock()
    coordinator.hooks.mount = MagicMock()
    coordinator.hooks.unmount = MagicMock()
    coordinator.get_capability = MagicMock(return_value=None)
    return coordinator


async def main():
    # Build mock coordinator with active_mode=None and empty agents config
    coord = _make_coordinator(active_mode=None, agents={})

    # Instantiate ModeDiscovery with [BUNDLE_ROOT/'modes'] search path
    discovery = ModeDiscovery(search_paths=[BUNDLE_ROOT / "modes"])

    # Instantiate ModeHooks
    hooks = ModeHooks(coord, discovery)

    # Call handle_provider_request
    result = await hooks.handle_provider_request("provider:request", {})

    # Get the injected context (if any)
    injected = result.context_injection if hasattr(result, "context_injection") else ""
    if injected is None:
        injected = ""

    # Assert 'Amplifier Mode Schema Reference' NOT in injected
    assert "Amplifier Mode Schema Reference" not in injected, (
        f"FAIL: 'Amplifier Mode Schema Reference' leaked into inactive session! "
        f"Injected context: {injected[:200]!r}"
    )

    # Assert 'mode-author' NOT in str(coord.config['agents'])
    agents_str = str(coord.config["agents"])
    assert "mode-author" not in agents_str, (
        f"FAIL: 'mode-author' leaked into inactive session agents! "
        f"Agents: {agents_str!r}"
    )

    print("OK: zero contributions visible in inactive session")


if __name__ == "__main__":
    asyncio.run(main())
