---
mode:
  name: mode-design
  description: Design a new Amplifier mode through structured authoring
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

This mode contributes substantial capability invisible to most sessions — a dedicated agent, a discipline skill, and the full mode YAML schema reference. Read the **Capabilities** listing below before proceeding so you know what tools are already in context.

## Capabilities while this mode is active

- **Agent `mode-author`** — Drafts a complete mode `.md` file from your brief intent and tool policy. Invoke via `delegate(agent="mode-author", instruction="...")`. The agent receives the mode-schema-reference from context automatically.

- **Skill `mode-design-discipline`** — Authoring discipline: anti-bloat patterns, naming hygiene, narration rules, and the four overlap scenarios. Load at the start of every design session via `load_skill("mode-design-discipline")`.

- **Reference `mode-schema-reference.md`** — The full mode YAML schema, already injected into context by this mode. Covers every supported field, allowed values, and validation rules.

## Workflow

### Phase 1 — Intent

Narrate the mode's purpose in 1–2 sentences. Answer three questions:
- Who triggers this mode? (What kind of work or situation?)
- What changes on activation? (What becomes safe, confirmed, or blocked?)
- What is the exit condition? (How does the user leave the mode?)

A clear intent statement prevents scope creep and over-speccing during the body draft.

### Phase 2 — Tool policy and contributions

Walk through the tool policy with the user:

1. **`default_action`** — Start with `block` unless the mode is designed to extend rather than restrict. `allow` makes sense for modes that relax constraints on top of a restricted baseline.
2. **`safe` / `confirm` / `block`** — List explicitly. `confirm` is appropriate for file writes and commands that are useful but irreversible. `block` reserves absolute prohibitions.
3. **Contributions** — Decide whether `contributes` is needed:
   - Add `contributes.agents` when the mode's workflow requires a dedicated delegate target.
   - Add `contributes.context` when reference material should be in context at all times.
   - Add `contributes.skills` when authoring discipline should be auto-discoverable.
4. **Referential-integrity cross-check** — If `contributes.agents` is present, confirm `delegate` is in `tools.safe`. If `contributes.skills` is present, confirm `load_skill` is in `tools.safe`. The parser will warn if either invariant is violated, but it is better to catch it here.

### Phase 3 — Body draft

Delegate to `mode-author` with a fully specified instruction. Use this template:

```
delegate(
  agent="mode-author",
  instruction="""
  Draft modes/<name>.md with:
  - name: <name>
  - intent: <1-2 sentence purpose statement>
  - tool policy: safe=[...], confirm=[...], block=[...]
  - default_action: block | allow
  - advertised: true | false
  - contributions: <agents/context/skills or none>
  - write target: modes/<name>.md

  Body must include: purpose header, capabilities listing (if contributes),
  workflow section, and /mode off exit line.
  """
)
```

Review the draft. Refine with follow-up delegates or direct edits (via `write_file` or `edit_file`, which will prompt for confirmation in this mode).

## Discipline

Load the discipline skill at the start of every session:

```
load_skill("mode-design-discipline")
```

The skill covers:
- **Anti-bloat patterns** — Modes should do one thing. Resist adding every safe tool "just in case."
- **Naming hygiene** — Names must match `^[a-z][a-z0-9_-]*$`. Shortcuts default to the name.
- **Narration rules** — Body prose narrates contributions and capabilities; YAML carries policy. Do not duplicate policy in prose.
- **`advertised: false` modes** — This field hides the mode from LLM-facing listings. Use it for modes that are loaded programmatically or via bundle contributions, where a surprise `/mode <name>` listing would confuse the LLM. Modes with `contributes` blocks are almost always `advertised: false`.

Encourage an S2 integration test after writing: activate the new mode (`/mode <name>`), verify the tool policy is in effect, and exercise any contributed agents or skills before shipping.

## Exit

Use `/mode off` when the new mode is written, parses cleanly, and is agreed to ship.
