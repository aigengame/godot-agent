---
status: accepted
---

# Structured params input: a uniform `--params-json` channel, the params model as the single source

> **Amendment (2026-08-19, #669):** the emitted contract now DOES carry CLI-binding
> metadata — an `argv` list alongside the schema halves, naming each parameter's
> positional slot or option spelling (the
> [ADR-0004 amendment](0004-schema-flag-self-description.md) of 2026-08-18). Two
> sentences below are superseded by it: the framing that the dump "deliberately does
> not encode CLI binding", and the rejected option's claim that encoding it would
> "reopen ADR-0012's contract".
>
> **What this ADR decided remains in force, unchanged.** gda-mcp still forwards an
> MCP tool's input object **verbatim** through `--params-json`, reconstructs no argv,
> and ignores `argv` entirely — so the rejected option's real cost, pushing fragile
> typed-argv encoding (booleans, arrays, nested objects, defaults) into gda-mcp,
> never materializes. The binding metadata exists for a DIFFERENT consumer: an agent
> driving the CLI directly, which had no way to learn a required field's spelling
> without a `--help` round trip (dogfooding GDA-DF-003). Two audiences, two channels,
> one params model behind both.
>
> The distinction the rejection rested on also holds: argv is still not mechanically
> recoverable from the `input` schema ALONE, which is exactly why the binding is
> published as a separate, derived projection rather than by enriching the schema —
> `input` and `output` stay byte-identical, so ADR-0012's mapping is untouched.

gda commands take their params as CLI argv — a mix of positional `Argument`s and
`--kebab` `Option`s. [gda-mcp](../../CONTEXT.md) (ADR-0011/0012) must forward an MCP
tool's input object to gda over gda's **public CLI ABI**. ADR-0012's aggregate
schema dump describes each command's input as a JSON Schema derived from its
Pydantic model, but that schema deliberately does **not** encode CLI binding
(which field is positional vs an option, the flag spelling). This ADR fixes how a
caller supplies a whole params object as structured input, so gda-mcp can pass it
through verbatim rather than reconstruct argv.

## Decision

- **A uniform structured params-input channel: `gda <group> <command> --params-json <json | ->`.**
  The value is a single JSON object of the command's params; `-` reads it from
  **stdin**. gda deserializes it into the command's existing Pydantic input model
  (`model_validate_json`). Command selection stays in argv (Typer routing is
  unchanged); only the params *source* changes.

- **The params (input) model is the single source of truth for the input side** —
  both the emitted `input` schema (`--schema` / the `gda schema` dump, via
  `model_json_schema`) and structured input parsing (`model_validate_json`). The
  MCP-facing input schema and the accepted input format are therefore the *same
  model* — aligned by construction, never hand-maintained twice. This extends
  ADR-0004's model-driven self-description from the *emit* direction to the
  *input-supply* direction. **ADR-0004's three-channel separation is preserved**: a
  command's success `--json` result stays owned by its own `output` model and the
  failure envelope by `error`; `--params-json` adds an *input* channel and does not
  touch `output` or `error`. (`gda schema` is the aggregate-schema meta command
  shipped in #192 — ADR-0012 deferred its surface form to the PRD, now resolved as
  `gda schema`; this ADR references that decision, it does not re-make it.)

- **Normalization lives in the model, not the CLI body.** Any normalization or
  derivation a command currently performs in its CLI function (e.g. path
  normalization, derived defaults like scene-create's root name) moves into the
  params model (field/model validators), so the argv path and the `--params-json`
  path produce **identical** params. The CLI function becomes a thin argv→model
  adapter.

- **`--params-json` is mutually exclusive with individual positional/option args**;
  supplying both is reported as gda's structured `GdaError` envelope on a non-zero
  exit (per ADR-0011 / ADR-0002 — a public CLI failure, never a bare traceback or
  ad-hoc text). The exact stable `code` / `category` for this usage failure is
  settled by the implementation (#199) against ADR-0002's `GdaError.code` registry;
  this ADR does **not** mint a new code. A bare `--schema` still wins (it is
  emit-only and ignores params). `--json` (a *result* projection) composes freely
  with `--params-json` (an *input* source) — they are orthogonal directions. (These
  compositional rules — exclusivity, `--schema` precedence, `--json` composition —
  are ADR-0015 refinements beyond #198's sketch, recorded here as the deliberate
  input ABI.)

- **stdin for large payloads.** `--params-json -` reads the object from stdin so
  large fields (e.g. `script create` / `shader create` `content`) avoid OS argv
  length limits and never leak into process listings.

- **gda-mcp forwards verbatim.** gda-mcp maps an MCP tool's input object straight
  onto `--params-json` (over the subprocess's stdin), so it performs no argv
  reconstruction and carries no per-command binding knowledge — it stays a pure
  schema→tool + passthrough transform (ADR-0011/0012).

## Considered options

- **A uniform `--params-json` input channel, model as single source (chosen).**
  Verbatim passthrough for gda-mcp, one source of truth for emit + parse, reuses
  Typer routing, and the input format tracks the model with zero drift.

- **gda-mcp reconstructs argv from the dump's `input` schema (rejected).** The dump
  cannot — and per ADR-0012 should not — encode CLI binding. gda has positional
  `Argument`s *and* options, and a required field may be either (`scene create`
  `path` is positional; `--root-type` is a required option), while Typer positionals
  have no `--name` form. So argv is not mechanically recoverable from the schema.
  Enriching the schema with binding metadata would reopen ADR-0012's contract,
  pollute an otherwise clean JSON Schema, and push fragile typed-argv encoding
  (booleans, arrays, nested objects, defaults) into gda-mcp.

- **A top-level JSON dispatcher `gda --parse-from-json {command, params}` (rejected).**
  Embeds the command name in the JSON and makes gda re-implement command routing
  from a string — duplicating Typer's routing, adding a failure surface, and forcing
  gda-mcp to build a `{command, params}` wrapper. Keeping the command in argv
  (the chosen form) reuses Typer and changes only the params source.

- **Make every param a `--kebab` option so keyword mapping works (rejected).** Would
  let gda-mcp build argv by key, but degrades the human CLI (no positional
  `gda scene create foo.tscn`) and still leaves gda-mcp owning typed-argv encoding.
  The JSON channel serves the agent path without disturbing the human-facing argv
  shape.

## Relationship to other decisions

- **ADR-0004 (`--schema` self-description) — orthogonal axis.** ADR-0004 governs what
  gda *emits* (its input/output/error contract) and reserved *caller-supplied output
  schemas* for future open-ended ops. This ADR governs how a caller *supplies input
  data*. `--schema` is unchanged, and `gda schema` (the dump) remains the necessary
  *description* channel — complementary to `--params-json` (the *dispatch* channel).
  On the **input** side, the emitted `input` schema and `--params-json` parsing both
  derive from the one params model; the `output` and `error` halves are unchanged and
  owned by their own models. This ADR touches only the input axis.

- **ADR-0011 / ADR-0012 (gda-mcp) — prerequisite.** This is the gda-side capability
  that lets gda-mcp forward tool inputs verbatim and stay a pure transform. It is
  required before gda-mcp dispatches any **parametrized** command; a no-arg command
  (e.g. `info`, the gda-mcp tracer bullet) does not need it.

- **ADR-0002 (structured output / `params_json`) — same idea, one layer up.**
  `--params-json` is the CLI-boundary analogue of the existing gda→engine
  `params_json` convention: params as one JSON object, applied at the caller
  boundary instead of the engine boundary.

## Consequences

- Every command gains `--params-json` at near-zero per-command cost: the flag is
  handled centrally (like `--schema`) in the shared headless command machinery,
  deserializing into the command's already-declared input model.
- Moving normalization into models is a one-time refactor for each command that
  carries CLI-body logic; afterwards both input paths are guaranteed identical and
  the model is the sole home of normalization.
- gda-mcp's dispatch becomes trivial and binding-free; new gda commands and new
  params reach the MCP surface with no gda-mcp changes (zero-touch sync, ADR-0012).
- A new public input ABI exists, covered by its own tests (round-trip parity,
  error / mutual-exclusivity) alongside the standing `--schema` invariant — the
  emitted `input` schema is exactly the model that `--params-json` accepts.

**No new CONTEXT.md glossary term is introduced.** `--params-json` is a *mechanism*
/ flag, recorded in an ADR exactly as `--schema` is (ADR-0004) rather than promoted
to the CONTEXT.md glossary (which holds shared domain nouns — Components,
Operations, Command surface, …). Phrases like "structured params input" and "input
ABI" in this ADR are descriptive prose, not coined canonical terms; the canonical
reference is the flag `--params-json` itself. (If the project later decides this
warrants a glossary noun, that is a separate CONTEXT.md change.)

Implemented in #199; recorded here (#198) as the authoritative decision.
