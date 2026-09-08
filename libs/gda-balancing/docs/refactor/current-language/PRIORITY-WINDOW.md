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

## Corrected authority-role bindings

[Four bounded counterexamples](evidence/priority-window/authority-name-counterexamples.json)
show that the provisional Kernel names LDB-owned numeric policy, typed-profile,
constructor and static structured-reason identities. The numeric probe changes 621
occurrences and both consumers report the same 31 typing refusals; its original public
build/check/run succeeds. The other three roles each fail admission and public build.
Those old probes produce no renamed RIR and make no later-execution claim.

The correction is integrated at `56872e5df`. Numeric capability selection derives actual
IDs from admitted exact Quantity definitions and selected profiles. Typed-envelope
selection uses its existing source/value role, and the profile owner must export one
complete constructor for every existing structured value-rule role. The fixed profile
ID and constructor ID list are deleted. Static structured faults use their Kernel
stage/signal, with the actual selected reason and diagnostic resolved by each consumer;
actual command refusal catalogs use the same current bindings. No compatibility alias,
fallback, numeric-law change, primitive or phase is introduced.

This replaces the provisional Kernel with `sha256:82c67a6d19daf616e680f25bf4b9dbda811d2bdfc9ac4d76a683b7e49af35f8a`.
It does not rehabilitate the old Kernel's failed invariance claim. The
[correction evidence](evidence/priority-window/authority-role-correction.json) preserves
the original and final authority identities, exact machine changes, observed Model
vector outcomes and raw report hashes. All 34 Model vectors retain their accepted or
refused outcome (13/21); only existing derived RIR/Debug identity oracles change, and a
fresh process confirms their fixed point. Seven maintained Models publish 56 members;
nine Experiment bindings are updated from actual RIRs and checked against the final
sealed graph. All seven authored Source files remain byte-identical.

Six public configurations (original, each role separately, all together) build and run
with value 7. The independent consumer compiles and executes each case; production
admits its six result members. All 24 existing structured-value vectors are checked per
role, together with public and admission refusals. The 106-test primary integration
suite passes. Required CI now includes these tests; collection accounts for 2113 tests
and 347 package vectors without missing or overlapping coverage. Full CI and final
independent review remain open.

A separate Spec review of this four-role patch at `56872e5df` finds no actionable
issue. Its isolated 21-test run and an additional public diagnostic rename pass;
wrong numeric law, borrowed profile ownership and wrong static stage refuse in both
authority consumers. Three other malformed-graph probes refuse at integrity ingress
only; they are not semantic-law evidence. This review does not cover the complete
issue. Primary revalidation also admits all seven previously published RIRs and checks
all nine committed Experiment files against the final sealed graph.

The next inventory checkpoint (`91d4bacac`) derives primitive signal reservations from
their exact Kernel stage/signal roles and records the real Type-ID projection edge.
The same spelling in a reason ID or another stage remains renamable. Its 52 integrated
inventory/CI tests pass; Ruff and all 211 Python format checks pass. The current
collection contains 2115 tests and 347 package vectors with no omitted or overlapping
test coverage. The semantic inventory remains incomplete; those test counts do not
establish its completeness.

## Rename authoring checkpoint

The rule/Formula checkpoint at `aaafb35a6` adds rule-variable key and term references,
judgment selection, Formula notation, slots, slot parameters and fixed-value aliases.
Source format markers stay bound to the declared wire-format equality. They are
protocol format parameters, not nominal identifiers or a reserved spelling list.

The conformance-only [rename authoring helper](../../../tests/schema2_extension_renaming_support.py)
derives and validates its own inventory before accepting a bijection. It applies
simultaneous edits at original value, key and independently parsed Formula AST
positions. Key collisions refuse; body and expression must still agree. It uses the
explicit supplied Kernel to reseal existing package/vector/root envelopes and refuses
missing membership. It returns authored inputs only. Fixed consumers must produce new
artifacts/results; numerical vector expectations are not recalculated.

The [bounded tests](../../../tests/test_extension_renaming.py) cover key swaps,
escaped positions, unchanged user text, a missed Formula reference, exact current
envelopes, missing members and unsupported identity contracts. A real renamed rule
binding reseals and admits in both authority consumers without changing any vector
set. The integrated inventory/authoring/CI suite passes 72 tests for `6b6f2ab76`;
Ruff and targeted Pyright pass. An independent review of the helper at
`aaafb35a6` reports no finding, with 58 plus 13 passing checks and additional real
rule-variable swaps and quoted Formula parameter names. The
[checkpoint record](evidence/priority-window/rename-authoring-checkpoint.json)
preserves source hashes and the distinct primary/review validation scopes. This is
bounded authoring evidence: the complete graph still has uncovered roles and the public apply helper
refuses it. No complete rename, final build freeze or full issue acceptance is claimed.

One subsequent coverage check catches a real inventory error: constructor member
selectors are open addresses, not fixed merely because present definitions use the
same names. A coherent Enum `members` to `labels` selector/parameter/definition-key
rename admits in both consumers under the unchanged Kernel. Actual public Python
Model/Experiment APIs also build and run the maintained structured-selection case;
the produced artifact set validates. Constructor-scoped address and key occurrences
enter the inventory at `1592ce626`; literal payload values remain data. The integrated
77-test checkpoint passes. This probe is not a CLI subprocess claim.

## Artifact protocol-role direction

Coherent RIR kind/schema renaming fails provisional authority admission; Trace and
Terminal Audit renaming admits but fails public Experiment contract preparation.
An isolated prototype puts one optional `protocol_role` on the existing Wire Schema
Definition. Identified artifacts resolve through its existing `schema_kind` link to
the Artifact Contract; standalone Source/Experiment inputs select the schema directly.
Generic APIs still use actual kind names. Required roles have unique owners; extra
schemas/contracts may omit a core role and retain open kind names.

The bounded schema-role prototype passes actual public build/check/success/refusal
paths with Source, Experiment, RIR, Trace and Terminal Audit kinds renamed together.
Independent Model output and Runtime member exchange pass, and resealed fabricated
Formula records and a false terminal reason still fail semantic validation. This is
an isolated prototype, not an integrated authority revision or full-family proof.
Independent architecture review supports the single schema owner. Existing Template
member-role bindings should be reused rather than adding their schema names to the
Kernel role list. Publication labels also require their own consumer check: a host's
fixed logical member name is not automatically a reserved Kernel identity.

The production correction is integrated in `3444efff8`, `12b5bb34d` and `724fe0395`;
bADR-0012 and the glossary record the role's single owner. The combined Kernel is
`sha256:9dc4e8991b70970d32d1012a7545dee57ef7ac2f4966721694255f39d6ff3c2c`.
It also replaces resolution routing's local-binder spelling constraint with the actual
field-to-binding-to-source reference. No additional primitive or phase is introduced.
Original and all-26-kind renamed authorities pass public build/check/run/inspect/Replay,
independent artifact exchange and semantic forgery checks. Four local-binder cases and
53 paired Template cases pass. All 34 Model vectors retain their existing expectations;
independent checking requires no oracle or package-semantic-identity changes.

The [integration record](evidence/priority-window/protocol-role-integration.json) separates
these worker scopes from primary validation. The primary combined run passes 135 cases
and exposes one outdated identity-map fixture. After supplying a real name-changing
bijection, that test still refuses the incomplete graph; its 16-case follow-up also
passes concurrent publication and forged-terminal checks. CI collection covers 2212
tests and 347 vectors with no omissions or overlap. Ruff and full Pyright pass.
The independent Formula notation helper's separately reproduced Source-kind selector
is corrected at `46937f6aa`. Actual rendered Formula text independently parses under
original and renamed Source kinds; missing or duplicate Source roles refuse. Complete
inventory, final fixed-build exchange and all-shard CI are not yet established.

The primary Formula/authoring follow-up passes 17 tests. Current collection after the
two new refusal cases covers 2214 tests and the same 347 vectors without omissions or
overlap. The worker also validates all seven maintained Models and nine existing
Experiment bindings without edits. Two real wheels, original and all-26-kind renamed,
load their modules from the wheel and pass public build/check/run plus numeric-overflow
refusal publication. These remain scoped packaging checks; they do not establish final
complete-graph extension invariance.

A bounded DDMA review at `8267f8d38` reports no actionable finding after 22 targeted
tests and an independent Template migration probe. Renaming all ten LDB-local Template
member roles and their references, then rebinding the authored release, passes both
authority consumers, real public get/instantiate and all eight Model outputs. The
concrete `quantity_minimal` authoring provider must migrate its own references when
that content changes; its unchanged local names do not establish a generic consumer
defect. The correction therefore adds no nine-role Kernel catalog or schema-shape
selector. This review does not close the complete issue or its token inventory.

## Operation selection counterexample

The [public counterexample](evidence/priority-window/operation-type-coupling.json) adds
an otherwise unused `inventory.otheritems.IntList4` input to the maintained periodic
Source. Both its namespace and `standard.conformance.structured` remain selected.
Consistently renaming only the new Type to `OtherItems` preserves A/B authority
admission, all three actual public build/check/run outcomes and the Metric observations.
It nevertheless changes selected Operations from 27 to 23: the four bounded-fold
Operations disappear, although their actual formal Type owner and every entrypoint
root are unchanged. The bare cross-package `types.id -> operations.owner_type` edge
causes this coupling. A separate admitted two-owner inventory case confirms that one
physical field cannot independently rename both nominal owners.

Delete `owner_type` and this edge. Select Operations from actual Source/Formula roots
and their admitted transitive dependencies, and independently derive the same closure
when importing RIR. Reuse existing reference and reachability judgments; do not add
another owner field, retain the old edge, or treat an unknown-root fallback to every
Operation as authority. Actual call typing, missing-owner/unknown-operation refusals,
selected numeric/runtime rules and resource accounting still apply. This correction
is implemented at `8eaf2c95d`. The witness also remains a regression input for #879's
final dependency and deletion review.

The implementation deletes the field, its machine declarations and the cross-owner
Type edge. Actual Source entrypoints and reachable normalized Formula roots seed the
existing reference closure; RIR import independently derives that same selection.
The unknown-root fallback is removed. An unused compiler namespace can remain absent
from declarations-only execution, while a reached Operation still requires its actual
numeric/runtime profile. No extra compiler-owner eligibility gate is introduced.

Seven maintained Models publish 56 members, and nine Experiments are rebound to the
actual new RIRs. All seven authored Source files remain unchanged. The 34 Model vectors
retain 13 admitted and 21 refused outcomes; only derived RIR/Debug identity oracles
change, and a fresh process verifies their fixed point. Paired worker suites pass
278 tests. An independent Spec review at `8eaf2c95d` reports no actionable finding
after 20 targeted tests and additional unused-Formula and resealed unbound-Formula
probes. These are scoped results, not a full #878 review.

The new closure changes the minimal compilation charge from 375 to 319. The permanent
test still checks two limits below, the exact limit and two above, including complete
refusal envelopes. The CI obligation inventory now requires all five current limits.
The two-owner specialization fixture selects both Operations through real entrypoints
and distinct Formula bindings, compares shared/equal/detached objects with independent
compilation, and separately checks that an unused copied Operation is absent.

## Refusal replay and local collection references

The paired priority run exposes a separate consumer defect: Runtime correctly refuses
List capacity overflow, but independent audit replay constructs a structured fault
with an LDB reason ID and an implicit static stage. The current fault API expects the
intrinsic signal and actual stage. `c7e2ae9bd` corrects that construction and removes
the redundant lookup. Existing selected-reason decoding and exact terminal checks
remain. Original and renamed reasons pass; five resealed position, path, site,
resource and reason forgeries still refuse. Runtime and machine authority are unchanged
by this correction. The integrated roots/public-priority/refusal/CI suite passes 40 tests.

Three type-closure collection references also used fixed host names despite their
open LDB declarations. `6c215a552` resolves the unique referenced collections and
checks their actual typed sources. It deletes the name constraints and retains exact
field/path/source validation. Renaming all 16 collection labels passes both authority
consumers, independent lowering, public CLI build/check/run and artifact admission.
The complete RIR and all Runtime members are equal without normalization. The same
public test fails before repair. Nineteen new cases and 182 related worker cases pass;
the primary projection/inventory/authoring/CI suite passes 99 tests.

The [correction record](evidence/priority-window/root-projection-correction.json)
preserves exact commits, source hashes, scoped reviews and parsed primary results.
CI collection accounts for 2175 tests and 347 package vectors with no missing,
overlapping or unassigned tests. Ruff and full Pyright pass. This is collection and
focused execution evidence; all-shard CI and the final complete rename remain open.

## Source address routing and build-freeze evidence

The first Source `modules` rename probe omitted the authored lowering selector and
five Model-check selector references. Its unresolved operand is not evidence of a
consumer defect. After those declarations are changed consistently, the existing
bounded-fold Model builds and runs. Separate Formula consumers still used the old
field address: pair checking skipped malformed expressions, the CLI output-schema
projection failed, and Debug Map/refusal pointers named the old field.

`b2df9a1bf` removes those literal reads and follows the existing profile mappings.
Fifteen permanent public cases pass under the original address and two changed
addresses, including `/` and `~`. For both bounded fold and the maintained RPG combat
Source, complete RIR and all six Runtime member bytes match across address changes.
Independent compilation matches four semantic members for both Sources. Independent
six-member Runtime exchange is verified for bounded fold; no independent whole-Runtime
claim is made for RPG combat. Static failures retain the exact Source identity and
escaped authored pointer. No Kernel, language authority or maintained Source changes
are needed for this repair.

The inventory now derives Source member addresses from the existing independent typed
selector. It publishes addresses only after the entire judgment succeeds. Schema
property declarations, required members, profile paths and actual Source keys share
the same field owner. Dot-path targets must be representable by that encoding; this
does not prohibit dots in unrelated token names. Formula authoring transports exact
expression pointers through field renames and reuses the actual mapped requests.
Negative lookup vectors retain proven absent names as references: renaming cannot
capture them into a declaration or exempt an ordinary missing provider.

An independent build audit confirms that the four-file reference Runtime identity is
not complete freeze evidence. Actual Formula helpers, shared data containers and
installed JSON Schema dependencies also execute. The final experiment must fix a
verified A wheel, complete B harness/driver, Python and installed dependency files
before inventory derivation, then compare the same file membership and hashes after
all exchanges. This is an external experiment condition; it does not add a product
manifest or change provenance fields. Existing wheel filenames alone are insufficient
to select the final implementation. The final freeze has not run.

The [integration record](evidence/priority-window/source-address-integration.json)
preserves scoped results, the incomplete-probe adjudication and the build audit.
The reader still reports 56 explicit gaps; these corrections do not establish a
complete inventory or a final #878 pass.

## Remaining proof and integration

- Complete the semantic-token inventory and resolve remaining demonstrated name
  coupling before the final build freeze. Artifact declaration IDs and protocol roles
  must be distinguished by actual authority; an open string cannot be exempted merely
  because a host recognizes its spelling. The old Type-to-Operation edge is deleted;
  its counterexample and permanent tests remain evidence for final dependency review.
  Preserve distinct nominal Type owners and validate the complete rename relation
  instead of merging their identities.
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
