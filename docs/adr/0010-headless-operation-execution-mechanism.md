---
status: accepted
---

# Headless operation execution: GDScript op-dispatch by default, native engine CLI mode for editor-only capabilities

ADR-0001 serves [headless operations](../../CONTEXT.md) by spawning one-shot
`godot --headless` processes. ADR-0002 then fixes *how* such a process reports its
result: a single GDScript operation in `operations.gd` emits a sentinel-delimited
payload on stdout and reports an **operation-source** error code (mirrored into the
GDScript const table). This is the default and, until now, the only execution
mechanism — and it works for every capability reachable from a `--headless --script`
runtime context (scene/node/script/resource/project edits, and the config-file reads
behind `export list` / `export get`).

`gda export run` (#121) is the first capability that is **not** reachable that way.
Verified against the engine source (`../godot`): Godot's export subsystem
(`EditorExportPlatform`, `EditorExportPreset`, the template manager) is **editor-only
C++** under `editor/export/`, not exposed to a runtime script; and the only headless
way to perform an export is the engine's dedicated top-level CLI modes
`--export-release` / `--export-debug` / `--export-pack` (tagged
`CLI_OPTION_AVAILABILITY_EDITOR` in `main/main.cpp`). An `operations.gd` op therefore
*cannot* execute an export: there is no runtime API to call, and the export mode is a
separate top-level engine invocation, not a script run.

## Decision

We recognise **two** execution mechanisms for headless operations, both still
one-shot `godot --headless` processes under ADR-0001:

1. **GDScript op-dispatch (default).** The capability is reachable from a runtime
   script, so it is an `operations.gd` op under the ADR-0002 sentinel contract and
   reports operation-source codes. This remains the default; new capabilities use it
   unless they cannot.
2. **Native engine CLI mode (editor-only capabilities).** When the capability is
   editor-only / unreachable from a runtime script, `gda` invokes the engine's native
   CLI mode directly and **classifies** the subprocess outcome (exit code + output)
   into **classifier-source** `GdaError` codes — the same mechanism ADR-0002 already
   uses for `engine_crashed` / `operation_failed`. Such codes live in the
   `src/gda/error_codes.py` registry and the ADR-0002 table only, and are **not**
   mirrored in GDScript (per ADR-0002: only operation-source codes are mirrored,
   because only those can be reported by an op). A drift test enforces this.

**Minimise the divergence.** Keep as much of an operation as possible on the default
rails; only the irreducibly-native step takes mechanism 2. `export run` is therefore
two-phase: phase 1 resolves the preset via the standard `export-get` op (so an unknown
preset is the operation-source `export_preset_not_found`); only phase 2 — the export
execution itself — uses the native CLI mode plus classifier (`export_path_unset`,
`export_templates_missing`, `export_failed`).

## Considered options

- **Force everything through `operations.gd`** — impossible for editor-only
  capabilities: the export classes do not exist in a runtime-script context.
- **Serve export through a persistent editor (ADR-0001 Phase 2 daemon)** — overkill
  and miscategorised: export is a stateless headless operation, not a live one; Phase 2
  exists for operations that need an already-running engine.
- **Native CLI mode + classifier, divergence minimised (chosen).**

## Consequences

- `gda` carries two execution paths for headless operations: the `operations.gd`
  sentinel path (default) and a native-CLI-mode runner whose outcome `gda` classifies.
  This is a new shape and maintenance surface (a native runner alongside the op
  runner), accepted because it is intrinsic to the capability, contained, and reuses
  the existing runner / `GdaError` machinery rather than duplicating it.
- Error-code sourcing follows from the mechanism: an editor-only-capability failure is
  classifier-source by nature (no op emits it) and is not GDScript-mirrored.
- The **agent-facing contract is unchanged**: typed models, `--json`, the ADR-0004
  `--schema` gate, and registered `GdaError.code`s apply identically; only the internal
  execution mechanism differs.
- Future editor-only capabilities (other `--export-*` variants, Android build-template
  install, etc.) follow this precedent rather than inventing a new pattern.
