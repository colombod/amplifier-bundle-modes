---
mode:
  name: test-overlap-mode
  description: "Test fixture — declares mode-author for S3/S4 testing. NOT for end users."
  shortcut: false
  advertised: false
  default_action: block
  allow_clear: true

  tools:
    safe:
      - read_file
      - todo
      - mode
      - delegate

  contributes:
    agents:
      mode-author:
        source: "@modes:agents/mode-author"
---

# Test Overlap Mode

This mode exists **only as a test fixture**. It is not intended for end users and must never be shipped as part of the modes bundle.

## Purpose

This fixture declares the same `mode-author` agent as `/mode-design` (via `source: "@modes:agents/mode-author"`), enabling the runtime-overlay refcount logic to be tested across two critical overlap scenarios:

- **S3** — Item in two modes: both `mode-design` and `test-overlap-mode` contribute `mode-author`. The runtime must increment the refcount when the second mode is activated and decrement it on deactivation, without ejecting the agent prematurely.
- **S4** — Item in session + two modes: `mode-author` is contributed by the session context as well as both modes. The runtime must correctly handle the three-way refcount so the agent remains available until all sources are cleared.

## Do not ship this mode

This file lives under `modules/hooks-mode/tests/fixtures/` and is loaded only by the integration test module. It must not be added to any production mode discovery path.

## Exit

This mode does not have a natural user-facing workflow. Use `/mode off` to clear it during testing.
