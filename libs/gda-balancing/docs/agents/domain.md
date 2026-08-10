# Domain Docs — gda-balancing (local override)

How the engineering skills should consume **this package's** domain documentation. This is
the authoritative copy of the local convention; `../../AGENTS.md` carries the short pointer.

It **overrides** the repo-root domain-doc convention (`/CONTEXT.md` + `/docs/adr/`) for all
balancing-domain knowledge. The toolkit's context is confined to this directory.

## Before exploring, read these

- **`BALANCING-CONTEXT.md`** at this package's root — the toolkit's glossary / shared language.
- **`docs/ARCHITECTURE.md`** — the Standard Schema 2.0 macro architecture, subsystem boundaries,
  cross-subsystem invariants, and validation order; read it for any 2.x architecture work.
- **`docs/badr/`** — balancing decision records (bADR); read the ones touching the area
  you'll work in.

If any of these don't exist yet, **proceed silently**. Don't flag their absence; don't
suggest creating them upfront. They are created lazily when a term or decision actually gets
resolved.

## File structure

This is a single local context, scoped to this subdirectory:

```
libs/gda-balancing/
├── BALANCING-CONTEXT.md     # toolkit glossary  (analogue of the repo-root CONTEXT.md)
└── docs/
    ├── ARCHITECTURE.md       # Standard Schema 2.0 macro architecture authority
    └── badr/                 # balancing decision records (analogue of docs/adr/)
```

`ARCHITECTURE.md` consolidates accepted decisions but does not replace `BALANCING-CONTEXT.md`,
individual bADRs, PRD acceptance status, or the future Kernel Specification/LDB machine authority.
If it and an accepted bADR appear to conflict, surface and reconcile the conflict rather than
choosing one silently.

## Skill remap

The domain skills hardcode `CONTEXT.md` / `docs/adr/` as string literals — they have no way
to discover this layout on their own. When running one **inside this package**, restate and
apply this remap before acting:

| In the skill body | Use here |
|---|---|
| `CONTEXT.md` | `BALANCING-CONTEXT.md` |
| `docs/adr/` | `docs/badr/` |
| `CONTEXT-MAP.md` | not applicable — single local context, ignore |

Applies to `grill-with-docs`, `improve-codebase-architecture`, and `reconcile`. `to-prd` and
`to-issues` defer abstractly to "the project's domain glossary" — point them at
`BALANCING-CONTEXT.md`.

**Isolation boundary.** Never **write** toolkit terms or decisions into the parent root
`CONTEXT.md` or `docs/adr/`; balancing-domain language and decisions live only here. You
**may read** the parent `gda` docs when the work concerns CLI-interface-style alignment or
family conventions — just don't treat them as this toolkit's domain authority.

## Use the glossary's vocabulary

When your output names a toolkit concept (an issue title, a refactor proposal, a test name),
use the term as defined in `BALANCING-CONTEXT.md`. Don't drift to synonyms the glossary avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing
language the toolkit doesn't use (reconsider) or there's a real gap (note it for
`grill-with-docs`, remapped to `BALANCING-CONTEXT.md`).

## Flag bADR conflicts

If your output or `ARCHITECTURE.md` contradicts an existing bADR, surface it explicitly rather than
silently overriding:

> _Contradicts bADR-0000 (…) — but worth reopening because…_
