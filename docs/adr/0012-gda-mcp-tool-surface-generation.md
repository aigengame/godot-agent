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
> The enum has since grown two self-description-only values on the ADR-0031
> migration pattern: `script_run` (ADR-0031) and `import` (#668, the native
> project-wide `--import` pass behind `resource import`) — gda-mcp's mapping
> remains unchanged either way.

> **Outcome (2026-06-22, #233 / PR #245):** each manifest entry gained an
> additive `constraints` field (the command's `LiveStackConstraints` — platform
> set + minimum Godot version, ADR-0021; `null` for non-live-stack commands), so
> the entry above is now `{name, description, input, output, error, kind,
> constraints}`. gda-mcp's mapping is unchanged — it ignores `kind` /
> `constraints` — so the addition is backward compatible. On the aggregate entry
> the `constraints` key is always present, its value nullable.

> **Outcome (2026-08-18, #669):** each manifest entry gained an additive `argv`
> field (the command's `ArgvBinding` list — how each parameter is written on a
> command line, ADR-0004's amendment of the same date), so the entry above is now
> `{name, description, input, output, error, kind, constraints, argv}`. gda-mcp's
> mapping is unchanged — it ignores `kind` / `constraints` / `argv` — and **the
> `argv` addition leaves both mapped halves byte-identical**, so no registered
> tool's wire schema changes because of it. (One tool's `input_schema` did change
> in the same PR for an unrelated reason: `gda input sequence`'s own params model
> became a per-kind discriminated union. That is a model change, not a
> manifest-shape one, and it is the only entry whose `input` differs.)
> The bindings come from the same live-tree walk this ADR established: the walker is
> already standing in the Typer tree, so it reads each leaf's Click parameters
> there rather than consulting anything else. On the aggregate entry the `argv` key
> is always present, its list empty for a command with no operation parameters.

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

> **Outcome (2026-07-31, ADR-0039/#601):** the transform survived the MCP SDK v2
> migration unchanged — still one startup dump, one generic dispatcher, zero
> per-command knowledge. Only the SDK-side spelling of the mirrored fields
> changed (`inputSchema`/`outputSchema` → `input_schema`/`output_schema` on the
> v2 wire models); this ADR's prose keeps the v1 names as its point-in-time
> record.

> **Outcome (2026-09-01, #687):** the aggregate's per-entry repetition of the shared
> `error` schema is now the dominant term in the manifest's size. ADR-0004's #687
> amendment added typed `evidence` to the one shared failure envelope, and because
> each of the 76 entries carries its own copy of that envelope, one shared change
> moved the dump from 675,342 to 979,618 bytes (+45%). Nothing about the transform
> changed — gda-mcp still consumes the dump with zero per-command knowledge, and the
> `error` half is still ONE schema, byte-identical across all 76 entries.
>
> That identity is what makes the obvious remedy mechanical: hoisting the shared
> envelope to a manifest-level `$defs` and referencing it per entry would land the
> document BELOW its pre-#687 size, because the repetition predates that amendment.
> It changes the entry shape gda-mcp reads, so it is this ADR's contract to change,
> not #687's, and it is not urgent — startup cost is one dump and one parse.
> Recorded here so the next amendment to the shared envelope is priced against the
> aggregate rather than against one entry. Recorded as a follow-up; not yet
> tracked by an issue.
