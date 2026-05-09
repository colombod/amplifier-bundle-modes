# Built-in Modes

This bundle ships the following modes out of the box. Any mode can be overridden by placing a file with the same `name:` value in a higher-precedence location:

- **Project-level override:** `.amplifier/modes/` in the project root
- **User-level override:** `~/.amplifier/modes/` in your home directory

A file at either location with a matching `name:` field shadows the bundle version for that session.

---

## Mode Listing

| Mode | Shortcut | Description | Advertised |
|------|----------|-------------|------------|
| `plan` | `/plan` | Analyze, strategize, and organize — no implementation | Yes |
| `careful` | `/careful` | Full capability with confirmation for destructive actions | Yes |
| `explore` | `/explore` | Zero-footprint codebase exploration — read-only | Yes |
| `mode-design` | `/mode-design` | Design a new Amplifier mode through structured authoring | **no** — hidden from LLM listings; activate via slash command |

---

## mode-design — note

`/mode-design` carries `advertised: false` in its frontmatter. This means:

- The LLM does **not** see it in the `mode(list)` tool output, so it will not spontaneously suggest or list it.
- It does **not** appear in `/modes` without the `--all` flag (CLI v1.1; until that flag lands `/modes` may list all modes by default — see the CLI section below).

### What it contributes on activation

Activating `/mode-design` materializes three artifacts into the session context:

| Artifact | Type | Purpose |
|----------|------|---------|
| `mode-author` | Agent | Drafts complete mode `.md` files from a brief intent statement |
| `mode-design-discipline` | Skill | Anti-bloat patterns, naming hygiene, narration rules, and overlap scenarios |
| `mode-schema-reference.md` | Context | Full mode YAML schema injected into every turn |

All three materialize on activation and **disappear on deactivation**. For sessions that never activate `/mode-design`, none of those three artifacts contribute any tokens to the context window.

---

## CLI /modes listing of unadvertised modes (status)

The Amplifier CLI's `/modes` slash command currently does **not** filter on `advertised`. That flag affects only the `mode(list)` tool operation — the programmatic listing visible to the LLM.

The `--all` flag for `/modes` is scheduled for **v1.1**. Until it lands, `/modes` may surface unadvertised modes to humans by default.

This is intentional: **humans benefit from discovery; the LLM does not.** A human exploring available modes should be able to see everything. The LLM, by contrast, should only see modes that are meant to be spontaneously suggested or listed — modes with `advertised: false` are opt-in by slash command and should not appear in LLM-facing listings.

---

## Authoring a new mode

The fastest way to author a new mode is to activate `/mode-design`:

```
/mode-design
```

This mode contributes the `mode-author` agent, the `mode-design-discipline` skill, and the full schema reference. Together they guide you through intent statement → tool policy → body draft in a single session.

For a quickstart without activating the mode, see the **Creating Custom Modes** section in the bundle `README.md` (one level up from this directory).

The full schema reference is at `context/mode-schema-reference.md` — reachable directly as `@modes:context/mode-schema-reference.md` or by activating `/mode-design`, which injects it automatically.
