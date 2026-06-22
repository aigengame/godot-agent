---
status: accepted
---

# `--schema` is self-description, not a caller-supplied contract

> **Outcome (2026-06-22, #230 / PR #232):** the per-command `--schema` object
> gained a fourth, additive key — `kind`, the command's static `ExecutionKind`
> (`headless` / `export` / `live`, ADR-0017) — alongside `input` / `output` /
> `error`. Like the `{input, output}` → `{input, output, error}` move described
> below, this is a strict superset: `gda-mcp` still maps only `input` / `output`,
> so it stays backward compatible (ADR-0012). `kind` is `null` only for a
> self-description emitted without a backing command (e.g. `gda schema --schema`);
> in the aggregate manifest (ADR-0012) every dispatchable entry's `kind` is
> required and enum-constrained.

ADR-0000 lists `--schema` as a core capability without defining it. We fix its
semantics here, and deliberately scope out an overloaded interpretation.

## Decision

- **`gda <command> --schema` emits the command's own machine-readable contract**: a
  JSON object with three keys — an `input` JSON Schema (the command's
  arguments/params), an `output` JSON Schema (the shape of its **success** `--json`
  result), and an `error` JSON Schema (the **uniform** failure envelope, #43). The
  contract is owned by `gda`; the flag only *emits*, it never *accepts*, a schema.

- **`output` describes only the success result; `error` describes the failure
  envelope** (#43). `output` is the command's own success result model, exactly as
  before — it is *not* turned into a success/failure union. `error` is the shared
  `GdaErrorEnvelope` schema, **identical for every command**, that `gda` emits on a
  non-zero exit. Keeping the two halves separate mirrors how the result reaches the
  caller: a successful `--json` result on exit 0, a structured error envelope on a
  non-zero exit. The change is a strict superset of the old `{input, output}`
  contract — `output` is untouched — so it is backward compatible.

- **Schemas are model-driven.** Each command's input and output are defined as typed
  models (Pydantic/msgspec on the Python 3.13 stack). The same model both serializes
  / validates the `--json` result and produces the `--schema` document
  (`model_json_schema()`), so the contract is never hand-maintained twice. The
  `error` half is derived the same way from the one shared `GdaErrorEnvelope` model,
  so it costs **zero per-command maintenance** — every command's `error` is byte-for-byte
  the same schema.

- **`gda-mcp` derives tool definitions mechanically** from `--schema`: `inputSchema`
  from `input`, `outputSchema` from `output`. The success/failure split maps onto
  MCP's two channels: `output` → MCP `outputSchema` (a tool's success result /
  `structuredContent`), while a `gda` non-zero-exit failure maps to MCP's separate
  `isError` channel. The `error` schema makes that failure envelope **discoverable**
  but is deliberately kept **out of `outputSchema`** — the future adapter must not
  fold `error` into `outputSchema`. This is what makes `gda-mcp` a thin adapter
  (ADR-0001) rather than a parallel hand-written surface.

- **Per-command *operation* error codes are out of scope for the `error` key.** The
  `error` schema is the uniform envelope shape, not an enumeration of which
  `GdaError.code` values a given command can report. Whether `--schema` should also
  advertise a command's specific operation error codes is a separate, later question.

- **`--schema` does not accept a custom schema.** Making one flag both emit the
  output contract and accept an input contract overloads two opposite directions onto
  the same flag. A caller wanting to validate `gda`'s output against their own schema
  can do so with any external validator.

- **Caller-supplied return schemas are reserved for future open-ended operations
  only.** For a fixed command the output shape is known and `gda` owns it. Only an
  open-ended operation where `gda` cannot know the shape — e.g. a future
  `gda eval`/`exec` that runs arbitrary GDScript — has a legitimate need for the
  caller to declare an expected return schema. When that operation is introduced it
  will use a **separate** flag (e.g. `--output-schema <file>`) scoped to that command.
  It is not built now (no such command exists yet).

## Scope / sequencing

- The `--schema` capability is implemented as its **own vertical slice** after the
  `gda info` tracer bullet (issue #2), not folded into it.
- To avoid rework, issue #2 must already carry the `gda info` result in a typed model,
  so adding `--schema` later is just exposing that model's schema.

## Considered options

- **Emit input + output + error contract** (chosen) — fully self-describing; lets
  `gda-mcp` generate tool definitions for free, and makes the uniform failure
  envelope discoverable for the `isError` channel without per-command cost (#43).
- **Fold the failure envelope into `output` as a success/failure union** (rejected)
  — conflates the two MCP channels: `output` should map to `outputSchema` (success /
  `structuredContent`) only, while failures belong to `isError`. A `oneOf` union
  would force the adapter to discriminate success from failure inside `outputSchema`.
- **Emit output only / input only** — narrower; insufficient for `gda-mcp` to derive
  both `inputSchema` and `outputSchema`.
- **Accept a custom schema on `--schema`** (rejected) — overloads the flag with the
  opposite direction; projection/filtering and external validation are better served
  by other means; caller-declared return shapes belong only to future open-ended ops.

## `--schema` is mandatory for every domain command (hard gate)

Once the mechanism lands on `gda info` (issue #4), every subsequent domain command
ships with a working `--schema` as part of its **definition of done**: a passing
`--schema` test is a merge gate, with **no exceptions**. The cost is near-zero — a
command already defines a typed model to back `--json`, and `--schema` is derived from
that same model — and the no-exceptions rule is exactly what guarantees `gda-mcp` can
generate its entire tool surface mechanically. A single command without a schema would
silently break that guarantee, so the gate is absolute rather than best-effort.

## Consequences

- Adding a new `gda` command means defining its I/O models; `--json` and `--schema`
  then both come for free, and `gda-mcp` picks it up without bespoke work.
- #4 (the `--schema` mechanism on `gda info`) is sequenced **before** any domain
  command slice, so that the self-description gate above is enforceable from the first
  domain command onward.
