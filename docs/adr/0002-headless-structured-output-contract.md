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

## `GdaError.code` registry

`GdaError.code` values are a public ABI for agents. Their authoritative source is
the Python registry in `src/gda/error_codes.py`; the table below mirrors that
source and is checked by tests. GDScript mirrors only the rows whose source is
`operation`, because only those codes can be reported by headless operations.

| Code | Category | Source | Meaning |
| --- | --- | --- | --- |
| `binary_not_found` | `environment` | `runner` | The Godot binary could not be launched. |
| `launch_timeout` | `environment` | `runner` | Godot launched but did not return before the runner timeout. |
| `unsupported_version` | `version` | `version_gate` | The detected Godot version is below the supported minimum. |
| `engine_crashed` | `operation` | `classifier` | Godot terminated abnormally, such as by signal death. |
| `operation_failed` | `operation` | `classifier` | The engine or operation failed without a valid registered operation error envelope. |
| `usage_error` | `operation` | `operation` | The operation dispatcher was invoked without the required operation name. |
| `unknown_operation` | `operation` | `operation` | The operation dispatcher received an unknown operation name. |
| `invalid_params` | `operation` | `operation` | The operation dispatcher received params that are not a JSON object. |
| `invalid_path` | `operation` | `operation` | A required path parameter is missing or invalid. |
| `invalid_root_type` | `operation` | `operation` | A requested Godot root node type cannot be instantiated as a `Node`. |
| `invalid_root_name` | `operation` | `operation` | A requested root node name is empty or would be rewritten by Godot. |
| `already_exists` | `operation` | `operation` | A create operation target already exists and will not be overwritten. |
| `save_failed` | `operation` | `operation` | A scene could not be packed or saved. |
| `path_not_found` | `operation` | `operation` | A requested scene file does not exist. |
| `not_a_scene` | `operation` | `operation` | A requested file cannot be loaded as a `PackedScene`. |
| `parent_not_found` | `operation` | `operation` | A requested parent node path does not resolve to a node in the scene. |
| `invalid_node_type` | `operation` | `operation` | A requested node type is neither an instantiable `Node` class nor a registered `class_name`. |
| `invalid_node_name` | `operation` | `operation` | A requested node name is empty or would be rewritten by Godot. |
| `duplicate_node_name` | `operation` | `operation` | The parent node already has a child with the requested name. |
| `missing_dependency` | `operation` | `operation` | A scene's declared nodes vanished on load, typically an unresolvable instanced sub-scene; re-saving would silently drop them. |
| `contract_violation` | `parse` | `parser` | The process claimed success but violated the structured-output contract. |

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
- `gda <command> --schema` currently describes the success result model. Whether
  command output schemas should include failure envelopes is a separate decision
  tracked in #43.
