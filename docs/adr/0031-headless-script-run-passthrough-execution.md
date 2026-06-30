---
status: accepted
---

# Headless script-run execution: a third shape — pass the user script's run through, classify only launch/crash

ADR-0010 recognised **two** execution mechanisms for [headless operations](../../CONTEXT.md):
① GDScript op-dispatch under the ADR-0002 sentinel contract (the default), and ② native engine
CLI mode for editor-only capabilities (e.g. `--export-*`), whose outcome `gda` classifies from the
process exit code. ADR-0025 then fixed *which* capabilities earn a command, and explicitly listed
`--script` one-shot among the candidates admissible "case by case, only if a concrete agent need
appears."

That need appeared (#343, surfaced dogfooding the Panda Adventure walking skeleton, #329/#341): a
data-driven game's **pure logic seam** — Controller/formula logic over Resource data, asserted
headless — must run an arbitrary project `.gd` and read its result. With no `gda` runner, the test
shells out to `godot --headless --path <proj> --script res://…` directly, bypassing `gda` entirely
(no structured result, no engine-error classification, manual binary resolution).

This capability fits **neither** ADR-0010 mechanism. It uses `--script` (not an editor-only native
CLI mode), but the entry script is the **user's own**, so it cannot emit the ADR-0002 sentinel —
and unlike mechanism ②'s `export run`, `gda` does **not** know the script's semantics, so it has no
gda-defined typed result to synthesize. ADR-0002 already weighed and **rejected** "raw passthrough
(like godot-mcp)"; this ADR records a **bounded exception** to that rejection, for the one case where
the payload *is* user-authored output rather than a structured operation result.

## Decision

`gda script run res://path.gd` runs the user's script as a one-shot `godot --headless [--path
<project>] --script <res://…>` process (still ADR-0001), through the recipe channel (ADR-0023) under
a new `ExecutionKind.SCRIPT_RUN`. It is a **third execution shape — a user-script passthrough run**.

**Bifurcated outcome, split by *whose* failure it is:**

- **gda-/engine-level failure** — the binary could not be launched, the run timed out, or the engine
  died on a signal (`exit_code < 0`) → an **[Error envelope](../../CONTEXT.md)**, classified by the
  shared `classify_launch_or_crash` into the existing classifier-source codes (`binary_not_found`,
  `launch_timeout`, `engine_crashed`). These are gda-level outcomes; they are not GDScript-mirrored,
  consistent with ADR-0002 / ADR-0010 mechanism ②.
- **The script ran to completion** — the engine exited normally (`exit_code >= 0`) → a **success
  result** carrying `{exit_status, stdout, stderr}`, **passed through verbatim, even when
  `exit_status != 0`**. `gda` does not interpret the user script's semantics: a deliberate `quit(1)`
  (e.g. an assertion-failed logic-seam test) is meaningful **data the agent reads**, not a gda
  failure.

This makes `script run` the one operation whose **success result *is* a [Raw run](../../CONTEXT.md)**
— the previously internal `{stdout, stderr, exit_code, …}` shape — minus its `launch_failure` axis,
which is exactly the part lifted out into the Error envelope above.

**Scope: project-scoped + `res://`-only.** `script run` requires a resolved project (ADR-0006) and
takes a `res://…` script path, consistent with the rest of the `script` command group (which all act
on `res://`). A `res://` path needs a project to resolve, and the motivating need is project-scoped.
Running a standalone script by absolute path with no project is **out of scope** here; it can be
added incrementally under ADR-0025 if a concrete need appears.

## Considered options

- **Map a non-zero *script* exit to a synthesized `script_failed`** (mirroring `export run`'s
  `export_failed`) — **rejected.** `export run` may do this because `gda` knows the export semantics
  (it either completed or it did not). `gda` does **not** know a user script's semantics; a
  meaningful non-zero `quit()` would be mis-reported as a gda error and would discard the script's
  own output as mere diagnostics.
- **Full raw passthrough, including launch/crash** (godot-mcp style) — **rejected.** It abandons
  gda's error-classification value. A missing binary, a timeout, and a signal crash *are* gda-level
  outcomes and belong in the stable Error envelope, not in an undifferentiated blob.
- **Force an ADR-0002 sentinel wrapper around the user script** — **rejected.** The contract cannot
  be imposed on a user-authored entry script without rewriting it, which defeats the purpose (run
  *their* script and read *its* output).
- **Treat it as ADR-0010 mechanism ② unchanged** — **rejected.** Mechanism ② yields a gda-defined
  typed result; this yields a passthrough result gda does not interpret. It is genuinely a third
  shape, recorded here rather than silently overloading mechanism ②.

## Consequences

- **`script run` is the only command whose *success* result can carry a non-zero `exit_status`.**
  Agents and tooling must read `exit_status` and must not assume `success == zero`. This is a public
  ABI and is hard to reverse, which is why it is recorded here.
- **ADR-0002's passthrough rejection still stands for *operations*.** This is a bounded exception for
  running user-authored code, where there is no structured operation result to emit. The
  agent-facing machinery is otherwise unchanged: typed models, `--json`, the ADR-0004 `--schema`
  gate, and the registered classifier `GdaError.code`s all apply.
- **The [Project-code execution surface](../../CONTEXT.md) (ADR-0009) widens** — from "autoloads +
  the `_init` of instantiated scene scripts" to "the **full execution** of a named project script."
  This stays **within** ADR-0009's Trusted-project assumption (gda already runs project-authored code
  on every `--project` op); it adds **no new defence** and no new trust axis — only a documented
  widening of the same surface.
- **Implementation reuses existing machinery** — the shared `launch()` headless-launch primitive and
  the recipe channel — rather than inventing a runner. The new `ExecutionKind.SCRIPT_RUN` must be
  handled by **every** cross-cutting CLI channel that branches on `kind`/`recipe` (dispatch routing,
  `--params-json`), or the command routes to the wrong runner — a known hazard from the non-sentinel
  dispatch channels.
- **Large output** streams through stdout like any headless result; if a future need surfaces, the
  ADR-0002 result-file escape hatch applies, but it is not committed here.
