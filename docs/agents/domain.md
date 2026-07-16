# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root, or
- **`CONTEXT-MAP.md`** at the repo root if it exists — it points at one context glossary per context (`CONTEXT.md` or a local equivalent). Read each one relevant to the topic.
- **`docs/adr/`** — read ADRs that touch the area you're about to work in. In multi-context repos, also check `src/<context>/docs/adr/` for context-scoped decisions.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The producer skill (`/grill-with-docs`) creates them lazily when terms or decisions actually get resolved.

## File structure

The repo root's own context is the `gda` domain:

```
/
├── CONTEXT-MAP.md
├── CONTEXT.md
├── docs/adr/
│   ├── 0000-architecture-design.md
│   └── ...
└── src/
```

This repo is **multi-context**: `CONTEXT-MAP.md` at the repo root is the single routing
authority for which domain contexts exist and where. A non-root domain's layout and
override rules live in that subtree's own `AGENTS.md` / `docs/agents/domain.md` — inside
such a subtree, follow the local convention instead of this file.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/grill-with-docs`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0000 (architecture design) — but worth reopening because…_
