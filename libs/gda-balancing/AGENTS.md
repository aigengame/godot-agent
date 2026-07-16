This directory is **gda-balancing** — a standalone, engine- and game-agnostic numeric
design & balancing toolkit: Standard Schema numeric design (attributes, builds, growth,
economy, encounters), simulation-backed balance validation and tuning, structured JSON
output. It is a **sibling product** of `gda` in the same family — it neither depends on
nor extends `gda`; the `gda-` prefix is the product-family brand, not component
ownership. Requirements record: PRD #501; milestones #8 (Phase 1) / #9 (Phase 2).

## Inherited from the repo root

Align with the repo-root `AGENTS.md` for everything **except domain docs**:

- `RULES.md` — communication & collaboration conventions.
- Issue tracker — toolkit issues go to the same `aigengame/godot-agent` tracker, with titles
  prefixed **`[gda-balancing]`** to distinguish them from `gda`-tool issues (unprefixed).
  See `../../docs/agents/issue-tracker.md` (inherited, not duplicated here).
- Triage labels. See `../../docs/agents/triage-labels.md`.

## Agent skills

### Domain docs (local override)

**This section is the toolkit domain's local convention** — the repo root routes domain
contexts via `CONTEXT-MAP.md` and delegates each non-root domain's layout and override
rules to its own `AGENTS.md`, i.e. here. The toolkit's domain context is confined to this
directory and must **not** pollute the parent's docs.

Local layout (analogue of the parent's):

| Parent (gda domain) | Here (balancing domain) | Holds |
|---|---|---|
| `CONTEXT.md` | `BALANCING-CONTEXT.md` | the toolkit's shared language / glossary |
| `docs/adr/NNNN-*.md` | `docs/badr/NNNN-*.md` | balancing decision records (bADR), same numbering |

**Skill remap.** The domain skills hardcode `CONTEXT.md` / `docs/adr/` as literals. When you
run one **inside this package**, restate and apply this remap before acting:

- any skill's `CONTEXT.md` → `BALANCING-CONTEXT.md`
- any skill's `docs/adr/` → `docs/badr/`
- `CONTEXT-MAP.md` → not applicable (single local context — ignore)

Applies to `grill-with-docs`, `improve-codebase-architecture`, and `reconcile`. `to-prd` /
`to-issues` already defer abstractly to "the project's domain glossary" — point them here.

**Isolation boundary.** Never **write** toolkit terms or decisions into the parent root
`CONTEXT.md` or `docs/adr/` — balancing-domain language and decisions live only under this
directory. You **may read** the parent `gda` docs when the work concerns
CLI-interface-style alignment (see below) or family conventions — just don't treat them as
this toolkit's domain authority.

This section is the loaded summary; `./docs/agents/domain.md` is the authoritative
detail — on any divergence, it wins.

## Development conventions

- **CLI interface style follows `gda`** (adjudicated 2026-07-15, recorded on PRD #501):
  the family's interface conventions and `gda`'s accumulated CLI spec experience are the
  reference. The binding contract (command taxonomy, result/error envelopes, exit-code
  semantics, self-description) will be designed under issue #518 and recorded as bADRs —
  once landed, those bADRs are the single authority; read the parent CLI-contract ADRs as
  *reference input* only.
- **Engine- and game-agnostic core** — the toolkit names no game identity and imports no
  game or engine code (nor `gda`); agnosticism is enforced by packaging plus an isolation
  gate (landing with #502) at the hardened (recursive, AST-level) standard.
- **Schema is the single authority** — the Standard Schema is the sole spec and authority
  source for numeric design; games consume the toolkit's Standard Schema output (PRD #501).
