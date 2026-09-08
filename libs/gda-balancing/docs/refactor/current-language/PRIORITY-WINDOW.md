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

## Direct Replay observation members

Replay check keys were redundant hyphenated aliases of the Kernel's fixed observation
members. Both admission consumers translated the same four names, and Comparison
contained the translation table twice. `f62e0135d` deletes this translation: the policy
and comparison keys now directly name the actual observation members. `1985faeb8`
removes the final CLI conformance projection alias. There is no legacy fallback.
The policy still has its own authored ID, owner and canonical comparator; complete
ordering, semantic-profile equality and publication authentication remain required.

Only the owning policy, two vector key lists and their ordinary derived identities
change in three authority files. The Kernel, numeric expectations and all 34 Model
vector artifact expectations remain unchanged. Actual public build/check/run/Replay
passes with the existing bounded-fold observations. A controlled post-evaluation
observation change produces a `metric_dataset_identity` mismatch; this is a refusal
path test, not evidence of naturally nondeterministic execution.

The inventory follows these policy and vector references through their real Kernel
comparison law. The policy ID remains renameable; a coherently renamed Package and
its two vectors pass both authority consumers. Missing, misowned, unreserved and
false-law observation references refuse. The integrated Replay/inventory/authoring/CI
suite passes 111 tests. The [integration record](evidence/priority-window/replay-member-integration.json)
preserves exact authority differences and checked raw evidence. Other inventory gaps
and the final fixed-build experiment remain open.

## Explicit Formula grammar authority

The old Source JSON Schema stored two unreferenced `$defs` entries as Formula metadata.
Both authority consumers admitted coherently renamed metadata keys, but the actual public
renderer failed with an internal error. These entries were a host lookup convention with
no Schema-reference role. `9d3dcd611` deletes the containers and their readers, the unused
`version: 1.1.0` label and equality guard, and the otherwise unused `$defs` dialect keyword.

The Source Wire Schema Definition now carries `formula_grammar` and
`operation_notation_schema`. The Kernel's fixed Source-notation contract requires both
on the `model-source-package` role and forbids them on other definitions. The same
`standard.schema` owner retains grammar; contextual resolution remains compiler-owned.
Neither a metadata-key alias nor a fallback survives. Independent parsing and rendering
also use the declared binding keyword instead of a literal `let`.

A real `let` to `bind` grammar change passes both pair consumers and public
render/parse/check/build. Package/LDB identities and actual RIR expression content change;
Source Schema identity, Package Lock and RIR semantic identity remain stable. All seven
maintained Models preserve both RIR identities, and nine Experiments admit without
authored changes. Integration with Source routing and Replay passes 127 focused tests.
The [integration record](evidence/priority-window/formula-wire-integration.json) records
the exact scopes and authority merge. Other Formula punctuation and the complete
non-Kernel rename proof remain outside this result.

## Finite value vector identities

`560a8cf85` extends inventory through all 24 value-program vectors and ten admitted,
nominally owned structured-value vectors. Program operands, local targets and result
references share lexical ownership; evaluation-site references retain their vector
owner. Typed Enum and Record values follow their actual constructor and nominal Type.
Numeric observations, exact charges and Ref instance keys remain data.

The structured pass reuses the same Type/value traversal as ordinary declarations.
It checks actual independent observations before certifying roles and retains gaps for
the other fourteen structured vectors, including anonymous definitions and negative
payload/diagnostic paths. The larger gap count in its scoped receipt reflects finer
unresolved obligations; it is not a complete inventory. Legal changed graphs retain
their own original observations under both actual consumers. A newly authored isolated
Enum witness exercises a structured rename without claiming the existing Operation
vector family has already been completely renamed.

The combined inventory/renaming/Replay/Formula/CI-policy suite passes 119 tests at
`560a8cf85`. The [integration record](evidence/priority-window/value-vector-integration.json)
pins its 1575 tokens, 6110 occurrences and 84 explicit gaps to one graph containing
the full current LDB, all referenced packages/vector sets and the bounded-fold Source.
Experiment and artifact/result graphs have not yet been added to that proof scope.

## Enum parameter refusal boundary

The earlier constructor-selector probe left three anonymous Type expressions using
the old field. Correcting those authored references preserves all 24 structured-value
observations under both consumers. Its partial rename therefore does not establish a
semantic-equivalence failure. Existing public Source and Experiment schemas also
reject those malformed anonymous Type shapes.

A separate malformed owned-authority probe exposes a product defect: an Enum's selected
member parameter could be missing, null, an integer or a string. The first three cases
crashed public `package list`; a string containing the old names was accepted through
substring membership. `d0525e3a1` checks the required list container before membership
in the existing typed-value validator. The independent consumer performs its own check
and deletes its missing-parameter-to-empty-list fallback. All four cases now return
the existing typed refusal. No Kernel, reason inventory or global validator changes.

The [integration record](evidence/priority-window/enum-parameter-integration.json)
retains the four failing baseline cases, unchanged original/renamed public execution,
the 11-test worker scope and 97-test integrated scope. The new permanent tests are
registered in required CI; this result does not close the remaining inventory proof.

## Unordered value-program bindings

Independent review found that the first finite value-program rename used names whose
lexical order matched the original inputs. Changing `left/right` to `z_left/a_right`
preserves both actual evaluators' results but the two authority consumers reject it.
Their shared sorting restriction is absent from the Kernel's value-program contract.
It is also unnecessary: both executors immediately construct a name-to-value mapping;
their cache keys normalize that mapping separately. Instructions retain their execution
order and determine charging and the first refusal.

The adopted correction deletes the sorting requirement in both admission implementations
and the inventory. It retains name uniqueness, input shape and numeric checks. No
authoring sorter or new Kernel field is introduced. Permanent checks exercise a
non-order-preserving rename and all finite input permutations against unchanged
observations, including cache entries, charges and refusal sites. Duplicate names still
refuse at either end of the input list, where accepting them would let row order choose
different values. This correction does not change instruction ordering or vector oracles.

The [correction record](evidence/priority-window/value-operand-order.json) preserves
the independent 2276-permutation recapture, the failing rename, six passing targeted
checks and 177 passing inventory/authority/CI-policy integration tests. Source fingerprints
are verified at the recorded review head; required whole-issue CI remains separate.

## Anonymous structured roles and projection addresses

`39e894750` extends the shared typed traversal to anonymous Enum and Record members,
negative values and diagnostic paths. Equal anonymous comparison types share their
lexical owner; nominal members retain their package and Type owner. Missing member
references cannot capture a declared member. The reader checks the actual independent
observation before certifying these roles; a changed first-fault path leaves a gap.
All 24 current structured vectors retain their authored observations under both
consumers. The Enum-selector rename includes its nominal and anonymous occurrences;
other constructor renames still depend on uncovered vector families.

Diagnostic pointers use decoded RFC 6901 segments. Authoring transports every selected
segment together and then encodes the pointer, including names containing `/` and `~`.
It does not rewrite equal strings in ordinary user data. Independent review of the
structured slice found no actionable issue, including separate nominal/anonymous
owners and a rename that changes which extra Record field causes the first refusal.

`be57268d0` exposes the Schema addresses already checked by independent semantic
projection admission. It preserves all 13 baseline admission decisions and publishes
addresses only after the entire check succeeds. Ordinary content-identity exclusions
remain exact root keys; absent keys do not acquire fabricated Schema targets. This
interface is preparation for inventory references, not completion of those gaps.

The [integration record](evidence/priority-window/structured-projection-integration.json)
records the combined suite, the scoped inventory, raw checks and unchanged public
priority-window execution. Complete graph coverage and the final fixed-build proof
remain separate obligations.

## Closed Formula resolution and deleted syntax subsets

`5bb784c76` replaces the compiler Resolution profile's `standard.formula` extension
wrapper with one required, closed `formula_resolution` field. Source grammar remains
owned by the Source Wire Schema Definition; Runtime Formula lifecycle remains owned by
the Runtime profile. The new boundary relates actual Source selectors to their fields
and local-result inference to existing Kernel node laws. It retains real budgets,
charges, aliases and normalization choices without a second node specification.

The first pass deleted seven ineffective fields. Independent review then demonstrated
two more: narrowing `allowed_operand_kinds` and `allowed_binding_sites` did not restrict
actual compilation. A third field, `allowed_body_nodes`, filtered Operation calls but
Formula calls bypassed it. `812359313` deletes all three, including the partial filter.
It does not add enforcement solely to preserve the old knobs. The Kernel and admitted
Source alternatives define accepted Formula shapes; reintroduced old fields refuse.
This retires nine ineffective configurations and one inconsistent extra policy.

The conformance inventory reads the same explicit compiler field and uses the actual
Kernel shape sets. Its former extension-shape search and separate subset checks are
deleted. The [integration record](evidence/priority-window/formula-resolution-integration.json)
separates the original 32-command public verification from the later deletion checks,
records unchanged identities for all seven maintained RIRs, and captures independent
review and integrated validation. These checks do not establish the remaining complete
inventory or final fixed-build exchange.

## Fixed protocol structure counterexample

A Schema-only Trace field rename exposes another admitted configuration that the host
does not implement. At `be57268d0`, rename root `events` to `trace_rows` in both properties
and required members, then reseal the Package and LDB. Both authority consumers admit
the candidate; Model Build and Experiment check succeed. The original Experiment run
exits 0, while the candidate exits 4. The actual producer still writes the same three
`events` rows and fails its selected Schema at `ArtifactContract.identify`: `trace_rows`
is missing and `events` is unexpected. Code, Kernel, Model, Experiment and RIR remain
the same across the comparison. A separate Model check was not run for this probe.

The [counterexample record](evidence/priority-window/protocol-structure-counterexample.json)
also captures the missing prerequisite for Artifact projection inventory: its seven
RIR Schema targets have no interpreted field declarations yet. References cannot create
their own owners or borrow the unrelated Source field owner.

The accepted direction in bADR-0013 is to define fixed core protocol structures in the
Kernel and delete their independently configurable LDB copies. Derivation must reuse
the actual node, scheduler, outcome and typed-value laws. Moving every current raw
Schema into the Kernel would retain stale duplication: the
[maximum-node follow-up](evidence/primitives/maximum-wire-followup.json) confirms one
obsolete initialization union branch that still passes the public wire contract after
#876, although semantic RIR admission refuses it. #879 owns that deletion witness.

The Trace slice and review corrections are implemented at `a63025243`. Its independently
authored LDB Schema is deleted. The existing language index derives the fixed structure
from three Kernel container contracts and the existing scheduler, outcome and
nominal-value laws. RNG records and resolved-symbol targets reuse their existing owners;
they do not gain duplicate contracts. Independent B admission constructs its own Schema. The actual
Kernel is an explicit projection input; there is no ambient authority or old-placement
fallback. Unsupported resealed Kernel mutations refuse through the existing build
support boundary, without an additional field-name allowlist.

Both the old placement and the `events` to `trace_rows` override now refuse in A/B and
public ingress. Real public typed-Record scenarios succeed with original names and
distinct renamed Schema/Artifact names. A structurally valid forged call still fails
complete ArtifactSet semantic admission. The fixed protocol does not make nominal
payload data or real Source selectors Kernel-owned.

The [Trace integration record](evidence/priority-window/trace-structure-integration.json)
separates the initial 110 artifact pairs across seven Models and nine Experiments from
the final correction's 14-pair periodic-Effect case. Their RIRs, Metrics and Trace
observations remain unchanged within each stated comparison. The initial Schema omits
eight redundant enum constraints; the correction uses the existing RNG alphabet/width
projection with an equivalent regex spelling. Exact wire/content identities and dependent
references change truthfully. Preserving an internal identity does not justify another
regex-conversion mechanism.

The final 168-test integration passes. Scoped Standards and DDMA findings are closed;
the implementation and authored-inventory Spec reviews have no actionable findings.
Canonical equality preserves malformed Boolean/integer fixtures for real refusal, and
projection results no longer alias the input Kernel. All 2,362 collected tests and 347
vectors have CI assignments; this is not an all-shard execution result. At this Trace
checkpoint, the whole-LDB/vector/bounded-fold-Source inventory has 1,582 tokens,
6,137 occurrences and 54 remaining gaps, with its physical graph and Kernel unchanged. Other protocol
structures and complete graph/Experiment/result traversal remain open.

The [next owner record](evidence/priority-window/protocol-owner-followup.json) captures
the corresponding RIR counterexample at `18e2fcfa4`: a coherent `formulas` to
`formula_rows` Schema/projection change admits in both authority consumers, but actual
public Model check and build fail in the unchanged semantic projector. The RIR slice below
deletes the independent RIR Schema and structural exclusion recipe. It also deletes
collection output-name/shape settings, the two fixed package-output recipes and
`lowering.output_member`. The last setting only names an already computed declaration
list; it does not select types, rules or composition. Derivation uses actual Kernel
source roles and the selected lowering's terminal Fact contracts. Real selection graphs,
Source routing, rule chains, typed data and resource accounting remain.

The same record distinguishes a missing Source-to-initial-Fact transport law. A Source
property with the same spelling as a Kernel Fact field does not acquire that owner by
text equality. The existing generic copy and symbol/type adapters need one explicit
transport law before inventory can derive that join and close the five selector gaps.
The observed incomplete Source rename is not a valid semantic rename; its public
refusal does not justify a field-name exception. This follow-up remains pending after
the serial RIR authority change.

## Operation relation inventory

The existing Kernel relation contract now supplies the owners of Operation metadata
selectors, relation IDs, capability-policy copies and their projected vector values.
The two periodic apply Operations keep distinct owners for equal member spellings.
Their metadata extension labels and capability ID can rename independently; no machine
law binds those original equal strings. Schedule projections reuse actual instruction
roles. Projecting an object value excludes its enclosing key.

The [integration record](evidence/priority-window/operation-extension-inventory.json)
separates 27 focused tests, 93 retained tests and the primary's 49-test integration. Original
and renamed public paths preserve every ordered transition state. Co-mutated semantic
negatives update their policy/vector copies before refusal, while erased or misowned
references and invented names in canonical metadata still refuse. The witness runs both
authority consumers and production artifact-set validation; it does not claim independent
Runtime result exchange.

Independent Spec review found a legal declaration-order counterexample: an earlier
canonical copy omitted indirect Operation references while reverse validation passed.
The fix at `dbe667409` computes a finite closure over existing value positions and
propagates canonical equality in both directions. Other projections stay directed.
Four permanent order/direction cases now admit before and after renaming; removing their
indirect references refuses. The independent recheck preserves the original candidate
bytes, passes all 27 focused cases and refuses 16 additional erased, misowned or opaque-data
mutants. No scoped finding remains.

All 12 relation vectors are covered. At this Operation checkpoint, the complete
LDB/vector/bounded-fold Source graph has 1,610 tokens, 6,538 occurrences and 47 gaps,
down from 54. All 347
physical vectors remain. The 2,389-test CI collection has complete, disjoint assignments;
full CI execution and the remaining extension proof stay open.

## RIR protocol ownership

The [RIR integration record](evidence/priority-window/rir-structure-integration.json)
pins the production and independent-consumer change at `1768c8bbd`. The authored RIR
Schema, structural identity recipe, collection output names/shapes, two fixed package
output recipes and lowering output member are deleted. The generated protocol uses
the selected terminal Fact contracts, actual semantic collection sources and existing
numeric, assignment, composition and closure owners. RIR and Trace share the common
artifact envelope and Formula-reference structure. Source selectors, nominal data and
local collection names remain under their original owners.

Seven maintained Models and nine Experiments pass 32 actual public commands. Comparing
each RIR with its baseline changes only wire/content identity; every remaining payload
member is canonically byte-identical, including semantic identity. All 34 Model-vector
verdicts are retained; the 13 positive cases produce equal four-member artifacts in
both lowerers. Only their 26 RIR/debug identity expectations are refreshed. The command
capture precedes that vector-only reseal; the record distinguishes these evidence scopes.

Generated schemas are detached once before ordering. Required members and schema
alternatives have canonical order, while const data and arrays inside enum values retain
their order and duplicates. The inventory uses independent B projection on a detached
view, without adding a ghost Schema or identity recipe to the authored graph. Reusing
that view reduces its construction count from 60 to 14 on the same complete graph;
all inventory fields remain canonically byte-identical. The measured times are local
observations, not a general performance guarantee.

The initial 155-case integration has 154 passes and one stale expectation that the deleted
identity recipe must remain an inventory gap. Its correction and Operation/CI regressions
pass 40 cases. Separate public-projection follow-up passes 16 cases while retaining
generic projection and Formula closure checks. All 2,427 collected tests and 347 vectors
have complete, disjoint CI assignments. Full-package type and Ruff checks pass; this does
not claim execution of every CI partition. This checkpoint has 1,610 tokens, 6,537
occurrences and 45 explicit gaps across all current packages/vectors and bounded-fold
Source, with the authored graph and Kernel unchanged by inventory traversal.

Standards and Spec report no scoped findings. DDMA finds one real regression: arbitrary
collection exclusions can delete execution-required Operation fields while both admission
consumers accept the graph. Four correctly resealed cases (`id`, `body`, `inputs` and
`resource_bounds`) refuse at the baseline, admit at the candidate, and then break public
Model entrypoint resolution. The accepted correction deletes the arbitrary member and
extension exclusion settings. The fixed RIR owner must omit only Operation evidence
references, and Model lowering must reuse the existing Package runtime semantic
projection for notation exclusion. Neither an independent shadow Schema nor a second
notation exclusion list is restored. That correction is implemented at `7a077a757`; fresh-Kernel negative cases and
original/renamed public flows close the original DDMA finding. Seven maintained whole
RIR and Debug artifacts and their generated RIR Schema remain unchanged. The Lock
projection removes 140 notation occurrences; Source and Package semantic identities
remain unchanged, while affected content/build provenance identities change. All 34
Model-vector verdicts and existing oracles remain unchanged.

The corrected inventory reader and public CI registration pass 87 integrated cases.
The 2,444-test collection and all 347 vectors have complete, disjoint assignments;
the complete current package/vector inventory still records 45 gaps. This is not
full CI execution or final extension acceptance.

A subsequent independent Spec counterexample found that adding the actual
`standard.formula-slots` extension to the Package exclusion list admits under both
consumers, but unchanged public Model check/build regress from success at `1768c8bbd`
to internal `StopIteration` at `7a077a757`. The projection removes metadata before
Formula specialization, and Runtime also needs it for Formula evaluation evidence.
The correction at `2897fbffd` deletes the authored Package exclusion list from all
13 Packages, its Kernel member contract and its projection lookup. The existing
Kernel Source-notation contract now supplies the one actual Operation address used
by Formula parsing/rendering and Package semantic projection. Only notation at that
address is omitted. Formula slots, other families' same-spelling members and nested
opaque data retain their original owners. The independent consumer implements the
projection separately and both paths use the actual supplied Kernel.

Independent Spec re-runs the original correctly resealed slot candidate at
`d334e9989`: both admissions and actual public Model check/build refuse the deleted
Package member at ingress; the unchanged control succeeds. Six public notation and
Formula cases pass independently. Seven maintained whole RIR, Debug Map and Model
Explanation artifacts and the generated RIR Schema are byte-identical to `7a077a757`.
All 34 Model-vector verdicts remain unchanged, with equal four-member outputs and
mutual admission for the 13 positive cases; no vector oracle is rewritten. Actual
Runtime comparison preserves five full members byte-for-byte, including both
complete Formula evaluations (`45 - 8 = 37`, `20 - 6 = 14`). The evaluator manifest
changes only its content and implementation-provenance identities. Other compiled
artifact changes are confined to recorded provenance identity leaves.

The inventory follows the same supplied Kernel notation address, including escaped
pointer characters, while preserving unrelated opaque data. Its address-change test
checks interpretation of a supplied Kernel; it does not claim that a fixed host
accepts a new Kernel. The 136-case integration initially has one incomplete copied
contract-vector fixture; updating only those declared copied subtrees makes that
case pass. All 2,457 collected tests and 347 vectors have complete, disjoint CI
assignments. The physical graph inventory still has 45 gaps. These collection and
focused results do not claim full CI execution or complete #878 acceptance.

Protocol derivation also exposed a refusal-stage defect. Correctly resealed malformed
definitions were reported as a caller-index identity mismatch. Production now
distinguishes protocol derivation failure from actual index tampering; both independent
paths report the existing static reason at the actual language-definition or Runtime
owner. Runtime classification reuses its existing component validator only on the
failure path. The prior 97-case run preserves its one incorrect Runtime-subject result;
the correction does not weaken the original Runtime assertion.

Independent Spec then combines an invalid root identity with duplicate collections in
one consistent raw graph. The old independent consumer continued into protocol
derivation and mixed ingress with static diagnostics. The permanent regression fails
on that old implementation. At `b83626757`, both consumers stop at ingress and no
protocol projector runs. The existing derived-index tamper case remains an ingress
refusal. The integrated affected selection passes 22 cases; one redundant transient
index-tamper test is then removed, with the equivalent permanent independent case
retained. Final collection verifies 2,458 tests and 347 vectors with complete, disjoint
assignments. Full-package Pyright and Ruff checks pass. These results close the scoped
protocol classification defects; they do not close the remaining extension proof.

## Source-to-Fact ownership

The [Source transport record](evidence/priority-window/source-fact-transport.json)
records a real interpretation gap before the final build freeze. A coherently sealed
Source Schema can rename a copied Quantity member from `domain` to `opaque_domain`;
both authority consumers admit it, but its initial Facts violate the existing Fact
contracts. Previously, language rules ran before that violation was detected and the
public command reported a later Formula boundary.

The existing Kernel Model-lowering contract now states one fixed transport law:
unadapted Source Symbol members retain their names and values; existing Symbol-name,
resolved-Symbol, imported-Type and nominal-export adapters own their destinations;
collisions refuse. Both compilers check every selected initial Fact with their existing
independent predicates before the first Model-lowering rule. Refusal uses the existing
Source structural reason at the actual Symbol pointer. There is no per-package mapper,
new primitive, extra execution phase or packaged-Kernel fallback.

Independent DDMA review found a further distinction: the nominal-export adapter owns
the absence of its discriminator too. A copied `value_kind` could previously make a
non-nominal Type enter structured rules even though its Fact shape passed. The same
candidate now refuses before any lowering rule in both implementations. Actual profile
Symbol-name or Type inputs may still be named `value_kind`; permanent public controls
retain all five Symbols, exactly two actual nominal markers, identical complete RIR
and the bounded-fold results `2` and `1234`. This is role-based ownership, not a global
ban on a spelling.

The initial transport change preserves all 34 Model-vector verdicts, including
independently equal and mutually admitted four-member outputs for the 13 positives.
No Package or vector file is rewritten. A historical seven-Model comparison has 29
byte-identical members among 57 compiled/schema artifacts; the other 28 differ only
at the recorded Kernel/LDB and dependent provenance identity leaves. That comparison
precedes the inactive-adapter correction. The follow-up separately preserves all
4,189 initial Fact values byte-for-byte, re-runs the full vector gate and checks the
mixed public controls. These are distinct evidence scopes; no complete Runtime
artifact comparison across all maintained Models is claimed for this slice.

The inventory joins actual Source Schema addresses to the selected initial Fact
contracts. Copied Fact members remain Kernel-bound only at their actual Source
addresses; profile input names retain their separate roles. Same-instance schema
applicators and array selector steps follow their existing contracts without treating
nested payload properties as peer Source fields. Five Model-check selector gaps are
retired. The remaining 40 gaps and the full fixed-build non-RPG acceptance stay open.

Independent Spec review found two inventory defects: a member declared only in a
same-instance `oneOf` branch could disappear from coverage, and a legal swap of the
profile's Symbol-name and Type input names could make the reader treat a Symbol name
as a Type reference. The correction uses the same schema-address traversal for
member discovery, occurrences and selector ownership, and excludes both actual
adapter inputs from the separate value-contract traversal. The original candidates
remain unchanged. The current Kernel permits `oneOf` in these authored wire schemas;
other tested applicators refuse at authority admission, so this repair does not expand
the supported Schema language.

The final paired Source tests pass 28 cases; the corrected inventory scope passes 102.
Independent review also re-runs all 34 Model-vector verdicts and existing oracles.
The 2,511 collected tests and 347 vectors have complete, disjoint CI assignments;
full-package Pyright and Ruff checks pass. Collection proves coverage, not execution
of the full CI matrix. These results do not close the remaining extension proof.

## Runtime Formula contexts

At the Source checkpoint `90907e57020a519451dbb4cdafcf520877215a8b`,
RuntimeProfile Formula metadata repeats the fixed lifecycle phases and Snapshot
domain. Compilation and artifact admission copy and compare the static `frame`
labels, but execution uses the phase and actual frame identity. Other extension
metadata has no execution reader. The Snapshot-domain helper checks the scheduler's
existing domain and discards its return value.

The implementation deletes this extension and the unused RuntimeProfile `extensions`
member, static Formula slot/site/Trace `context.frame` fields, their Schema declarations,
and the Snapshot-domain helper and call. The existing Kernel Runtime configuration
adds only `formula_initialization_phase`; Event and observation phases derive from
the existing active lifecycle role and scheduler observation law. Compiler callers
pass their actual Kernel laws; execution and result consumers use the selected
execution closure. The old host phase table and attribute-based grouping are deleted.
There is no new lifecycle phase, profile selector or packaged-Kernel fallback.

The compiled context retains `phase`. Actual Initialization-frame and Snapshot
identities, explicit operands, site identities, cache charging, and atomic refusal
boundaries remain. `game.effect.periodic.magnitude.frame` and its Operation-relation
policy have a separate meaning and remain unchanged; matching spelling alone is
not a deletion boundary.

The [Runtime context evidence](evidence/priority-window/runtime-formula-contexts.json)
separates the original deletion probes, later output-Schema correction, independent
Model checks, and maintained-consumer comparison. Independent DDMA review found that
the resolved Runtime Profile output Schema still permitted `extensions`. Its sole
remaining property is now deleted. A permanent test starts with an actual published
profile and reidentifies the old-field mutant; the wire Schema itself refuses it at
`runtime_profile`, before any whole-set argument can mask the residual contract.

The final independent gate retains all 34 Model-vector verdicts and mutually admits
the same four artifact kinds for all 13 positives. Resource comparison retains all
347 vector IDs and all other numerical, resource and verdict values: only 26 observed
artifact-identity expectations and four actual Formula slot `context.frame` fields
change. Ten independent regressions cover the retired interface, phase-only contexts,
real slot admission, and malformed-context Schema boundaries.

All seven maintained Models and nine Experiments run on the baseline and candidate
through 64 real CLI commands. Both sides pass complete outcome artifact-set admission;
Event outcomes, facts, state, Snapshot values and Metrics match. The nine checked-in
Experiments change only their observed RIR semantic identity. A separate RPG comparison
also retains four complete RNG rows, two nonempty Formula argument/result records and
all Snapshot resource ledgers. That comparison predates the identity-only vector
refresh; the record keeps those scopes distinct. It does not claim complete artifact
byte equality or independent Formula Runtime execution.

The integrated focused tests pass 33 cases; the five public Formula lifecycle cases
retain actual frames, cache charging and atomic refusals. Standards review then found
nine retired context labels in existing fixtures and exact expectations. Removing
only those labels preserves all other assertions and restores the intended numerical
and semantic-tamper checks; eleven affected cases pass. Some initial pytest artifacts
were automatically removed by later runs. Their original manifests remain historical;
new captures in explicit stable directories preserve the repeated checks and raw outputs.
The resource rebuild tool's
remaining old projection argument now passes its actual Kernel, and its two existing
tests prove exact current-byte reconstruction and invalid-namespace refusal. CI policy
passes 12 cases; 2,522 collected tests and 347 vectors have complete, disjoint shard
coverage. Ruff and Pyright pass. Collection is not full CI execution.

The inventory drops only the deleted RuntimeProfile extension gap, from 40 to 39;
its 1,618 tokens, 6,606 occurrences and 109 reserved tokens remain unchanged. This
correction precedes the final build freeze and does not close the remaining inventory
or non-RPG proof.

## Evidence candidate validation

The next inventory counterexample concerns the LDB Evidence claim definition.
A legal claim-id rename admits in both consumers and passes public Model and
Experiment execution, but the CLI's fixed `Literal["evaluable"]` result rejects it
as an internal fault. A coherent subject-role/edge rename also admits, then fails
in the host's graph projector. Excluding `success` from the selected claim policy
instead produces a correct eligibility refusal. These observations distinguish
the unnecessary representation from a policy that affects real behavior.

The candidate path accepts an authenticated run receipt, RIR and Experiment; it
does not accept a caller-authored graph. The six reconstructed graph edges repeat
existing admission checks. Experiment owns the RIR semantic binding; complete
ArtifactSet admission recomputes the expected profile and checks outcome members,
producer capabilities, journal state and terminal-audit closure. Publication
authenticates original bytes and closed membership. The extra producer edge even
compares the same manifest identity to itself. There is no uncovered semantic
relationship that requires preserving this graph or moving it into the Kernel.

The implementation deletes `subject_roles`, `prerequisite_edges`, synthetic
`vector.input.graph`, and the host subject/edge/graph values, projector and graph
checker. It also deletes the unused `permitted_issuer_classes` and
`permitted_verifier_classes`: both current lists are empty, and no production
consumer reads them. Their presence does not supply an issuer/verifier contract.
Application authenticates the original publication, admits explicit
RIR/Experiment, selects the claim, validates the complete outcome and then invokes
Domain eligibility. Domain derives success, verdict or post-dispatch refusal from
the validated actual primary member. It receives existing checked values rather
than caller-supplied outcome or dispatch flags. Candidate output names the same
five identities directly and carries the actual admitted claim id.

The selected producing-outcome policy, unknown-claim refusal, original producer
acceptance and all real artifact/terminal checks remain. The Kernel change only
removes obsolete grammar; it adds no graph law, scheduling phase or identity.
Future assertion issuance, trust and #542–#544 activation remain deferred.

Retirement is explicit. Five inner `evaluable.graph-*` vectors and four graph-only
reasons/diagnostics retire with their eight outer predicate vectors. The packaged
outer count changes from 347 to 339. Four inner outcome/dispatch vectors retain
their actual inputs and expectations after removing `input.graph`. The real
full-set mismatch reason and its two predicate vectors become
`evaluable-outcome-mismatch`; their predicates and expected results remain.
Malformed actual members and cross-bindings still refuse at their existing owners.
An internal cycle with no public graph input is retired, not reassigned to an
unrelated test. Synthetic edge pointers and graph-specific multi-error counts are
not preserved; the full-set mismatch points at the actual run receipt.

The original #541 graph-shape requirement is narrowly superseded for this candidate
path, together with bADR-0018 and the current architecture/glossary descriptions.
The [structured verification record](evidence/priority-window/evidence-candidate-validation.json)
keeps producer, independent-consumer and review observations separate. Forty
production-side cases retain the actual artifact boundaries, including eight
full-set mutations. Four public cases exercise three admitted claim/policy
candidates through real Model/Experiment commands: all produce the same complete
RIR and numeric results, the renamed claim works, its retired name refuses, and an
actual policy excluding success refuses the otherwise successful publication.
Independent review additionally authenticates three original outcome publications
and twelve malformed variants; all original candidates pass and all variants refuse.

The independent gate preserves all 34 Model-vector verdicts: four artifact kinds
agree and are mutually admitted for thirteen positives; twenty-one negatives
retain their complete diagnostics. Eighty-six inventory cases and that Model gate
pass together. Spec review then found that an extra reserved classification could
hide a claim-local name from the rename domain. The reverse pass now checks the
exact Evidence reserved partition; the new regression fails before the fix and
all ten Evidence inventory cases pass after it. Independent recheck rejects extra
exemptions for all four local names and omissions of all fifteen Kernel markers.
Standards, Spec and DDMA findings for this deletion are resolved.

The current inventory has 1,607 tokens, 6,464 occurrences, 124 reserved tokens and
38 explicit gaps. Only the Evidence definition gap closes; all other gap rows are
unchanged. CI policy passes twelve cases, and collection accounts for 2,555 tests
and 339 vectors with no missing or overlapping shard coverage. Resource rebuild,
Ruff and Pyright pass. This is not full CI execution or the final fixed-build
non-RPG proof. Rollback restores the whole prior code, Kernel, LDB, tests and
current inputs; there is no reader or graph fallback in the candidate.

## Receipt framing and identity projection

The receipt counterexample exposes two independently configurable descriptions of
one fixed protocol. Four correctly resealed candidates admit in both authority
implementations. A nonexistent identity exclusion is accepted without effect;
excluding `descriptor_identity` makes receipts for different descriptors share a
content identity. Coherently renaming `manifest_locator` in the authored Schema
and exclusion list still admits, but an actual public Model build exits 4 because
Publication produces the fixed field. The unchanged control builds successfully.
These observations do not establish acceptance of an authenticated forgery.

The correction extends the existing Kernel receipt protocol with one fixed
binding/transport structure, reusing the ordinary artifact envelope. The exact
Wire Schema and transport-only identity projection are derived together. All 24
authored `identity_excluded_members` fields, their Artifact Contract grammar and
the authored receipt Schema are deleted. Physical overrides refuse even when
they equal the generated values. The selected private Artifact Contract retains
one uniformly derived projection for existing identity consumers; it is not an
authored policy, alternate protocol or fallback. The core canonical hash still
excludes its own `content_identity`; that separate fixed law is unchanged.

This preserves the original 950 canonical Schema bytes and wire identity. The
original fixed and public receipt values retain their complete canonical bytes
and content identities under the selected contract. Descriptor, invocation and
manifest changes still affect identity; transport relocation does not. This
comparison does not claim an old Experiment rerun or cross-version authenticated
publication compatibility. Current recovery, alias and symlink checks retain
their existing outcomes. Thirty-three other Schema declarations are unchanged:
31 physical authored Schemas and the existing derived Trace/RIR declarations.
Package vector bytes and the existing publication authentication API are unchanged.

Real public build/inspect succeeds with separate renamed receipt artifact and
Schema names. Independent B derives the same encoding without calling the
production projection. Its paired original and renamed cases lower four matching
Model artifacts, mutually admit them, reconstruct the actual receipt for A
admission and public inspection, and publish/inspect eight-member sets under
opaque logical labels. The renamed receipt's distinct wire identity truthfully
reflects its changed artifact kind. Illegal authored overrides and missing or
ambiguous actual schema-to-contract bindings still refuse. Fixture refresh only
removes canonical-equal generated values; it preserves co-mutated Schema and
exclusion attacks so actual admission rejects them.

The [structured verification record](evidence/priority-window/receipt-protocol-structure.json)
separates the original counterexamples, producer and independent checks, integration
and review. The complete current package/vector inventory has 1,607 tokens,
6,463 occurrences, 124 reserved tokens and 36 remaining gaps. Exactly the receipt
Schema and arbitrary identity-exclusion gaps close; all other gap rows are
unchanged. This is a prerequisite deletion checkpoint, not complete inventory,
full CI execution or the final fixed-build non-RPG proof. Whole-slice rollback
restores the prior code, Kernel, LDB, tests and current inputs together.

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
