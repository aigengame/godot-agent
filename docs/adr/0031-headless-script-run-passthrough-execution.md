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
> **1. A script that never ran is a failure, by default.** Godot reports **three** such shapes
> **only on stderr — and still exits `0`**: a missing `--script` entry point; an entry script (or a
> dependency it preloads) that fails to parse or compile; and one that compiles but does not extend
> `SceneTree`/`MainLoop`, so it can never be a one-shot entry point. The first two were verified
> against Godot 4.6.3 as reliably reproducible. The **third is not**: its exit-0 form is real and
> captured, but the engine more often prints nothing and simply keeps idling — falling through to
> the project's main loop — which surfaces as `launch_timeout` (#655). That is a failure by another
> route, so gda never reports success for it either way; only the exit-0 form is what this decision
> has to correct.
>
> Passing that status through made `gda script run res://does-not-exist.gd` return
> `{"exit_status": 0}`, which no reading of the contract calls a successful run. These are
> **defects, not the contract**: the passthrough exists because gda does not know a user script's
> *semantics*, and a script that never started has none. They now classify to an **Error envelope**
> (all `operation` category, exit `4`):
>
> | shape | code |
> | --- | --- |
> | the entry script does not exist | `script_not_found` (new) |
> | the entry script or a preloaded dependency does not compile | `script_compile_failed` (reused) |
> | the entry script compiles but is not a `SceneTree`/`MainLoop` | `incompatible_script_type` (reused) |
>
> The two reused codes already name these exact conditions for `script attach`; only the genuinely
> new condition — "the engine could not load the entry script, so the run never happened" — is
> minted. The verdict is read from the engine's error stream, never from the exit code, and is keyed
> on the **entry script's own `res://` path**: a running script that itself fails to load some
> *other* resource stays a success. When a run emits several of these, the earliest-stage, most
> specific cause wins (missing > compile > parse > load > not-a-main-loop) — the engine reports the
> whole cascade, and only the first cause explains the rest.
>
> **2. `--strict` inverts the non-zero-exit default, opt-in only.** The considered option
> "map a non-zero *script* exit to a synthesized `script_failed`" stays **rejected as the default**,
> for the reason recorded below: the Raw-run promotion is what lets a user script use its exit codes
> freely. But a caller whose gate *is* the process exit code — a shell `&&` chain, a conventional CI
> step — cannot express that with a command that always exits `0` (GDA-DF-017). `--strict` is that
> expression: for that invocation, a completed run with a non-zero `exit_status` becomes the
> registered `script_failed` envelope. The child status is **not** propagated as gda's process exit
> code — a script's `quit(3)` would alias `EXIT_VERSION` — so strict exits `4`.
>
> The envelope keeps the evidence the flag exists to act on. `diagnostics` carries **both** of the
> script's streams under the fixed labels `--- script stdout ---` and `--- script stderr ---` (both
> sections always present, empty when the stream was). Carrying stderr alone would defeat the flag's
> own use case: a GDScript test runner reports through `print()`, i.e. stdout, so a CI caller would
> receive a failure with no content. Without the flag, behaviour is exactly as decided below.
>
> **3. The success result gains classified `diagnostics`.** Recognized script errors parsed out of
> the engine's stderr are surfaced as structured entries alongside the verbatim `stderr`, so a
> runtime GDScript error the script *survived* (leaving a clean `exit_status`) is visible without
> matching engine prose. Advisory, in ADR-0002's sense: the stable outcome is still the
> success/failure verdict, never the parsed text. Not interpreting the *script's* semantics was
> never a reason to ignore the *engine's* report.
>
> **Shape of the two diagnostics channels — deliberately different, and not symmetric.** The
> structured `ScriptError[]` of point 3 appears **only on success results**, which are typed models
> free to carry any shape. The **failure** channel is ADR-0004's `GdaError`, whose `diagnostics` is a
> free-form `str`, so everything a failure reports — the labelled streams of point 2, the engine
> stderr behind a point-1 verdict — is **prose**. The child's numeric exit status likewise survives
> only as message prose, not as a structured field. Giving the failure channel structured
> diagnostics means changing the ADR-0004 envelope, which is a decision of its own; **#687 owns it**
> (#655's timeout envelope names the same constraint and adopts #687's outcome).
> This amendment deliberately does **not** make that change.
>
> This bounds how far #651's "preserve the raw process status and stderr as secondary evidence"
> criterion is met here: **fully on the success path** (verbatim `stdout`/`stderr` plus the typed
> `ScriptError[]`), **partially on failure paths** — the evidence is there, as labelled prose in
> `diagnostics` and a status named in the message, but it is not typed. That gap is the deferral
> above, not an oversight.

> **Amendment (2026-08-16, #675) — `script run` accepts BOTH script-path forms; the `res://`-only
> scope below is superseded.** That scope rests on a rationale that does not hold: "consistent with
> the rest of the `script` command group (which all act on `res://`)". The rest of the group takes a
> **project-relative** path as well, through the shared path normalization every path-taking command
> uses (ADR-0006, ADR-0015). `script run` alone refused it, so a caller who addressed a script one way
> for `script validate` had to rewrite it for `script run` (dogfooding GDA-DF-019).
>
> **`script run` now accepts the project-relative form beside `res://`.** A project-relative path is
> lifted onto the scheme it is already relative to — the `res://` root of the resolved `--project`
> (ADR-0006) — and then put through the same `canonical_res_path` the amendment above introduced. Both
> spellings therefore converge on **one** address before any launch, so the argv handed to the engine,
> the entry-load verdict matching, and every message keep the single canonical identity that amendment
> established. No second normalization rule is added.
>
> **The success result gains a `path` field** carrying that canonical `res://` address. A caller who
> addressed the script project-relatively reads back what the engine was actually asked to run —
> otherwise the accepted form and the form every failure message quotes would differ with nothing to
> connect them. This is a schema addition in ADR-0004's sense, moving with the implementation.
>
> **Amendment (2026-08-31, #697 / #763) — the upward escape leaves this ABI edge for the
> shared containment code, and the resolved project must OWN the script.** Two changes, both
> from ADR-0006's amendment of the same date.
>
> The path gate below refuses seven shapes as `invalid_path`. Six are questions about the
> FORM of an address and stay exactly as recorded. The seventh — a path **escaping above the
> root** — is not a spelling question but the containment question every path-taking command
> asks, so it now reports `target_outside_project`, the code `script validate` and
> `resource import` report for the same condition, and it reaches that verdict through the
> shared rule (`gda.project.res_escape_remainder`) instead of a copy of it. The gate itself
> returns the refusal rather than `None`, so each shape carries its own code. Because the
> whole path edge is decided ahead of the projectless check, this one refusal names no
> resolved root and carries no typed evidence — it has neither.
>
> Second: after the project resolves, `script run` also requires it to be the script's OWNER
> — no nearer `project.godot` between the two. The lexical gate cannot see one, and running
> against the outer root would resolve the script's own `res://` references against a root
> that is not its own. One rule, two commands, one code.
>
> **What stays refused**, all decided before any launch as `invalid_path`: an **absolute** path;
> **another engine scheme** (`user://`, `uid://` — lifting one would splice a second scheme into a
> res:// address and send the engine after a path nobody typed); a leading `~` (a filesystem HOME
> reference, including an unresolvable one); a path naming the project **root** (`""`, `"."`,
> `"sub/.."`, and the `res://` / `res://.` spellings — a directory, not a script); a canonical address
> ending in a code point at or below **U+0020**, which Godot removes before reporting the path; and a
> canonical address containing any line boundary recognized by `gda.engine_log`'s line protocol.
> The ABI edge below names "a non-`res://` **or absolute** script path"; only its first half is lifted
> here.
>
> The root and escape shapes are refused — the root as `invalid_path`, the escape as
> `target_outside_project` — for a reason beyond tidiness, and both were **verified**. The
> engine
> answers a root or escape address with `Can't load script: res://.` / `res://..`, whose address the
> error parser reads back with the sentence period stripped — so it never matches the entry, the
> never-ran verdict misses it, and the run reports a phantom `exit_status: 0`. Worse, an escape that
> *resolves* (`../outside.gd`) **executes a script outside the project**, which is precisely the
> ADR-0009 widening cited just below as the reason absolute paths stay refused; admitting it by the
> relative spelling would make that reasoning false. Both shapes are reachable on the pre-amendment
> `res://` spelling too, so this closes a pre-existing hole rather than one the widening created — but
> the widening is what made them reachable from the ordinary project-relative form, so they are closed
> here. The residual parser weakness (a trailing-period strip that mis-reads `res://..`) is **not**
> addressed here; it belongs to the error parser and is tracked separately.
>
> **Path-identity boundary (2026-08-28, #698 review).** The two character rules above preserve the
> same canonical identity on both sides of the entry-load verdict. Godot 4.6.3's
> `String::strip_edges()` removes trailing code points at or below U+0020; Python `str.rstrip()` is
> intentionally not the rule because it additionally removes Unicode spaces such as NBSP (U+00A0)
> and EM SPACE (U+2003), which Godot preserves. Separately, `gda.engine_log` parses engine output with
> `str.splitlines()`. Any address containing one of those line boundaries is therefore impossible to
> recover from one diagnostic record and is refused before launch. Leading and internal ASCII spaces,
> and Unicode spaces that Godot preserves, remain valid project-relative characters.
>
> **Outcome (2026-08-27, #698):** the error parser's `_CANT_LOAD` regex (`gda.script_errors`) no
> longer strips a genuine trailing dot. It mirrors `main.cpp:4271`, which never appends sentence
> punctuation, so any strip was always wrong; the strip is dropped, so `Can't load script: res://..`
> now round-trips to `res://..` instead of the `res://.` mis-read this paragraph describes. The
> sibling `_FAILED_LOADING_RESOURCE` regex was tightened too (its strip is now mandatory rather than
> optional, mirroring `resource_loader.cpp:343`'s guaranteed trailing period), but — verified — its
> old optional strip never actually mis-read a well-formed captured line, for any dot count; that
> change is a fail-closed robustness improvement, not a fix for observed corruption. Neither change is
> a general longest-candidate heuristic.
>
> Adversarial review of the #698 PR found a second, independent defect in the same two regexes: their
> path capture was `\S+`, which cannot match a SPACE, so a project-relative path containing one
> (`res://missing file.`) failed the WHOLE line rather than losing a character — no diagnostic at all,
> so `entry_load_failure` found nothing and the run reported a phantom success. Pre-existing on `main`
> before #698 (its `\S+?\.?$` could not match a space either) and masked whenever the path also
> carried a recognized extension (`_OPEN_FAILED`'s quoted capture is space-safe), so it surfaces only
> on an extension-less spelling. Both regexes now capture `.+` — `gda.engine_log` has already split
> stderr into lines before either regex sees one, so `.+` cannot run past the line it belongs to — and
> genuinely capture to end of line unconditionally, which is what this outcome note now describes.
>
> The refusals this decision records stay in place regardless of either parser fix — they are
> load-bearing for reasons beyond the parser weakness (ADR-0009's Trusted project, above) — but the
> parser itself no longer mis-reads a dot-terminated or horizontal-space-containing `res://` address if
> a
> future route ever reaches it again.
>
> Absolute stays refused for two **verified** reasons, not merely as deferred scope. First, the engine
> reports a failed run under the **`res://` spelling even when launched with an absolute in-project
> path**, so accepting absolute without also mapping it back to `res://` would break the
> canonical-identity match the verdict above depends on and reopen the phantom success it closed.
> Second, `--script <absolute path OUTSIDE the project>` really **does execute** (verified against
> Godot 4.6.3), so accepting absolute would widen the
> [Project-code execution surface](../../CONTEXT.md) past ADR-0009's Trusted project — a trust
> decision that belongs in its own ADR, not in a path-form amendment. `script validate` does accept an
> absolute path today, so the two commands are **not** at full parity; the shared representation this
> amendment establishes is the two **portable** forms, which is what an agent needs to address a
> script once and use it for either.
>
> The `script validate` result still echoes the path spelling it was given, as every sentinel
> operation does. Making one operation report a canonical form would trade this inconsistency for a
> different one, so it is left alone deliberately; the convergence decided here is `script run`'s,
> whose path must be canonical because its verdict machinery matches on it.

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

> **Amendment 2026-08-17 (#653).** The shared `launch()` primitive this decision reuses has since
> grown a third responsibility, so what `script run` inherits from it is wider than described
> above. `launch()` now also owns each launch's **`User-data placement`**: it always passes a
> gda-owned `--log-file` (Godot builds its file logger before any project code and dies with
> signal 11 if it cannot open the log; the engine default is additionally one per-project rotated
> file that concurrent invocations contend over), and it preflights that placement by creating it.
> Two consequences for this ADR's own contract, neither of which changes the passthrough decision:
> the argv is `[binary, --headless, --log-file <path>, *args]` rather than `[binary, --headless,
> *args]`; and `Raw run.launch_failure` has a third value, `USER_DATA_UNWRITABLE`, which — like the
> existing two — is lifted out of the promoted `script run` success result into an `Error envelope`
> (`user_data_unwritable`). The per-invocation `--user-data-root` also makes `user://` writable for
> a `script run` under a restricted profile. See CONTEXT.md's `User-data placement` entry for the
> shared-language definition.

> **Amendment 2026-08-17 (#655) — a run `gda` ends reports what it captured, and a
> caller may declare when a run is not worth waiting out.** Two dogfooding defects, one
> cause. A script error aborted a test before its `quit()`; the engine stayed alive, and
> after the fixed 120s ceiling the `launch_timeout` envelope contained only the timeout
> message — although Godot had printed the error within a second (GDA-DF-012). And a
> healthy suite that grew past the same ceiling was indistinguishable from a hang: no
> partial output, no elapsed data, and no way to raise the limit (GDA-DF-032). The
> passthrough decision below is unchanged for every run that COMPLETES; this note covers
> only the runs gda itself ends.
>
> **1. The `Headless launch` gains a second capture strategy.** The discard was in the
> shared primitive: its **buffered** strategy captures with one `subprocess.run` call, which
> throws the child's output away when the timeout expires. It now also offers a **streaming** strategy,
> selected by the channel passing a watch — both pipes read as they arrive, decoded with
> one incremental UTF-8 decoder so a chunk boundary inside a multi-byte sequence does not
> corrupt a character. Verified against Godot 4.6.3 while building this: the engine's
> stdout and stderr *do* arrive incrementally (the banner at ~0.1s, a script error at
> ~0.2s), gda's own `--log-file` does not divert stderr, and a `SIGTERM` makes the engine
> exit through its normal shutdown and flush. What made an earlier attempt look
> block-buffered was reading with `BufferedReader.read(n)`, which blocks until it has *n*
> bytes; the read is on the raw descriptor for that reason.
>
> The streaming strategy owes one guarantee the buffered one gets free from
> `subprocess.run`: a launch must never **outlive** its gda process. Reaping the child is
> therefore unconditional — on the deadline, on an early abort, and on any exception out of
> the poll loop, `KeyboardInterrupt` included, which is the case that matters when gda sits
> in its own process group and the signal never reaches the engine. Left on the happy path
> it would orphan exactly the runs this strategy exists for: ones that do not stop on their
> own, so an orphan idles forever and repeated interruptions accumulate engines contending
> over `user://`.
>
> `script run` uses the streaming strategy; the **sentinel and export channels keep the
> buffered strategy, with their defaults and their published timeout diagnostics
> byte-identical**. Moving them across is named follow-up work, deliberately not folded
> in: their timeout results are part of their own error envelopes. Both strategies return
> through one shared timeout / launch-failure mapping, so the taxonomy still has one home.
> `Raw run` consequently gains `elapsed_seconds` (streaming only) and `launch_failure`
> gains a fourth value, `ABORTED`.
>
> **2. `--timeout` replaces the fixed ceiling.** Per-invocation, defaulting to the
> previous 120s, honored and reflected in the failure. It is a params field, not an argv
> flag, so a JSON/MCP caller reaches it too (ADR-0015) — a knob only argv could turn would
> have left gda-mcp on the defect.
>
> **3. The timeout envelope carries the run's evidence.** Still `launch_timeout`: the
> condition is exactly the one that code names, and this ADR already recorded this path
> under it, so the code is reused and the message discriminates (ADR-0002). What it now
> carries is the captured partial output — tail-capped at a fixed **16 KiB of UTF-8 bytes**
> per stream, stated in the message (a character cap of the same number let non-ASCII output
> through at 3-4x the intended size, so a bound meant to keep the payload small did not) —
> under the same `--- script stdout ---` /
> `--- script stderr ---` labels `--strict` uses, plus the elapsed wall clock, one
> **termination phase** (`launched` / `output_seen` — the third phase of the closed
> set, `aborted_on_error`, travels only on point 4's `script_aborted`, never on this
> envelope), and the recognized script errors. Those errors are read with the
> **existing** parser stack (`gda.engine_log` through `gda.script_errors`), so the lines
> an agent sees on a timeout are the lines it sees on a completed run; nothing is parsed
> twice in two ways. A capture whose errors would satisfy the point-1 never-ran verdict is
> deliberately **not** re-verdicted — the shape this decision records as failing "by
> another route" keeps doing so, and narrowing it is a separate decision.
>
> The phases are keyed on whether the engine wrote anything at all, which is the only
> honest signal the capture carries: the version banner means output arriving does not
> prove the *script* started, so `launched` marks the narrower case of an engine that
> never reached its own startup output.
>
> **4. A caller-declared `Completion marker` ends an aborted run early** — the new
> registered `script_aborted` code (operation, exit 4). Whether a run that printed an
> error can still finish is **not decidable by observation from outside the process**:
> a GDScript runtime error aborts only the function that raised it, so a script can
> survive one — *in the entry script itself* — and keep working; and working can look
> exactly like death (blocked in `OS.execute` or a wait, the script consumes no CPU while alive;
> during an `await` the main loop iterates just as an abandoned one does). Review
> falsified both observational rules tried here on real paired runs: silence-plus-error
> killed a script that completed without a marker, and a CPU-idleness probe both spared
> nothing that blocks (blocking burns no CPU) and silently lost the early abort wherever
> CPU time cannot be read (`ps`-less or restricted hosts, Windows), making the promised
> seconds-bound platform-dependent. So the abort does not claim to detect death. Issue
> #655 originally keyed the kill on "a fatal script error" that "prevents `quit()`" —
> a condition the findings above show is not decidable from outside the process — and
> was therefore **explicitly amended (2026-08-18, its "Amendment — completion-marker
> semantics" section) to define the deterministic form of the same intent**, which this
> ADR implements: declaring the marker is the caller asserting the script keeps
> producing output until the marker line says it finished. The decision is a pure
> function of the observed text and the clock — deterministic and identical on every
> platform — and all three of these must hold:
>
> 1. a recognized error **attributable to the entry script** has appeared on stderr —
>    decided by reusing `entry_load_failure` plus a `RUNTIME_ERROR` naming the entry's
>    canonical `res://` path, so an error about some *other* resource (a `load()` the
>    running script survived) says nothing and arms nothing. Attribution is how this
>    ADR operationalizes the issue's "fatal script error": GDScript exposes no
>    observable fatal/recoverable distinction, so the entry's own trouble is the
>    narrowest honest arming condition;
> 2. the declared marker has **not** appeared. This is the opt-in: this ADR rejected
>    imposing a gda-owned sentinel wrapper on a user-authored entry script, so gda cannot
>    know a run "should" have finished — only the caller can say what finishing looks like.
>    With no marker declared the watch never aborts and the ceiling is waited out as
>    before. **This is not the ADR-0002 op-dispatch sentinel**: that is gda's contract with
>    its own `operations.gd` payload; a marker is an arbitrary caller *line*, compared by
>    whole-line equality (substring matching let `NOT DONE YET` count as the marker `DONE`
>    and silently disarm the abort) and read for one boolean;
> 3. neither stream has produced output for a fixed 3s — the contract's liveness bound,
>    reset by any output line.
>
> The contract's price is stated where the caller declares it, not hidden: a script that
> survives an entry-attributable error and then works past the bound in **total silence**
> is ended even though it would have finished. That is the declared semantics — the
> caller's escape hatches are to print progress during quiet stretches (any line resets
> the window) or to omit the marker and wait out `--timeout`. This ADR records the
> falsified alternatives above so the CPU probe is not reintroduced as an "improvement":
> any rule that tries to spare a silent contract-violating run reopens both failure
> directions review demonstrated.
>
> `script_aborted` is minted rather than reused because no registered code names the
> condition. `launch_timeout` would be untrue (gda did not wait, it decided not to);
> `script_failed` means "ran to completion and chose a non-zero status", is recorded as
> never reported without `--strict`, and sends an agent to read a status that does not
> exist here; the point-1 verdicts say the entry never loaded, and here it loaded and ran.
>
> **5. All of it is prose.** The elapsed time, the phase and the error lines live in the
> failure's `message` and `diagnostics`, not in structured envelope fields — the same
> constraint the #651 amendment records above, and the same deferral: **#687 owns** the
> ADR-0004 envelope decision, and this change adopts its outcome rather than pre-empting
> it. The gap named at the end of that amendment is therefore unchanged in kind, only
> narrowed in content: a failure path now carries far more evidence, still untyped.

> **Amendment (2026-08-26, #665) — the success result's `stdout` is bounded, the ONE
> qualification of the verbatim passthrough.** Production-scale dogfooding
> (GDA-DF-036) showed a project inspector's stdout growing linearly with content
> (1,128 → 1,288 all-passing per-frame records), and an envelope that grows with the
> project blows the consuming agent's context. Above a 64 KiB cap the returned
> `stdout` is the stream's LEADING cap bytes (cut on a UTF-8 boundary) and the
> COMPLETE stream spills to a gda-named file; three always-present result fields
> disclose it — `stdout_bytes` (the full stream's size, reported whether or not
> truncation happened), `stdout_truncated`, and `stdout_file`
> (required-but-nullable). Bounded, not summarized: gda still does not parse or
> interpret the script's output — record semantics stay with the project tool
> (per-file aggregate verdicts are #663's surface) — and nothing is lost, since the
> spill file holds every byte. **The bound is unconditional** (PR #748 review): a
> spill file gda cannot create or complete is the registered typed failure
> `stdout_spill_failed` — never an unbounded success and never a silently lost
> tail — whose message carries the run's forensics (it DID run, with its exit
> status and full byte count) and the TMPDIR remediation; a post-create failure
> releases the descriptor and unlinks the partial file before failing. `stderr`
> and the failure envelopes' partial-output evidence keep their existing shapes.

> **Outcome (2026-08-31, #714) — the buffered strategy is gone; every channel streams.**
> The 2026-08-17 amendment above recorded the sentinel and export channels staying on the
> buffered capture, with their published timeout envelopes byte-identical, and named moving
> them as follow-up work. That follow-up landed. Three channels moved, not two — the
> `resource import` engine pass calls the same primitive and classifies through the same
> branch — which left the buffered strategy with no caller and it was deleted, so a future
> channel cannot be silently left on the discard. The shared `launch_timeout` branch
> (`classify_launch_or_crash`) now builds the envelope for all three: the captured partial
> output under `--- captured stdout ---` / `--- captured stderr ---` (the script-run labels
> above are untrue of an export or an import pass), tail-capped at the same 16 KiB per
> stream, plus the elapsed wall clock and the ceiling that was reached. Both ride the
> `Raw run` — the wall clock in its existing `elapsed_seconds`, the channel label and
> ceiling in the new `timeout_bound` — because the runner seam hands a classifier a raw
> run and nothing else. `script run` and `scene preflight` are unchanged: each still classifies its
> own timeout, since each carries something the shared branch cannot know (a termination
> phase and the recognized script errors; a `timeout` STATUS that is the command's answer).
> The `--- script stdout ---` labels, and every non-timeout envelope, keep their bytes.

> **Outcome (2026-08-31, #716) — the "failure by another route" shape is decided, and
> not here.** The #651 amendment at the top of this ADR records a `script run` whose
> entry never loaded reaching `launch_timeout` rather than a #651 verdict — "a failure
> by another route". Whether the captured stream should NARROW it is deferred a step
> later, in point 3 of the 2026-08-17 (#655) amendment: "narrowing it is a separate
> decision". Since #714 that shape belongs to four channels rather than one, so the
> decision was taken where all four are governed: the captured stream stays ADVISORY
> and never re-verdicts the timeout. The reasoning, and the
> sibling decision that the code keeps its `environment` category, are in ADR-0002's
> `Outcome (2026-08-31, #716 / #717)` note beside the `launch_timeout` registry row;
> they are not restated here. `script_run_timeout_failure` is unchanged in verdict, in
> code and in its three numbers; what it gained is one clause SAYING the rule, because
> this is the channel where it matters most — its diagnostics open with "recognized
> script errors seen before the timeout", so it is the one envelope that hands an agent
> a parsed #651-shaped cause under a timeout verdict. (The shared builder for the other
> three channels gained the same clause, plus the caller-first remediation order this
> channel's message already had.) Typed delivery of those parsed errors — which serves
> the same need better than a re-verdict would — remains #687's.

> **Outcome (2026-08-31, #687) — the deferral above is settled: ADOPTED.** The two
> amendments that named #687 promised this channel's envelope would adopt whatever it
> decided; it decided to carry typed evidence, so the promise is now discharged rather
> than left open. The shape, the criterion for what may enter it, and the boundaries
> are recorded ONCE in
> [ADR-0004's `Amendment (2026-08-31, #687)`](0004-schema-flag-self-description.md) and
> are not restated here. What changes for `script run`:
>
> - The child's numeric **exit status** is data on `--strict`'s `script_failed`
>   envelope, not only message prose — the asymmetry that argued for it is this ADR's
>   own: the very same run WITHOUT `--strict` returns a typed `exit_status` on its
>   success result, so opting into the flag used to cost the caller a parsed value.
> - The **parsed `ScriptError[]`** rides every failure of this channel — the point-1
>   verdicts (`script_not_found` / `script_compile_failed` /
>   `incompatible_script_type`), `--strict`'s `script_failed`, and both gda-ended
>   runs — as the WHOLE list, not only the entry-load error that decided the verdict.
>   The rest of the list is frequently the real cause (a dependency that would not
>   preload). Note the set is wider than "failures decided from stderr": only the
>   point-1 verdicts are decided that way, `script_failed` is decided from the exit
>   status and the two gda-ended runs from the clock and the silence watch — they
>   carry the parsed list because it exists, not because it decided anything. The
>   records keep the same four keys they have on the success result, `path` / `line`
>   null where the engine named neither.
> - The **elapsed clock, the ceiling and the termination phase** are data on the two
>   gda-ended envelopes, and `TerminationPhase` moved out of this command into the
>   shared model: every launch-backed channel's `launch_timeout` reports it now, so it
>   is a property of the envelope rather than of `script run`.
>
> Two things deliberately did NOT change. The **prose is kept byte-for-byte** —
> `diagnostics` still opens with the recognized errors and carries both labelled
> streams, rendered from the same single parse the typed key carries — so this is
> additive for every consumer that reads it. And the `launch_timeout` verdict is
> **still not re-verdicted** by a recognized error in the capture: ADR-0002's
> `Outcome (2026-08-31, #716 / #717)` note stands unchanged, and typed evidence is
> what makes it comfortable to leave standing — the honest verdict now ships with the
> precise cause attached.

> **Outcome (2026-09-05, #850) — the promoted Raw run also carries WHERE the run's
> user data was.** The 2026-08-17 (#653) amendment above records `launch()` taking
> over each launch's `User-data placement` and notes that `--user-data-root` makes
> `user://` writable for a `script run` under a restricted profile. What it did not
> give the caller was any way to READ that: the placement was prepared and dropped
> inside the primitive, so only the `user_data_unwritable` refusal ever named it, and
> a persistence-bearing run whose `user://` write failed kept being diagnosed as a
> game regression (GDA-DF-049, PIPE-DF-077). The `Raw run` now carries the placement
> out of the launch — the root, the platform-derived data path, and the log file —
> and this ADR's promotion publishes it as three flattened keys, so the promoted
> shape is `{path, exit_status, stdout, stderr, stdout_bytes, stdout_truncated,
> stdout_file, diagnostics, engine_data_path}` plus `user_data_root` and `log_file`
> where they apply.
>
> Which keys apply is decided by what is a FACT, not by what is convenient:
> `engine_data_path` is required-but-nullable (null means the platform's own
> variable is unset, which gda reports rather than guessing a path);
> `user_data_root` is present only when a root was given, and `log_file` only then
> too — by default the log is a private temporary file the launch removes on the way
> out, so naming it would hand a caller a dangling path. Both are **omitted, never
> null**, which is also what keeps a default run's result byte-identical to what it
> emitted before this change.
>
> Three boundaries. The facts come from the ONE launch primitive and are read off
> the raw run; `script run` resolves no root and derives no data path of its own, so
> it cannot report a placement the run did not have. This stays the ONE channel that
> publishes them: `scene preflight`, `export run`, `resource import` and every
> sentinel command take the same facts off the same raw run and disclose none, so
> their results are unchanged (a registry test holds them to it). And it is the
> SUCCESS result alone: this channel's failure envelopes — `--strict`'s
> `script_failed`, the two gda-ended runs — keep the shape the #687 outcome above
> gave them, because putting `engine_data_path` on an Error envelope means extending
> ADR-0004's `Failure evidence` producer set, a decision that ADR owns and that #850
> did not scope. The follow-up is named rather than taken here. The human rendering
> is unchanged too — `script run` without `--json` stays the script's own output, per
> this ADR's passthrough decision.
