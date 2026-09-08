# Early priority-window witness (#878)

Base: shared dev `1596e77ea6807d4b91b8709da52c72eed346b0de`, after #877.
[#878](https://github.com/aigengame/godot-agent/issues/878) owns acceptance; the
[plan](PLAN.md) owns sequencing. This record starts with a falsified candidate and
open implementation work. Functional evidence remains candidate/open; #575 retains
the complete scenario family and #542–#544 retain their activation conditions.

## Contract and first checks

The existing bADR-0014/0016/0017 boundaries remain binding: `game.action` owns pending
actions and their outcomes; `game.turn` owns response order, priority, pass/close policy
and bounded nesting. Runtime owns the existing input/transition/observation phases.
The witness must execute reusable Operations, compute its state from inputs, and
expose the resulting stack, priority and stable pending identities at each boundary.

Two responders, a proposal, a counter, a counter-to-counter and consecutive passes
form the initial candidate. Resolution must inspect the actual pending graph in
reverse order. A counter proposal does not immediately erase its target; cancellation
occurs prospectively during resolution after the window closes. A valid pass-choice
variant must change the final result under the same rules. An invalid responder or
counter target must have a declared rollback outcome. These are proposed scenario boundaries,
not implemented observations.

The first checks target two independent risks: whether the current value/Operation
basis can represent that protocol without fabricated state, and whether complete
renaming exposes host-selected meanings. No Record construction, extra phase or
callback is assumed to exist. A concrete missing capability reopens the basis before
dependent content expands; it must not be hidden by a prescribed trace or a genre
branch.

## Falsified Formula owner selection

The [first counterexample](evidence/priority-window/notation-owner-counterexample.json)
renames the exact namespace `standard.schema` to `probe.schema`. Both authority
graphs admit; Kernel bytes and its fixed constructor/profile/reason tokens are
unchanged. The same Source bytes pass public `model check` and `model build` on the
baseline, producing all eight Model members. The renamed graph refuses both commands
with `language.source_contract_mismatch` at the two Formula bodies.

The host's Formula notation resolver filters by the literal package name before
looking for the unique admitted `model-source-package` wire-schema owner. That
restriction contradicts the already admitted graph. Remove it and derive the owner
through the existing closure role and artifact kind, retaining uniqueness checks.
This is a prerequisite repair to generic authority consumption, not a new genre
dispatch rule. Its permanent public regression must distinguish the original defect.

The original dev candidate therefore fails this bounded renaming check. After repair,
freeze both implementations before deriving the full witness graph, inventory and
bijection. The same fixed builds must then process original, extended, renamed and
input-variant cases. Do not describe the original build as invariant, or count this
single namespace substitution as complete inventory validation.

The prerequisite is implemented by reusing the existing unique Source schema selector
and deleting both package-name filters and the duplicate scan. Four permanent tests
cover the real Formula and generic Source check/build paths plus missing/duplicate
schema-owner refusal at Authority admission. On the preserved old implementation,
the Formula rename case fails and the other three pass; after the correction these
and related Formula/namespace cases pass (17 tests). Kernel/LDB resources are unchanged.
Final fixed-build and complete inventory acceptance still require the work below.

## Scheduled-argument counterexamples

The [second evidence record](evidence/priority-window/scheduled-arguments-counterexamples.json)
preserves the original typed protocol and a diagnostic scalar contrast at the same dev
base. The original candidate adds admitted `game.action` and `game.turn` content,
builds all eight Model artifacts, and passes Experiment check. Runtime captures legal
nominal arguments for the final scheduled resolution, but Event Trace publication
raises an internal validation error. Two LDB wire positions still allow only integer
scheduled values: Event Trace and the committed trace prefix in Runtime Terminal Audit.
The existing integer-or-closed-typed-value carrier is the appropriate correction;
the selected nominal contracts and independently replayed capture remain mandatory.

The diagnostic contrast adjudicates the same pending graph before scheduling a scalar
final effect. Under one RIR, the full counter chain computes cancellation `[2]` and
final power 7, while the consecutive-pass variant computes cancellation `[1]` and
final power 0. The baseline result is incorrectly refused by complete artifact
admission: a duplicate check compares a captured port with its pre-Event value even
though an earlier invocation in that Event legitimately changed it. The same owner
already reconstructs the actual capture through Replay. Removing the stale comparison
must retain that exact reconstruction, schedule instruction, ordering, identities and
StateRefs, with coordinated forgery tests.

These are generic authority/consumer repairs. They require neither a new Kernel
primitive nor a genre dispatch branch. The scalar contrast does not replace the
original typed protocol. Public success after the repairs, dynamic conformance,
negative boundary cases and complete fixed-build invariance remain open. Wrong
priority or target may be declared gameplay-alternative rollback outcomes; those
outcomes must not be mislabeled as Runtime failures. Bounds and illegal callback or
phase cases retain their actual refusal requirements.

Both repairs are integrated at `c0a204f2d`. Re-running the original typed builder
without changes now completes public build/check/run and complete artifact admission
for both inputs. The original Source SHA-256 remains
`cf8533d08fe527d194a9926b3c9b9dd46864394688fa49f8371968878675af7f`.
The baseline has 12 trace entries, 123 charged node steps, cancellation `[2]` and
final power 7; the pass variant has 10 entries, 87 steps, cancellation `[1]` and
final power 0. These counts belong to the original typed protocol, not the earlier
scalar contrast or the pending permanent candidate. The observation-file SHA-256 is
`0351f3faadc65e925d62a44bafa2886629d3781ccccd0a555cec84448bf90786`.

Permanent public regressions cover capture after a preceding write, nominal List/Enum
value capture, retained writable references, and publication of a later-refusal audit.
Coordinated argument/name/StateRef and nominal type/value/capture mutations still fail
the semantic catalog consumer; malformed bare values and open envelopes fail wire
admission. Both test files run in the required `composition` CI partition. The
integrated focused suite and CI policy checks pass (22 tests). The wire correction
changes only two schema leaves and their seals; all seven maintained Model RIRs are
byte-identical before and after it, so their Experiments need no rebinding.

## Permanent candidate design corrections

The bounded design review accepts the pending-ID/Counter lists and reverse fold.
Action owns ID allocation, target validity and refusal of a second proposal in this
one-window witness. Turn owns window/priority/pass policy and propagates Action's
declared rollback outcomes. A direct Action invocation must not bypass its lifecycle
or target checks. Actor input is bounded to the two responders.

Use a final resolution slot at logical time 7 for the permanent candidate. This also
admits the longest legal seven-choice sequence: proposal, pass, counter, pass,
counter, pass, pass. The original diagnostic's slot at time 5 cannot cover that
sequence because it closes at time 6. Inputs outside the stated timing contract must
retain the existing scheduling refusal; no clock primitive, new phase, reset protocol
or reentrant window is introduced. The maximum valid sequence must complete under
the unchanged Event/run budgets. These corrections await their permanent public tests.

## Remaining proof and integration

- Derive every reachable non-Kernel token and occurrence from the applicable Kernel/LDB,
  node, constructor and authored-input contracts. An ordinary JSON string walk cannot
  distinguish an identity from user data. A graph rooted at the complete LDB includes
  all of its referenced packages and vector sets; selected RIR closure alone does not
  replace that graph.
- Independently validate complete coverage and an exhaustive bijection. Missing classes
  or members, duplicate/extra mappings and renamed reserved Kernel identities refuse.
  Keep exact renamed artifact identities distinct; inverse-map observations only for
  the declared equivalence comparison.
- Reuse independent authority admission, lowering and Event execution. Four independently
  lowered artifact kinds and a helper that executes one Operation do not by themselves
  prove complete multi-boundary result exchange. Close that consumer path explicitly.
- Run the real baseline and input variants, plus bounds, illegal callback and phase cases.
  Then run required CI and separate Standards/Spec/DDMA reviews before merging into dev.

Rollback restores the complete base code, authority, authored inputs and evidence in
an isolated checkout and repeats a public build/run. No fallback, parallel owner or
formal Extension Invariance Receipt is introduced to make this functional tracer pass.
