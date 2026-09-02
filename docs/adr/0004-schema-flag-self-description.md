---
status: accepted
---

# `--schema` is self-description, not a caller-supplied contract

> **Outcome (2026-06-22, #230 / PR #232):** the per-command `--schema` object
> gained a fourth, additive key — `kind`, the command's static `ExecutionKind`
> (`headless` / `export` / `live`, ADR-0017) — alongside `input` / `output` /
> `error`. Like the `{input, output}` → `{input, output, error}` move described
> below, this is a strict superset: `gda-mcp` still maps only `input` / `output`,
> so it stays backward compatible (ADR-0012). `kind` is `null` only for a
> self-description emitted without a backing command (e.g. `gda schema --schema`);
> in the aggregate manifest (ADR-0012) every dispatchable entry's `kind` is
> required and enum-constrained. The enum has since grown two
> self-description-only values on the ADR-0031 migration pattern: `script_run`
> (ADR-0031) and `import` (#668, the native project-wide `--import` pass behind
> `resource import`).

> **Outcome (2026-06-22, #233 / PR #245):** the per-command `--schema` object
> gained a fifth, additive key — `constraints`, the command's
> `LiveStackConstraints` (platform set + minimum Godot version) for
> live-stack-dependent commands, `null` otherwise. The platform/version values
> are decided in ADR-0021 and now surfaced **structurally** rather than in
> `--help` / manifest prose, sourced from the single
> `gda.execution.live_stack_constraints` predicate so the structured field and
> the surrounding prose cannot drift. Like `kind`, gda-mcp ignores it (ADR-0012),
> so it stays a strict superset — backward compatible.

> **Amendment (2026-08-16, #667):** the uniform failure envelope (`GdaError`, the
> `error` half of every command's `--schema`) gains ONE optional key — `probe`, an
> `EnvironmentProbe` `{name, platform}` naming the host call that decided an
> ENVIRONMENT failure `gda` resolved by probing the machine rather than by running
> the engine (`CGSessionCopyCurrentDictionary`,
> `bootstrap_look_up(com.apple.windowserver.active)`, `$DISPLAY / $WAYLAND_DISPLAY`).
> Motivation: `--windowed` refusals had two causes — no window server was detected
> (`live_windowed_unavailable`), versus the window-server lookup was REFUSED
> (`live_windowed_permission_denied`, which proves confinement, not that one exists) —
> distinguishable only by reading English prose, so automation recorded a sandbox
> boundary as a machine-capability gap and silently skipped rendered QA (dogfooding
> GDA-DF-029).
>
> Three properties keep it additive:
>
> - **Optional and OMITTED, never `null`.** `emit_failure` serializes with
>   `exclude_none`, so every failure that sets no probe emits byte-identically to
>   before. Only the two windowed-refusal codes — `live_windowed_unavailable` and
>   `live_windowed_permission_denied` — set one today.
> - **The stable trio is untouched.** `category` / `code` / `message` (and
>   `diagnostics`) keep their contract; `probe` is context ABOUT the classification,
>   never a substitute for branching on `code`. `gda-mcp` passes the envelope through
>   to its `is_error` channel unchanged and needs no adapter work (ADR-0012).
> - **Schema-derived, zero per-command cost.** `error` is still the one shared
>   `GdaErrorEnvelope` schema, identical for every command — it changed once, for all.
>
> **Scope boundary with #687.** #687 owns the separate, larger decision on whether the
> failure ABI carries operation-scoped typed EVIDENCE — a script's numeric exit status,
> parsed `ScriptError[]`, a timeout's elapsed seconds (#651, #655). This amendment
> deliberately does NOT decide that and does not pre-empt its shape: `probe` answers
> only "which host call decided this environment verdict", a fixed two-string context
> with no per-operation variation. The two axes compose — an evidence key adopted by
> #687 would sit alongside `probe` under the same "optional keys are omitted when
> absent" rule established here — and #687 stays free to adopt, reshape, or decline
> typed evidence on its own merits.
>
> **Carried on the daemon relay too** (revised on review, 2026-08-17). The refusal
> that actually gates every live op is the daemon's lazy-launch guard, not the CLI's
> optional fail-fast, so leaving `probe` off the relay made the AUTHORITATIVE path the
> poorer one — and #667's acceptance criterion is unqualified. The live channel's
> envelope therefore takes the same optional key: `LiveError` is `{code, message,
> probe?}` and `classify_live` carries it into the public `GdaError`.
>
> The two channels keep **separate models**, which is what keeps this narrow: the
> headless sentinel (`OperationError`, GDScript-emitted) stays strict, `extra="forbid"`
> and probe-less, because a GDScript operation has no host probe to report and widening
> it would invite a key the other language can never fill. On the wire the key is
> omitted when absent, so every other live reply and every headless envelope is
> byte-identical to before.

> **Amendment (2026-08-18, #670):** the uniform failure envelope gains a SECOND
> optional key — `hint`, a string naming the supported invocation to run instead
> (`"gda scene get"`, `"gda schema"`, `"gda script run <path>"`). Motivation: an
> unrecognized command or option used to leave this contract entirely, as prose on
> stderr, so an agent that mistyped had nothing to branch on and no pointer at the
> working sibling (dogfooding GDA-DF-024/025/032/033/041). The correction is the one
> thing such a caller has to retype, so it is carried as a value rather than embedded
> only in a sentence.
>
> It is additive on the same three properties the #667 amendment above established,
> and deliberately mirrors them:
>
> - **Optional and OMITTED, never `null`** — the same `exclude_none` emit path, so
>   every failure that sets no hint emits byte-identically to before.
> - **The stable trio is untouched.** `hint` is guidance ABOUT the refusal, never a
>   substitute for branching on `code`; `gda-mcp` passes the envelope through
>   unchanged (ADR-0012).
> - **Schema-derived, zero per-command cost** — still the one shared
>   `GdaErrorEnvelope` schema, changed once for all.
>
> Two boundaries. **It is set only where gda RECOGNIZES the mistake**, from the
> curated table in `src/gda/hints.py` — never from a string-similarity guess, which is
> silent when the spelling is not close and can name a different operation than the one
> meant. And it stays on the **CLI-side** envelope: neither GDScript surface emits or
> reads it, so `OperationError` stays `extra="forbid"` and the live `LiveError` is
> unchanged. The registry side of the same change — the `usage` category, `EXIT_USAGE`,
> and the two codes that carry a hint — is recorded in
> [ADR-0002's scope note](0002-headless-structured-output-contract.md) with its table
> rows; this note is the envelope-shape half.
>
> **Scope boundary with #687** is unchanged by this: `hint` is CLI-layer guidance for
> an invocation gda could not resolve, not operation-scoped typed EVIDENCE of a failure
> an operation reported. The two compose under the same omitted-when-absent rule, and
> #687 stays free to decide its axis on its own merits.

> **Amendment (2026-08-18, #669):** the per-command `--schema` object gains a SIXTH,
> additive key — `argv`, the list of `ArgvBinding`s naming how each parameter `input`
> describes is written on a command line (`kind` positional/option, `position` or
> `option` spelling, `required`, `flag`, `multiple`, `json_value`, and the
> `input_property` it fills). Motivation: the contract stated a command's required fields but not their
> CLI spelling, so an agent could not build argv from it — `screen capture` takes its
> required output as `--output`, `input mouse-click` takes `x y` positionally, and
> `input action` takes a positional ACTION it rejects as `--action` (dogfooding
> GDA-DF-003). The self-description was accurate and still insufficient.
>
> It is additive on the same properties the notes above establish:
>
> - **A sibling of the schema halves, never a key inside them.** Adding the key
>   leaves `input` / `output` byte-identical — a test emits each command's contract
>   with and without the bindings and requires both halves to match — so gda-mcp's
>   `input_schema` / `output_schema` are unchanged by it and it needs no adapter
>   work; it maps only `input` / `output` / `description` (ADR-0012). Measured
>   across the whole surface at the time of the change, exactly one `input` differs
>   for an unrelated reason (`input sequence`, whose own params model became a
>   per-kind union in the same PR), and no `output` / `error` / `description` /
>   `kind` / `constraints` differs at all.
> - **Derived, never declared.** The bindings are read off the LIVE Typer/Click
>   parameters at emission time, through one projection shared by the per-command
>   `--schema` and the aggregate manifest (ADR-0012's live-tree walk, ADR-0023 §2).
>   An `argv` field on the `HeadlessCommand` descriptor was rejected: a
>   hand-maintained spelling table is a second authority for a fact the Typer
>   signature already owns, and it would silently rot the moment a signature changed.
>   Reading the registered parameters also makes it correct on every dispatch channel
>   at once — the sentinel path, the EXPORT / LIVE kinds, and the recipe commands.
> - **Zero per-command cost**, like the halves it joins: a new command's spelling
>   appears because it registered parameters, not because anyone wrote it down. The
>   binding expresses a positional, an option, a valueless flag, a repeated value
>   and a JSON-encoded one; a registration test fails if the surface ever grows a
>   Click shape it cannot write (a `--x/--no-x` pair, an n-ary option, a counting
>   option), so the contract is extended deliberately rather than emitting a
>   binding no caller can follow.
>
> Two boundaries. `argv` covers the OPERATION parameters — the same set
> `--params-json` treats as exclusive of the individual arguments (ADR-0015) — so the
> cross-cutting flags every command shares (`--json` / `--schema` / `--params-json` /
> `--godot` / `--project`) stay out; they are not per-command information. And
> `input_property` is `null`, not guessed, where a parameter's property is revealed
> by neither its name nor its long option: a wrong link would read as authoritative.
> The surface has **no such parameter** — where an option renames the property it
> fills (`project list --all` → `include_defaults`, `skill --dir` → `install_dir`)
> the Python parameter carries the property's name, so the link resolves — and a
> test holds that every **directly supplyable** property has a binding. The nullable
> value stays part of the contract for a future parameter that cannot be resolved,
> rather than being forced into a guess. The one exemption from that guard is a
> property the CLI COMPUTES rather than takes (`script set`'s and `shader set`'s
> `mode`, from `--replace` / `--search`), which its own description declares. On the
> aggregate entry the `argv` key is required, its list possibly empty — the same
> "key always present" guarantee `constraints` has.

> **Amendment (2026-08-31, #687) — ADOPTED: the failure envelope carries typed
> EVIDENCE, as a THIRD optional key of one universal shape.** This is the decision
> the #667 and #670 notes above reserved for #687, and it is decided the way they
> framed it rather than the way #687's first triage recommendation proposed.
>
> **What was wrong before.** On a failure gda had already computed the facts a caller
> needs and then published only prose. `script run --strict` parsed the run's
> `ScriptError[]`, used it to decide the verdict, and threw it away — the same run
> WITHOUT `--strict` returns those errors typed on its success result, so opting into
> the flag cost the caller the parsed cause and forced it to read the child's exit
> status out of an English sentence (#651, and #651's own scope-reconciliation
> comment). A `launch_timeout` names its ceiling, its elapsed clock and its
> termination phase in a sentence and asks the caller to compare them (#655, #714).
> Both facts existed as values; neither could be branched on without parsing prose.
>
> **The shape: ONE key on the ONE shared envelope, not a per-command `error`
> schema.** `GdaError` gains `evidence`, a `FailureEvidence` object. The variability
> that a per-operation shape was reaching for lives INSIDE that object — every field
> is individually optional and omitted when absent, so a timeout populates the clocks
> and phase while a strict script failure populates the child's status, without
> either being a different `error` schema. A per-command `error` was rejected as out
> of scope and wrong: this ADR fixes `error` as "the one shared `GdaErrorEnvelope`
> schema, identical for every command", which is what lets a consumer learn the
> failure shape once; overturning it is a far larger decision than #687 was scoped to
> make, and it would silently undo the property the three-key contract bought.
>
> Additive on exactly the three properties #667 and #670 established:
>
> - **Optional and OMITTED, never `null`.** The same `exclude_none` emit path, and
>   recursive — the fields inside `evidence` are dropped by the same rule — so every
>   failure that computes no evidence emits byte-identically to its pre-#687 bytes. A
>   regression test builds a failure for EVERY registered code through the shared
>   builder and requires the four-key envelope, so the property is pinned across the
>   registry rather than sampled.
>
>   **The rule stops one level down, at a nested model that is also published on a
>   success result** (added by this PR's review). `evidence.script_errors` carries
>   `ScriptError`, the same model `script run` returns as its success `diagnostics`
>   and whose published `path` / `line` say "or null". Letting the filter recurse into
>   the records rendered the SAME error with two different key sets depending on which
>   half of the contract a caller read it from — four keys on success, two or three
>   inside `evidence` — while one `$defs/ScriptError` describes both. The
>   omitted-never-null rule exists to buy byte-identity for the failures that compute
>   NO evidence; it was never a claim about a nested model's published shape, so the
>   nested records keep their full key set and a record reads the same everywhere. Any
>   future nested model that is also published on a success result gets the same
>   treatment.
> - **The stable trio is untouched.** `category` / `code` / `message` (and
>   `diagnostics`) keep their contract. `evidence` is the evidence BEHIND a verdict,
>   never a substitute for branching on `code` — in particular a recognized error
>   carried under a `launch_timeout` stays ADVISORY and does not re-verdict the
>   timeout, which is the rule [ADR-0002's 2026-08-31 note](0002-headless-structured-output-contract.md)
>   records for #716. That note deferred "the cause as DATA" to this decision; this
>   is what makes the rule workable rather than merely stated, because the honest
>   verdict now ships WITH the precise cause rather than instead of it.
> - **Schema-derived, zero per-command cost** — still the one shared
>   `GdaErrorEnvelope` schema, changed once for all; `gda-mcp` passes the envelope
>   through to its `is_error` channel unchanged and needs no adapter work (ADR-0012).
>
> **What may enter it.** This paragraph is the AUTHORITY for the criterion; the
> restatements beside the code (`gda.models`) and in `CONTEXT.md` are reader's copies
> that point back here. The fact must ALREADY be computed on the failure path, be
> unrecoverable from the envelope without parsing prose, and change what the caller
> does next. The first five fields are `exit_status` (the CHILD's status on `script
> run --strict`, never gda's own registry exit code), `elapsed_seconds`,
> `timeout_seconds`, `termination_phase` (`launched` / `output_seen` /
> `aborted_on_error` — a closed enum promoted out of `script run` because every
> launch-backed channel now reports it), and `script_errors` (the parsed
> `ScriptError[]` of #651). The criterion is what keeps `script run`'s silence window
> and declared completion marker OUT: both are the caller's own inputs, so neither
> tells it anything it did not already know. The same ground keeps the UNREACHED
> ceiling off `script_aborted`: an abort stops short of its `--timeout`, so that value
> is the caller's own input, not a fact the run measured — `timeout_seconds` ships
> only where the ceiling was reached and is the verdict. The captured streams stay in
> `diagnostics` alone for the same kind of reason — copying two 16 KiB captures into
> the object would double the payload to say the same thing twice.
>
> `script_errors` has **three** states, not two, and the middle one is deliberate:
> ABSENT means this failure's channel does not parse stderr at all (the shared
> `launch_timeout` builder), so the caller reads `diagnostics`; `[]` means it parsed
> and recognized nothing, which is itself a finding — a run that died without saying
> anything gda knows how to read; a populated list is what it recognized. Collapsing
> `[]` to absent would erase that distinction, so the emit path keeps it.
>
> **Who carries it today — this decision's recorded boundary.** Seven builders in
> `gda.errors`: `launch_timeout_failure` (the shared one, so every launch-backed
> channel), `script_did_not_run_failure`, `script_exit_status_failure`,
> `script_run_timeout_failure`, `script_run_aborted_failure`, and — added by
> [ADR-0006's 2026-08-31 amendment](0006-project-context-and-path-resolution.md)
> (#697/#763) — `target_outside_project_failure` and
> `target_owned_by_another_project_failure`. The set is asserted in
> `tests/test_error_registry.py`, read out of the source, so a further producer
> cannot join the axis without this paragraph being revisited in the same change.
>
> The last two are the axis's first producers that are **not** reporting on a run.
> They pass the criterion on the same three clauses: gda has already computed the
> target's location, the root it resolved and (for the owner half) the
> `project.godot` it found, none of the three is recoverable from the message
> without parsing prose, and together they are exactly what the caller re-issues
> with. `script run`'s pre-launch escape (`script_escapes_project_failure`) reaches
> the same verdict holding none of the three and therefore carries no evidence at
> all, rather than a partially invented triple — which is the omitted-never-null
> rule applied to a producer, not an exception to it.
>
> **Answering ADR-0002's open pointer (#717): the ceiling's PROVENANCE is declined, on
> the criterion.** That note left the question here — whether a `launch_timeout`'s
> ceiling was the caller's `--timeout` or one of gda's own fixed bounds "belongs on
> #687's evidence object" if it is ever wanted as data. It does not enter. The fact
> fails the criterion's second clause: it is recoverable without reading anything, from
> the invocation the caller itself made — of the shared builder's channels only
> `resource import` and `script run` expose a `--timeout` at all, so a caller that
> passed one knows the ceiling is its own, and a caller that ran `export run` or a
> sentinel op knows it is not. That makes it the caller's own input, which is the same
> ground the silence window and the declared completion marker are excluded on.
> `timeout_seconds` still ships the ceiling's VALUE, which is not recoverable that way
> and is what choosing the next bound needs; the remedy that follows from the
> provenance is in the message, which since #716/#717 names it for both cases.
>
> Facts that MEET the criterion and are still left in prose, so a later reader can
> tell a decision from an oversight: `scene preflight`'s
> `_ended_before_the_verdict` discards a parsed `ScriptError[]` it already holds;
> `engine_crashed` names the signal only in its message; `resource import` and
> `export run` name the child's exit code only in theirs. #687 scoped to `script run`
> and #655's timeout envelope, and widening the set is a follow-up with its own issue,
> not a silent extension of this one.
>
> **The cost this decision does pay, measured.** "Zero per-command maintenance" is
> not zero per-command PAYLOAD: the one shared `error` schema is repeated once per
> command in the aggregate manifest, so a richer envelope multiplies by the surface.
> Publishing `FailureEvidence` (with `TerminationPhase` and `ScriptError`) takes the
> shared `error` schema from 3,719 to 7,921 bytes, and `gda schema` from 675,342 to
> 979,618 bytes (+45%) across **76** commands.
>
> It was reduced where it could be, and the reduction is worth naming exactly rather
> than gesturing at: the `ScriptError` prose that is a reader's explanation moved into
> comments beside the code, leaving only the branching rules an agent needs in the
> schema `description`s. Without that, the same manifest measures 1,103,083 bytes —
> so the slimming removes **31%** of the growth this decision would otherwise have
> cost.
>
> Two disclosures about what the slimming took with it. First, it is not confined to
> the failure envelope: `ScriptErrorKind` and `ScriptError` are published on the
> SUCCESS results of `script run` and `scene preflight` too, so those two schemas lost
> description text as well — `ScriptErrorKind` 1,288 → 314 bytes (its multi-paragraph
> `description` reduced to its one-line summary), `ScriptError` 1,962 → 1,249. #687
> does not otherwise touch those commands; the reduction is a deliberate price for
> repeating the model 76 more times, not an incidental edit. Second, three reader's
> facts left the schema entirely and now live only in the code comment above
> `ScriptError`: that `path` is canonical in `canonical_res_path`'s sense, that an
> engine-side load error carries no script line at all, and that a `push_error`'s line
> is the engine's own backtrace call site rather than a synthesized number.
>
> The multiplication itself is structural, and the alternative that would remove it
> (emitting the shared envelope ONCE in the manifest and referencing it per entry) is
> a change to ADR-0012's aggregate contract, not this decision's to make. Recorded so
> the next key on this axis is priced before it is added, not after.
>
> Two boundaries. It is **CLI-side**, like `hint`: the GDScript sentinel's
> `OperationError` stays strict, `extra="forbid"` and evidence-less — a GDScript
> operation reports its own code and message and has no launch clock to report — and
> the live `LiveError` is unchanged, since no live failure computes any of these
> facts today. And the prose is **kept, not superseded**: `diagnostics` still carries
> the recognized errors and both labelled streams, rendered from the SAME single
> parse the typed key carries, because `diagnostics` is what a human reads and what
> every pre-#687 consumer already reads. The typed key is additive on the wire and in
> the reading.

ADR-0000 lists `--schema` as a core capability without defining it. We fix its
semantics here, and deliberately scope out an overloaded interpretation.

## Decision

- **`gda <command> --schema` emits the command's own machine-readable contract**: a
  JSON object with three keys — an `input` JSON Schema (the command's
  arguments/params), an `output` JSON Schema (the shape of its **success** `--json`
  result), and an `error` JSON Schema (the **uniform** failure envelope, #43). The
  contract is owned by `gda`; the flag only *emits*, it never *accepts*, a schema.
  (The three-key shape is the original decision. The outcome notes above have
  since grown the object to six top-level keys — `{input, output, error, kind,
  constraints, argv}`: `kind` from #230, `constraints` from #233, `argv` from
  #669. The #667, #670 and #687 amendments evolve fields *nested inside* the
  `error` envelope — `probe`, `hint` and `evidence` — and add no top-level key.)

- **`output` describes only the success result; `error` describes the failure
  envelope** (#43). `output` is the command's own success result model, exactly as
  before — it is *not* turned into a success/failure union. `error` is the shared
  `GdaErrorEnvelope` schema, **identical for every command**, that `gda` emits on a
  non-zero exit. Keeping the two halves separate mirrors how the result reaches the
  caller: a successful `--json` result on exit 0, a structured error envelope on a
  non-zero exit. The change is a strict superset of the old `{input, output}`
  contract — `output` is untouched — so it is backward compatible.

- **Schemas are model-driven.** Each command's input and output are defined as typed
  models (Pydantic/msgspec on the Python 3.13 stack). The same model both serializes
  / validates the `--json` result and produces the `--schema` document
  (`model_json_schema()`), so the contract is never hand-maintained twice. The
  `error` half is derived the same way from the one shared `GdaErrorEnvelope` model,
  so it costs **zero per-command maintenance** — every command's `error` is byte-for-byte
  the same schema.

- **`gda-mcp` derives tool definitions mechanically** from `--schema`: `inputSchema`
  from `input`, `outputSchema` from `output`. The success/failure split maps onto
  MCP's two channels: `output` → MCP `outputSchema` (a tool's success result /
  `structuredContent`), while a `gda` non-zero-exit failure maps to MCP's separate
  `isError` channel. The `error` schema makes that failure envelope **discoverable**
  but is deliberately kept **out of `outputSchema`** — the future adapter must not
  fold `error` into `outputSchema`. This is what makes `gda-mcp` a thin adapter
  (ADR-0001) rather than a parallel hand-written surface.

- **Per-command *operation* error codes are out of scope for the `error` key.** The
  `error` schema is the uniform envelope shape, not an enumeration of which
  `GdaError.code` values a given command can report. Whether `--schema` should also
  advertise a command's specific operation error codes is a separate, later question.

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

- **Emit input + output + error contract** (chosen) — fully self-describing; lets
  `gda-mcp` generate tool definitions for free, and makes the uniform failure
  envelope discoverable for the `isError` channel without per-command cost (#43).
- **Fold the failure envelope into `output` as a success/failure union** (rejected)
  — conflates the two MCP channels: `output` should map to `outputSchema` (success /
  `structuredContent`) only, while failures belong to `isError`. A `oneOf` union
  would force the adapter to discriminate success from failure inside `outputSchema`.
- **Emit output only / input only** — narrower; insufficient for `gda-mcp` to derive
  both `inputSchema` and `outputSchema`.
- **Accept a custom schema on `--schema`** (rejected) — overloads the flag with the
  opposite direction; projection/filtering and external validation are better served
  by other means; caller-declared return shapes belong only to future open-ended ops.

## `--schema` is mandatory for every domain command (hard gate)

Once the mechanism lands on `gda info` (issue #4), every subsequent domain command
ships with a working `--schema` as part of its **definition of done**: a passing
`--schema` test is a merge gate, with **no exceptions**. The cost is near-zero — a
command already defines a typed model to back `--json`, and `--schema` is derived from
that same model — and the no-exceptions rule is exactly what guarantees `gda-mcp` can
generate its entire tool surface mechanically. A single command without a schema would
silently break that guarantee, so the gate is absolute rather than best-effort.

## Consequences

- Adding a new `gda` command means defining its I/O models; `--json` and `--schema`
  then both come for free, and `gda-mcp` picks it up without bespoke work.
- #4 (the `--schema` mechanism on `gda info`) is sequenced **before** any domain
  command slice, so that the self-description gate above is enforceable from the first
  domain command onward.
