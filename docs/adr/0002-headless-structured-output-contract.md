---
status: accepted
---

# Headless structured output: sentinel-delimited JSON on stdout

> **Outcome (2026-06-23, #260):** the sentinel result format now has a single home
> for both directions — `gda.parser.build_result` (write) is the inverse of
> `gda.parser.parse_result` (read) — and a daemon- or live-client-synthesized reply
> is built once through `gda.daemon.protocol.result_reply` / `error_reply` (the
> latter over the shared `gda.parser.error_envelope`), replacing four hand-rolled
> copies of the `<<<GDA:RESULT>>>…<<<GDA:END>>>` wrapping. No contract change — the
> emitted bytes, exit codes, and envelope shape are identical.

Structured output is `gda`'s core differentiator (ADR-0000), but a headless Godot
process mixes its version banner, warnings, errors, and `print()` output into
stdout/stderr. `godot-mcp` does not solve this — it returns the raw stdout blob as
text, leaving the agent to parse noise.

For [headless operations](../../CONTEXT.md) we define a result contract:

- The GDScript emits **exactly one** result payload to **stdout**, wrapped in unique
  sentinels: `<<<GDA:RESULT>>>{...json...}<<<GDA:END>>>`.
- On success, the sentinel payload is the command's result object and the process
  exits `0`.
- On operation failure, the sentinel payload is a minimal error envelope with an
  operation-reported error code and message, and the process exits non-zero. `gda`
  validates the reported code, assigns the `operation` category, and attaches
  stderr diagnostics before emitting the public `GdaError`.
- The GDScript routes **all** of its own diagnostics (logs, warnings, progress) to
  **stderr**. stderr is diagnostic only; it is never parsed for stable error codes.
- `gda` extracts the bytes between the sentinels and parses that as the result;
  everything else on stdout is ignored, and stderr is surfaced for diagnostics.
  The payload echoes user-controlled content (a path, and later node names /
  script source) that may itself contain the end sentinel text, so extraction
  takes the **last** end sentinel after the begin sentinel as the terminator.
  This rests on two invariants below: the operation emits exactly one result and
  writes nothing else to stdout, so any sentinel-shaped bytes are payload content
  *before* the real terminator and cannot truncate the result (issue #34).
- A **result file** (a path passed in by `gda`, written by the GDScript) is reserved
  as an escape hatch for large or binary payloads that should not stream through
  stdout.

## Failure contract

The process exit code selects the success/failure channel; the sentinel payload
provides the structured detail for that channel:

- `exit_code == 0` plus a success payload means success.
- `exit_code == 0` plus an error envelope is a structured-output contract
  violation.
- `exit_code != 0` plus a valid, registered operation error envelope means an
  `operation` failure with the reported code and message.
- `exit_code != 0` without a valid operation error envelope falls back to
  `operation_failed`.

An operation failure payload has this wire shape:

```json
{"error":{"code":"path_not_found","message":"scene file does not exist: res://missing.tscn"}}
```

The GDScript payload owns only `code` and `message`. `gda` owns the public
`GdaError` wrapper: it validates that the code is registered, assigns the
`operation` category, preserves the message, and copies stderr into diagnostics.

### stderr as advisory diagnostics

stderr is still **never** parsed for the success/failure *outcome* or for stable
error codes — those come only from the exit code and the stdout sentinel, as
above. A command **may**, however, surface engine error text from stderr as
**advisory, best-effort diagnostics** on its *success* result, when a useful
detail is available nowhere else. `script validate` (#118) is the established
case: when it reports `valid=false`, the per-error `line` and `message` exist
only in the engine's stderr (no bound API exposes them), so `gda` parses them
into the result's `diagnostics`. This stays within the contract: the diagnostics
are advisory (they may hold only the first error, and `column` is unavailable on
the standard build), and they never determine the outcome or a stable code.

## `GdaError.code` registry

`GdaError.code` values are a public ABI for agents. Their authoritative source is
the Python registry in `src/gda/error_codes.py`; the table below mirrors that
source and is checked by tests. GDScript mirrors only the rows whose source is
`operation`, because only those codes can be reported by headless operations.

Each row carries the process `Exit Code` a shell consumer keys on. It is
per-code, not per-category: within `environment`, `binary_not_found` exits `127`
but `launch_timeout` exits `124`. The `exit_codes.py` registry defines the
values (`127`/`124` follow shell convention; `3`/`4`/`5` are the version,
operation, and parse codes the CLI assigns).

| Code | Category | Source | Exit Code | Meaning |
| --- | --- | --- | --- | --- |
| `binary_not_found` | `environment` | `runner` | `127` | The Godot binary could not be launched. |
| `launch_timeout` | `environment` | `runner` | `124` | Godot launched but did not return before the runner timeout. |
| `unsupported_version` | `version` | `version_gate` | `3` | The detected Godot version is below the supported minimum. |
| `engine_crashed` | `operation` | `classifier` | `4` | Godot terminated abnormally, such as by signal death. |
| `operation_failed` | `operation` | `classifier` | `4` | The engine or operation failed without a valid registered operation error envelope. |
| `usage_error` | `operation` | `operation` | `4` | The command was invoked incorrectly: the operation dispatcher received no operation name, or the CLI received `--params-json` together with the individual arguments (ADR-0015). |
| `unknown_operation` | `operation` | `operation` | `4` | The operation dispatcher received an unknown operation name. |
| `invalid_params` | `operation` | `operation` | `4` | Params do not match the command's contract: the operation dispatcher received non-object params, or a `--params-json` object was malformed or schema-invalid (ADR-0015). |
| `invalid_path` | `operation` | `operation` | `4` | A required path parameter is missing or invalid. |
| `invalid_root_type` | `operation` | `operation` | `4` | A requested Godot root node type cannot be instantiated as a `Node`. |
| `invalid_root_name` | `operation` | `operation` | `4` | A requested root node name is empty or would be rewritten by Godot. |
| `already_exists` | `operation` | `operation` | `4` | A create operation target already exists and will not be overwritten. |
| `save_failed` | `operation` | `operation` | `4` | A scene could not be packed or saved. |
| `delete_failed` | `operation` | `operation` | `4` | A file could not be removed from disk. |
| `file_changed_externally` | `operation` | `operation` | `4` | A read-modify-write operation's target file changed on disk between the read and the write, so the write was refused to avoid clobbering the external edit. |
| `project_not_found` | `operation` | `operation` | `4` | gda ran without a usable resolved Godot project: an operation needed one and none was resolved, or an explicit `--project` was empty, or a `--project`/`$GDA_PROJECT` does not name a Godot project (no `project.godot`). |
| `path_not_found` | `operation` | `operation` | `4` | A requested file does not exist. |
| `not_a_scene` | `operation` | `operation` | `4` | A requested file cannot be loaded as a `PackedScene`. |
| `parent_not_found` | `operation` | `operation` | `4` | A requested parent node path does not resolve to a node in the scene. |
| `invalid_node_type` | `operation` | `operation` | `4` | A requested node type is neither an instantiable `Node` class nor a registered `class_name`. |
| `invalid_node_name` | `operation` | `operation` | `4` | A requested node name is empty or would be rewritten by Godot. |
| `duplicate_node_name` | `operation` | `operation` | `4` | The parent node already has a child with the requested name. |
| `invalid_child_index` | `operation` | `operation` | `4` | A requested child insertion or move index is outside the valid sibling range. |
| `missing_dependency` | `operation` | `operation` | `4` | A scene's declared nodes vanished or degraded on load — an unresolvable instanced sub-scene, an unavailable node class, or a GDScript preload target that does not exist; re-saving would silently drop or downgrade scene data. |
| `uninstantiable_script` | `operation` | `operation` | `4` | A registered `class_name`'s script can no longer be loaded, compiled, or constructed, so it cannot be instantiated as a node or a resource. |
| `ambiguous_class_name` | `operation` | `operation` | `4` | A `class_name` is declared in more than one `.gd` script, so a request naming it (node add, resource create, or find-references) cannot resolve it to a single script; the conflicting script paths are named (ADR-0032). |
| `node_not_found` | `operation` | `operation` | `4` | A requested node path does not resolve to a node in the scene. |
| `cannot_target_root` | `operation` | `operation` | `4` | A structural edit targeted the scene root, which has no parent to be removed from, duplicated alongside, or reparented out of. |
| `cyclic_target` | `operation` | `operation` | `4` | The write would create a cycle: a node move targeted the node itself or one of its own descendants, or a scene instancing (node add --instance) targeted the host scene itself. |
| `unknown_property` | `operation` | `operation` | `4` | A requested property does not exist as a settable property on the target node or resource. |
| `uncoercible_value` | `operation` | `operation` | `4` | A supplied value cannot be coerced to the property's declared Godot type. |
| `expected_resource_path` | `operation` | `operation` | `4` | An Object-typed property was given a value that is not a `res://` resource path; assign an existing Resource by its `res://` path (ADR-0033, #363). |
| `not_a_resource` | `operation` | `operation` | `4` | A `res://` value for an Object-typed property does not load as a Resource (the path is missing or does not name a resource) (ADR-0033, #363). |
| `resource_type_mismatch` | `operation` | `operation` | `4` | A `res://` resource's type is incompatible with the Object-typed property's expected engine class (ADR-0033, #363). |
| `use_script_attach` | `operation` | `operation` | `4` | The `script` property is bound with `gda script attach` (which verifies the script compiles and its base type matches), not with `node set` / `resource set` (ADR-0033, #363). |
| `unsupported_property_type` | `operation` | `operation` | `4` | An Object-typed property expects a type `node set` / `resource set` cannot yet assign a `res://` resource to: a script `class_name`-typed property (deferred to the ADR-0032 resolver) or an Object property with no declared engine class (ADR-0033, #363). |
| `no_search_match` | `operation` | `operation` | `4` | A search-replace script edit found no occurrence of the search string. |
| `invalid_line_range` | `operation` | `operation` | `4` | A line-range script edit specified lines outside the script's bounds, or end before start. |
| `script_compile_failed` | `operation` | `operation` | `4` | A script could not be attached to a node because it does not compile. |
| `incompatible_script_type` | `operation` | `operation` | `4` | A script compiles but its native base type is incompatible with the target node's type. |
| `signal_not_found` | `operation` | `operation` | `4` | A requested signal does not exist on the source node. |
| `already_connected` | `operation` | `operation` | `4` | A signal is already connected to the target node's method. |
| `connection_not_found` | `operation` | `operation` | `4` | A requested signal-to-method connection does not exist on the source node. |
| `invalid_resource_type` | `operation` | `operation` | `4` | A requested resource type cannot be instantiated as a `Resource`. |
| `export_presets_not_found` | `operation` | `operation` | `4` | The project has no export_presets.cfg, so it defines no export presets. |
| `export_preset_not_found` | `operation` | `operation` | `4` | No export preset with the requested name exists in export_presets.cfg. |
| `export_path_unset` | `operation` | `classifier` | `4` | An export run has no destination — neither a `--output` override nor a configured `export_path` (#170). |
| `export_templates_missing` | `operation` | `classifier` | `4` | A release/debug export needs the export templates for the running engine version, which are not installed (pack needs no platform templates and is exempt; #170). |
| `export_output_parent_failed` | `operation` | `classifier` | `4` | An export run could not create the output parent directory before native export (#402). |
| `export_failed` | `operation` | `classifier` | `4` | A native Godot export run failed (the engine reported the export did not complete). |
| `invalid_uid` | `operation` | `operation` | `4` | A requested `uid://` value is not a syntactically valid resource UID. |
| `unknown_uid` | `operation` | `operation` | `4` | A syntactically valid resource UID is not registered in the engine's UID cache. |
| `no_uid_assigned` | `operation` | `operation` | `4` | A resource path exists but has no UID assigned in the engine's UID cache. |
| `unknown_setting` | `operation` | `operation` | `4` | A requested project setting does not exist in the project's ProjectSettings. |
| `invalid_target` | `operation` | `operation` | `4` | A project find-references target is empty or not a valid `res://` path or `class_name`. |
| `invalid_key` | `operation` | `operation` | `4` | An input-action key could not be resolved to a Godot keycode (unknown key name or non-positive keycode). |
| `contract_violation` | `parse` | `parser` | `5` | The process claimed success but violated the structured-output contract. |
| `tree_too_deep` | `parse` | `classifier` | `5` | The engine emitted a valid result tree that nests past gda's recursion limit; the payload is contract-conformant, the limit is wrapper-side (shares the `parse` exit code; the `code` distinguishes it from `contract_violation`). |
| `daemon_not_running` | `live` | `classifier` | `6` | A live command found no running gda-daemon for the project; start one with `gda daemon start` (Phase 2, ADR-0017 / ADR-0021). |
| `engine_session_not_running` | `live` | `classifier` | `6` | The daemon is running but holds no live engine session to serve the live operation (Phase 2). |
| `engine_disconnected` | `live` | `classifier` | `6` | The engine session disconnected before the live operation returned — the game crashed or the harness connection dropped (Phase 2). |
| `live_timeout` | `live` | `classifier` | `6` | A live operation did not return from the engine session before the daemon's timeout (Phase 2). |
| `daemon_running` | `live` | `classifier` | `6` | A daemon-lifecycle command was refused because a gda-daemon is running for the project; stop it first with `gda daemon stop` (Phase 2, #225). |
| `daemon_already_running` | `live` | `classifier` | `6` | A `gda daemon start --scene` was refused because a gda-daemon is already running for the project; `--scene` only takes effect at start, so stop it with `gda daemon stop` then start again with `--scene` (Phase 2, #278). |
| `live_node_not_found` | `live` | `classifier` | `6` | A live game operation's node path does not resolve to a node in the running scene tree (Phase 2, #220). |
| `live_not_control` | `live` | `classifier` | `6` | A live game rect operation targeted a running node that is not a Control (Phase 2, #419). |
| `live_unknown_property` | `live` | `classifier` | `6` | A live game get or set targeted a property name the running node does not expose as an addressable runtime, storage, or attached-script property (Phase 2, #220, #422). |
| `live_uncoercible_value` | `live` | `classifier` | `6` | A live game set value cannot be coerced to the addressed runtime property's or script variable's Godot type (Phase 2, #220, #422). |
| `live_log_unavailable` | `live` | `classifier` | `6` | A live engine session was launched but its diagnostics log file is missing or unreadable, so `gda diag` cannot read the running game's errors/output (Phase 2, #224). |
| `live_scene_not_found` | `live` | `classifier` | `6` | A `gda daemon start --scene` selector did not load: the launched session ran a different scene (Godot silently falls back to main_scene for a missing/invalid path or UID), verified by the harness at launch — gda never falls back (Phase 2, #278). |
| `live_perf_node_not_found` | `live` | `classifier` | `6` | A live perf monitor's node path does not resolve to a node in the running scene tree (Phase 2, #223). |
| `live_perf_property_not_found` | `live` | `classifier` | `6` | A live perf monitor targeted a property the running node does not expose for reading (Phase 2, #223). |
| `live_perf_signal_not_found` | `live` | `classifier` | `6` | A live perf monitor targeted a signal the running node does not declare (Phase 2, #223). |
| `live_invalid_key` | `live` | `classifier` | `6` | A live input key event named a key the engine could not resolve to a keycode (Phase 2, #221). |
| `live_unknown_action` | `live` | `classifier` | `6` | A live input action targeted an action the running game's InputMap does not declare (Phase 2, #221). |
| `live_invalid_event_spec` | `live` | `classifier` | `6` | A live input sequence event has a type the harness does not recognize (Phase 2, #221). |
| `live_display_unavailable` | `live` | `classifier` | `6` | A live `screen` capture ran on a headless engine session (the dummy DisplayServer cannot read pixels); start the daemon windowed with `gda daemon start --windowed` (Phase 2, #222). |
| `live_unsupported_platform` | `environment` | `classifier` | `127` | Live operations require a UNIX platform (macOS/Linux); they use Unix domain sockets, unavailable here. Phase-1 headless is unaffected (Phase 2, ADR-0021). |
| `live_windowed_unavailable` | `environment` | `classifier` | `127` | A windowed live session (`gda daemon start --windowed`) was requested but the host has no usable DisplayServer (no on-console GUI session / no `$DISPLAY`), so the session cannot come up; refused before spawning Godot (Phase 2, #345). |

## Considered options

- **Sentinel-delimited JSON on stdout** (chosen) — simplest, streamable, and the
  unique marker isolates the result from engine noise. Generalises to the
  per-message protocol the daemon will need in Phase 2.
- **Separate `gda-error:<code>:` marker on stderr for operation failures** —
  rejected; stderr is also where engine and script diagnostics appear, so parsing
  it for stable codes is spoofable. Regex capture also truncates multiline
  messages. Success and failure should share one structured channel instead.
- **Result file always** — strongest isolation from stdout noise, but adds temp-file
  lifecycle and cannot stream; kept only as the large-payload escape hatch.
- **Raw passthrough** (like `godot-mcp`) — rejected; it abandons the structured-output
  goal.

## Consequences

- Every GDScript operation must discipline its logging to stderr; emitting to stdout
  outside the sentinels is a contract violation that corrupts results.
- The sentinel strings are part of the wire contract between `gda` and its GDScript
  payloads, and changing them is a breaking change.
- Adding or changing a `GdaError.code` requires updating the Python registry, this
  ADR's registry table, and any GDScript operation-code mirror. Tests must reject
  drift between those copies.
- `gda <command> --schema` describes the success result model under its `output`
  key. Whether command schemas should include the failure envelope was resolved in
  #43: `--schema` now also carries a uniform `error` key holding this ADR's failure
  envelope (the shared `GdaErrorEnvelope` schema), kept separate from `output` so the
  success result and the failure envelope stay distinct channels. See ADR-0004.
