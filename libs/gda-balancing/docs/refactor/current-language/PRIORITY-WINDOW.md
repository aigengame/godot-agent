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
counter target must have a declared rollback outcome. The permanent candidate below
now executes these boundaries; its complete invariance proof remains open.

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
the unchanged Event/run budgets.

The permanent candidate is implemented at `f2809d98e` in
`tests/priority_protocol_support.py`, with 16 public cases in
`tests/test_priority_protocol_public.py`. These authored candidate packages remain
separate from installed package promotion and full #575 conformance. The tests execute
real admitted content through public build/check/run and validate the produced artifacts.
They do not supply expected traces as Runtime input. The unchanged rules produce power
7 for the counter chain and power 0 for both the pass variant and a same-depth variant
whose two counters both target the root. This last case distinguishes target-graph
semantics from a shortcut based on response depth.

The permanent Source and Experiment builders establish bounded public execution
evidence. Their metadata vectors do not establish complete package conformance.
Promotion into the maintained LDB requires applicable manifest-bound execution
vectors and independent conformance checks under bADR-0016. #878 does not promote
these candidate packages or duplicate that future #575 work.

Action's target, root-existence and single-proposal guards propagate rollback outcomes
through Turn. Direct Action calls and attempts to reopen a closed window do not allocate
new IDs or overwrite the pending graph. The longest seven-choice sequence completes at
the fixed slot. Baseline, pass and longest paths charge 127, 90 and 151 node steps;
their maximum Event charges are 44, 28 and 44. The same-depth retarget path charges
133 steps with a maximum Event charge of 50. All stay within 256/Event and 4096/run.
Depth overflow and backward scheduling produce validated Runtime Terminal Audits.
Callback, extra phase and unbounded List mutations update their body probes and seals
before the actual admission checks reject them. The integrated public suite and CI
policy checks pass (28 tests).

## Independent consumer checkpoints

The original typed protocol independently lowers to four equal Model members and both
consumers admit the semantic trio at `c0a204f2d`. This is compiler evidence only.
`20f1c967e` and `e3c446fe4` then extend the existing independent Event walker and add a
Scenario/artifact driver. The bounded proof uses one Scenario with two transition roots
and Snapshot scalar Metrics. B produces all six result members before A runs; A admits
B's members, and B compares A's members with fresh independent execution. Five semantic
members agree exactly; the truthful producer manifests differ. The driver consumes
selected RIR semantics and refuses unsupported scope. Its checked Source context supplies
independent RIR admission, artifact wire selection and artifact identity domains; it
does not replace the selected RIR execution laws.

Formula lifecycle, external inputs, scheduled events, Scenario RNG continuation and
refusal artifact production are not closed by that checkpoint. Its partial build
fingerprint must include the actual transitive independent semantic support before the
final build freeze. No complete priority-result exchange is claimed yet.

The independent consumer also finds a new integrity counterexample: change a genuine
Metric sample from 1234 to 1235, reseal the dataset, update the primary artifact's dataset
identity and reseal the primary. At `1776d4556`, all individual members and the complete
production set still admit although the authenticated observation remains 1234 and
`within_target` remains true for target 1234. B's fresh consumer rejects it. The existing
complete-set validator must verify exact samples and verdicts from already replayed
observations and admitted Metric contracts.

The repair is integrated at `ee64df662`: complete-set admission reconstructs the complete
canonical sample set from already validated observations and checks exact values,
metadata, target flags and primary verdicts. It adds no Runtime interpreter. The old
implementation fails 17 of 22 permanent cases; all 22 pass after repair, including five
legitimate controls. The integrated Metric, independent-consumer and CI policy suite
passes (48 tests). The separate authenticated-pending-root defect remains owned by #879.

At `33ec7b73f`, the existing independent structured-value validator also accepts the
selected RIR input view. It uses exactly one input mode, retains missing-owner/profile
refusals, and shares the existing recursive judgment with the package-vector path.
The build fingerprint now includes its bootstrap support dependency. Six selected-value
cases, the 14 mutual-consumption cases and two existing diagnostics cases pass in the
worker checkpoint. This does not yet close external-input or scheduled-event execution.
The integrated selected-value, inventory and CI policy suite passes (59 tests); the
CI inventory contains 2066 unique tests and 347 maintained package vectors, with no
missing, overlapping or uncovered tests. This is collection evidence, not a full CI run.

At `c16896a3b`, the independent driver executes the real priority baseline and pass
variant, including typed external inputs and future scheduled resolution. B produces
all six members before A executes. A admits B's complete set and B admits A's set by
fresh independent execution; the five semantic members agree exactly and the producer
manifests remain truthfully distinct. The values are 7 and 0. The integrated suite
passes 78 cases, including the existing independent fold and CI policy checks.
The [captured checkpoint](evidence/priority-window/independent-runtime-checkpoint.json)
records raw artifact, command and test hashes. Formula lifecycle, Scenario RNG, Runtime
cancel instructions and terminal-audit production remain unsupported by this bounded
independent Scenario driver; the ordinary public negative tests retain their actual scope.

Consistent renaming of four LDB effect identities exposes another real defect. Both
authority consumers admit the graph, independent compilation succeeds, and public
Model build and Experiment check pass. A's public run then exits 4 with an internal
`ValidationError`; B's old driver refuses the declared effects because its capability
list contains their original spellings. At `4d229d193`, B instead derives effect labels
from actual reachable Operations after checking every reached node's supported Kernel
semantics. It executes both renamed variants and A admits B's six members. The 34
integrated mutual-consumption cases pass.

Production's corresponding repair lands at `231c8e717`. Effect labels are opaque
permission-set identities projected from admitted reachable Operations; supported
instruction semantics remain a separate capability dimension checked before dispatch.
Wider profile permissions do not require the current program to exercise every effect.
The same six new cases fail before repair and pass afterwards: original and renamed
public runs, a caller's forged required effect, and an unsupported operator that must
refuse before dispatch. The integrated producer, independent-consumer and CI policy
suite passes 52 tests. Numeric handling is unchanged by this repair. This partial
rename remains a defect discriminator, not exhaustive invariance evidence.

The required `extension` CI partition owns the inventory, public priority and independent
Runtime tests. The earlier composition partition took 329.641 seconds in the final #877 run;
the new public suite alone took 83.76 seconds before integration. Separating the added
extension work preserves the existing 480-second per-shard budget as validation grows.

## Inventory and equivalence boundaries

The inventory checkpoint at `36d86e2ce` records scoped declarations and references,
source entry points, vector identities and Operation operands. A projection of the
existing independent composition judgment distinguishes a Record field identity from
a dynamic List key with the same spelling; no second type checker is added. The
integrated inventory, independent compiler and CI policy checks pass (40 tests).
The inventory still reports uncovered DSL, vector and artifact surfaces and refuses
to certify completeness. Its present token count is not a full-graph acceptance claim.

At `53d524b15`, the inventory also parses actual Formula expressions through the
existing independent parser and checks AST references and rendering in both directions.
Its independent Formula schema lookup drops the same stale namespace filter found in
production. Occurrence validation now requires its actual Kernel input directly; no
compatibility mode is retained for this new internal helper. The integrated inventory
and CI policy suite passes 45 tests. The current test collection accounts for 2092
unique tests and 347 maintained vectors with no missing or overlapping coverage;
Ruff checks/format (210 files) and Pyright pass. Complete semantic-token coverage and
full CI execution are still open.

The [named-stream counterexample](evidence/priority-window/named-stream-renaming.json)
also limits the equivalence judgment. Kernel `named_rng` explicitly hashes the UTF-8
stream name into initial RNG state. Thus `selection` is both a non-Kernel binding
identity and an entropy input: with seed 20260811, its first bounded draw is 0, while
`renamed.selection` draws 1. A real admitted Source/Experiment then changes from success
to the declared `candidate_mismatch` refusal. Both complete result sets validate, and
production and independent execution agree on each graph. The one tested normative
vector passes its original numerical expectation only before renaming.

The complete inventory must include and rename the stream; its entropy role is not an
exemption. For this tracer, the declared comparison preserves the same Kernel laws,
core projections and builds and requires independent agreement on each graph. When a
renamed identity is an explicit input to a Kernel numerical law, compare the derived
value against that law for the renamed input and retain its downstream behavioral
consequences. This is a specific dependency, not permission to accept arbitrary output
differences merely because two implementations agree. Ordinary bound-name observations
still compare under the inverse mapping, and exact artifact identities stay distinct.
Keep the unchanged golden assertion's failure visible; do not rewrite numerical
expectations or report renamed all-vector conformance. This interpretation does not
change RNG semantics or activate an authenticated Extension Invariance claim.

## Remaining proof and integration

- Remove demonstrated LDB-name coupling before the final build freeze. In addition to
  effect whitelists, the provisional Kernel directly names the LDB numeric policy,
  typed-envelope profile, four structured constructors and four static structured
  reasons. [Four bounded counterexamples](evidence/priority-window/authority-name-counterexamples.json)
  preserve actual A/B admission and public build refusals after coherent renaming.
  The numeric probe changes 621 occurrences and both consumers report the same 31
  typing refusals; its original public build/check/run succeeds. The other three roles
  each fail admission and public build. No renamed RIR or later execution is claimed.
  Ownership inspection identifies these as references to LDB declarations;
  their occurrence in Kernel text does not make them reserved identities. Reuse the
  admitted policy definitions, unique profile role, constructor value laws and distinct
  fault bindings. Keep missing/duplicate/unsupported semantics refusing. The pending
  correction replaces the provisional contract and requires affected conformance and
  authored-input revalidation; it does not claim the old Kernel passed full renaming.
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
