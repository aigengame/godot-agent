---
status: accepted
---

# Headless script-run execution: a third shape — pass the user script's run through, classify only launch/crash

> **Amendment (2026-08-15, #651) — `gda` is the authority on whether the engine RAN the script;
> the script stays the authority on what its own exit status means.** Dogfooding (GDA-DF-007,
> GDA-DF-017, GDA-DF-032) found the passthrough reporting success for runs that never happened. The
> decision below is unchanged for a **completed** run; this note draws the line the original text
> left implicit, and adds one opt-in inversion.
>
> **1. A script that never ran is a failure, by default.** Godot reports a missing `--script` entry
> point, and an entry script (or a dependency it preloads) that fails to parse or compile, **only on
> stderr — and still exits `0`** (verified against Godot 4.6.3). Passing that status through made
> `gda script run res://does-not-exist.gd` return `{"exit_status": 0}`, which no reading of the
> contract calls a successful run. These are **defects, not the contract**: the passthrough exists
> because gda does not know a user script's *semantics*, and a script that never started has none.
> They now classify to the registered `script_not_found` / `script_compile_failed` **Error
> envelope** (both `operation` category, exit `4`). The verdict is read from the engine's error
> stream, never from the exit code, and is keyed on the **entry script's own `res://` path** — a
> running script that itself fails to load some *other* resource stays a success.
>
> **2. `--strict` inverts the non-zero-exit default, opt-in only.** The considered option
> "map a non-zero *script* exit to a synthesized `script_failed`" stays **rejected as the default**,
> for the reason recorded below: the Raw-run promotion is what lets a user script use its exit codes
> freely. But a caller whose gate *is* the process exit code — a shell `&&` chain, a conventional CI
> step — cannot express that with a command that always exits `0` (GDA-DF-017). `--strict` is that
> expression: for that invocation, a completed run with a non-zero `exit_status` becomes the
> registered `script_failed` envelope. The child status is **not** propagated as gda's process exit
> code — a script's `quit(3)` would alias `EXIT_VERSION` — so strict exits `4` and keeps the status
> readable in the message and the script's stderr in `diagnostics`. The script's **stdout is not
> carried by the envelope**; re-run without `--strict` to read the full passthrough result.
> Without the flag, behaviour is exactly as decided below.
>
> **3. The success result gains classified `diagnostics`.** Recognized script errors parsed out of
> the engine's stderr are surfaced as structured entries alongside the verbatim `stderr`, so a
> runtime GDScript error the script *survived* (leaving a clean `exit_status`) is visible without
> matching engine prose. Advisory, in ADR-0002's sense: the stable outcome is still the
> success/failure verdict, never the parsed text. Not interpreting the *script's* semantics was
> never a reason to ignore the *engine's* report.
>
> **Not decided here:** a script that compiles but does not extend `SceneTree`/`MainLoop` also never
> runs, and the engine reports it the same way. It is parsed and surfaced as a diagnostic
> (`not_a_main_loop`) but does **not** flip the verdict — it is neither missing nor non-compiling,
> so it needs a code and a decision of its own.

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

**Public `kind` surface — a fourth value.** The execution `kind` is **public self-description**: it
is projected into `gda <cmd> --schema` and the gda-mcp manifest (ADR-0004, ADR-0012), where it was
previously the closed set `headless` / `export` / `live`. Because `script run` is a genuinely third
execution shape, it carries a **fourth** value, `script_run` — representing it under an existing kind
would *misdescribe its contract* (`headless` implies the ADR-0002 sentinel; `export` implies the
native export recipe). Per ADR-0023 the dispatch seam is `recipe` **xor** the `kind`-runner, and
`script run` routes by its `recipe`; so the new `kind` adds **no runner-selection branch** — it is a
self-description label only. The migration this entails, landing **with** the implementation, is
therefore an ABI/schema-surface change, not a dispatch change: extend the `ExecutionKind` enum, the
`--schema`/`CommandSchema` `kind` enum (ADR-0004) and the gda-mcp manifest surface (ADR-0012), and
the schema tests that pin the kind set. ADR-0017's `kind` taxonomy is referenced but unaffected (it
governs the `live` channel only).

**Scope: project-scoped + `res://`-only.** `script run` requires a resolved project (ADR-0006) and
takes a `res://…` script path, consistent with the rest of the `script` command group (which all act
on `res://`). A `res://` path needs a project to resolve, and the motivating need is project-scoped.
Running a standalone script by absolute path with no project is **out of scope** here; it can be
added incrementally under ADR-0025 if a concrete need appears.

**Explicit ABI edges (public, called out so the contract is not merely implied):**

- A **non-`res://` or absolute** script path, or an invocation with **no resolved project**, returns
  a structured `GdaError` (e.g. `invalid_path` / `project_not_found`) — **never** a crash or a raw
  engine failure.
- `gda script run --schema` self-describes the **success result** (`{exit_status, stdout, stderr}`)
  **and** the uniform Error envelope, exactly like every command (ADR-0004) — the success `output`
  and the `error` envelope kept as the two distinct channels ADR-0004 defines.

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
- **Reuse an existing `kind` (`headless`/`export`) + a `recipe`, adding no fourth value** —
  **rejected.** It is the smaller change (no public-enum expansion), and ADR-0023's `recipe` seam
  would route it correctly regardless of `kind`. But `kind` is public self-description (ADR-0004 /
  ADR-0012): advertising `script run` as `headless` would promise the ADR-0002 sentinel it does not
  emit, and as `export` would promise the native export recipe. Misdescribing the shape to dodge a
  recorded enum migration is the wrong trade; the fourth value is taken and its migration owned above.

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
- **The public `kind` enum gains a fourth value** (`script_run`), so the `--schema` / gda-mcp
  manifest `kind` set is no longer closed at three. This is an ABI/schema-surface expansion that
  moves as one unit with the implementation: the `ExecutionKind` enum, the `CommandSchema` `kind`
  enum (ADR-0004), the gda-mcp manifest surface (ADR-0012), and the schema tests that pin the kind
  set. It is **not** a dispatch change — routing is by `recipe` (ADR-0023).
- **Implementation reuses existing machinery** — the shared `launch()` headless-launch primitive and
  the recipe channel — rather than inventing a runner. The new kind/recipe must be handled by
  **every** cross-cutting CLI channel that branches on `kind`/`recipe` (dispatch routing,
  `--params-json`), or the command routes to the wrong runner — a known hazard from the non-sentinel
  dispatch channels.
- **Large output** streams through stdout like any headless result; if a future need surfaces, the
  ADR-0002 result-file escape hatch applies, but it is not committed here.
