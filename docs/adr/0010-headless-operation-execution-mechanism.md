---
status: accepted
---

# Headless operation execution: GDScript op-dispatch by default, native engine CLI mode for editor-only capabilities

> **Outcome (2026-06-30, #343):** a **third** execution shape was later recognised — a *user-script
> passthrough run* (`gda script run`). It fits neither mechanism below: it runs the user's own `.gd`
> via `--script`, so it emits no ADR-0002 sentinel, yet — unlike mechanism ②'s `export run` — `gda`
> does **not** know the script's semantics, so it passes the script's `{exit_status, stdout, stderr}`
> through verbatim and classifies only launch/crash. See ADR-0031.

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
   CLI mode directly and **classifies** the subprocess outcome into
   **classifier-source** `GdaError` codes — the same mechanism ADR-0002 already
   uses for `engine_crashed` / `operation_failed`. The native CLI mode emits no
   ADR-0002 sentinel, so the classification keys on the **process exit code** plus a
   **structured pre-check** performed before the native run — never on the engine's
   stderr text. Consistent with ADR-0002, stderr is **never** parsed to choose a
   stable code; it is surfaced **only** as the advisory `message` / diagnostics on
   the outcome (the same advisory-diagnostics carve-out ADR-0002 grants `script
   validate`). Such codes live in the `src/gda/error_codes.py` registry and the
   ADR-0002 table only, and are **not** mirrored in GDScript (per ADR-0002: only
   operation-source codes are mirrored, because only those can be reported by an op).
   A drift test enforces this.

**Minimise the divergence.** Keep as much of an operation as possible on the default
rails; only the irreducibly-native step takes mechanism 2. `export run` is therefore
staged so that everything decidable from structured data is decided *before* the
native run:

- **Resolve (op-dispatch).** The preset is resolved via the standard `export-get`
  op, so an unknown preset is the operation-source `export_preset_not_found` and a
  project with no `export_presets.cfg` is `export_presets_not_found`.
- **Structured preflight (classifier, no native run).** `export-get` already reports
  the preset's configured `export_path` and, structurally, its template readiness
  (`templates_installed` — the readiness field built for exactly this check). From
  those: no **effective destination** — neither a `--output` override (#170) nor a
  configured `export_path` — is `export_path_unset`; and uninstalled templates for the
  running engine version are `export_templates_missing`. The destination check applies
  to **every** mode, but the template check is for **release/debug only** — `pack`
  produces project data (a PCK/ZIP via Godot's native `--export-pack`) and needs no
  platform templates, so it is exempt (#170). Both checks are decided here, from
  structured fields, with **no** native export spawned — in particular
  `export_templates_missing` is *not* inferred from the engine's "due to configuration
  errors" stderr (which would violate ADR-0002 and also misfires for a
  merely-misconfigured preset). After those checks pass, `gda` creates any missing
  filesystem parent directories for the resolved output path; if that preflight cannot
  create the parent, it returns the classifier-source `export_output_parent_failed`
  before Godot runs, rather than letting locale/version-dependent engine prose decide
  the public error.
- **Native run (classifier on exit code).** Only the export execution itself uses the
  native CLI mode. A clean exit is the typed success result (with any advisory
  `WARNING` lines parsed off stderr as best-effort diagnostics); any non-zero exit is
  the generic `export_failed`, with the engine's stderr attached only as advisory
  diagnostics, never parsed to select the code.

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
