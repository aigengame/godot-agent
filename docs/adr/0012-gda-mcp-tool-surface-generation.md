---
status: accepted
---

# gda-mcp tool-surface generation: runtime introspection of a whole-surface schema dump, no hand-curated profiles

> **Outcome (2026-06-22, #230 / PR #232):** each manifest entry gained an
> additive `kind` field (the command's static `ExecutionKind` — `headless` /
> `export` / `live`, ADR-0017), so `{name, description, input, output, error}`
> below is now `{name, description, input, output, error, kind}`. gda-mcp's
> mechanical mapping is unchanged — it still derives `inputSchema` ← `input` and
> `outputSchema` ← `output` and simply ignores `kind` — so the addition is
> backward compatible. On the aggregate entry `kind` is required and
> enum-constrained, so a consumer of `gda schema --schema` can rely on it.

ADR-0011 fixes [gda-mcp](../../CONTEXT.md) as a subprocess adapter that consumes
`gda`'s public ABI. ADR-0004 / ADR-0005 make each command self-describing
(`--schema` → `{input, output, error}`) and give a deterministic CLI→MCP name map
(`gda <group> <command>` → `<group>_<command>`). This ADR fixes *how* gda-mcp turns
that self-description into its registered MCP tool surface, and how (not) it manages
the surface's size.

## Decision

**Generate the tool surface at runtime by introspection, not at build time by
codegen.** On startup gda-mcp shells out **once** to a new `gda` aggregate-schema
meta command that emits, in a single process, the whole surface as one JSON
document — every command's `{name, description, input, output, error}` — and
registers one MCP tool per entry (`description` ← the command's help text,
`inputSchema` ← `input` carrying per-field descriptions from the Pydantic `Field`s,
`outputSchema` ← `output`, failures via the `isError` channel per ADR-0011). gda-mcp
is therefore, at any moment, a faithful
mirror of the installed `gda`: a new command appears as a new tool the next time the
server starts — no codegen step, no release-pipeline coupling, no drift.

- The aggregate dump is the whole-surface generalisation of ADR-0004's per-command
  `--schema`; it belongs to `gda` (the self-describing layer), not to gda-mcp.
  Because it describes `gda` itself rather than a Godot domain object, it is a **meta
  command** in ADR-0005 terms — top-level and ungrouped, a sibling of `gda info`
  (exact surface form — a `gda schema`-style subcommand vs a top-level `--schema-all`
  flag — is a taxonomy detail left to the PRD). gda-mcp **never parses `gda --help`
  prose** to enumerate the surface.

**The dump is the dispatchable-operation surface (refinement, #193).** It carries
one entry per command that accepts the `--params-json` structured-input channel
(ADR-0015) — i.e. has a backing operation gda-mcp can actually invoke. A
*non-dispatchable* meta command (no backing operation, hence no `--params-json`)
is excluded **at the source**, inside `gda`'s own surface walk, keyed on the one
fact the command's registration already carries (its backing operation, `None`
for such a command). `gda schema` is the only such command today: a pure
self-describer, excluded from the surface it describes (re-listing it would be
circular), while it still self-describes under its own `--schema`. This keeps the
sole authority for "is this an MCP-dispatchable operation" in `gda`, so gda-mcp
stays a pure transform that registers exactly what the dump reports and never
advertises a tool it cannot fulfil — it holds no exclusion list of its own. This
exclusion is a **soundness** property (gda-mcp can only serve what it can
dispatch), distinct from the optional, user-facing group/tool *filtering* below
(a surface-*size* control).

**Expose the full surface; do not ship hand-curated profiles.** gda-mcp registers
every tool the dump reports. It explicitly does **not** provide named tiers (full /
lite / minimal). If a tool-count-limited client ever needs a smaller surface, the
sanctioned mechanism is **config-driven group/tool filtering** — an allowlist /
denylist keyed on the ADR-0005 groups the surface already has, applied to the dump
before registration, defaulting to "all". The user decides what to drop; gda-mcp
does not decide for them.

## Considered options

- **Build-time codegen of a static tool manifest (rejected).** Fast startup and an
  inspectable artifact, but the manifest lags the `gda` actually installed on the
  user's machine (drift), needs a release-pipeline step, and contradicts ADR-0004's
  zero-touch-sync goal.
- **Per-command `--schema` fan-out at startup (rejected as the enumeration path).**
  Correct, but spawns ~one `gda` process per command (dozens) on every startup; the
  aggregate dump gets the same data in one process.
- **Hand-curated named profiles à la godot-mcp-pro (rejected).** full / lite /
  minimal require a maintained central membership list — a centralised-registry
  append hotspot — and break zero-touch: every new command forces a "which tier?"
  decision, reintroducing the manual sync ADR-0004 / ADR-0011 exist to remove.
- **Runtime introspection of a whole-surface dump + optional config filtering
  (chosen).**

## Consequences

- `gda` gains one new meta command (the aggregate schema dump). It is small, belongs
  to the self-describing layer, and is independently useful as the machine-readable
  manifest of the whole surface. It is a **prerequisite of the first gda-mcp slice**:
  build the dump in `gda` first, then have gda-mcp consume it.
- gda-mcp startup cost is one `gda` subprocess plus schema parsing — negligible, and
  independent of command count.
- The first gda-mcp delivery exposes all ~42 tools. Whether that count strains any
  client is left to be measured; if it does, group/tool filtering — not named tiers —
  is the agreed response, and it composes cleanly with runtime introspection (filter
  the dump, then register).
- gda-mcp carries no per-command knowledge: it is a pure schema→tool transformation,
  so it stays correct as the `gda` surface grows without edits to gda-mcp.
