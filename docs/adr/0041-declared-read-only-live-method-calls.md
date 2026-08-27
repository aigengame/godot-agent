---
status: accepted
---

# Live method calls are declared by the class, in a statically-read script constant

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

### 1. The declaration site is the class's own script constant, read statically

A class declares what gda may call in a script constant on the node's attached script:

```gdscript
extends Node2D

const GDA_CALLABLE := ["qa_current_state_contract"]

func qa_current_state_contract() -> Dictionary:
	return {"phase": _phase, "ready": true}
```

`gda game call <node> --method <name>` invokes the method only when the addressed
node's class names it there. The set is merged along the script's **base chain**, so a
shared debug base class declares once for its subclasses, the way any other class
member is inherited.

This implements the issue's triage decision — a **project-side** declaration rather
than a per-invocation CLI flag, because a flag would let any caller assert anything ad
hoc, reducing "no undeclared call" to nothing — and takes its rationale to the end: the
read-only assertion is a property of the method, so it belongs beside the method, under
the project's own code review.

Two properties decided the FORMAT (a constant, not a `_gda_callable()` hook method):

- **Reading the allowlist runs no project code.** gda reads the constant map
  (`Script.get_script_constant_map()`, walking `get_base_script()`), which the engine
  serves from the compiled script. A hook method would mean gda's first act on a
  `game call` is to invoke an undeclared project method to learn which methods are
  declared — bootstrapping the very thing the allowlist exists to bound.
- **The assertion is statically reviewable.** A reader (or a reviewer, or a linter)
  sees the whole callable surface of a class by reading its source; nothing is decided
  at runtime.

> **Recorded deviation from the triage wording.** The triage decision says
> "project-side declaration, read by the harness at `Engine session` start". Its
> substance — project-side, not a per-invocation flag — is honoured. The *timing*
> clause described the config-file shape the triage envisioned; with a per-class
> declaration the read happens per call instead, which is strictly stronger: it cannot
> go stale, and it covers nodes instantiated after session start. The format was
> explicitly left to the implementer, and this ADR is the record the acceptance
> criteria asked for.

**Known limitation, engine-enforced and loud.** GDScript forbids a subclass from
redeclaring a base class's constant: a subclass that declares its own `GDA_CALLABLE`
while a base declares one fails to PARSE with
`Parse Error: The member "GDA_CALLABLE" already exists in parent class <base>`
(reproduced on Godot 4.6.3 while implementing this). So within one inheritance chain
exactly one class declares: either the base (listing what its subclasses expose) or the
leaf (with no base declaration above it). The failure is a parse error naming the exact
member — the project does not load — never a silent wrong allowlist.

### 2. Failures are distinguishable, and existence is checked first

Three registered LIVE codes ([ADR-0002](0002-headless-structured-output-contract.md)),
each with its own remediation:

| Code | Condition | What the caller does |
| --- | --- | --- |
| `live_unknown_method` | the node has no such method | fix the name |
| `live_method_not_allowlisted` | the node has it; the class never declared it | add it to `GDA_CALLABLE` |
| `live_invalid_call_args` | argument count outside the method's accepted range | fix the arguments |

**Existence is checked before the allowlist.** For a name that is both absent and
undeclared, the caller is told the name is wrong, which is the useful diagnosis. This
leaks which method names exist on a node — deliberately, since the project is trusted
and `game get` already exposes its property surface; it is not a boundary this ADR
defends.

The arity check runs BEFORE the call, from the method's own `get_method_list()` entry
(required = declared arguments minus defaults; a vararg method has no upper bound),
because `callv` with a wrong argument count pushes an engine error and returns null —
which gda would otherwise report as a successful read of `null`.

The `live_method_not_allowlisted` message names the class's declared set, so discovery
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

Arguments are JSON values passed as their natural Variant forms (a JSON object becomes
a Dictionary, an array an Array). The string-to-Godot-type coercion table that
`node set` / `game set` own is deliberately NOT reused here: a call's arguments are
typed by the method, not by a stored property's declared type, and inventing a second
coercion authority for them would create exactly the drift ADR-0015 exists to prevent.

## Consequences

- The `Project-code execution surface` (CONTEXT.md) gains one point: a `game call`
  runs one method the target class declared. Reading the declaration adds none — it is
  a constant-map read. The trust axis is unchanged (ADR-0009).
- `game call` is a `kind = LIVE` `game` command, served by the existing harness op
  dispatch and single-writer serialization — one method per request, at a frame
  boundary, so ADR-0020's state consistency covers it like any other live op.
- A project adopting it writes one constant. Nothing is callable until it does; there
  is no default-open state and no gda-side list to keep in sync with the project.
- If a future package needs mutating calls, this ADR does not cover them: the
  declaration asserts read-only, and a mutating surface would need its own decision
  (and, unlike this one, a real argument about `State consistency`).
