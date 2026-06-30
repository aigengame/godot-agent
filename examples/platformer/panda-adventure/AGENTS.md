This directory is **Panda Adventure** — a 2D-platformer game demo, built with `gda`
(see the `/gda` Skill) by driving the Godot Engine. It is a subproject of the parent
`godot-agent` repo, but a **different domain**: its shared language is about the game
(pandas, gravity guns, enemy waves), not about `gda`'s CLI, daemon, or headless runners.

## Inherited from the repo root

Align with the repo-root `AGENTS.md` for everything **except domain docs**:

- `RULES.md` — communication & collaboration conventions.
- Issue tracker — game issues go to the same `aigengame/godot-agent` tracker, with titles
  prefixed **`[Panda Adventure]`** to distinguish them from `gda`-tool issues. (The prefix is for
  **game-self** issues only; `gda`-feedback issues are filed **unprefixed** — see *gda feedback*
  below.) See the repo-root `../../../docs/agents/issue-tracker.md` (these docs are inherited, not
  duplicated here).
- Triage labels. See the repo-root `../../../docs/agents/triage-labels.md`.

## Agent skills

### Domain docs (local override)

**This section supersedes the repo-root "Domain docs" convention** (`Single-context: one
CONTEXT.md + docs/adr/ at the repo root`) for all **game-domain** knowledge. The game's
domain context is confined to this directory and must **not** pollute the parent's docs.

Local layout (analogue of the parent's):

| Parent (gda domain) | Here (game domain) | Holds |
|---|---|---|
| `CONTEXT.md` | `GAME-CONTEXT.md` | the game's shared language / glossary |
| `docs/adr/NNNN-*.md` | `docs/gadr/NNNN-*.md` | game decision records (gADR), same numbering |
| — | `docs/gdd/` | committed game design doc(s) |

**Skill remap.** The domain skills hardcode `CONTEXT.md` / `docs/adr/` as literals. When you
run one **inside this subproject**, restate and apply this remap before acting:

- any skill's `CONTEXT.md` → `GAME-CONTEXT.md`
- any skill's `docs/adr/` → `docs/gadr/`
- `CONTEXT-MAP.md` → not applicable (single local context — ignore)

Applies to `grill-with-docs`, `improve-codebase-architecture`, and `reconcile`. `to-prd` /
`to-issues` already defer abstractly to "the project's domain glossary" — point them here.

**Isolation boundary.** Never **write** game terms or decisions into the parent root `CONTEXT.md`
or `docs/adr/` — game-domain language and decisions live only under this directory. You **may
read** the parent `gda` docs when the work concerns the `gda` tool itself (its CLI, schema, daemon,
or `logger` protocol); just don't treat them as the game's domain authority.

See `./docs/agents/domain.md` for the authoritative detail.

## Development conventions

- **Architecture** — layered (Resource / Controller / CanvasItem) and data-driven, with JSON as
  the single authoritative config source converted to Godot `Resource`. See `docs/gadr/0000-architecture-design.md`.
- **Logger-based feedback development** — game code logs at module (and key function) entry/exit so
  the agent can observe runtime behavior in a closed loop — enough to trace behavior, not noisy
  per-call spam. Log output conforms to the `gda logger tail` protocol so the agent can parse it.

## gda feedback (dogfooding)

Building this demo is also a way to **validate and improve `gda`**: driving the tool surfaces real
gaps. Whenever you hit one while developing the game, **proactively file it as a separate issue** on
the `aigengame/godot-agent` tracker so the demo doubles as a `gda` quality signal. Categories:

- **Quality defect** — a `gda` capability that is claimed but unusable or behaves incorrectly.
- **Feature improvement** — a `gda` capability that works but is incomplete or awkward.
- **Performance** — a `gda` capability that works but is slow/janky.
- **New-feature need** — a capability `gda` lacks that would meaningfully speed up development.

These are **`gda`-tool issues, not game issues** — file them as regular `gda` issues **without** the
`[Panda Adventure]` prefix, so they land in the tool's own issue view rather than the game's.
