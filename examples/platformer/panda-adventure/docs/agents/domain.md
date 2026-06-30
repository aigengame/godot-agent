# Domain Docs — Panda Adventure (local override)

How the engineering skills should consume **this subproject's** domain documentation. This
is the authoritative copy of the local convention; `../../AGENTS.md` carries the short pointer.

It **overrides** the repo-root domain-doc convention (`/CONTEXT.md` + `/docs/adr/`) for all
game-domain knowledge. The game's context is confined to this directory.

## Before exploring, read these

- **`GAME-CONTEXT.md`** at this subproject's root — the game's glossary / shared language.
- **`docs/gadr/`** — game decision records (gADR); read the ones touching the area you'll work in.
- **`docs/gdd/`** — the committed game design doc(s).

If any of these don't exist yet, **proceed silently**. Don't flag their absence; don't
suggest creating them upfront. They are created lazily when a term or decision actually gets
resolved.

## File structure

This is a single local context, scoped to this subdirectory:

```
examples/platformer/panda-adventure/
├── GAME-CONTEXT.md          # game glossary  (analogue of the repo-root CONTEXT.md)
└── docs/
    ├── gadr/                # game decision records (analogue of docs/adr/)
    │   ├── 0000-architecture-design.md
    │   └── ...
    └── gdd/                 # committed game design doc(s)
```

## Skill remap

The domain skills hardcode `CONTEXT.md` / `docs/adr/` as string literals — they have no way
to discover this layout on their own. When running one **inside this subproject**, restate
and apply this remap before acting:

| In the skill body | Use here |
|---|---|
| `CONTEXT.md` | `GAME-CONTEXT.md` |
| `docs/adr/` | `docs/gadr/` |
| `CONTEXT-MAP.md` | not applicable — single local context, ignore |

Applies to `grill-with-docs`, `improve-codebase-architecture`, and `reconcile`. `to-prd` and
`to-issues` defer abstractly to "the project's domain glossary" — point them at `GAME-CONTEXT.md`.

**Hard prohibition.** Game work must **never** read or write the parent root `CONTEXT.md` or
`docs/adr/`; those are the `gda` tool's domain. Game terms and decisions live only here.

## Use the glossary's vocabulary

When your output names a game concept (an issue title, a refactor proposal, a test name), use
the term as defined in `GAME-CONTEXT.md`. Don't drift to synonyms the glossary avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing
language the game doesn't use (reconsider) or there's a real gap (note it for `grill-with-docs`,
remapped to `GAME-CONTEXT.md`).

## Flag gADR conflicts

If your output contradicts an existing gADR, surface it explicitly rather than silently
overriding:

> _Contradicts gADR-0000 (architecture design) — but worth reopening because…_
