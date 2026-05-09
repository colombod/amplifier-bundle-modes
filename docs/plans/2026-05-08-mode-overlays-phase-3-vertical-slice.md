# Mode Runtime Overlays — Phase 3 Implementation Plan (Vertical Slice)

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Ship the `/mode-design` mode (advertised:false; contributes an agent, a context file, and a skill) plus integration tests that exercise the four overlap scenarios end-to-end against the real `RuntimeOverlay` machinery.

**Architecture:** This phase is the user-visible payload that exercises Phase 1 (foundation infrastructure) and Phase 2 (modes-bundle integration). It ships four authored markdown files (mode + agent + skill + context-reference), a test-only fixture mode, and an integration test module that drives the live overlay through S1–S4, advertised-filtering, atomic rollback, and a full end-to-end activation of `/mode-design`. The phase is implementation-only on the bundle and tests-only on the modules; no production Python is added in Phase 3.

**Tech Stack:** Python 3.11+, `pytest` + `pytest-asyncio` (already used by `modules/hooks-mode/tests/`), YAML frontmatter parsing already available in `parse_mode_file()`, the markdown-with-YAML-frontmatter convention already used by every other file in this bundle.

---

## Prerequisites — DO NOT START Phase 3 UNTIL THESE PASS

This phase depends on Phases 1 and 2 being complete. Run these three checks **before Task 1**. If any fails, stop and finish the prior phase.

### Pre-check 1: Phase 1 — schema parser sees the new fields

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes/modules/hooks-mode
python -c "
from pathlib import Path
import tempfile, textwrap
from amplifier_module_hooks_mode import parse_mode_file
with tempfile.TemporaryDirectory() as td:
    f = Path(td) / 'sample.md'
    f.write_text(textwrap.dedent('''
        ---
        mode:
          name: sample
          advertised: false
          contributes:
            agents:
              foo:
                source: \"@modes:agents/foo\"
          tools:
            safe: [read_file]
          default_action: block
        ---
        body
    '''))
    md = parse_mode_file(f)
    assert md is not None
    assert md.advertised is False, f'advertised parsing missing: {md!r}'
    assert md.contributes is not None and 'agents' in md.contributes, f'contributes parsing missing: {md!r}'
    print('OK: parse_mode_file reads advertised and contributes')
"
```
**Expected:** `OK: parse_mode_file reads advertised and contributes`

If this fails, Phase 1 (schema-parser extension) is not done. Stop.

### Pre-check 2: Phase 1 — `RuntimeOverlay` is importable from foundation

Run:
```bash
python -c "from amplifier_foundation.configurator import RuntimeOverlay; print('OK:', RuntimeOverlay)"
```
**Expected:** `OK: <class 'amplifier_foundation.configurator.RuntimeOverlay'>` (or similar). Path may be `amplifier_foundation.configurator.runtime_overlay` — adjust if needed.

If `ImportError`, Phase 1 (`RuntimeOverlay` primitive) is not done. Stop.

### Pre-check 3: Phase 2 — hooks-mode wires `RuntimeOverlay` into transitions

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes/modules/hooks-mode
grep -nR "RuntimeOverlay\|apply\b\|revoke\b" amplifier_module_hooks_mode/ | head -20
```
**Expected:** at least one line referencing `RuntimeOverlay` and calls to `apply(...)` / `revoke(...)` inside the activation/deactivation flow.

If empty, Phase 2 (transition handlers) is not done. Stop.

If all three checks pass, proceed to Task 1.

---

## Working directories

- **Bundle root:** `/home/bkrabach/dev/modes-updates/amplifier-bundle-modes`
- **Tests cwd:** `/home/bkrabach/dev/modes-updates/amplifier-bundle-modes/modules/hooks-mode`

All paths below are bundle-relative unless noted otherwise.

---

## Task list (14 tasks + 1 final verification)

| # | Task | Type |
|---|---|---|
| 1 | Create `context/mode-schema-reference.md` (token-heavy reference) | Content |
| 2 | Create `skills/mode-design-discipline/SKILL.md` | Content |
| 3 | Create `agents/mode-author.md` | Content |
| 4 | Create `modes/mode-design.md` | Content |
| 5 | Create `modes/README.md` | Content |
| 6 | Create test fixture `tests/fixtures/test-overlap-mode.md` | Content |
| 7 | Create integration-test scaffolding (helpers, fixtures, conftest hooks) | Test infra |
| 8 | TDD: `test_S1_session_overlap` | Test |
| 9 | TDD: `test_S2_mode_only` | Test |
| 10 | TDD: `test_S3_two_modes_same_item` | Test |
| 11 | TDD: `test_S4_session_plus_two_modes` | Test |
| 12 | TDD: `test_advertised_false_filtering` | Test |
| 13 | TDD: `test_contribution_failure_rollback` | Test |
| 14 | TDD: `test_mode_design_end_to_end` | Test |
| 15 | Feature-complete verification (token measurement, full suite) | Verification |

---

## Task 1: Create `context/mode-schema-reference.md`

**Files:**
- Create: `context/mode-schema-reference.md`

This is the token-heavy reference file that `/mode-design` contributes. It is intentionally substantial (target: 5–10K tokens, ~25–40KB of markdown). When the mode is **inactive**, this file is never loaded into the LLM context — that's the whole token-savings story we're demonstrating.

**Step 1: Create the file with the exact content below**

```markdown
# Amplifier Mode Schema Reference

This is the canonical reference for Amplifier mode YAML frontmatter. It is loaded
into the LLM context only while `/mode-design` is active. When designing a new
mode, consult this document before writing the frontmatter.

> **Audience:** Bundle authors writing a new mode `.md` file.
> **Source of truth:** This file. The bundle's README is a quickstart, not a
> reference.

---

## 1. File location and naming

A mode is a single Markdown file:

- **Bundle-shipped modes:** live in `<bundle-root>/modes/<name>.md`. Filename
  stem does not have to equal the mode's `name:` field, but conventionally it
  does — the discovery layer caches by filename stem first.
- **Project modes:** `.amplifier/modes/<name>.md` in the project working
  directory.
- **User modes:** `~/.amplifier/modes/<name>.md`.

Precedence on collision: project > user > bundle (first-wins).

A mode file has two parts: a YAML frontmatter block bracketed by `---` lines,
and a Markdown body. The body is injected as `<system-reminder>` content
whenever the mode is active.

---

## 2. Top-level frontmatter fields

Every mode lives under a `mode:` key:

\`\`\`yaml
---
mode:
  name: <string>
  description: <string>
  shortcut: <string | false>
  advertised: <bool>
  default_action: <"block" | "allow">
  allowed_transitions: [<string>, ...]
  allow_clear: <bool>
  tools:
    safe: [...]
    warn: [...]
    confirm: [...]
    block: [...]
  contributes:
    agents: { ... }
    context: [...]
    skills: [...]
    tools: [...]      # v1.1 — see §6
    config: { ... }   # v1.1 — see §6
---
\`\`\`

### 2.1 `name` (string, required)

The canonical mode identifier. Used by:

- The `/mode <name>` slash command.
- `mode(set, "<name>")` tool calls.
- The system-reminder banner injected on activation.

**Conventions:** lowercase, hyphenated. Examples: `plan`, `careful`,
`mode-design`, `research-deep`. Avoid spaces, underscores, or capital letters —
shortcut validation rejects them.

If absent, defaults to the filename stem.

### 2.2 `description` (string, recommended)

One-line human-readable summary. Shown in `/modes` listings. Keep under ~80
characters. Imperative or noun-phrase voice both fine.

Good: `"Design a new Amplifier mode through structured authoring"`.
Bad: `"This mode is for designing modes and you should use it when you want to design a mode."`

### 2.3 `shortcut` (string | false, optional)

The slash-command alias. If absent, defaults to `name`. Set to YAML `false` to
disable the alias entirely (mode is still reachable via `/mode <name>`).

\`\`\`yaml
shortcut: plan       # /plan activates the mode
shortcut: false      # only /mode plan activates it
# (omitted)          # /<name> activates it
\`\`\`

Shortcuts are normalized to lowercase and validated against
`^[a-z][a-z0-9_-]*$`. Invalid values log a warning and are dropped.

### 2.4 `advertised` (bool, default `true`)

**New in v1.** Controls whether the mode appears in LLM-facing listings
(`mode(list)` tool operation) and `/modes` listings without an explicit flag.

- `advertised: true` (default) — mode appears in both LLM and human listings.
- `advertised: false` — mode is **invisible** to the LLM. It is still
  activatable by humans via slash command (`/<name>` or `/mode <name>`), and
  appears in `/modes --all`. The mode's contributions remain pre-activated at
  bundle prep, so activation is fast.

Use `advertised: false` for **rare specialist workflows** (mode-design,
deep-research, security-review) where the cost of cluttering the LLM's
attention budget outweighs the marginal value of advertising. Do **not** use it
to hide work-in-progress modes — those should not ship at all.

### 2.5 `default_action` (`"block"` | `"allow"`, default `"block"`)

The fallback policy for tools not listed in any of `safe`, `warn`, `confirm`,
or `block`.

- `default_action: block` — only listed tools are reachable. Recommended for
  most modes.
- `default_action: allow` — all tools allowed except those in `block`. Use
  sparingly.

### 2.6 `allowed_transitions` (list of strings, optional)

Restricts which other modes the LLM may transition to via `mode(set, ...)` while
this mode is active. Omit to allow any transition.

\`\`\`yaml
allowed_transitions: [plan, careful]
\`\`\`

Useful when a methodology mode wants to enforce a workflow phase order.

### 2.7 `allow_clear` (bool, default `true`)

If `false`, the LLM cannot exit the mode via `mode(clear)` — it must transition
to another mode. Used in methodology bundles like `superpowers` to prevent the
LLM from escaping a workflow phase.

---

## 3. The `tools` policy block

The `tools:` block is **policy** — it constrains how already-mounted tools may
be used while the mode is active. It does **not** mount or unmount tools.
(Mounting is the `contributes:` block's job — see §5.)

Four buckets:

\`\`\`yaml
tools:
  safe:    [read_file, glob, grep]   # always allowed, no friction
  warn:    [bash]                    # 1st call denied with explanation; retry allowed
  confirm: [write_file, edit_file]   # delegated to the approval hook
  block:   [delete_file]             # always denied
\`\`\`

### 3.1 `safe`

Allowed unconditionally. The LLM sees them in its tool list and may call them
freely.

### 3.2 `warn`

The first call to a `warn` tool while the mode is active is **denied** with a
deny-message that the LLM reads. The LLM then decides whether to retry. The
retry is allowed. Subsequent calls in the same mode session pass through. The
warn-set is intended to add **friction**, not to block — it gives the LLM a
chance to reconsider an action that the mode would prefer it think about.

### 3.3 `confirm`

The mode's confirm-list is written into
`session_state["require_approval_tools"]`. The approval hook
(`amplifier-module-hooks-approval`, registered in `behaviors/modes.yaml`) then
prompts the **human user** for each call. This is how a mode delegates
human-approval-in-the-loop without owning the approval UX itself.

### 3.4 `block`

Always denied with a structured deny-message. Use for tools that are dangerous
in this mode regardless of friction (e.g. `delete_file` in `plan` mode).

### 3.5 Infrastructure-tool bypass

Two tools — `mode` and `todo` — are hardcoded as **infrastructure tools** that
bypass the cascade entirely. The LLM can always use them regardless of
`default_action`. This is so a mode can never trap the LLM in a state where it
cannot exit (`mode`) or track its work (`todo`). See `ModeHooks.__init__` if
you need to override.

---

## 4. The mode body

Everything below the closing `---` is the **mode body**. It is injected as
`<system-reminder source="mode-<name>">...</system-reminder>` content on every
provider request while the mode is active. It is not a system prompt — it is
an ephemeral context block.

### 4.1 What to put in the body

- **Mode banner.** First line should restate the mode and its intent. The hooks
  layer adds a `MODE ACTIVE: <name>` banner automatically, so don't repeat it.
- **Workflow narration.** What the LLM should do, in what order, with what
  output format.
- **Capability narration.** If the mode contributes agents, skills, tools, or
  context (see §5), the body **must** enumerate them so the LLM is not
  surprised when they appear in its tool list / agent registry / skill index.
- **Constraints.** "Do NOT modify files. Do NOT delegate." Be explicit.

### 4.2 What NOT to put in the body

- Actual implementation steps. Modes shape behavior, they don't ship code.
- Long preamble. Token cost is paid on every request while the mode is active.
- Schema documentation. That's what files like this one are for; reference
  them via `contributes.context` (or `@`-mention) instead.

### 4.3 `@`-mention inline expansion

Lines of the form `@<bundle>:path/to/file.md` (alone on a line) are expanded
inline at injection time. Useful for pulling in shared context fragments.
Mentions inside paragraph text are not expanded.

---

## 5. The `contributes:` block (new in v1)

The `contributes:` block declares **additional capabilities that become live
only while the mode is active**. Items are pre-activated at bundle prep time
(downloaded, installed, importable) but **not mounted**. On mode activation,
the runtime-overlay primitive mounts them; on deactivation, it unmounts them
(subject to refcount semantics — see §7).

Three categories ship in v1: `agents`, `context`, `skills`. Two categories
land in v1.1: `tools`, `config`. See §6.

### 5.1 `contributes.agents`

\`\`\`yaml
contributes:
  agents:
    mode-author:
      source: "@modes:agents/mode-author"
    research-synth:
      source: "git+https://github.com/example/agent-research-synth@main"
\`\`\`

**Schema:** mapping of `<agent-name>` to a config dict containing at minimum a
`source` (a `@bundle:path` reference or git URL).

**Activation:** the named agents are added to the delegate tool's agent
registry. The LLM reaches them via `delegate(agent="<name>", ...)`. The agent
runs in a fresh sub-session with its own tools (declared in the agent's own
frontmatter) — the agent-tool-spawn precedent applies here.

**Referential integrity:** if `contributes.agents` is non-empty, the mode
**must** allow the `delegate` tool — i.e. `delegate` must be in `tools.safe` or
`default_action` must be `"allow"`. The parse-time lint warns otherwise.

### 5.2 `contributes.context`

\`\`\`yaml
contributes:
  context:
    - "@modes:context/mode-schema-reference.md"
    - "@modes:context/mode-design-examples.md"
\`\`\`

**Schema:** list of `@bundle:path` references to markdown files.

**Activation:** the file contents are appended to the mode body's
system-reminder injection on every provider request. They are token-cost-free
when the mode is inactive.

**Use for:** the kind of token-heavy reference material (long schema docs,
example libraries, glossaries) that you don't want polluting the base session
context.

### 5.3 `contributes.skills`

\`\`\`yaml
contributes:
  skills:
    - "@modes:skills/mode-design-discipline"
    - "@modes:skills/some-other-skill"
\`\`\`

**Schema:** list of `@bundle:path` references to skill directories (each
containing a `SKILL.md`).

**Activation:** the skills become discoverable via `load_skill(search=...)` and
loadable via `load_skill(name=...)`. They are invisible to the skill index when
the mode is inactive.

**Referential integrity:** if `contributes.skills` is non-empty, the mode
**must** allow `load_skill` (in `tools.safe`, or `default_action: allow`). The
parse-time lint warns otherwise.

---

## 6. v1.1 contribution categories (preview)

These are **not** in v1. They are documented here so authors don't write
forward-incompatible YAML, and so v1.1 has a clear shape to land into.

### 6.1 `contributes.tools` (v1.1)

\`\`\`yaml
contributes:
  tools:
    - module: tool-perplexity
      source: "git+https://github.com/example/tool-perplexity@v1.0"
      config:
        api_key_env: PERPLEXITY_KEY
\`\`\`

Mirrors the bundle's top-level `tools:` list shape exactly. Activation mounts
the tool with its config; deactivation unmounts. Tools have a name-collision
hazard absent from agents/skills (two modules can both register a tool named
`bash`); the activation handler will fail loudly on collisions rather than
silently shadowing.

### 6.2 `contributes.config` (v1.1)

\`\`\`yaml
contributes:
  config:
    orchestrator.config.model: "claude-opus-4-20250514"
    delegate.default_timeout: 600
\`\`\`

Scalar config overrides applied via an overlay stack. Pushed on activation,
popped on deactivation. Only one mode active at a time, so no stacking
conflicts in v1.1.

---

## 7. Activation, deactivation, and overlap

### 7.1 What happens on activation

1. Schema validation; `@`-mention sources resolved.
2. For each contributed item, the runtime overlay computes the delta against
   the current effective state.
3. New items are mounted; existing items have their refcount incremented (no
   remount — avoids in-flight tool-call hazards).
4. `contributes.config` overrides pushed.
5. Mode body injected as system-reminder.
6. `active_mode` set in `session_state`.
7. `mode:transition_completed` event emitted with the delta.
8. **On any failure during steps 3–4:** all items mounted in this transition
   are unmounted; mode is marked inactive; `mode:activation_failed` emitted.

### 7.2 What happens on deactivation

1. For each contributed item: refcount decrement; unmount if reaches 0.
2. `contributes.config` overrides popped.
3. Mode body injection removed.
4. `active_mode` cleared.
5. `mode:transition_completed` emitted.

### 7.3 Overlap scenarios (S1–S4)

The runtime overlay uses **refcount semantics** to handle items declared in
multiple places.

| Scenario | Setup | Behavior |
|---|---|---|
| **S1** | Item X in session AND in mode M | M activate: refcount 1→2 (no mount). M deactivate: refcount 2→1 (no unmount). X stays. |
| **S2** | Item X only in mode M | M activate: refcount 0→1 (mount). M deactivate: refcount 1→0 (unmount). X disappears. |
| **S3** | Item X in mode M1 AND mode M2 (not session) | M1 active → 0→1 mount. Switch to M2 → M1 deactivate (1→0 unmount), M2 activate (0→1 remount). v1: brief unmount/remount churn is acceptable. v1.1: cross-mode-transition optimization may compute net delta and skip. |
| **S4** | Item X in session AND M1 AND M2 | Refcount always ≥ 1. Never unmounted across any transition. |

**Mode authors should test their mode against S1 and S2 at minimum.**

---

## 8. Authoring checklist

Before shipping a new mode, confirm:

- [ ] `name` and `description` set; `description` is one line.
- [ ] `default_action` chosen deliberately (block is right for most modes).
- [ ] `tools` policy lists are complete and minimal — every tool the mode
      touches is in exactly one bucket.
- [ ] If `contributes.agents` non-empty, `delegate` is reachable.
- [ ] If `contributes.skills` non-empty, `load_skill` is reachable.
- [ ] If `advertised: false`, the body explicitly enumerates the contributed
      capabilities (the LLM has no other warning they exist).
- [ ] Mode body fits on one screen unless deep guidance is genuinely required.
- [ ] No production secrets, no PII, no environment-specific paths in the
      body.

---

## 9. Common patterns

### 9.1 Read-only analyst mode

\`\`\`yaml
mode:
  name: analyst
  description: "Analyze without modifying"
  default_action: block
  tools:
    safe: [read_file, glob, grep, web_search, web_fetch, todo, mode]
\`\`\`

### 9.2 Write-with-friction mode

\`\`\`yaml
mode:
  name: careful-write
  default_action: block
  tools:
    safe: [read_file, glob, grep, todo, mode]
    confirm: [write_file, edit_file, bash]
\`\`\`

### 9.3 Specialist mode with hidden capabilities

\`\`\`yaml
mode:
  name: deep-research
  advertised: false
  default_action: block
  tools:
    safe: [read_file, web_search, web_fetch, load_skill, todo, mode, delegate]
  contributes:
    agents:
      research-coordinator:
        source: "@modes:agents/research-coordinator"
    skills:
      - "@modes:skills/deep-research-discipline"
\`\`\`

---

## 10. Anti-patterns

- **Hiding incomplete work behind `advertised: false`.** Don't ship it.
- **Long mode bodies.** Token cost compounds across every provider request
  while the mode is active. Refactor into a `contributes.context` reference
  if the content is large.
- **Modes that contribute everything.** If the contribution list is long,
  consider whether the capabilities belong in the base bundle.
- **Modes that block infrastructure tools.** `mode` and `todo` bypass the
  cascade, but if you also block `delegate` while contributing agents, the
  contribution is unreachable.
- **Tool buckets that overlap.** A tool listed in two buckets is a bug; the
  parser uses first-match wins by bucket order (safe → warn → confirm → block)
  but this is undocumented and may change.

---

## 11. Reading the source

If this reference is ever wrong or incomplete, the source of truth is:

- **Schema parser:** `amplifier_foundation.bundle._dataclass._load_mode_file_metadata`
- **Hook-side parser:** `amplifier_module_hooks_mode.parse_mode_file`
- **Discovery / listing:** `amplifier_module_hooks_mode.ModeDiscovery`
- **Tool-policy enforcement:** `amplifier_module_hooks_mode.ModeHooks.handle_tool_pre`
- **Runtime overlay:** `amplifier_foundation.configurator.RuntimeOverlay`
- **Activation/deactivation flow:** `amplifier_module_hooks_mode.ModeHooks` (transition handlers)

When in doubt, read the parser.
```

> **Note to implementer:** the file above is approximately 6.5K tokens / ~28KB. If the rendered file is significantly shorter than that after stripping markdown formatting, expand `§9 Common patterns` and `§10 Anti-patterns` with one or two more examples each — the goal is a "weighty" reference document. Do not let it balloon past 12K tokens; the point is "noticeable when injected, free when not".

**Step 2: Verify the file exists and has expected size**

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
test -f context/mode-schema-reference.md && wc -c context/mode-schema-reference.md
```
**Expected:** a byte count between 20000 and 50000.

**Step 3: Commit**
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
git add context/mode-schema-reference.md
git commit -m "feat(mode-design): add mode-schema-reference context file

Comprehensive YAML schema reference for mode authors. Token-heavy by
design — contributed by /mode-design only when active, zero cost
otherwise.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 2: Create `skills/mode-design-discipline/SKILL.md`

**Files:**
- Create: `skills/mode-design-discipline/SKILL.md`

The skill captures authoring discipline — anti-bloat patterns, naming hygiene, when `advertised: false` is right, the four overlap scenarios, and the "body must narrate contributions" rule.

**Step 1: Create the directory**

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
mkdir -p skills/mode-design-discipline
```

**Step 2: Create `SKILL.md` with this exact content**

```markdown
---
name: mode-design-discipline
description: "Authoring discipline for Amplifier modes. Anti-bloat patterns, naming hygiene, when advertised:false is right, narrating contributions, testing the four overlap scenarios. Use when designing or reviewing a mode."
---

# Mode Design Discipline

A mode is a runtime behavior overlay. It costs tokens whenever active. It
risks LLM confusion whenever it materializes capabilities the LLM did not know
about. It hides intent whenever its body is too long to fit on a screen. The
discipline below is the difference between a mode that pays for itself and a
mode that becomes someone else's debugging problem.

## 1. Most modes don't need contributions

The `contributes:` block exists for the case where a capability is **specific
to a workflow phase** and would clutter the base bundle if always-on.

> Reach for `contributes:` only when the capability genuinely does not belong
> in the base bundle.

If three modes all contribute the same agent, that agent should probably be
in the base bundle, not in three modes. The same applies to skills and (in
v1.1) tools.

**Smell tests for "this should be in the bundle, not the mode":**

- The capability is referenced by more than one mode.
- The capability is useful outside any specific workflow phase.
- The capability is small and cheap to load.

**Smell tests for "this belongs in the mode":**

- The capability is genuinely specialist (deep-research, mode-design,
  security-audit).
- The capability brings substantial token cost (large reference docs,
  complex agents with large system prompts).
- The capability is rarely used and would clutter the LLM's tool list /
  agent registry / skill index for the 95% of sessions that don't need it.

## 2. Tool policy minimalism

`default_action: block` plus a small `safe:` list beats a long `block:` list.

**Rule of thumb:** the `safe:` list should fit on three screen lines. If it's
longer, the mode is probably trying to be a methodology, not a behavior
overlay.

**Don't list tools you don't need.** Every tool in `safe:` is one more thing
the LLM will reach for inappropriately. The LLM is biased toward action; the
mode is the safety rail.

**Don't list infrastructure tools.** `mode` and `todo` bypass the cascade.
Listing them in `safe:` is harmless but noise.

## 3. Naming hygiene

Mode names should clearly indicate **workflow phase or behavioral stance**.

**Good:**
- `plan` — phase
- `careful` — stance
- `mode-design` — phase + topic
- `deep-research` — phase + intensity

**Bad:**
- `mode1`, `mode2` — meaningless
- `bobs-mode` — author tag, not phase
- `wip` — implies it's not real
- `everything` — defeats the point of a mode

The shortcut should match the name unless there's a real collision risk.
Don't use `shortcut: false` to "lock down" a mode — it just means humans have
to type more.

## 4. When `advertised: false` is right

`advertised: false` is right for **rare specialist workflows**:

- The mode addresses a workflow that happens once per project, not once per
  session.
- The mode brings substantial context that would crowd the LLM's attention
  budget.
- The mode is invoked deliberately by a human, never inferred by the LLM.

`advertised: false` is **wrong** for:

- **Hiding work-in-progress.** WIP modes shouldn't ship. Use a feature
  branch.
- **Deceiving the LLM.** If the LLM should know about the capability, advertise
  it. If the capability shouldn't exist for the LLM, don't ship the mode.
- **Hiding mistakes.** A mode that has buggy contributions and survives
  because nobody can find it is worse than a removed mode.

## 5. The body must narrate contributions

When `advertised: false` and `contributes:` is non-empty, the LLM has **no
warning** that capabilities are about to materialize. The mode body must
narrate them explicitly.

**Required body sections when contributing:**

1. Brief statement of mode intent.
2. Enumeration of contributed capabilities, by category:
   - Contributed agents and what they do.
   - Contributed skills and when to load them.
   - Contributed context files (less critical — context is just text).
3. Workflow narration.
4. Exit conditions ("/mode off when …").

Example fragment:

```markdown
While this mode is active, the following capabilities are available:

- **Agent `mode-author`** — drafts mode YAML + body from a brief description.
  Reach via `delegate(agent="mode-author", ...)`.
- **Skill `mode-design-discipline`** — authoring discipline. Load via
  `load_skill("mode-design-discipline")` when starting.
- **Reference `mode-schema-reference.md`** — full schema reference. Already
  in your context.
```

This is not boilerplate — the LLM uses this section to find the new
capabilities. Without it, the mode is a quiet trap.

## 6. Test the four overlap scenarios

Every mode that uses `contributes:` should be tested against the four overlap
scenarios from the runtime-overlay design:

- **S1.** Item already in the session. Activate: no remount. Deactivate: item
  stays. (Verify: session-level capability not lost.)
- **S2.** Item only in this mode. Activate: mounts. Deactivate: unmounts.
  (Verify: contribution actually disappears.)
- **S3.** Item in this mode AND another mode. Switch between them. (Verify:
  acceptable — item may briefly unmount/remount in v1, that's OK.)
- **S4.** Item in session, this mode, and other modes. (Verify: item never
  disappears across any transition.)

For S2 specifically: write a test that activates the mode, asserts the
contribution is reachable, deactivates the mode, asserts the contribution is
**gone**. If you skip this test, the bug ships.

## 7. Anti-patterns

- **Treating the mode body as a system prompt.** It is ephemeral context
  injected on every provider request. Long bodies are paid for repeatedly.
- **Putting the schema in the body.** That's what `contributes.context` is
  for.
- **Modes that block their own contributions.** Contributing an agent while
  blocking `delegate` is a parse-time warning, but the lint isn't infallible.
  Read your own YAML.
- **Modes that depend on session state set elsewhere.** A mode is supposed to
  be self-contained. If activation requires "first run X to populate Y",
  re-design.

## 8. Workflow when designing a new mode

1. **Write the intent in one sentence.** If you can't, the mode isn't ready.
2. **Decide tool policy** before contributions. Most modes only need a
   policy, no contributions. Save yourself the work.
3. **Decide whether `advertised: false` is right** (§4).
4. **Draft the body.** Narrate workflow first, then contributions if any.
5. **Add `contributes:` last.** Each entry has to justify its weight.
6. **Run the parse-time lints.** They catch the obvious referential-integrity
   bugs.
7. **Write the S1/S2 test** at minimum.
8. **Have someone else read the body cold.** If they don't know what to do
   after one read, neither will the LLM.

## 9. Reading order for new authors

1. The bundle README — a quickstart.
2. `mode-schema-reference.md` — the full schema (contributed by `/mode-design`).
3. The existing modes (`plan.md`, `careful.md`, `explore.md`,
   `mode-design.md`) — read all four before authoring your own.
4. This skill — for the discipline that doesn't fit in the schema reference.

---

When the mode you're designing surprises you in a way that requires a new
section here, edit this skill rather than copy-pasting tribal knowledge into
each mode's body.
```

**Step 3: Verify and commit**

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
test -f skills/mode-design-discipline/SKILL.md && wc -l skills/mode-design-discipline/SKILL.md
git add skills/mode-design-discipline/SKILL.md
git commit -m "feat(mode-design): add mode-design-discipline skill

Authoring discipline for Amplifier modes — anti-bloat patterns,
naming hygiene, when advertised:false is right, narrating
contributions, testing the four overlap scenarios.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```
**Expected:** line count > 100; clean commit.

---

## Task 3: Create `agents/mode-author.md`

**Files:**
- Create: `agents/mode-author.md`

The `mode-author` agent drafts mode YAML and body from a brief intent
description. It is reached via `delegate(agent="mode-author", ...)` only when
`/mode-design` is active.

**Step 1: Create `agents/` directory if it doesn't exist**

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
mkdir -p agents
```

**Step 2: Create the file with this exact content**

```markdown
---
meta:
  name: mode-author
  description: |
    Use after /mode-design conversation to draft a new mode .md file from a
    brief intent description and tool-policy decisions.

    Examples:
    <example>
    Context: User is in /mode-design mode and has agreed on the mode's intent
    and tool policy.
    user: "Draft the mode file"
    assistant: "I'll delegate to modes:mode-author to write the mode .md."
    <commentary>mode-author writes the file after the conversation has
    settled the intent and policy.</commentary>
    </example>

    <example>
    Context: Schema reference loaded; tool policy decided.
    user: "Write the mode for me"
    assistant: "I'll use modes:mode-author to draft a complete mode file."
    <commentary>Drafting from a settled intent is the mode-author's sole
    responsibility — it does not negotiate scope.</commentary>
    </example>

  model_role: [reasoning, general]
tools:
  - module: tool-filesystem
    source: git+https://github.com/microsoft/amplifier-module-tool-filesystem@main
---

# Mode Author Agent

You draft a complete Amplifier mode `.md` file (YAML frontmatter + Markdown
body) from a brief intent description and tool-policy decisions provided in
your delegation instruction. You write the file to disk and stop.

## Your Role

You receive a delegation instruction containing at minimum:

- **Mode name** (string).
- **Intent** — one or two sentences describing what the mode is for.
- **Tool policy** — which tools should be in `safe`, `warn`, `confirm`, `block`.
- Optional: contribution list (`agents`, `context`, `skills`).
- Optional: `advertised` flag, `default_action`, `allowed_transitions`,
  `allow_clear`.
- Optional: target directory (defaults to `<bundle-root>/modes/`).

Your job:

1. Validate the inputs against the schema reference (`mode-schema-reference.md`)
   already in the orchestrator's context.
2. Draft a complete mode file:
   - YAML frontmatter using the exact field names and conventions from the
     schema.
   - Markdown body that **narrates the workflow and (if any) the contributed
     capabilities**.
3. Write the file to `<target_dir>/<name>.md`.
4. Report back with the path written.

You do **not** conduct conversations, ask design questions, or negotiate
scope. The orchestrator handled that.

## Output File Template

```markdown
---
mode:
  name: <name>
  description: <description>
  shortcut: <shortcut>          # optional
  advertised: <bool>            # default true
  default_action: <block|allow>
  allow_clear: <bool>           # default true

  tools:
    safe: [...]
    warn: [...]                 # if any
    confirm: [...]              # if any
    block: [...]                # if any

  contributes:                  # if any
    agents: { ... }
    context: [...]
    skills: [...]
---

# <Mode Title>

<one-paragraph statement of mode intent>

## Workflow

<numbered list of steps the LLM should follow>

<if contributes is non-empty:>
## Capabilities while this mode is active

- **Agent `<name>`** — <one-line>. Reach via `delegate(agent="<name>", ...)`.
- **Skill `<name>`** — <one-line>. Load via `load_skill("<name>")`.
- **Reference `<file>`** — <one-line>. (already in context).

## Exit

Use `/mode off` when <exit condition>.
```

## Discipline

- **Schema first.** Cross-check every field against
  `mode-schema-reference.md` in your context. Do not invent fields.
- **Body narrates capabilities.** If `contributes` is non-empty, the body
  **must** enumerate them. The schema reference explains why; the
  `mode-design-discipline` skill is the canonical statement.
- **Tool-policy referential integrity.**
  - If `contributes.agents` non-empty → `delegate` must be in `safe` or
    `default_action: allow`.
  - If `contributes.skills` non-empty → `load_skill` must be in `safe` or
    `default_action: allow`.
  - Surface mismatches in your final report; do not silently fix.
- **No production secrets, no PII, no environment-specific paths.**
- **One file per delegation.** You write one mode and stop.

## Red Flags — Stop and Report

- The orchestrator's instruction is incomplete (no name, no intent, no policy).
- A contribution source is malformed (`@bundle:path` looks wrong, git URL
  doesn't parse).
- The orchestrator asked for a tool not known to the ecosystem.
- The target directory does not exist or is not writable.

In all of these, write nothing; report back to the orchestrator with the
specific gap.

@foundation:context/shared/common-agent-base.md
```

**Step 3: Verify and commit**

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
test -f agents/mode-author.md
git add agents/mode-author.md
git commit -m "feat(mode-design): add mode-author agent

Drafts a complete mode .md file from intent + tool-policy decisions.
Reached via delegate(agent=\"mode-author\") only while /mode-design
is active.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 4: Create `modes/mode-design.md`

**Files:**
- Create: `modes/mode-design.md`

This is **the mode itself** — the YAML from §9.1 of the design doc, plus a
body that narrates the contributed capabilities.

**Step 1: Create the file with this exact content**

```markdown
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
      - delegate
    confirm:
      - write_file
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

You are designing a new Amplifier mode. This mode contributes substantial
capability that is invisible to most sessions — read the capabilities listing
below before doing anything else.

## Capabilities while this mode is active

The following are available **only** while `/mode-design` is active. They were
not in your tool list, agent registry, or skill index a moment ago.

- **Agent `mode-author`** — drafts a complete mode `.md` (YAML + body) from a
  brief intent and tool-policy decisions. Reach via
  `delegate(agent="mode-author", instruction="...")`.
- **Skill `mode-design-discipline`** — authoring discipline (anti-bloat
  patterns, naming hygiene, narration rules, the four overlap scenarios). Load
  via `load_skill("mode-design-discipline")` at the start of the conversation.
- **Reference `mode-schema-reference.md`** — the full mode YAML schema. It is
  already in your context.

## Workflow

Three phases. Do not skip.

1. **Intent.** With the user, narrate the mode's purpose in one or two
   sentences. Who triggers it? What changes when it activates? What is the
   exit condition? If you cannot answer all three, the mode is not ready.

2. **Tool policy & contributions.** Walk the user through the `tools` policy
   (`safe`, `warn`, `confirm`, `block`) and `default_action`. Decide whether
   the mode needs `contributes` at all — most don't. If it does, decide which
   categories. Cross-check referential integrity:

   - Contributing an agent? `delegate` must be in `safe`.
   - Contributing a skill? `load_skill` must be in `safe`.

3. **Body draft.** Delegate to `mode-author` for the first pass:

   ```
   delegate(
     agent="mode-author",
     instruction="Draft a mode named '<name>' with intent: ...
       Tool policy: safe=[...], confirm=[...], block=[...].
       default_action: block. advertised: <bool>.
       Contributions: agents=[...], skills=[...], context=[...].
       Write to modes/<name>.md."
   )
   ```

   Then refine. The `mode-author` agent is a draftsman, not a designer — you
   own the design.

## Discipline

- **Read the discipline skill first.** `load_skill("mode-design-discipline")`
  before drafting. It captures lessons that don't fit in the schema.
- **Body narrates contributions.** If the new mode uses `contributes:`, the
  body **must** enumerate the new capabilities. `advertised: false` modes
  surprise the LLM otherwise.
- **Tests.** Encourage the user to add at least an S2 (mode-only-item)
  integration test for any contribution.

## Exit

Use `/mode off` when the new mode file is written, parsed cleanly, and the
user has agreed to ship.
```

**Step 2: Verify the mode parses cleanly**

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes/modules/hooks-mode
python -c "
from pathlib import Path
from amplifier_module_hooks_mode import parse_mode_file
md = parse_mode_file(Path('../../modes/mode-design.md'))
assert md is not None, 'parse failed'
assert md.name == 'mode-design'
assert md.advertised is False, f'advertised: {md.advertised!r}'
assert md.contributes is not None
assert 'agents' in md.contributes and 'mode-author' in md.contributes['agents']
assert 'context' in md.contributes
assert 'skills' in md.contributes
assert 'delegate' in md.safe_tools
assert 'load_skill' in md.safe_tools
assert 'write_file' in md.confirm_tools
print('OK: mode-design.md parses correctly')
"
```
**Expected:** `OK: mode-design.md parses correctly`

**Step 3: Commit**

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
git add modes/mode-design.md
git commit -m "feat(mode-design): add /mode-design mode

advertised:false mode that contributes mode-author agent,
mode-design-discipline skill, and mode-schema-reference context.

Vertical slice for the runtime-overlay design (Phase 3).

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 5: Create `modes/README.md`

**Files:**
- Create: `modes/README.md`

A brief listing of built-in modes with one-line descriptions, including the
`advertised: false` flag where relevant.

**Step 1: Create the file with this content**

```markdown
# Built-in Modes

The `modes` bundle ships these modes out of the box. Project-level modes
(`.amplifier/modes/`) and user-level modes (`~/.amplifier/modes/`) override
these by name.

| Mode | Shortcut | Description | Advertised |
|---|---|---|---|
| `plan` | `/plan` | Analyze, strategize, and organize — but don't implement. | yes |
| `careful` | `/careful` | Full capability with confirmation for destructive actions. | yes |
| `explore` | `/explore` | Zero-footprint exploration — understand before acting. | yes |
| `mode-design` | `/mode-design` | Design a new Amplifier mode through structured authoring. Hidden from LLM listings; activate via slash command. | **no** |

## `mode-design` — note

`/mode-design` is `advertised: false`. The LLM does not see it in
`mode(list)` output, and it does not appear in `/modes` without the `--all`
flag (CLI v1.1; until then, `/modes` may list all modes by default — see
below). It contributes the `mode-author` agent, the
`mode-design-discipline` skill, and the `mode-schema-reference.md` context
file — all of which materialize on activation and disappear on deactivation.

For a session that never activates `/mode-design`, none of those three
artifacts contribute any tokens to the LLM context.

## CLI `/modes` listing of unadvertised modes (status)

The Amplifier CLI's `/modes` slash command currently does **not** filter on
`advertised`. The flag affects only the `mode(list)` tool operation visible
to the LLM. A `--all` flag for `/modes` is scheduled for v1.1; until it
lands, `/modes` may surface unadvertised modes to humans by default. This is
intentional — humans benefit from discovery; the LLM does not.

## Authoring a new mode

See `/mode-design` and `mode-design-discipline` (skill, contributed by
`/mode-design`).

The bundle README has a quickstart in the "Creating Custom Modes" section.
The full schema reference (`context/mode-schema-reference.md`) is reachable
either by reading the file directly or by activating `/mode-design`.
```

**Step 2: Verify and commit**

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
test -f modes/README.md
git add modes/README.md
git commit -m "docs(modes): add modes/README listing built-in modes

Includes mode-design with advertised:false note and CLI /modes
filtering status.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 6: Create test fixture `tests/fixtures/test-overlap-mode.md`

**Files:**
- Create: `modules/hooks-mode/tests/fixtures/test-overlap-mode.md`

A test-only mode that declares the **same** `mode-author` agent that
`/mode-design` declares, used to exercise S3 (item in two modes) and S4
(item in session + two modes) without polluting the shipped modes set.

**Step 1: Create the directory**

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
mkdir -p modules/hooks-mode/tests/fixtures
```

**Step 2: Create the fixture file with this content**

```markdown
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

This mode exists only as a test fixture. It declares the same `mode-author`
agent as `/mode-design` so the runtime-overlay refcount logic can be tested
across S3 (item in two modes) and S4 (item in session + two modes).

Do not ship this mode. It lives under `modules/hooks-mode/tests/fixtures/`
and is loaded only by the integration test module.
```

**Step 3: Verify and commit**

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
test -f modules/hooks-mode/tests/fixtures/test-overlap-mode.md
git add modules/hooks-mode/tests/fixtures/test-overlap-mode.md
git commit -m "test(mode-overlay): add test-overlap-mode fixture

Test-only mode declaring mode-author for S3/S4 overlap scenario
testing. Not shipped to users.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 7: Integration-test scaffolding

**Files:**
- Create: `modules/hooks-mode/tests/test_overlay_integration.py` (initial scaffold; tests added in Tasks 8–14)

This task creates the test file with shared helpers and a single placeholder
test that exercises imports. Each subsequent task adds one scenario via
strict TDD.

**Step 1: Create the file with this exact scaffold**

```python
"""Integration tests for the mode runtime-overlay vertical slice.

Each test exercises the live RuntimeOverlay through hooks-mode transition
handlers, validating the four overlap scenarios (S1-S4), advertised:false
filtering, atomic rollback on contribution failure, and full activation of
the /mode-design mode end-to-end.

These tests assume Phases 1 and 2 of the mode-overlay design are complete:
- foundation parses `advertised` and `contributes` from mode YAML
- `RuntimeOverlay` is importable from amplifier_foundation.configurator
- hooks-mode transition handlers call RuntimeOverlay.apply / .revoke
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# Bundle root, used to locate shipped artifacts
BUNDLE_ROOT = Path(__file__).resolve().parents[3]
MODES_DIR = BUNDLE_ROOT / "modes"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _make_coordinator(active_mode: str | None = None, agents: dict[str, Any] | None = None) -> MagicMock:
    """Build a mock coordinator with the surface area the overlay touches.

    `agents` lets tests pre-populate the agent registry to simulate
    session-level capabilities (S1, S4 scenarios).
    """
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
    coordinator.mount = MagicMock()
    coordinator.unmount = MagicMock()
    coordinator.get_capability = MagicMock(return_value=None)
    return coordinator


def _agent_registry(coordinator: MagicMock) -> dict[str, Any]:
    """Single accessor for 'where the agent registry actually lives'.

    The agent-tool-spawn precedent stores agents in coordinator.config['agents'].
    Phase 1/2 should preserve that. This helper centralizes the assertion
    target so a future move (e.g. to a dedicated registry capability) only
    needs to be updated here.
    """
    return coordinator.config.get("agents", {})


@pytest.mark.asyncio
async def test_imports_and_scaffold_smoke() -> None:
    """Smoke test: integration-test module loads, coordinator helper works."""
    coord = _make_coordinator()
    assert coord.session_state["active_mode"] is None
    assert _agent_registry(coord) == {}
```

**Step 2: Run the smoke test**

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes/modules/hooks-mode
pytest tests/test_overlay_integration.py::test_imports_and_scaffold_smoke -v
```
**Expected:** `1 passed`. If it fails, fix imports before continuing.

**Step 3: Commit**
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
git add modules/hooks-mode/tests/test_overlay_integration.py
git commit -m "test(mode-overlay): add integration-test scaffold

Coordinator factory, agent-registry accessor, smoke test.
Per-scenario tests added in subsequent commits.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 8: TDD — `test_S1_session_overlap`

**Files:**
- Modify: `modules/hooks-mode/tests/test_overlay_integration.py`

**Scenario:** session has agent `mode-author`; `/mode-design` also contributes
`mode-author`. Activate `/mode-design` → no remount. Deactivate → `mode-author`
stays in the registry (it's the session's agent).

**Step 1: Write the failing test**

Append to `tests/test_overlay_integration.py`:

```python
@pytest.mark.asyncio
async def test_S1_session_overlap() -> None:
    """S1: session has X; mode contributes X.

    Activate: refcount 1 -> 2, no mount.
    Deactivate: refcount 2 -> 1, no unmount. X stays.
    """
    from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks

    session_agent = {"source": "session-fake-source", "_marker": "from-session"}
    coord = _make_coordinator(agents={"mode-author": session_agent})

    discovery = ModeDiscovery(search_paths=[MODES_DIR])
    hooks = ModeHooks(coord, discovery)

    # Activate /mode-design
    coord.session_state["active_mode"] = "mode-design"
    await hooks.handle_mode_activated("mode:activated", {"mode": "mode-design"})

    # mode-author still present, still the SESSION's instance (not replaced)
    reg = _agent_registry(coord)
    assert "mode-author" in reg, "mode-author must remain in the registry"
    assert reg["mode-author"] is session_agent, (
        "S1: existing instance must NOT be replaced by the mode's contribution "
        "(avoids in-flight tool-call hazards)"
    )

    # Deactivate
    coord.session_state["active_mode"] = None
    await hooks.handle_mode_deactivated("mode:deactivated", {"mode": "mode-design"})

    reg_after = _agent_registry(coord)
    assert "mode-author" in reg_after, (
        "S1: deactivating the mode must NOT unmount X — session still references it"
    )
    assert reg_after["mode-author"] is session_agent
```

**Step 2: Run and verify it fails**

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes/modules/hooks-mode
pytest tests/test_overlay_integration.py::test_S1_session_overlap -v
```
**Expected:** FAIL — likely because `ModeHooks` does not yet have
`handle_mode_activated` / `handle_mode_deactivated` (Phase 2's responsibility),
or the handler does not yet wire the session-overlap correctly.

**Step 3: Wire the test against the real Phase 2 handlers**

The test invokes `handle_mode_activated` and `handle_mode_deactivated` —
Phase 2 transition handlers. If those method names don't match what Phase 2
actually shipped, update the test to call the real method names. Do **not**
modify production code here — Phase 3 is tests-only. If a real bug surfaces,
file it as a Phase 2 follow-up and skip the test with a clear `pytest.skip`
reason.

**Step 4: Run and verify it passes**

Run:
```bash
pytest tests/test_overlay_integration.py::test_S1_session_overlap -v
```
**Expected:** PASS.

**Step 5: Commit**
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
git add modules/hooks-mode/tests/test_overlay_integration.py
git commit -m "test(mode-overlay): S1 session-overlap refcount

mode-design contributes mode-author; session also has mode-author.
Activate: no remount. Deactivate: stays.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 9: TDD — `test_S2_mode_only`

**Files:**
- Modify: `modules/hooks-mode/tests/test_overlay_integration.py`

**Scenario:** session has no `mode-author`. Activate `/mode-design` →
`mode-author` appears. Deactivate → it disappears.

**Step 1: Write the failing test**

Append:

```python
@pytest.mark.asyncio
async def test_S2_mode_only() -> None:
    """S2: item only in mode.

    Activate: 0 -> 1 mount.
    Deactivate: 1 -> 0 unmount.
    """
    from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks

    coord = _make_coordinator(agents={})  # no mode-author at session level
    discovery = ModeDiscovery(search_paths=[MODES_DIR])
    hooks = ModeHooks(coord, discovery)

    assert "mode-author" not in _agent_registry(coord)

    # Activate
    coord.session_state["active_mode"] = "mode-design"
    await hooks.handle_mode_activated("mode:activated", {"mode": "mode-design"})

    reg = _agent_registry(coord)
    assert "mode-author" in reg, "S2: contribution must mount on activation"

    # Deactivate
    coord.session_state["active_mode"] = None
    await hooks.handle_mode_deactivated("mode:deactivated", {"mode": "mode-design"})

    reg_after = _agent_registry(coord)
    assert "mode-author" not in reg_after, (
        "S2: contribution must unmount on deactivation"
    )
```

**Step 2: Run and verify FAIL → wire → PASS**

Run:
```bash
pytest tests/test_overlay_integration.py::test_S2_mode_only -v
```
If failing, confirm the cause is wrong test wiring (not a real production bug).
Adjust the call surface to match Phase 2's shipped handler names if needed.

Run again:
```bash
pytest tests/test_overlay_integration.py::test_S2_mode_only -v
```
**Expected:** PASS.

**Step 3: Commit**
```bash
git add modules/hooks-mode/tests/test_overlay_integration.py
git commit -m "test(mode-overlay): S2 mode-only contribution

mode-design contributes mode-author; session has nothing.
Activate: mounts. Deactivate: unmounts.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 10: TDD — `test_S3_two_modes_same_item`

**Files:**
- Modify: `modules/hooks-mode/tests/test_overlay_integration.py`

**Scenario:** two modes (`/mode-design` and the test-overlap fixture) both
contribute `mode-author`. Session has none. Activate M1 → mounts. Switch to
M2 → for v1, brief unmount/remount churn is **acceptable** (documented in
design §7); we assert the **end state** is correct (`mode-author` mounted
when either mode is active).

**Step 1: Write the failing test**

Append:

```python
@pytest.mark.asyncio
async def test_S3_two_modes_same_item() -> None:
    """S3: item in mode M1 AND mode M2 (not session).

    v1 behavior: switching modes may briefly unmount and remount.
    End-state assertion: the contributed item is mounted whenever
    either mode is active.
    """
    from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks

    coord = _make_coordinator(agents={})
    # Search paths: the shipped modes dir AND the fixtures dir (so test-overlap-mode is found)
    discovery = ModeDiscovery(search_paths=[MODES_DIR, FIXTURES_DIR])
    hooks = ModeHooks(coord, discovery)

    # Activate /mode-design
    coord.session_state["active_mode"] = "mode-design"
    await hooks.handle_mode_activated("mode:activated", {"mode": "mode-design"})
    assert "mode-author" in _agent_registry(coord), (
        "S3: M1 active -> mode-author mounted"
    )

    # Switch to test-overlap-mode (M2 contributes the same agent)
    await hooks.handle_mode_deactivated("mode:deactivated", {"mode": "mode-design"})
    coord.session_state["active_mode"] = "test-overlap-mode"
    await hooks.handle_mode_activated(
        "mode:activated", {"mode": "test-overlap-mode"}
    )

    assert "mode-author" in _agent_registry(coord), (
        "S3: M2 active -> mode-author mounted (after the v1 unmount/remount churn)"
    )

    # Deactivate M2 -> nothing keeps mode-author alive
    coord.session_state["active_mode"] = None
    await hooks.handle_mode_deactivated(
        "mode:deactivated", {"mode": "test-overlap-mode"}
    )
    assert "mode-author" not in _agent_registry(coord), (
        "S3: both modes inactive -> mode-author unmounted"
    )
```

**Step 2: Run, fail-then-pass cycle**

Run:
```bash
pytest tests/test_overlay_integration.py::test_S3_two_modes_same_item -v
```
**Expected:** PASS after wire-up. If `test-overlap-mode` is not discoverable
because Phase 2's discovery does not consult fixture dirs, add the fixture
search path explicitly via `discovery.add_search_path(FIXTURES_DIR)` (the
current `ModeDiscovery` API supports it).

**Step 3: Commit**
```bash
git add modules/hooks-mode/tests/test_overlay_integration.py
git commit -m "test(mode-overlay): S3 two modes contribute same item

mode-design and test-overlap-mode both contribute mode-author.
Switch between: end state correct (mounted when either active,
unmounted when both inactive).

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 11: TDD — `test_S4_session_plus_two_modes`

**Files:**
- Modify: `modules/hooks-mode/tests/test_overlay_integration.py`

**Scenario:** session has `mode-author`; both `/mode-design` and
`test-overlap-mode` also contribute `mode-author`. The agent is reachable
across every transition; never unmounted.

**Step 1: Write the failing test**

Append:

```python
@pytest.mark.asyncio
async def test_S4_session_plus_two_modes() -> None:
    """S4: item in session AND M1 AND M2.

    Refcount always >= 1. Item never unmounts across any transition.
    """
    from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks

    session_agent = {"source": "session-fake-source", "_marker": "from-session"}
    coord = _make_coordinator(agents={"mode-author": session_agent})
    discovery = ModeDiscovery(search_paths=[MODES_DIR, FIXTURES_DIR])
    hooks = ModeHooks(coord, discovery)

    def _assert_session_instance() -> None:
        reg = _agent_registry(coord)
        assert "mode-author" in reg
        assert reg["mode-author"] is session_agent, (
            "S4: existing session instance must never be replaced by mode contributions"
        )

    _assert_session_instance()

    # Activate /mode-design
    coord.session_state["active_mode"] = "mode-design"
    await hooks.handle_mode_activated("mode:activated", {"mode": "mode-design"})
    _assert_session_instance()

    # Switch to test-overlap-mode
    await hooks.handle_mode_deactivated("mode:deactivated", {"mode": "mode-design"})
    coord.session_state["active_mode"] = "test-overlap-mode"
    await hooks.handle_mode_activated("mode:activated", {"mode": "test-overlap-mode"})
    _assert_session_instance()

    # Deactivate M2 -> session still has it
    coord.session_state["active_mode"] = None
    await hooks.handle_mode_deactivated("mode:deactivated", {"mode": "test-overlap-mode"})
    _assert_session_instance()
```

**Step 2: Run, fail-then-pass**

Run:
```bash
pytest tests/test_overlay_integration.py::test_S4_session_plus_two_modes -v
```
**Expected:** PASS.

**Step 3: Commit**
```bash
git add modules/hooks-mode/tests/test_overlay_integration.py
git commit -m "test(mode-overlay): S4 session + two modes contribute same item

mode-author in session and in two modes. Refcount stays >=1 across
every transition; session instance never replaced.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 12: TDD — `test_advertised_false_filtering`

**Files:**
- Modify: `modules/hooks-mode/tests/test_overlay_integration.py`

**Scenario:** `mode-design` is `advertised: false`. It must be hidden from
LLM-facing listings but visible to humans. Specifically:

- `ModeDiscovery.list_modes(include_unadvertised=False)` (or whatever the
  Phase 2 signature is) does **not** include it.
- `ModeDiscovery.list_modes(include_unadvertised=True)` **does** include it.
- The `tool-mode` `mode(list)` operation surfaces only advertised modes.

**Step 1: Write the failing test**

Append:

```python
@pytest.mark.asyncio
async def test_advertised_false_filtering() -> None:
    """advertised:false hides from LLM, not from humans."""
    from amplifier_module_hooks_mode import ModeDiscovery

    discovery = ModeDiscovery(search_paths=[MODES_DIR])

    # LLM-facing listing: must NOT include mode-design
    llm_visible = discovery.list_modes(include_unadvertised=False)
    llm_visible_names = {entry[0] for entry in llm_visible}
    assert "mode-design" not in llm_visible_names, (
        "advertised:false mode must be hidden from LLM listings"
    )

    # Human-facing listing: must include mode-design
    human_visible = discovery.list_modes(include_unadvertised=True)
    human_visible_names = {entry[0] for entry in human_visible}
    assert "mode-design" in human_visible_names, (
        "advertised:false mode must still appear with include_unadvertised=True"
    )

    # The advertised modes (plan, careful, explore) are in both
    for advertised in ("plan", "careful", "explore"):
        assert advertised in llm_visible_names, f"{advertised} should be LLM-visible"
        assert advertised in human_visible_names, f"{advertised} should be human-visible"
```

**Step 2: Run, fail-then-pass**

Run:
```bash
pytest tests/test_overlay_integration.py::test_advertised_false_filtering -v
```

If `list_modes()` does not yet accept `include_unadvertised`, that signals
Phase 2 didn't ship the discovery filter. Stop and finish Phase 2.

**Expected after Phase 2:** PASS.

**Step 3: Commit**
```bash
git add modules/hooks-mode/tests/test_overlay_integration.py
git commit -m "test(mode-overlay): advertised:false filtering

mode-design hidden from LLM-facing listings (default), visible
with include_unadvertised=True.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 13: TDD — `test_contribution_failure_rollback`

**Files:**
- Modify: `modules/hooks-mode/tests/test_overlay_integration.py`

**Scenario:** activation deliberately fails partway through (e.g. one of the
contributed sources is unresolvable). The runtime overlay must roll back
**every** item it mounted in that transition, mark the mode inactive, and
emit `MODE_ACTIVATION_FAILED`.

**Step 1: Write the failing test**

Append:

```python
@pytest.mark.asyncio
async def test_contribution_failure_rollback(tmp_path: Path) -> None:
    """Atomic rollback: a failing contribution unmounts everything mounted in
    this transition; mode is marked inactive; MODE_ACTIVATION_FAILED emitted.
    """
    from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks

    # Build a temporary mode that contributes one good agent and one
    # deliberately-broken source.
    bad_mode_dir = tmp_path / "modes"
    bad_mode_dir.mkdir()
    bad_mode_file = bad_mode_dir / "broken-overlap.md"
    bad_mode_file.write_text(textwrap.dedent("""\
        ---
        mode:
          name: broken-overlap
          shortcut: false
          advertised: false
          default_action: block
          tools:
            safe: [delegate, mode]
          contributes:
            agents:
              mode-author:
                source: "@modes:agents/mode-author"
              this-does-not-exist:
                source: "@modes:agents/this-does-not-exist"
        ---
        Broken on purpose.
    """))

    coord = _make_coordinator(agents={})
    # Search paths include the broken fixture's modes dir AND the shipped agents dir
    discovery = ModeDiscovery(search_paths=[MODES_DIR, bad_mode_dir])
    hooks = ModeHooks(coord, discovery)

    coord.session_state["active_mode"] = "broken-overlap"
    await hooks.handle_mode_activated("mode:activated", {"mode": "broken-overlap"})

    # 1. Mode is marked inactive (rollback unwound the activation)
    assert coord.session_state.get("active_mode") in (None, ""), (
        "Failed activation must clear active_mode"
    )

    # 2. The 'good' contribution that may have been mounted before the failure
    #    has been unmounted.
    assert "mode-author" not in _agent_registry(coord), (
        "Atomic rollback: items mounted before the failure must be unmounted"
    )

    # 3. The failure event was emitted
    emit_calls = coord.hooks.emit.await_args_list
    failed_events = [
        call for call in emit_calls
        if call.args and "activation_failed" in str(call.args[0]).lower()
    ]
    assert failed_events, (
        "MODE_ACTIVATION_FAILED (or equivalent) must be emitted on rollback. "
        f"Saw events: {[c.args[0] if c.args else None for c in emit_calls]}"
    )
```

**Step 2: Run, fail-then-pass**

Run:
```bash
pytest tests/test_overlay_integration.py::test_contribution_failure_rollback -v
```

If the `RuntimeOverlay` does not implement atomic rollback, this is a Phase 1
gap — stop and fix in Phase 1, not in Phase 3.

**Expected:** PASS once Phase 1 atomic-apply is real.

**Step 3: Commit**
```bash
git add modules/hooks-mode/tests/test_overlay_integration.py
git commit -m "test(mode-overlay): atomic rollback on contribution failure

A mode with one good and one broken contribution: failure unwinds
the partial activation, clears active_mode, emits MODE_ACTIVATION_FAILED.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 14: TDD — `test_mode_design_end_to_end`

**Files:**
- Modify: `modules/hooks-mode/tests/test_overlay_integration.py`

**Scenario:** full activation of `/mode-design`. After activation:

1. `mode-author` is reachable in the agent registry (proxy for delegate).
2. The body of `mode-schema-reference.md` ends up in the injected context.
3. The skill `mode-design-discipline` is discoverable.

After deactivation, all three are gone.

**Step 1: Write the failing test**

Append:

```python
@pytest.mark.asyncio
async def test_mode_design_end_to_end() -> None:
    """Full activation of /mode-design: agent + context + skill all live;
    deactivation: all three gone.
    """
    from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks

    coord = _make_coordinator(agents={})
    discovery = ModeDiscovery(search_paths=[MODES_DIR])
    hooks = ModeHooks(coord, discovery)

    # ---- ACTIVATE ----
    coord.session_state["active_mode"] = "mode-design"
    await hooks.handle_mode_activated("mode:activated", {"mode": "mode-design"})

    # 1. Agent
    reg = _agent_registry(coord)
    assert "mode-author" in reg, "mode-author agent must be reachable while active"

    # 2. Context — the schema reference body must be present in the injected
    #    system-reminder when handle_provider_request fires.
    result = await hooks.handle_provider_request("provider:request", {})
    assert result.action == "inject_context", (
        f"Expected inject_context, got {result.action}"
    )
    injected = result.context_injection or ""
    # A signature line we wrote into mode-schema-reference.md
    assert "Amplifier Mode Schema Reference" in injected, (
        "mode-schema-reference content must be in the injected context"
    )

    # 3. Skill discoverability — the skill registry / config must include it.
    #    The exact registry shape is a Phase 2 decision; we use the same
    #    coordinator.config slot the agents use, which Phase 2 should have
    #    already plumbed.
    skills_in_play: Any = (
        coord.config.get("skills") or coord.config.get("tool-skills", {}).get("skills") or {}
    )
    assert "mode-design-discipline" in skills_in_play or any(
        "mode-design-discipline" in str(v) for v in (skills_in_play or {}).values()
    ), (
        "mode-design-discipline skill must be discoverable while active. "
        f"Saw: {skills_in_play!r}"
    )

    # ---- DEACTIVATE ----
    coord.session_state["active_mode"] = None
    await hooks.handle_mode_deactivated("mode:deactivated", {"mode": "mode-design"})

    # 1. Agent gone
    assert "mode-author" not in _agent_registry(coord), (
        "mode-author must be unmounted on deactivation"
    )

    # 2. Context gone — provider request returns continue, no injection
    result_after = await hooks.handle_provider_request("provider:request", {})
    if result_after.action == "inject_context":
        injected_after = result_after.context_injection or ""
        assert "Amplifier Mode Schema Reference" not in injected_after, (
            "Schema reference must not be injected once mode is inactive"
        )

    # 3. Skill gone
    skills_after: Any = (
        coord.config.get("skills") or coord.config.get("tool-skills", {}).get("skills") or {}
    )
    if skills_after:
        assert "mode-design-discipline" not in skills_after, (
            "mode-design-discipline must be unregistered on deactivation"
        )
```

**Step 2: Run, fail-then-pass**

Run:
```bash
pytest tests/test_overlay_integration.py::test_mode_design_end_to_end -v
```

If the skill registry shape doesn't match either of the two slots checked,
Phase 2 chose a different storage location. Update the assertion to match
the real location — but only the `skills_in_play`/`skills_after` lines, not
the test's overall structure.

**Expected:** PASS.

**Step 3: Commit**
```bash
git add modules/hooks-mode/tests/test_overlay_integration.py
git commit -m "test(mode-overlay): /mode-design end-to-end activation

Activate: agent reachable, schema reference injected, skill discoverable.
Deactivate: all three gone. The full vertical slice in one test.

Co-authored-by: Amplifier <amplifier@microsoft.com>"
```

---

## Task 15: Feature-complete verification

**Files:**
- None modified — this is a final verification pass.

**Step 1: Run the full integration-test suite**

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes/modules/hooks-mode
pytest tests/test_overlay_integration.py -v
```
**Expected:** 8 tests pass (smoke + S1 + S2 + S3 + S4 + advertised + rollback + end-to-end).

**Step 2: Run the full hooks-mode test suite to confirm zero regressions**

Run:
```bash
pytest tests/ -v
```
**Expected:** all tests pass. If any pre-existing test now fails, stop and
investigate — Phase 3 should not regress earlier tests.

**Step 3: Token-cost-when-inactive measurement**

The headline claim of this design is that a session that never activates
`/mode-design` pays **zero tokens** for the three contributions. Validate
with a synthetic measurement:

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes/modules/hooks-mode
python -c "
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import asyncio
from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks

BUNDLE_ROOT = Path('../..').resolve()
coord = MagicMock()
coord.session_state = {'active_mode': None, 'require_approval_tools': set()}
coord.config = {'agents': {}}
coord.hooks = MagicMock()
coord.hooks.emit = AsyncMock()
coord.get_capability = MagicMock(return_value=None)

discovery = ModeDiscovery(search_paths=[BUNDLE_ROOT / 'modes'])
hooks = ModeHooks(coord, discovery)

# Inactive session: provider request must NOT inject any of the three artifacts.
async def main():
    result = await hooks.handle_provider_request('provider:request', {})
    injected = result.context_injection or ''
    assert 'Amplifier Mode Schema Reference' not in injected, 'schema ref leaked into inactive session'
    assert 'mode-author' not in str(coord.config['agents']), 'mode-author leaked into inactive session'
    print('OK: zero contributions visible in inactive session')

asyncio.run(main())
"
```
**Expected:** `OK: zero contributions visible in inactive session`

**Step 4: Confirm `mode-design` is filtered from `mode(list)` for the LLM**

This was already covered by `test_advertised_false_filtering`. Double-check:

Run:
```bash
pytest tests/test_overlay_integration.py::test_advertised_false_filtering -v
```
**Expected:** PASS.

**Step 5: Confirm CLI `/modes` listing — expected behavior note**

The CLI's `/modes` slash command (in `amplifier-app-cli`) does not yet
filter on `advertised`. Per `modes/README.md` and the design's §10, the
`--all` flag for `/modes` is scheduled for v1.1. **For the v1 deliverable**,
`/modes` from the CLI may surface `mode-design` to humans by default; this
is intentional (humans benefit from discovery). Confirm the README captures
this correctly:

Run:
```bash
cd /home/bkrabach/dev/modes-updates/amplifier-bundle-modes
grep -n "v1.1" modes/README.md
```
**Expected:** at least one line referencing the `--all` deferral.

**Step 6: Final commit if any cleanup happened**

If steps 1–5 surfaced any minor doc or comment cleanup, commit it as a
single tail commit:

```bash
git status
# If clean: nothing to do.
# If dirty: review, then:
# git add ... && git commit -m "chore(mode-design): final cleanup after Phase 3 verification"
```

---

## Feature-Complete Checklist

When all 15 tasks are committed and the verification in Task 15 has passed,
the v1 vertical slice is shippable. Confirm:

- [ ] `/mode-design` activates and deactivates cleanly (covered by
      `test_mode_design_end_to_end`).
- [ ] `mode-author` agent is reachable via `delegate` while `/mode-design` is
      active and unreachable when inactive (covered by `test_S2_mode_only` and
      `test_mode_design_end_to_end`).
- [ ] `mode-schema-reference.md` content appears in injected context only
      while `/mode-design` is active (covered by `test_mode_design_end_to_end`).
- [ ] `mode-design-discipline` skill is discoverable via `load_skill` only
      while `/mode-design` is active (covered by
      `test_mode_design_end_to_end`).
- [ ] Token measurement on a session that never activates `/mode-design`:
      zero bytes from any of the three contributed artifacts (covered by
      Task 15 Step 3).
- [ ] All four overlap scenarios pass (S1–S4 — Tasks 8–11).
- [ ] Atomic rollback validated (Task 13).
- [ ] `mode-design` does NOT appear in `mode(list)` for the LLM (Task 12).
- [ ] `mode-design` listing behavior in CLI `/modes` documented in
      `modes/README.md` (Task 5; CLI `--all` flag deferred to v1.1).

After this phase, **the v1 feature is shippable.** Phase 4 (v1.1) adds
`contributes.tools`, `contributes.config`, and the CLI `--all` flag — those
are not gating the v1 release.

---

## Appendix: How to recover if a task fails irrecoverably

If a test reveals a real production-code bug (not a test wiring mistake):

1. **Stop.** Do not edit production code in this Phase 3 plan.
2. Open an issue describing the bug, with a minimal repro — the failing test
   itself is usually a good repro.
3. Mark the test with `pytest.skip(reason="blocked on issue #N")` and commit
   the skip with the issue number in the message.
4. Continue with the remaining tasks.
5. After the production fix lands (Phase 1 or 2 follow-up), unskip the test
   and verify it passes.

If a content file (mode/agent/skill/context) needs revision after a test
exposes a mistake:

1. Edit the content file directly.
2. Re-run the affected test.
3. Amend the original content commit with `git commit --amend` if the fix is
   small; otherwise a new follow-up commit is fine.

The plan's commit boundaries are not load-bearing — clean history is good,
but coherent tests are better.
