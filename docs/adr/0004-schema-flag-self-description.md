---
status: accepted
---

# `--schema` is self-description, not a caller-supplied contract

ADR-0000 lists `--schema` as a core capability without defining it. We fix its
semantics here, and deliberately scope out an overloaded interpretation.

## Decision

- **`gda <command> --schema` emits the command's own machine-readable contract**: a
  JSON object containing both an `input` JSON Schema (the command's arguments/params)
  and an `output` JSON Schema (the shape of its `--json` result). The contract is
  owned by `gda`; the flag only *emits*, it never *accepts*, a schema.

- **Schemas are model-driven.** Each command's input and output are defined as typed
  models (Pydantic/msgspec on the Python 3.13 stack). The same model both serializes
  / validates the `--json` result and produces the `--schema` document
  (`model_json_schema()`), so the contract is never hand-maintained twice.

- **`gda-mcp` derives tool definitions mechanically** from `--schema`: `inputSchema`
  from `input`, `outputSchema` from `output`. This is what makes `gda-mcp` a thin
  adapter (ADR-0001) rather than a parallel hand-written surface.

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

- **Emit input + output contract** (chosen) — fully self-describing; lets `gda-mcp`
  generate tool definitions for free.
- **Emit output only / input only** — narrower; insufficient for `gda-mcp` to derive
  both `inputSchema` and `outputSchema`.
- **Accept a custom schema on `--schema`** (rejected) — overloads the flag with the
  opposite direction; projection/filtering and external validation are better served
  by other means; caller-declared return shapes belong only to future open-ended ops.

## Consequences

- Adding a new `gda` command means defining its I/O models; `--json` and `--schema`
  then both come for free, and `gda-mcp` picks it up without bespoke work.
