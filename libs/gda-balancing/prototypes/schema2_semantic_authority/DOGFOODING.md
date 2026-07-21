# Semantic-authority prototype dogfooding

This log records design feedback from implementing the disposable vertical slice. `Confirmed`
means the narrow mechanism was executable. `Refined` means the design needs a sharper normative
contract. `Unvalidated` means this prototype could not substantiate the broader claim. None of
these findings closes a Genre coverage row.

## Iteration log

### Iteration 1 — close the bootstrap boundary

Started with a Kernel Specification identity, closed fact/premise/node inventories, structured LDB
rules, and two bootstrap interpreters. The first draft only checked premises; implementing a real
bound conclusion forced the probe to add `bind_field`, repeated-binding behavior, and a deterministic
judgment shape. Unknown operators, ambiguous selection, and removed/changed consulted rules became
executable refusal vectors.

### Iteration 2 — separate semantics from provenance

Built two source forms and compiler paths. Source ordering, aliases, comments, AST/HIR identities,
compiler identity, and lowering maps initially wanted to leak into the RIR. Moving them into Debug
Maps and Build/Resolution receipts produced byte-identical semantic RIR artifacts while preserving
traceability. The Package Lock similarly had to exclude resolver identity.

### Iteration 3 — remove RPG behavior from the host

The first runtime sketch was tempted to dispatch `resource.reserve` and `action.resolve` in Python.
Replacing that with an LDB-authored expression composition over closed kernel nodes allowed both
evaluators to contain zero RPG operation ids. This made an LDB damage-composition mutation change
identity and both evaluator results, and made an unknown primitive refuse rather than fall back.

### Iteration 4 — make Numeric, RNG, outcome, and rollback observable

Implemented exact Int64 checks and the named-stream SHA-256 input/mapping law twice. A known-answer
candidate exposed all seed/stream/counter byte choices. Counting every rejected RNG candidate
against the draw budget was necessary to make the limit meaningful. `Reserved | Insufficient`
showed that gameplay branches must remain values: the insufficient path completed normally, did
not draw, emit a damage metric, or commit resource/state transitions. Runtime limits instead
produced a typed refusal and rolled the current event back.

### Iteration 5 — close replay and profile honesty

Resolved Runtime profile identities necessarily differed because they truthfully included evaluator
and platform identity. An initial implementation silently weakened replay to “same semantic profile”
and issued positive Evidence. Review against bADR-0014/0018 showed that this contradicted the
accepted identical-Resolved-profile requirement. The final probe preserves both authorities,
returns an `evaluation` decision-required gate report, and issues neither Replay comparison nor
Evidence assertion.

### Iteration 6 — make publication recoverable

Added caller-known Invocation keys, exact-request idempotency, conflict refusal, pre-commit fault
injection, directory-rename commit, and post-commit delivery failure recovery. The first refusal
draft published only a terminal-audit artifact, leaving its RIR/profile references absent in a fresh
store. The final prototype-local terminal-audit dependency set therefore includes successful
build/profile dependencies, while forbidding partial Evaluation/Metric/Replay/Evidence success
artifacts. Review then exposed that the first key format, channel/exit behavior, canonical input,
descriptor binding, and rehash-on-read logic all drifted from bADR-0015/0021; those became
descriptor-driven and adversarially tested.

### Iteration 7 — enforce the accepted runtime boundary

The first evaluator mutated working state immediately, used last-write-wins, accepted a plain
`{"outcome": ...}` record as one branch of a supposed union, and admitted an under-bound Runtime
profile. Both evaluators were changed independently to bind exact Kernel/LDB/Package Lock/RIR/
profile/evaluator/platform/budgets, validate the closed `{tag, fields}` shape, read only the
pre-event snapshot, buffer state writes, reject duplicate slot writes, and commit once after a valid
entry outcome. Tamper, write-then-read, duplicate-write, unknown-tag, and malformed-payload vectors
now guard those contracts.

### Iteration 8 — make residual trust and descriptor claims explicit

Four independent consumers now rehash the Kernel before admitting or executing it. Publication
adds an atomic commit marker that anchors the originally committed receipt, so a coherent rewrite
of a member, record, and reidentified receipt is detected while the local index/filesystem trust
boundary remains intact. Descriptor reverse conformance also forced `compare` to declare itself
gate-only, with no success outcome variant or parameters. Finally, separate identity and
malformed-rule fixtures made the prototype's local ingress/static split executable instead of
implicit.

## Findings

### SA-01 — RPG host dispatch can be removed; Kernel authority remains open (`Unvalidated`)

Given one shared handwritten understanding of the narrow kernel-node semantics, two evaluator
implementations execute the domain flow with no RPG/domain branch and react consistently to LDB
composition changes. However, the `KERNEL_SPEC` artifact mostly inventories nodes and names selected
laws; neither evaluator derives its behavior from independently executable laws. Agreement can
therefore reflect coordinated Python code rather than an adequate machine authority.

**Design feedback:** treat “no RPG host branch” as useful connectivity evidence only. Kernel-law
independent implementability remains a root Standard Schema gate, below the LDB compilation gaps in
SA-03/07.

### SA-02 — Bootstrap law needs binding and diagnostic-order semantics (`Refined`)

Closing fact and premise operator names was insufficient. Independent bootstraps also needed the
evaluation order of premises, binding creation, repeated-binding unification, conclusion
substitution, rule-selection cardinality, diagnostic precedence, and judgment ordering. Without
those laws, two conforming implementations can disagree while consuming the same structured rule.

**Design feedback:** extend the Kernel Specification's judgment machine contract and normative
vectors with all of the above; do not leave binding/substitution or diagnostic ordering to prose.

### SA-03 — Admission rules do not yet prove language-content authority over compilation (`Unvalidated`)

The prototype's two compilers independently duplicate source binding, small-shape type checks,
operation-closure discovery, and lowering. They agree, but their agreement is test-coordinated; it
is not derived by executing LDB name-resolution, typing/effect, exhaustiveness, and lowering rules.
The design says those rules belong to the LDB, so this remains the largest conformance gap.

**Design feedback:** require the next conformance harness to execute the same structured LDB
judgments through independent judgment engines for Source → HIR → RIR, including mutation vectors
where changing a consulted typing/lowering rule changes both outputs or produces the same refusal.

### SA-04 — Semantic RIR / Debug Map / receipt separation works (`Confirmed`)

Equivalent source spelling, order, aliases, comments, AST/HIR shape, compiler identity, and source
mapping produced one byte-identical RIR while Debug Maps and Build receipts differed. A semantic
constant change produced a different RIR. This supports bADR-0013's semantic-normal-form boundary.

### SA-05 — RIR must normatively choose embedded programs versus LDB dereference (`Refined`)

The probe embeds the closed operation programs used at runtime in RIR while also binding the exact
LDB identity. This makes RIR a self-contained cross-evaluator boundary but duplicates LDB semantic
content. A reference-only RIR would instead require an evaluator to resolve the LDB artifact.

**Design feedback:** specify one canonical rule: which admitted LDB semantic fragments are embedded
or projected into RIR, how their identity is checked against the bound LDB, and whether an evaluator
may execute with RIR alone. Do not permit evaluator-specific projection choices.

### SA-06 — LDB composition removes RPG-specific dispatch (`Confirmed, narrow`)

Resource reservation, the closed outcome, success-only commit, RNG sampling, damage, state writes,
and Metric emission are generic kernel-node compositions. Mutation of `add_int` to `sub_int` in the
LDB changed both identity and both evaluator behaviors. An unknown primitive produced the same
runtime refusal in both evaluators, with no host fallback. This claim assumes the shared handwritten
kernel-node interpretation and does not upgrade SA-01.

### SA-07 — Closed variants require static Typed-HIR exhaustiveness (`Unvalidated`)

The runtime correctly prevents the `Insufficient` branch from reaching success-only transitions,
but the prototype compilers do not derive and statically verify match exhaustiveness from operation
result variants. A missing arm would be found only at runtime. That is weaker than the bADR-0016
contract.

**Design feedback:** add variant-set formation, exhaustive match, unreachable-arm, and
success-capability refinement judgments to the LDB rules and normative HIR vectors. The
orthogonality/extensibility prototype should treat this as an explicit gate.

### SA-08 — Exact Numeric/RNG behavior can agree independently (`Confirmed`)

The evaluators separately implement Int64 type/overflow checks and the full seed + stream + counter
SHA-256 message, first-u64 extraction, rejection threshold, modulo result, and counter consumption.
They agree on the exact candidate `12569293548191996068` and all observable results. Invalid seed,
zero draw budget, and step-limit vectors refuse consistently.

### SA-09 — RNG budgets count candidate attempts, not successful samples (`Refined`)

Unbiased bounded mapping may reject multiple candidates. Charging only accepted samples permits
unbounded work and makes replay resource evidence ambiguous.

**Design feedback:** Runtime Profiles and audit artifacts must distinguish candidate draws from
accepted samples, count every candidate against the draw budget, and record rejected candidates in
the replay trace. Seed range and counter overflow require stable diagnostics.

### SA-10 — Gameplay outcome and typed refusal remain distinct (`Confirmed`)

Both `Resolved` and `Insufficient` use the same closed `{tag, fields}` representation.
`Insufficient` completes with unchanged state and no damage Metric/RNG use; unknown tags and
malformed payload containers refuse. Runtime budget exhaustion is a distinct typed refusal with
terminal audit. Variant-specific field schemas are still a static gap under SA-07.

### SA-11 — Single-event buffering works; scheduler atomicity remains open (`Partially confirmed`)

Both evaluators now read a fixed pre-event snapshot, buffer writes, reject a second write to one
slot, commit successful writes once, and discard buffers on refusal. Write-then-read and duplicate
write vectors agree. This validates the narrow event transaction seam, but there are no previously
committed events, nested schedules, cancellation, simultaneous ordering, signals, or cycle handling.

**Design feedback:** retain event atomicity and invocation publication atomicity as separate
contracts. A later runtime conformance fixture must prove prior-event durability plus current-event
rollback under schedule/signal faults.

### SA-12 — Independent-evaluator Replay has an authority conflict (`Design conflict`)

Independent implementations legitimately have different Resolved Runtime profile identities. A
comparison that ignores that fact is dishonest; bADR-0014 nevertheless requires identical Resolved
Runtime profiles while the same bADR/glossary requires the profile to bind evaluator/platform.
Those statements make the requested independent-evaluator positive Replay impossible as written.

**Design feedback:** this is a Standard Schema foundation decision, not a prototype-local policy.
The probe now emits `evaluation.resolved-runtime-profile-identity-conflict`, records equal semantic
observations and both distinct profile identities, and issues no Replay comparison or Evidence.
Design authority must decide whether comparison binds one portable semantic execution profile plus
separate evaluator realizations, or changes the “identical Resolved Runtime profile” requirement.

### SA-13 — Descriptor-bound caller-known keys close delivery recovery (`Confirmed`)

An injected post-commit delivery failure can be recovered by exact retry using the same Invocation
key and canonical input. The key is exactly 32 octets/64 lowercase hex; canonical input excludes the
key and store locator and includes descriptor identity. Reuse with changed bound input is rejected
before handler dispatch; exact retry re-emits the stored original outcome. This validates the
caller-known-key addition to bADR-0015/0021.

### SA-14 — Publication semantics must be storage-abstract (`Refined`)

Same-filesystem directory rename proved atomic visibility and pre-commit cleanup locally, but it is
not a portable protocol for object stores or remote services. Rehash-on-read of every member,
receipt, and receipt member set was also necessary; a visible directory alone is not trustworthy.
An independently verified commit marker now anchors the original receipt identity and detects a
coherent member + record + reidentified-receipt rewrite. This works only while the local
index/filesystem containing that marker remains trusted. Full-index compromise and distributed
commit authorities remain outside the probe.

**Design feedback:** standardize abstract staged invisibility, immutable member identities, one
commit point, exact-request idempotency, conflict, receipt recovery, and fault vectors. Keep the
filesystem/object-store transaction mechanism implementation-specific and honestly declared in the
receipt.

### SA-15 — Prototype-local terminal-audit dependencies need referential closure (`Refined`)

Publishing only the audit left its RIR and Resolved Runtime profile unavailable in a fresh store.
The corrected prototype-local dependency set carries successful build/profile dependencies but
never partial Evaluation, Metric, Replay, or Evidence success artifacts. This proves only
referential closure for the fixture. It does not validate a complete terminal-audit contract for
trace prefix, last committed snapshot, refusing event, rollback facts, reproduction identifiers,
or diagnostic location.

**Design feedback:** bADR-0014/0015/0021 should explicitly permit and require terminal-audit
dependency closure, define which successful prerequisite artifacts may be members, and forbid all
artifacts that would falsely imply a completed evaluation. The stronger conformance harness must
also validate the terminal-audit schema and semantics, not infer them from set membership.

### SA-16 — Descriptor can own inputs, routing, outcomes, and artifact sets (`Confirmed, narrow`)

Each content-addressed descriptor now owns parameter types/defaults, handler binding, declared
success/refusal outcomes, channel/exit, and allowed artifact-set kinds. Dispatch resolves only the
descriptor's handler id through a closed implementation map, validates the returned outcome against
the descriptor, and a reverse-enumeration vector proves no handler/descriptor is extra or missing.

**Design feedback:** retain registry-walking reverse conformance; a parameter-only descriptor is not
the bADR-0015/0021 registration seam.

### SA-17 — Package closure is structurally represented, not generally solved (`Unvalidated`)

The Package Lock records exact selection, graph, provider, operation, type, conversion, resolution
profile, and conflict disposition, with resolver provenance separated. The fixture has only one
package and no adapters, transitive conflicts, optional capabilities, or competing providers.

**Design feedback:** no general resolution claim until independent resolvers pass multi-package
positive, conflict, missing-provider, conversion, operation-version, and deterministic tie-break
vectors.

### SA-18 — Evidence construction is not independent validation (`Unvalidated`)

The pipeline produces exact runs and datasets, but the accepted Replay profile rule blocks the next
gate. It therefore constructs no positive or `unsatisfied` Evidence assertion. Even after SA-12 is
resolved, a second independently implemented validator must re-open the artifact graph and verify
schemas/prerequisites before Evidence can be issued.

**Design feedback:** evidence conformance needs executable closed-schema validators, subject-kind
checks, prerequisite graph evaluation, tamper/missing-subject vectors, and independent validator
agreement. This prototype constructs no Evidence artifact; it reaches only the precondition/gate
boundary.

### SA-19 — Independence is source-level, not ecosystem-level (`Unvalidated`)

The paired implementations share only canonical/wire helpers at the source level, but both run on
CPython and use its SHA-256 implementation. This is enough to catch shared RPG dispatch and many
mapping mistakes, not common runtime/library defects.

**Design feedback:** final conformance evidence should require organizationally or technologically
independent implementations, while allowing a standardized cryptographic primitive. Record the
dependency/toolchain identities in conformance receipts.

### SA-20 — Canonical identity encoding is part of the kernel contract (`Refined`)

Cross-compiler equality depended on exact JSON canonicalization, artifact-kind domain separation,
identity exclusion rules, sorted maps/lists, and integer encoding. These cannot remain utility
conventions if RIR, locks, receipts, and invocation conflicts are normative.

**Design feedback:** bind an exact canonical wire/identity profile in the Kernel Specification and
provide positive, Unicode, ordering, numeric-boundary, and malleability vectors.

### SA-21 — Named kernel laws are not executable kernel semantics (`Root gap`)

The Kernel record names expression nodes, Int bounds, RNG byte rules, and event phrases, but many
node behaviors—environment lookup, call/return, match payloads, sequencing, Metric effects, and
transaction rules—remain prose-like strings or inventories. The two evaluators independently code
them from a shared human interpretation. This is stronger than sharing one runtime function but
weaker than bADR-0022's independently implementable machine authority.

**Design feedback:** the stronger conformance prototype needs a closed executable judgment/step
format or another normative formal encoding for every admitted kernel node, plus independent
implementations and mutation vectors. Until then, Kernel semantic authority is unvalidated even
when cross-evaluator results match.

### SA-22 — Invocation conformance requires hostile recovery tests (`Confirmed, narrow`)

The initial happy-path CLI accidentally accepted short keys, hashed transport metadata, dispatched
before conflict detection, returned runtime refusal as success, and trusted stored JSON. All were
plausible implementations that violated accepted bADRs. Descriptor identity binding, strict channel
tests, preflight spies, before/after-commit faults, exact outcome replay, forged-member rejection,
and receipt/member-set rehash vectors caught them.

**Design feedback:** these must remain mandatory descriptor-generated fixtures rather than ad hoc
CLI tests; otherwise future commands will repeat the drift.

### SA-23 — Diagnostic code and stage authority is still host-hardcoded (`Root gap`)

The LDB fixture declares only `runtime.limit-exceeded`, while the bootstraps, evaluators, pipeline,
and CLI contain roughly thirty additional diagnostic codes and assign their stages in host code.
Two implementations agreeing on those strings does not prove that the LDB or Kernel authorizes the
diagnostic vocabulary, precedence, payload schema, or stage.

**Design feedback:** the stronger prototype must project diagnostic code/stage/payload authority
from admitted LDB/Kernel data, or independently reverse-conform every host diagnostic against that
authority. Unknown, missing, duplicate, and wrong-stage diagnostic mutations must refuse.

### SA-24 — “Bundle admission” does not uniquely determine refusal stage (`Design ambiguity`)

The executable local policy classifies identity and Kernel/LDB safe-admission failures as
`ingress`, admitted rule/fact container and semantic failures as `static`, and evaluator failures as
`runtime`. This matches bADR-0015's earliest-stage split, but bADR-0022 uses “bundle-admission
refusal” without publishing the same stage table. The phrase can therefore be read as either a
subsystem boundary or an ingress-stage promise.

**Design feedback:** publish one normative diagnostic-to-stage table. Reserve `ingress` for
identity/version/binding/safe-admission checks; use `static` for admitted LDB rule/fact structural
and semantic invalidity; use `runtime` only after evaluation begins. Descriptors and conformance
vectors should be generated from, or reverse-conformed to, that table.

## Result

The probe proves a narrower result than the first draft claimed: under one shared handwritten
kernel-node interpretation, a vertical RPG flow can remove RPG host dispatch and agree across two
source-level implementation paths. It does **not** prove the Kernel Specification or complete
Schema 2.0 feasible. The root gaps are executable kernel semantics (SA-01/21), executable LDB
Source → HIR → RIR authority (SA-03), static closed-outcome typing (SA-07), the Resolved-profile
Replay contradiction (SA-12), general package solving (SA-17), and independent Evidence validation
(SA-18), diagnostic semantic authority (SA-23), and normative diagnostic staging (SA-24). These are
design/conformance gates, not cleanup tasks.
