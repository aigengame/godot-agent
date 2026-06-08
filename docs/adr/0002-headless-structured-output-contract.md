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
- The GDScript routes **all** of its own diagnostics (logs, warnings, progress) to
  **stderr**. stdout carries nothing but the contract.
- `gda` extracts the bytes between the sentinels and parses that as the result;
  everything else on stdout is ignored, and stderr is surfaced for diagnostics.
- A **result file** (a path passed in by `gda`, written by the GDScript) is reserved
  as an escape hatch for large or binary payloads that should not stream through
  stdout.

## Considered options

- **Sentinel-delimited JSON on stdout** (chosen) — simplest, streamable, and the
  unique marker isolates the result from engine noise. Generalises to the
  per-message protocol the daemon will need in Phase 2.
- **Result file always** — strongest isolation from stdout noise, but adds temp-file
  lifecycle and cannot stream; kept only as the large-payload escape hatch.
- **Raw passthrough** (like `godot-mcp`) — rejected; it abandons the structured-output
  goal.

## Consequences

- Every GDScript operation must discipline its logging to stderr; emitting to stdout
  outside the sentinels is a contract violation that corrupts results.
- The sentinel strings are part of the wire contract between `gda` and its GDScript
  payloads, and changing them is a breaking change.
