# Orthogonality/extensibility prototype dogfooding

This log records design feedback from the disposable probe. `Confirmed` means the narrow mechanism
was executable. `Refined` means implementation forced a sharper contract. `Unvalidated` means the
probe cannot substantiate the broader claim. Nothing here closes a PRD acceptance item or Genre
coverage row.

## Iteration log

### Iteration 1 — reject a dead-field attribute demonstration

The first fixture added `focus` as root-shaped data. It was replaced with a complete Quantity-typed
symbol that reaches AST/HIR/RIR/runtime/Metrics/public artifacts. This established the exact
attribute change surface but initially invented `probe.game.focus` as an inline nominal kind.

### Iteration 2 — discover that split extension registries are not one authority

The first implementation split extension facts across `MECHANIC_FACTORIES` and
`MECHANIC_PACKAGES`, assembled them under another name registry, and initially considered mutating
an existing package without changing its version. Although generated projections agreed, the
release was neither one immutable record nor a closed identity boundary.

### Iteration 3 — move use-site exhaustiveness into Typed HIR

Runtime-only tag validation was insufficient. Model use-site matches now derive the exact tags and
payloads from the selected Operation result and reject missing, duplicate/unreachable, unknown, and
wrong-payload arms before RIR.

### Iteration 4 — remove mechanic dispatch from host paths

Resource reservation, interruption/refund, stacking, reapplication, and removal were expressed as
generic closed nodes. Source scans and runtime admission reject mechanic-specific host fallback.
The first pass did not validate that package bodies themselves matched their declared results and
effects, so an authority record could still lie while the generic interpreter executed it.

### Iteration 5 — separate compensation from Event rollback

Reservation commits one Snapshot; interruption is a later compensating transaction. Runtime
rollback discards only the refusing current Event's buffers. The first rollback vector refused the
first Event and therefore did not prove that a prior commit survives a later refusal.

### Iteration 6 — expose the observation and publication boundaries

The first pass constructed an Experiment after execution from a host `scenario` argument, always
emitted every Metric, always returned `satisfied`, and published through an unanchored record. It
therefore did not prove independent experiment authority, selector/acceptance execution, or
recoverable original-receipt identity.

### Iteration 7 — measure identity blast radius, then correct its attribution

The first Package Lock included the whole LDB identity. Adding an unused package changed both Lock
and RIR. Review showed that the Lock invalidation was a prototype implementation choice rather than
a necessary consequence of the accepted design. RIR still normatively binds the exact LDB, so its
identity remains affected under the current bADR wording.

### Iteration 8 — repair independent Experiment authority

Model Source now declares typed symbols and operation use sites only. An independently identified
Experiment owns input overrides, ordered use-site dispatch, Metric selectors, and acceptance. It is
verified and final-bound to exact RIR before dispatch. Insufficiency is produced by overriding the
declared input-role resource Quantity, not by changing Model Source. Empty selectors emit no
samples; changing acceptance changes `satisfied` to `unsatisfied`.

### Iteration 9 — repair Quantity and package admission

`focus` now uses the already selected foundation release's `game.stat.generic` Quantity kind,
`game:point` unit, and `exact-int-v1` Numeric profile. Unknown kind/unit/profile refuses. Every
extension is one complete content-addressed `domain-package-release` containing metadata,
dependencies/capabilities, type/profile surfaces, complete operations, vectors, and diagnostics.
Package Lock binds exact release identities.

### Iteration 10 — close package program/result/effect drift

Before RIR, every operation of every selected package is traversed through the closed Kernel-node
inventory. The compiler derives state reads/writes and reachable outcome payload types, compares
them exactly with declared effects/results, and checks bounds. Undeclared health writes, wrong
tags/payloads, and unknown nodes now refuse statically. HIR marks checks complete only after this
pass succeeds.

### Iteration 11 — repair admission, profile, and prior-commit audit

Runtime now rejects any RIR use site absent from exact Lock operation bindings even when the whole
LDB contains that operation. Resolved Runtime profile binds Kernel/LDB/Lock/RIR/profile definition/
Numeric/event law/evaluator/platform/budgets and is fully verified before dispatch. Pre-dispatch
refusals publish no terminal audit. With a two-write budget, reservation commits resource `7` and
reservation `3`; the later three-write interruption refuses and its audit preserves that Snapshot,
the committed trace prefix, refusing event, discarded buffers, full Diagnostic, profile, and all
reproduction identities.

### Iteration 12 — make descriptor and publication claims executable

The descriptor now owns the closed request envelope, key/store rules, parameter schemas, every
reachable outcome/channel/exit, and complete artifact-set membership/multiplicity/forbidden-kind
contracts. Handler registration and returned results reverse-conform. A changed request under the
same Invocation key is a usage error on stderr before handler dispatch. Publication now has a
trusted prototype-local anchor binding the original receipt and record identities; lookup verifies
anchor → receipt → record metadata → exact member ids/bytes. Record/receipt outcome disagreement
and a coherent member+record+reidentified-receipt rewrite with unchanged anchor are rejected.

### Iteration 13 — reject nominally bound but operationally unrelated inputs

Review found three reidentified substitutions that were still accepted: reusing one Experiment
against a different RIR, claiming another evaluator or platform in the Resolved Runtime profile,
and overriding an input Quantity outside its declared support. Admission now requires exact
Experiment → RIR identity, exact actual evaluator/platform, and the RIR symbol's representation and
support before any Event dispatch. These are pre-dispatch refusals and issue no terminal audit.

### Iteration 14 — close the embedded Operation boundary, not only its program body

The prior compiler rejected unknown node tags but ignored extra fields on known nodes, while
runtime rechecked only release/version/program bindings. A reidentified RIR could therefore change
result/effect declarations without changing the executed program. Node encodings are now exact
field sets. Operations declare kind/unit rules, permitted Numeric profiles, and the complete
state/signal/schedule/cancel/random effect inventory. HIR/RIR carry the full selected Operation
projection, and runtime compares every field with the exact selected release.

### Iteration 15 — close observable refusals and the first over-budget Event

The descriptor formerly recognized an outcome name but did not close each handler/public envelope;
missing, extra, or wrong-typed fields could escape. The Runtime audit also used a reduced
stage/code/location object, and `max_events = 0` did not identify a refusing Event. Outcome models
are now closed and enforced on both sides of transport. A prototype-local Diagnostic authority owns
the tested Runtime codes/messages/location tags, and every post-dispatch refusal records the first
refusing Event plus a full code/message/tagged-primary/related-locations Diagnostic. This repairs
the probe; the handwritten diagnostic authority does not close the Kernel/LDB authority gate.

### Iteration 16 — close nested Operation declarations and malformed Quantity support

Exact-head mutation review showed that closed Operation top-level fields and closed Kernel nodes
were insufficient. Reidentified releases could still add Result fields, use a non-string Result
kind, name unknown kind/unit laws, declare an unused parameter, choose host-defined purity despite
writes, or add/mistype resource bounds. A string bound also escaped as a host `TypeError` rather
than a typed refusal. The compiler now closes Result variants/payload types, resolves kind/unit laws
against selected authorities, rejects parameters because this narrow Kernel has no parameter-read
node, checks purity against the complete effect set, and requires exact nonnegative integer bounds
equal to derived reads/writes. Quantity support now has an exact integer shape and ordered bounds
before comparison. Every reproduced mutation is a `static` refusal; none leaks a host exception.

## Findings

### ORTH-01 — Model-Source-only admitted Quantity extension is viable (`Confirmed, narrow`)

One `focus` symbol using the pre-admitted generic stat kind becomes a Typed-HIR symbol, RIR state,
Metric sample, Capability-manifest entry, and published artifact. Kernel, LDB, selected releases,
Package Lock, compiler/runtime source, and operation behavior remain unchanged.

**Design feedback:** an ordinary attribute may instantiate an admitted generic Quantity contract.
Adding a new nominal Quantity kind is not Model-Source-only; it remains a Domain-package release
edit and open design/coverage gate.

**Root attribution:** generic symbol/type resolution is Standard Schema foundation. The RPG
attribute inventory and any new nominal kinds are template/package content.

### ORTH-02 — One extension can be one content-addressed package release (`Confirmed, narrow`)

Each selected mechanic enters through one complete immutable release artifact. Lock binds its
content identity; projections cover package, dependency, capability, Quantity-kind, unit,
Numeric/Runtime-profile, Operation kind/unit/Numeric/effect contracts, vector, and diagnostic
surfaces. Tampering without reidentifying the release refuses before resolution.

**Design feedback:** retain the complete-release artifact and exact Lock binding. This prototype
does **not** prove that two different contents cannot reuse the same package id/version across
different LDBs; historical semver uniqueness and same-version semantic-reuse refusal require an
external release index/transparency authority and remain unvalidated.

**Root attribution:** release identity/history is Standard Schema foundation; operation bodies and
vectors are Domain-package content.

### ORTH-03 — Lock locality is repairable; exact-LDB RIR blast radius remains a design tension (`Refined`)

Removing whole-LDB identity from semantic Package Lock makes Lock byte-identical when an unused
package is added and the selected release/type/capability/profile/operation closure is identical.
Runtime behavior also stays identical. RIR identity still changes because current bADR-0013 binds
the exact whole LDB.

**Design feedback:** the first-pass Lock blast radius was an implementation defect and is repaired.
For RIR, do not choose a prototype-local final policy: the design authority must decide whether
exact whole-LDB binding intentionally invalidates unrelated RIR, or whether a selected-LDB
projection/compatibility binding can preserve authority without global identity churn.

**Root attribution:** Standard Schema authority/identity design, not RPG template content.

### ORTH-04 — Closed use-site and Operation-result variants are statically enforceable (`Confirmed, narrow`)

Use-site matches and package programs both derive from one Operation result. Missing/duplicate/
unknown/wrong-payload arms, program-produced wrong tags/payloads, unknown node tags, and extra
fields on known nodes refuse before execution.

**Design feedback:** retain result-schema-derived exhaustiveness and result refinement. Diagnostic
selection remains handwritten rather than an executable LDB judgment.

**Root attribution:** static variant machinery is Standard Schema foundation; selected variants are
Domain-package content.

### ORTH-05 — Package bodies can be generic without becoming unchecked (`Confirmed, narrow`)

Five selected operations execute through closed generic nodes. Static traversal derives exact
state read/write effects and reachable results; the Operation also closes kind/unit rules,
permitted Numeric profiles, and signal/schedule/cancel/random effects. Runtime revalidates the full
embedded Operation projection against the selected release and Lock identity. An LDB-only but
unselected operation cannot execute. Because this narrow Kernel has no parameter-read node,
declaring any parameter is refused rather than accepted as unused authority.

**Design feedback:** projection and closure checks are necessary, but handwritten traversal is not
executable Kernel/LDB authority and cannot close the Semantic-authority gate.

**Root attribution:** generic program checking/execution is Standard Schema foundation; concrete
compositions are package content.

### ORTH-06 — Refund and rollback are distinct and now audited (`Confirmed, narrow`)

Interruption refunds a prior reservation through compensation. A later Event refusal preserves the
prior committed Snapshot and exposes discarded current-event writes in terminal audit. An
event-count refusal at a zero budget identifies the first over-budget Event. Both audits carry a
prototype-authorized stable code/message, tagged primary Event location, and related locations.

**Design feedback:** use `refund`/`compensation` for package semantics and reserve `rollback` for
atomic Event failure. Keep pre-dispatch refusal outside terminal-audit issuance.

**Root attribution:** atomicity/audit terminology is Standard Schema foundation; refund policy is
resource/action package content.

### ORTH-07 — Effect lifecycle composes, but Effect completeness is open (`Confirmed, narrow`)

Apply, reapply, and remove produce deterministic Snapshots and outcomes without effect-specific
runtime branches. Capture, reducer algebra, maximum-stack conflicts, immunity, expiry, dispel,
periodic effects, signals, and scheduling remain absent.

**Design feedback:** treat this as extension-seam evidence only, not bADR-0017 Effect completeness.

**Root attribution:** missing mechanic breadth is RPG/Domain-package content; generic scheduler and
reducer machinery remains Standard Schema foundation.

### ORTH-08 — Independent Experiment inputs/selectors/acceptance are executable (`Confirmed, narrow`)

Experiment is verified before dispatch, final-bound to one exact RIR, drives support-checked
input-role overrides and Event sequence, executes zero-or-more Metric selectors, and computes
verdict from its acceptance policy. The same Experiment is refused against a different RIR. No host
scenario bypass remains in runtime.

**Design feedback:** the vertical authority split is viable. Selector and acceptance meanings are
still handwritten host logic; their typing, closure, ordering, empty behavior, and identity laws
must become executable LDB/Experiment contracts before conformance.

**Root attribution:** Standard Schema Experiment/Metric foundation.

### ORTH-09 — Anchored local publication closes the tested rewrite gap (`Confirmed, narrow`)

Descriptor validates closed handler/public outcome envelopes, exact member multiplicity, and
forbidden success artifacts. Runtime refusal returns a retrievable terminal-audit receipt. Trusted
anchor binds the original receipt and record; lookup rehashes metadata and member bytes. Coherent
rewrite with unchanged anchor and record/receipt outcome disagreement both fail.

**Design feedback:** retain an abstract trusted commit-anchor requirement and adapter-specific
vectors. Full anchor/index compromise, concurrency/races, crash recovery between directory and
anchor commits, distributed stores, and object-store adapters remain explicit non-claims.

**Root attribution:** Standard Schema CLI/artifact foundation.

### ORTH-10 — Semantic authority and complete Schema 2.0 remain unvalidated (`Unvalidated`)

Kernel nodes, static traversal, selector semantics, acceptance, the prototype Diagnostic authority,
and evaluator are one handwritten Python interpretation. Resolution covers exact acyclic fixtures
only. There is no independent Kernel/LDB judgment engine, independent evaluator, external release
index, general solver, portable store adapter, Cross-evaluator comparison, or independent Evidence
validator.

**Design feedback:** this repaired mechanism probe still must not close the prior Semantic-authority
gate or issue normative Replay/Evidence.

**Root attribution:** Standard Schema foundation, not RPG template content.

## Defensible result

The repaired selected slice passes the Orthogonality/extensibility **mechanism** question:
Model-Source-only admitted generic attributes and one-content-addressed-package mechanics traverse
the proposed layers without mechanic branches, while closed nodes and Operation projections,
exact-RIR Experiment authority, actual evaluator/platform admission, selected-Lock admission,
support-checked inputs, full Runtime Diagnostics/audits, closed descriptor envelopes, prior-commit
rollback, and anchored local publication are executable.

It does **not** prove complete Schema 2.0 feasibility, executable semantic authority, historical
package uniqueness, general package solving, portable publication, normative Evidence, or RPG/
Roguelike completeness. Those gates remain open.
