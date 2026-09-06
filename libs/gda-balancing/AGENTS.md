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

For Standard Schema 2.x architecture work, also read `docs/ARCHITECTURE.md`: it is the
human-readable macro architecture authority for topology, subsystem boundaries, cross-subsystem
invariants, and validation order. It does not replace the glossary, detailed bADRs, PRD acceptance
status, or Kernel/LDB machine authority.

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
  reference. bADR-0007…0011 preserve historical 1.x contracts; #868 retires their input
  implementation and the `model migrate` converter. Current source uses Model Source directly;
  bADR-0015 and bADR-0021 are the binding Standard Schema 2.x outcome and command-taxonomy
  contract. Read the parent CLI-contract ADRs as *reference input* only.
- **Engine- and game-agnostic core** — the toolkit names no game identity and imports no
  game or engine code (nor `gda`); agnosticism is enforced by packaging plus an isolation
  gate (landing with #502) at the hardened (recursive, AST-level) standard.
- **Standard Schema is the sole specification family** — inside 2.x, authority is scoped:
  the Schema-major Kernel Specification defines bundle interpretation and irreducible semantics;
  the Language Definition Bundle owns language content under that kernel; and Model Source
  Packages, Experiment Specifications, and Approval Records own their authored domains
  (bADR-0012/0022). Host implementations are conforming implementations, never authority. Games
  consume resolved Standard Schema output; no parallel game-config authority is adapted (PRD #501).
- **Own project, own release train** (ADR-0038) — this package is an independent uv project,
  not a workspace member: it locks separately, so every command run from the repo root needs
  `--project libs/gda-balancing` (see this package's README). Its PRs therefore use
  **truthful conventional-commit types** (`feat`/`fix`/…) and release under
  `gda-balancing-vX.Y.Z` tags — the non-releasing-title discipline that applied before #528
  is lifted **for this directory only**.
  - A PR that touches this directory **and anything outside it** is still attributed to the
    root `gda` package. The `Member releasing-PR scope guard` required check refuses such a
    PR when its title is releasing-typed — **split it** rather than downgrading the type,
    because a dependency change that warrants a release should not be recorded as a chore.
