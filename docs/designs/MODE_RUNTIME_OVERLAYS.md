# Mode Runtime Overlays

> **Summary.** Modes today can declare tool *policies* and inject context bodies, but cannot bring in additional capabilities. This design extends the `amplifier-bundle-modes` bundle so a mode YAML can declare a `contributes` block (agents, skills, context, tools, config overrides) that is **lazy-mounted on activation and unmounted on deactivation**. Combined with a new `advertised: false` flag, bundle authors can package speculative or context-heavy capabilities behind a slash-command-only gate — invisible to the LLM until a human flips the mode on, with refcount semantics that compose cleanly with session-level capabilities and other modes. The mechanism reuses the merge stack and module-activation pattern established by the recent agent-tool-spawn fix; no new kernel primitives required for v1.

---

## Orientation

The technical precedent for this design is the agent-tool-spawn fix landed in commits `96f45b0`, `9f129c2`, and `39b970c`. That work taught the ecosystem how to **separate module activation (download/install/import at bundle-prep time) from mounting (register with the live coordinator at runtime)**, and established a merge stack (`merge_module_lists`, `deep_merge`) for reconciling overlapping declarations. Modes are agents-applied-to-the-parent-session-at-runtime instead of agents-applied-to-a-spawned-child, so the same separation and the same merge stack apply. The design below leans on that precedent rather than inventing parallel infrastructure.

The audience is bundle authors and ecosystem contributors. Familiarity with bundles, modules, the kernel concepts (`coordinator.mount/unmount`, hook bus, `session_state`), and the existing modes mechanism is assumed.

---

## 1. Problem Framing

Modes today reach their limit at policy enforcement and inline `@`-mention context injection. Every other association between a mode and a capability — "use agent X while in this mode," "this mode benefits from skill Y," "this mode wants a different model" — is **prose convention** in the mode body, with no platform enforcement and no token-cost containment. The capability is loaded at session startup whether the mode ever activates or not, and is advertised to the LLM whether the mode is on or off.

Bundle authors need to package speculative or context-heavy capabilities behind a mode such that those capabilities are completely invisible — zero token cost, zero attention cost — to the LLM unless a human explicitly activates the mode via slash command.

### Goals

- Modes can declare additive capability contributions (agents, skills, context, tools, config overrides).
- Contributions are lazy-mounted on activation, unmounted on deactivation.
- Modes can be hidden from LLM-facing mode listings (`advertised: false`) while remaining slash-command-activatable by humans.
- Activation reconciles cleanly with session-level capabilities (refcount semantics).
- Failed activation rolls back atomically.
- Reuse the merge stack from the agent-tool-spawn fix rather than inventing parallel infrastructure.

### Non-goals (deferred)

- Hooks contribution (kernel `hook_suspend/resume_by_tag` primitive missing).
- Replace semantics (mode swapping out an existing item's config).
- Truly-lazy module activation deferred to first mode use (`lazy: true` flag).
- Persisting `active_mode` across session resume.
- Sub-mode stacking (multiple concurrent modes).
- Bundle hot-reload while a mode is active.

---

## 2. Explicit Assumptions

- The pre-loading cost of all declared mode contributions at session startup is acceptable. (User-confirmed: "we're 100% ok with the cost of pre-loading all even if we don't use.")
- The modes bundle may declare `amplifier-foundation` as a direct dependency in addition to `amplifier-core`. (User-confirmed dependency relaxation.)
- Only one mode is active at a time (existing constraint, unchanged).
- Modes are owned by bundle authors, not end users — the security boundary is identical to bundle composition.

---

## 3. System Boundaries and Components

The change touches three repos:

- **`amplifier-foundation`** (library): schema parsing, prepare-time pre-activation, the runtime overlay primitive.
- **`amplifier-bundle-modes`**: schema documentation, transition handlers in `hooks-mode`, discovery filter, the `/mode-design` worked example.
- **`amplifier-app-cli`**: optionally surfaces an `--all` flag on `/modes` for unadvertised mode listing (humans only).

Other modules require **no changes**:

- The **delegate tool** continues to read its agent registry from coordinator state.
- The **skills tool** continues to read its skill registry the same way.
- **Context injection** continues to flow through the existing `provider:request` hook path.

This is the load-bearing property of the design: consumers don't need to know about modes. Modes mutate the same coordinator structures that the consumers already read from.

---

## 4. Validated Requirements

| #  | Requirement |
|----|---|
| R1 | Mode YAML accepts a top-level `contributes` block with `agents`, `context`, `skills`, `tools`, `config` sub-keys, mirroring the bundle frontmatter shape. |
| R2 | Items in `contributes` are lazy-mounted on activation, unmounted on deactivation — zero load cost when the mode never activates (subject to the pre-activation startup cost noted in §2). |
| R3 | `advertised: false` hides the mode from LLM-facing listings; slash command still works for humans. |
| R4 | Activation reconciles overlap with session-level items without breaking them. |
| R5 | Refcount across overlapping mode contributions handles all four overlap scenarios (S1–S4 in §7). |
| R6 | Atomic transition with rollback on partial failure. |
| R7 | The modes bundle may depend on `amplifier-foundation` directly. |
| R8 | Hooks contribution is deferred to a follow-up that adds a kernel hook suspend/resume primitive. |

---

## 5. Recommended Design

**Core insight.** Modes are agents-applied-to-the-parent-session-at-runtime. The agent-tool-spawn fix established the precedent: separate **module activation** (download/install/import at bundle-prep time) from **mounting** (register with the coordinator at runtime). Modes follow the same pattern.

### 5.1 YAML schema additions

```yaml
---
mode:
  name: mode-name
  description: "..."
  shortcut: mode-name
  advertised: false               # NEW — hides from LLM-facing mode listings
  default_action: block
  allowed_transitions: [...]
  allow_clear: true

  tools:                          # existing — policy semantics unchanged
    safe: [...]
    warn: [...]
    confirm: [...]
    block: [...]

  contributes:                    # NEW — lazy-mounted on activation
    agents:
      agent-name:
        source: "@bundle:agents/agent-name"
    context:
      - "@bundle:context/file.md"
    skills:
      - "@bundle:skills/skill-name"
    tools:                        # v1.1 — see §10
      - module: tool-name
        source: git+https://...
        config: { ... }
    config:                       # v1.1 — overlay stack
      orchestrator.config.model: claude-opus-4-20250514
---

[mode body — system-reminder content while active]
```

The `contributes` block deliberately mirrors the shape of bundle frontmatter `tools`/`agents`/`context`/`skills` blocks. This lets the merge stack already used for agent spawning (`merge_module_lists`, `deep_merge`) handle overlap reconciliation without modification.

### 5.2 Three foundation code changes

1. **Schema extension (~30 lines).** In `amplifier_foundation/bundle/_dataclass.py`, extend `_load_mode_file_metadata()` — analogous to the `_load_agent_file_metadata()` change in commit `96f45b0` — to extract top-level `contributes` and `advertised` keys from mode frontmatter.

2. **Prepare-time pre-activation (~40 lines).** In `Bundle.prepare()`, after the existing agents walk added in commit `39b970c` (lines 404–430), add a modes walk that traverses each discovered mode's `contributes` and feeds module sources to `ModuleActivator`. Modules are downloaded, installed, and registered with `BundleModuleResolver._paths` — but **not mounted**. The LLM still sees nothing.

3. **`RuntimeOverlay` primitive (~150–250 lines).** A new type in foundation, layered on top of `SessionConfigurator` (`amplifier_foundation/configurator/`). Provides:

    - `apply(scope_name, contributions) -> TransitionResult` — atomic apply with rollback.
    - `revoke(scope_name) -> TransitionResult` — atomic revoke.
    - Per-item refcount across scopes. Session baseline contributes `+1`; each active scope contributes `+1` per declared item.
    - **Mount only at refcount 0→1; unmount only at 1→0.**
    - Config overrides via a separate overlay stack (last-pushed-wins for scalars).
    - Reuses `merge_module_lists` and `deep_merge` from the agent-spawn merge stack for overlap reconciliation.

    `RuntimeOverlay` is its own type with its own tests, not methods grafted onto `SessionConfigurator`. The configurator's existing live-coordinator mount/unmount paths are the substrate; the overlay adds refcount discipline and atomic apply/revoke on top.

### 5.3 Modes bundle changes

1. **Hooks-mode transition handlers (~150 lines).**
    - On `mode:activated`: build a delta against current effective state, call `RuntimeOverlay.apply("mode:<name>", contributions)`, inject the mode body context (existing mechanism), emit a single batched `mode:transition_completed` event with the delta payload.
    - On `mode:deactivated`: call `RuntimeOverlay.revoke("mode:<name>")`, remove the mode body injection, emit `mode:transition_completed`.
    - On any apply failure: rollback is automatic via the overlay primitive; emit `mode:activation_failed` with the failing item identified.

2. **Discovery filter (~10 lines).** `mode_discovery.list_modes(include_unadvertised: bool = False)`. The `tool-mode.list` operation calls with the default (LLM sees only advertised). The CLI's `/modes` command accepts a flag to call with `True` (humans see all).

3. **Parse-time lints — referential integrity at mode load.**
    - `contributes.agents` non-empty AND `delegate` not in `tools.safe` AND `default_action != allow` → WARN: contributed agents unreachable.
    - `contributes.skills` non-empty AND `load_skill` not in `tools.safe` AND `default_action != allow` → WARN.
    - `contributes.tools` non-empty AND those tool names not in `tools.safe` AND `default_action != allow` → WARN.

### 5.4 The principle to document

Two distinct concepts must be designed together but kept separate:

- **Tool policy** (`tools.safe/warn/confirm/block`) restricts what the LLM can do with already-mounted items.
- **Contributions** (`contributes.{...}`) expand what items are mounted while the mode is active.

A mode that contributes an agent **must** allow `delegate`. A mode that contributes a skill **must** allow `load_skill`. Same for contributed tools. The parse-time lints enforce this referential integrity.

---

## 6. Activation and Deactivation Flows

### Activation (`mode:activated`)

1. Validate `contributes` schema; resolve `@`-mention sources.
2. Compute delta vs current effective state (which items are new, which already exist).
3. For each new item: `coordinator.mount(category, name, instance, config)`. The instance comes from the pre-activated module via `BundleModuleResolver.async_resolve()`.
4. For each overlapping item: refcount `++`; deep-merge configs (mode's config wins per-key for the increment), but **the existing instance is not replaced** (see §8).
5. For each `contributes.config` entry: push onto the config overlay stack.
6. Inject the mode body as `<system-reminder source="mode-NAME">` (existing mechanism).
7. Persist `active_mode` to `session_state` (existing mechanism).
8. Emit `mode:transition_completed` with the delta payload (single batched event).
9. **On any failure during steps 3–5**: unmount everything mounted in this transition, pop everything pushed, mark mode inactive, emit `mode:activation_failed` with the failing item identified.

### Deactivation (`mode:deactivated`)

1. For each item this mode contributed: refcount `--`; if `0`, `coordinator.unmount(category, name)`.
2. Pop all config overlay entries for this scope.
3. Remove the mode body context injection.
4. Clear `active_mode` from `session_state`.
5. Emit `mode:transition_completed` with the unmount delta.

---

## 7. Overlap Scenarios — Validated Refcount Semantics

| Scenario | Setup | Activation behavior | Deactivation behavior |
|---|---|---|---|
| **S1** | Item X in session AND in mode M | Refcount 1→2; no mount call (already mounted) | Refcount 2→1; no unmount (still in session) |
| **S2** | Item X only in mode M | Refcount 0→1; mount fresh | Refcount 1→0; unmount |
| **S3** | Item X in mode M1 AND mode M2 (not session) | Activate M1: 0→1 mount. Switch to M2: M1 deactivates (1→0 unmount), then M2 activates (0→1 mount). Brief no-op churn. *(Future: cross-mode-transition optimization can compute net delta and skip churn.)* | Same as activation, reversed |
| **S4** | Item X in session AND M1 AND M2 | Always refcount ≥ 1 across all transitions; no mount/unmount churn | Always ≥ 1 |

---

## 8. Reconciliation Policy (v1)

- **Same module ID, any config.** Refcount only. The mode's config is merged via `deep_merge`; the mode's keys win for added keys, but **the existing instance is not replaced** (avoids in-flight tool-call hazards). Documented clearly: *mode adds, mode does not swap.*
- **Different module ID, same tool name (collision).** Activation **fails** with a structured error naming both modules. The mode stays inactive. Surface a clear conflict rather than silent shadowing.
- **`contributes.config` scalar overrides.** Layered via the overlay stack; popped on deactivation. Only one mode active at a time, so no stacking conflicts in v1.

---

## 9. The `/mode-design` Vertical Slice

Ship a concrete `/mode-design` mode as v1's worked example *and* the demonstrating slice. PR #13's existing `/mode-creation` (inline `@`-mention context plus tool policy only) is the v0 ancestor; `/mode-design` is the descendant that demonstrates the new mechanism.

### 9.1 The mode YAML

```yaml
---
mode:
  name: mode-design
  description: "Design a new Amplifier mode through structured authoring"
  shortcut: mode-design
  advertised: false
  default_action: block
  allow_clear: true

  tools:
    safe:
      - read_file
      - glob
      - grep
      - load_skill
      - todo
      - mode
      - delegate              # required — access path to contributed mode-author agent
    confirm:
      - write_file            # writing the new mode .md is the deliverable
      - edit_file
    block:
      - bash

  contributes:
    agents:
      mode-author:
        source: "@modes:agents/mode-author"
    context:
      - "@modes:context/mode-schema-reference.md"
    skills:
      - "@modes:skills/mode-design-discipline"
---

# Mode Design Mode

You are designing a new Amplifier mode. Workflow:

1. Intent — narrate the mode's purpose, who triggers it, what changes when active.
2. Tool policy & contributions — decide tool policy and what (if anything) to contribute.
3. Body draft — delegate to mode-author for a structured first pass, then refine.

The full mode schema is in your context. For deeper authoring discipline,
load_skill('mode-design-discipline'). The schema reference and the
mode-author agent are available only while this mode is active — keep that in
mind when documenting your new mode for others.
```

### 9.2 What each contribution exercises

| Contribution | Mechanism exercised |
|---|---|
| `mode-author` agent | Lazy-mount agent — appears in delegate tool's registry only while mode active |
| `mode-schema-reference.md` | Lazy-mount context — token-heavy file invisible until needed |
| `mode-design-discipline` skill | Lazy-mount skill — discoverable to `load_skill` only while active |
| `read_file`/`glob`/`grep`/`todo` (in `tools.safe` but not contributed) | Refcount overlap (S1) — already in session; activation/deactivation no-op |
| `advertised: false` | Discovery filtering — validates LLM-facing vs human-facing listing split |
| Failed activation rollback | Atomic transition — validated by deliberately breaking one source and confirming clean rollback |

---

## 10. v1 / v1.1 Staging

### v1 ships

- Schema extensions (`advertised`, `contributes` with `agents`, `context`, `skills`).
- Foundation prepare-time pre-activation.
- `RuntimeOverlay` primitive with refcount and atomic apply/revoke.
- Hooks-mode transition handlers.
- Discovery filter for `advertised: false`.
- Parse-time lints for referential integrity.
- The `/mode-design` mode (agents + context + skills contributions only).
- Integration tests covering S1 and S2 against `/mode-design` directly.
- A test-only fixture mode declaring the same `mode-author` to exercise S3 and S4.

### v1.1 adds

- `contributes.tools` (custom tool modules — exercises the full module-resolver path).
- `contributes.config` (scalar config overrides via overlay stack).
- A second agent in `/mode-design` (e.g., `mode-reviewer`).
- A `tool-mode-validate` custom tool as the first contributed tool — first real test of the tools path.
- An anti-pattern context file.
- CLI `--all` flag on `/modes` for human-facing listing of unadvertised modes.

### Deferred (future work)

- `contributes.hooks` (requires kernel `hook_suspend/resume_by_tag` primitive — see §12).
- `lazy: true` flag for truly-lazy module activation deferred to first mode use.
- Persistence of `active_mode` across session resume.
- Replace semantics (mode swapping out existing item config).
- Sub-mode stacking.
- Bundle hot-reload-while-mode-active.

---

## 11. Build Sequence

| Step | Build | Validates |
|------|---|---|
| 1 | Schema parser extension in foundation | Mechanical foundation work |
| 2 | `Bundle.prepare()` modes walk | Reuse of agent-fix precedent (commit `39b970c`) |
| 3 | `RuntimeOverlay` primitive with refcount | Refcount discipline (unit tests) |
| 4 | Hooks-mode transition handlers | Transition orchestration |
| 5 | Discovery filter | `advertised: false` |
| 6 | Parse-time lints | Referential integrity |
| 7 | Ship `/mode-design` with three contributions | End-to-end validation |
| 8 | Integration tests for S1–S4 (S3, S4 via test-fixture mode) | Overlap correctness |

---

## 12. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| **Refcount drift over time** — every increment must pair with a decrement across all code paths, including failures. | Single funnel through `RuntimeOverlay.apply/revoke`. Atomic delta application. Logged invariant check ("counter says N but no scope references this — leak"). `RuntimeOverlay` is its own type with its own tests. |
| **First-activation latency from module install.** | Pre-activation at bundle-prep time means mounting at activation is milliseconds, not seconds. Cost moves to startup, which the user accepted (§2). |
| **Failed activation leaves partial state.** | Atomic apply wrapper tracks `(category, name)` pairs mounted in this transition; rollback unmounts them all. Test with a deliberately-failing-import module before declaring v1 complete. |
| **`advertised: false` LLM behavioral surprise** when capabilities materialize without prior advertisement. | Mode body MUST narrate new capabilities ("you are now in research mode. New tools available: X. New agent: Y."). Document this as a mode-body authoring convention. Add to `mode-design-discipline` skill. |
| **Tool name collisions between session and mode (different module IDs).** | Activation fails with structured error. No silent shadowing. Add CLI lint command (`amplifier mode validate <name>`) for static detection. |
| **`configuration:changed` event flood from per-item activations.** | Suppress per-item events during mode transition; emit a single `mode:transition_completed` with delta payload. Observers can debounce on `transition_id`. |
| **Modes bundle dependency on foundation** is a precedent. | Document the principle in the modes bundle's README/REPOSITORY_RULES section: *runtime composition is foundation's domain, and modes is a runtime composition mechanism, therefore the dependency is structural, not incidental.* This justifies the relaxation and prevents erosion. |
| **`tool:pre` hook performance with per-tool-by-mode policy lookup.** | Add a counter; do not pre-optimize. Measure if it surfaces. |

---

## 13. Tradeoffs

This design optimizes for:

- **Reuse of tested precedent** (agent-spawn merge stack).
- **Zero LLM attention cost when mode inactive.**
- **Reversibility of design decisions** (small change surface; v1.1 adds opt-in features).
- **Operational simplicity** (single funnel, atomic apply, refcount invariant).

It sacrifices:

- **Memory and startup time** for declared but never-activated mode contributions (acceptable per user).
- **Replace semantics** for v1 (modes can add but not swap session items — re-evaluate when a real use case appears).
- **Hooks contribution** for v1 (deferred until a kernel suspend/resume primitive is justified by use case).

---

## 14. Alternatives Considered (and Rejected)

- **Pre-mount everything stashed at startup.** Requires every mode's modules to be in the bundle's mount plan up front, leaking mode contents into the bundle's surface. Doesn't satisfy "speculative features behind a mode for free" cleanly.
- **Generic contribution channels via `register_contributor`.** Rejected as the primary mechanism because the existing channel API has no `deregister` and registrations are mount-time-only. Could supplement (with conditional callbacks reading `session_state`) but doesn't cover tool/hook injection.
- **Modes-as-bundles (full bundle composition at activation).** Overkill. The configurator + provenance system already gives 90% of bundle composition semantics for runtime overlay.
- **Kernel `push_layer/pop_layer` primitive on `Coordinator`.** Reasonable but speculative. Two-consumers rule applies — build it when a second use case appears (e.g., recipes-with-scoped-capability, sub-session capability isolation). For modes alone, the foundation-level `RuntimeOverlay` over existing kernel primitives is sufficient.

---

## 15. Migration and Rollout

- All changes are additive. Existing modes (no `contributes` block, no `advertised` flag) continue to work unchanged.
- The foundation schema parser must default `contributes = {}` and `advertised = true` for backward compatibility.
- The agent-tool-spawn fix is already deployed; this work depends on it but does not modify it.
- Ship as a coordinated PR pair: foundation changes first (under feature flag if needed), then modes-bundle changes.

---

## 16. Success Metrics

- `/mode-design` activates and deactivates correctly with all four overlap scenarios passing.
- **Token measurement:** a session that never activates `/mode-design` shows zero context bytes from `mode-schema-reference.md`, zero entries in the agent registry from `mode-author`, and zero entries in skill discovery from `mode-design-discipline`.
- Activation latency under 100 ms on warm cache (modules pre-installed).
- Atomic rollback verified by injecting a deliberate import failure.
- Zero regressions in existing modes (`plan`, `careful`, `explore`).

---

## 17. The Catalytic Question

**What would have to be true for this to be the wrong choice?**

- If the agent-spawn precedent turns out to be brittle in ways not yet surfaced (different failure modes when applied to a live parent session vs. a spawned child), the reuse argument weakens.
- If multiple modes need to be active simultaneously (unanticipated use case), the single-active-mode constraint requires revisiting and refcount semantics need cross-mode review.
- If `RuntimeOverlay` accumulates enough functionality that it deserves promotion to amplifier-core (a third or fourth consumer appears), the foundation-level placement becomes a liability rather than a virtue.

Monitor for: refcount drift bug reports, activation latency complaints, requests for replace semantics, requests for hook contributions.

---

## Status

**Validated design — ready for implementation.** The validation was completed through a multi-turn `/systems-design` conversation covering problem framing, candidate evaluation, overlap-scenario analysis, dependency relaxation, an antagonistic ("crusty") review pass, and a corrected vertical-slice scope. The actionable punch list is the build sequence in §11:

1. Schema parser extension in foundation.
2. `Bundle.prepare()` modes walk.
3. `RuntimeOverlay` primitive with refcount.
4. Hooks-mode transition handlers.
5. Discovery filter.
6. Parse-time lints.
7. Ship `/mode-design` with three contributions.
8. Integration tests for S1–S4.
