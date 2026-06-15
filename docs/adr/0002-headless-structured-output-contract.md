---
status: accepted
---

# Headless structured output: sentinel-delimited JSON on stdout

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
| `usage_error` | `operation` | `operation` | `4` | The operation dispatcher was invoked without the required operation name. |
| `unknown_operation` | `operation` | `operation` | `4` | The operation dispatcher received an unknown operation name. |
| `invalid_params` | `operation` | `operation` | `4` | The operation dispatcher received params that are not a JSON object. |
| `invalid_path` | `operation` | `operation` | `4` | A required path parameter is missing or invalid. |
| `invalid_root_type` | `operation` | `operation` | `4` | A requested Godot root node type cannot be instantiated as a `Node`. |
| `invalid_root_name` | `operation` | `operation` | `4` | A requested root node name is empty or would be rewritten by Godot. |
| `already_exists` | `operation` | `operation` | `4` | A create operation target already exists and will not be overwritten. |
| `save_failed` | `operation` | `operation` | `4` | A scene could not be packed or saved. |
| `delete_failed` | `operation` | `operation` | `4` | A file could not be removed from disk. |
| `project_not_found` | `operation` | `operation` | `4` | An operation that enumerates a project's `res://` tree ran without a resolved Godot project. |
| `path_not_found` | `operation` | `operation` | `4` | A requested file does not exist. |
| `not_a_scene` | `operation` | `operation` | `4` | A requested file cannot be loaded as a `PackedScene`. |
| `parent_not_found` | `operation` | `operation` | `4` | A requested parent node path does not resolve to a node in the scene. |
| `invalid_node_type` | `operation` | `operation` | `4` | A requested node type is neither an instantiable `Node` class nor a registered `class_name`. |
| `invalid_node_name` | `operation` | `operation` | `4` | A requested node name is empty or would be rewritten by Godot. |
| `duplicate_node_name` | `operation` | `operation` | `4` | The parent node already has a child with the requested name. |
| `missing_dependency` | `operation` | `operation` | `4` | A scene's declared nodes vanished or degraded on load — an unresolvable instanced sub-scene or an unavailable node class; re-saving would silently drop or downgrade them. |
| `uninstantiable_script` | `operation` | `operation` | `4` | A registered `class_name`'s script can no longer be loaded, compiled, or constructed, so it cannot be instantiated as a node. |
| `node_not_found` | `operation` | `operation` | `4` | A requested node path does not resolve to a node in the scene. |
| `cannot_target_root` | `operation` | `operation` | `4` | A structural edit targeted the scene root, which has no parent to be removed from, duplicated alongside, or reparented out of. |
| `cyclic_target` | `operation` | `operation` | `4` | A node move targeted the node itself or one of its own descendants, which would detach the moved subtree from the scene. |
| `unknown_property` | `operation` | `operation` | `4` | A requested property does not exist as a settable property on the node. |
| `uncoercible_value` | `operation` | `operation` | `4` | A supplied value cannot be coerced to the property's declared Godot type. |
| `no_search_match` | `operation` | `operation` | `4` | A search-replace script edit found no occurrence of the search string. |
| `invalid_line_range` | `operation` | `operation` | `4` | A line-range script edit specified lines outside the script's bounds, or end before start. |
| `script_compile_failed` | `operation` | `operation` | `4` | A script could not be attached to a node because it does not compile. |
| `incompatible_script_type` | `operation` | `operation` | `4` | A script compiles but its native base type is incompatible with the target node's type. |
| `signal_not_found` | `operation` | `operation` | `4` | A requested signal does not exist on the source node. |
| `already_connected` | `operation` | `operation` | `4` | A signal is already connected to the target node's method. |
| `connection_not_found` | `operation` | `operation` | `4` | A requested signal-to-method connection does not exist on the source node. |
| `invalid_resource_type` | `operation` | `operation` | `4` | A requested resource type cannot be instantiated as a `Resource`. |
| `contract_violation` | `parse` | `parser` | `5` | The process claimed success but violated the structured-output contract. |

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
