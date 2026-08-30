---
status: accepted
---

# Live method calls are declared once per opted-in script chain, in a statically-read constant

> **Outcome (2026-08-28, #752):** the live-number limitation this ADR discloses
> twice below — small floats lost on the request side, and the same loss on the
> shared live-RESULT path — is decided and no longer open. A real-engine
> differential corpus (`tests/live_number_corpus.py`) measured both directions:
> the harness now writes every reply with Godot's full-precision JSON writer,
> which was exact on every corpus row but one — a negative zero, which the engine
> renders `0.0` before the writer's precision argument applies — so the RESULT
> path carries full binary64 apart from that one disclosed residual; and a float
> whose wire literal Godot's parser reads as `0.0` is REFUSED before the send, by
> the base every RELAYED live params model inherits — the ops the daemon answers
> itself never reach that parser — because the corpus shows no decimal spelling
> can deliver it. Values the parser
> does read still arrive changed in their low-order bits, and by more than a
> couple of doubles: the scientific band is tight, while a fixed-notation literal
> can lose its last decimal digits outright, the parser dropping everything past
> its 18th mantissa digit. Disclosed, not refused. The wire format is unchanged,
> so ADR-0021 needed no amendment. See `gda.live_numbers` for the decided
> contract and the measured bands, which this note deliberately does not restate.

`gda game get` reads a running node's stored properties. Dogfooding the kung-fu card
game hit the gap that leaves (GDA-DF-033, #673): a project exposed its debug state as
a METHOD — `qa_current_state_contract()` — and `game get` answered
`live_unknown_property`, so the package's evidence fell back to an index property plus
a screen capture and independently computed hashes. The live read surface needs a
bounded way to invoke a method and project what it returns.

The bound is NOT a trust boundary. The target project is trusted
([ADR-0009](0009-trust-boundary-trusted-project.md)) and gda already runs its code:
autoload constructors, `_init` on instantiation, and the whole of a named script via
`gda script run` ([ADR-0031](0031-headless-script-run-passthrough-execution.md)).
Anyone able to call `gda game call` can already call `gda script run`. What the bound
buys is different and worth stating precisely:

- it keeps the live **read** surface free of side effects gda did not ask for, so
  `State consistency` ([ADR-0020](0020-live-state-consistency.md)) still
  describes reads truthfully; and
- it keeps results inside what the `Value projection`
  ([ADR-0035](0035-value-projection-compound-variants-to-structured-json.md)) can
  render.

**Enforcement limit, stated up front:** gda cannot verify that a GDScript method has
no side effects. The declaration records the DECLARER's assertion. What gda guarantees
is that **no undeclared method is callable**.

## Decision

### 1. The declaration is resolved statically along the attached script's base chain

An inheritance chain opts in when one script in the addressed node's attached-script
base chain defines the constant:

```gdscript
extends Node2D

const GDA_CALLABLE := ["qa_current_state_contract"]

func qa_current_state_contract() -> Dictionary:
	return {"phase": _phase, "ready": true}
```

**The public rule, stated once:** gda resolves the declaration from the addressed
node's ATTACHED script along its **base chain**, and an opted-in chain has AT MOST ONE
declaration owner — the class that carries the constant. That owner is not necessarily
the class that defines every method it names: a base that declares owns the callable
surface of its subclasses too. `gda game call <node> --method <name>` invokes the method
only when the resolved declaration names it.

This implements the issue's triage decision — a **project-side** declaration rather
than a per-invocation CLI flag, because a flag would let any caller assert anything ad
hoc, reducing "no undeclared call" to nothing. The declaration stays in project source,
where the project's code review already looks, rather than in a separate registry that
drifts from it. It may live in a base or leaf script and need not share a file with every
method it names.

It is therefore an INHERITANCE-CHAIN declaration, not a per-class increment (see "Why
at most one owner per opted-in chain" below): a leaf class with no declaring base
declares its own methods; a base that declares must name the subclass methods it
authorizes. One authoritative list per opted-in chain, in one file — a real cost of
this format, stated rather than implied away.

Two properties decided the FORMAT (a constant, not a `_gda_callable()` hook method):

- **Reading the allowlist runs no project code.** gda reads the constant map
  (`Script.get_script_constant_map()`, walking `get_base_script()`), which the engine
  serves from the compiled script. A hook method would mean gda's first act on a
  `game call` is to invoke an undeclared project method to learn which methods are
  declared — bootstrapping the very thing the allowlist exists to bound.
- **The assertion is statically reviewable.** A reader (or a reviewer, or a linter)
  sees an opted-in chain's complete declaration in its one owner file; nothing is
  decided at runtime.

> **Amended triage decision (recorded on issue #673, 2026-08-27).** The triage comment
> says "project-side declaration, read by the harness at `Engine session` start", and
> names enumeration as the discovery path. Its substance — project-side, not a
> per-invocation flag — is implemented unchanged. Two clauses were AMENDED on the
> authoritative issue before this ADR was accepted, not merely deviated from here:
> the read happens **per call** rather than at session start (a per-class declaration
> has nothing to read at session start for a node that does not exist yet, and a
> per-call read of a compiled constant cannot go stale), and **enumeration is
> deferred** with the declared set carried on the `live_method_not_allowlisted`
> message instead. The format was explicitly left to the implementer; the amendment
> comment on #673 carries the decision, its rationale and this ADR's link.

**Why at most one owner per opted-in chain — engine-enforced and loud.** GDScript forbids a subclass from
redeclaring a base class's constant: a subclass that declares its own `GDA_CALLABLE`
while a base declares one fails to PARSE with
`Parse Error: The member "GDA_CALLABLE" already exists in parent class <base>`
(reproduced on Godot 4.6.3 while implementing this). Per-class INCREMENTAL declaration
is therefore not available in this format, which is why the decision above defines the
constant as the CHAIN's declaration rather than presenting an increment and then
withdrawing it. The failure is a parse error naming the exact member — the project does
not load — never a silent wrong allowlist. A project whose subclass must add methods
moves the declaration down to that subclass (taking the base's names with it), or
declares the union in the base.

### 2. Failures are distinguishable, and existence is checked first

Three registered LIVE codes ([ADR-0002](0002-headless-structured-output-contract.md)),
each with its own remediation:

| Code | Condition | What the caller does |
| --- | --- | --- |
| `live_unknown_method` | the node has no such method | fix the name |
| `live_method_not_allowlisted` | the node has it; its script chain never declared it | add it to `GDA_CALLABLE` |
| `live_invalid_call_args` | argument count outside the accepted range, or a value the declared parameter type cannot take | fix the arguments |

**Existence is checked before the allowlist.** For a name that is both absent and
undeclared, the caller is told the name is wrong, which is the useful diagnosis. This
leaks which method names exist on a node — deliberately, since the project is trusted
and `game get` already exposes its property surface; it is not a boundary this ADR
defends.

The argument check runs BEFORE the call, from the method's own `get_method_list()`
entry, and covers BOTH the count (required = declared arguments minus defaults; a vararg
method has no upper bound) AND each argument's TYPE. `callv` with arguments it cannot
convert pushes an engine error, returns null, and writes to the `Session log` — a
failure gda would otherwise report as a successful read of `null`, indistinguishable
from a void return (PR #749 review; reproduced on Godot 4.6.3 for a String into `int`,
null into `int`, a Dictionary into an `Object` parameter, and a JSON array into
`Array[int]`).

The type rule is the engine's own `Variant::can_convert_strict` closure
(`core/variant/variant.cpp`), which is not exposed to GDScript, restricted to the SIX
Variant types the live JSON parser produces — null, bool, float, String, Array, and
Dictionary. Godot's `JSON.parse_string` materializes every JSON number as float,
including a literal without a fractional part; `int` is therefore a reachable target
type, not a live JSON source type. Restricted that way the closure is small, so the
harness carries it as a table keyed by the SOURCE type: bool/float reach `int`/`float`,
a String reaches `Color` / `StringName` / `NodePath`, an Array reaches any of the ten
`Packed*Array` types, null reaches an `Object` parameter, an untyped (Variant) parameter
takes anything, and everything else is refused with the reason. A TYPED
container parameter (`Array[int]`) is refused whatever its contents, because the engine
refuses `Array` → `Array[int]` outright — no JSON argument can reach one, and saying so
beats letting the call fail as a null.

**Transcribing that closure by hand is exactly where this went wrong once** (PR #749
re-review): a first version omitted the `Color` and `Packed*Array` rows and so REJECTED
calls Godot performs. The table is therefore pinned by a real-engine conformance matrix
whose ORACLE IS THE ENGINE, not a second copy of the table. The test first asserts with
a declared `argument_type` method that both integer-looking and fractional-form number
literals reach the harness as float. A declared `probe_direct` method then performs the
call inside the game with `callv` and reports whether the method body RAN, and the matrix
asserts gda's verdict equals the engine's for every retained (parameter type, live JSON
value) pair. gda does not convert on the caller's behalf: where the engine converts the
wire value, gda calls; where it refuses, gda refuses first.

Arguments are also bounded at the CLI boundary, in the params model both invocation
paths share (ADR-0015), for two reproduced argument classes this slice can refuse
without changing the live protocol:

- a non-finite float (`NaN`, `Infinity` — which JSON has no literals for, but Python's
  decoder accepts by extension): left through, it produced a frame the harness's JSON
  parser could not read, so the call never arrived — the caller waited out the relay
  bound, got `live_timeout`, and the daemon retired the channel, losing the `Engine
  session`'s runtime state; and
- a JSON integer value outside ±(2^53 − 1): the harness's `JSON.parse_string` reads every
  number as binary64, so an integer outside that guaranteed-exact range can arrive as a
  DIFFERENT value and make the call succeed on something the caller never sent
  (`9007199254740993` doubled to `…984` instead of `…986`;
  `123456789012345678901234567890` arrived as `-2`). The params model therefore
  applies the interoperable bound to values the Python JSON decoder materializes as
  `int`. A finite Python `float` already is binary64 and does not inherit that integer
  bound; real-engine regressions pin the reproduced high-range values `1e17`,
  `2.5e17`, and `1e300` unchanged at the method.

That high-range evidence is not a full binary64 preservation guarantee. Godot 4.6.3
`JSON.parse_string` also has a decimal-shape-dependent lower-range defect: `1e-300`
and `1e-308` remain non-zero, but the ordinary normal value
`1.2345678901234567e-300`, `DBL_MIN` (`2.2250738585072014e-308`), and subnormal
values such as `1e-320` can become `0.0`. Python's `json.dumps` emits the failing
full-precision form for that normal value, so this is reachable from an ordinary
computed float. A CLI exponent/significant-digit heuristic would over-refuse valid
values and cover only requests; Godot's `JSON.stringify` can lose small result values
too. [Issue #752](https://github.com/aigengame/godot-agent/issues/752) owns the
cross-operation transport policy and fix. This slice discloses the limitation instead
of adding a partial guard.

Standard JSON Schema cannot express that lexical distinction: it treats an exponent-form
float such as `1e17` and the equal integer value as the same mathematical integer.
Applying `minimum` / `maximum` to that schema type would again block valid high-range
float parameters. The recursive schema therefore leaves its finite `number` branch broad
and publishes this limitation in the number and `args` descriptions; the params model is
the execution authority for the integer-token bound on both argv and `--params-json`.
The schema consumes RFC JSON, whose grammar excludes `NaN` and `Infinity`; some
in-memory JSON Schema validators accept those Python float extensions as `number`, so
the model/schema corpus pins that second deliberate over-acceptance and the params
model remains the execution authority for it too.

Both refusals are recursive — a nested value is as harmful as a top-level one — and
both failure modes were reproduced end to end before they were bounded.

The `live_method_not_allowlisted` message names the script chain's declared set, so discovery
rides the failure an agent already has to read. A dedicated enumerate operation is
DEFERRED, not rejected: if agents need the list without a failed call, it is a `game`
operation of its own, decided on its own evidence.

### 3. The return value is projected, never inlined raw

The value goes through the same recursive `Value projection` every gda read uses, so a
returned Dictionary arrives structured and a returned Object obeys ADR-0035's
projection kinds and whitelist. A method returning nothing projects as `null`. The
per-read `--texture-digest` opt-in that `game get` offers is NOT part of this first
version: a path-less `Texture2D` returned by a call projects with a null digest. Adding
it is a one-field change if a package needs it.

The projected value is still framed with Godot `JSON.stringify`. As recorded above and
in #752, Godot 4.6.3 can serialize small non-zero floats as `0.0`; the limitation affects
the shared live-result path, not only `game call` arguments.

Arguments are JSON values passed as the live parser's Variant forms (a JSON object
becomes a Dictionary, an array an Array, and every number a float). The string-to-Godot-type coercion table that
`node set` / `game set` own is deliberately NOT reused here: a call's arguments are
typed by the method, not by a stored property's declared type, and inventing a second
coercion authority for them would create exactly the drift ADR-0015 exists to prevent.

## Consequences

- The `Project-code execution surface` (CONTEXT.md) gains one point: a `game call`
  runs one method the target node's script chain declared. Reading the declaration adds none — it is
  a constant-map read. The trust axis is unchanged (ADR-0009).
- `game call` is a `kind = LIVE` `game` command, served by the existing harness op
  dispatch and single-writer serialization — one method per request, at a frame
  boundary, so ADR-0020's state consistency covers it like any other live op.
- A project adopting it writes one constant. Nothing is callable until it does; there
  is no default-open state and no gda-side list to keep in sync with the project.
- If a future package needs mutating calls, this ADR does not cover them: the
  declaration asserts read-only, and a mutating surface would need its own decision
  (and, unlike this one, a real argument about `State consistency`).
