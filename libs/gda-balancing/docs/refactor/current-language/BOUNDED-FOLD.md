# Bounded fold delivery (#877)

Base: reviewed dev `970f0323e259769fdc45dc363a1baf28081a8ef6` after #876.
The [accepted decision](../../badr/0029-bounded-pure-fold-and-list-construction.md) owns the
design rationale. [#877](https://github.com/aigengame/godot-agent/issues/877) owns acceptance;
the Kernel/LDB own executable laws. This record tracks implementation and evidence.
Design is accepted under the owner's implementation delegation. The issue and
[PR #917](https://github.com/aigengame/godot-agent/pull/917) record the final integration,
independent review and required CI disposition; this document records scoped evidence.

## Evidence at the starting boundary

- The live Kernel has neither `fold` nor `list-append`. Its static Operation projection
  counts a referenced body once; it does not multiply work by a selected List bound.
- The existing composition judgment accepts a pure `quantity.maximum` body replaced by
  an explicit invocation of `quantity.add`. This was an in-memory judgment probe only.
  The actual Event executor nevertheless reads `default_outcome`, which pure Operations
  do not have. Pure calls need a real shared execution boundary, not fabricated Event fields.
- Existing authored invocation sites and entrypoint ids accept nonempty strings, including
  `/` and `@`. A raw slash join cannot establish unambiguous dynamic iteration provenance.
  The design therefore escapes static segments and interprets iteration segments through
  the admitted Operation graph, preserving legal names.
- Existing refusal charge reconstruction derives its root from the reported `call_path`
  and walks static work. Dynamic traversal requires independent actual-value reconstruction
  and root/call-identity validation before such evidence can be accepted.

These observations guide implementation; they are not a completed public fold or an
independent-conformance result. The six original probes remain at their historical bases.

The first actual CLI build comparison uses identical Source bytes and unchanged baseline
production code in correctly sealed candidate trees. The control replaces the new nodes
with copies solely to test Source/types/packaging: it builds successfully. The intended
fold/append candidate refuses at the two new instruction shapes during static authority
admission, with exit 2 and empty stderr. This is a public integration RED, not Runtime
execution evidence. Nine additional compiler-projection regressions reproduce the missing
pure-call outcome handling and rejection of a valid value-produced local argument.

Independent baseline artifact mutations confirm that full result-set validation accepts
a substituted real call-site identity in numeric-overflow and step-limit audits. It also
accepts a forged root path in a first-call step refusal, and a different selected non-step
diagnostic substituted into both reason fields of a numeric refusal. Each artifact was
reidentified without changing counters, rollback or call rows. The corresponding original
sets validate; changed instruction positions refuse. These bounded counterexamples require
exact first-refusal reconstruction, rather than a comparison of the step-limit category.

Independent design review exposed a budget ambiguity: charging an iteration attempt inside
the new step budget would reject a legal one-copy step with `max_steps=1`. The adopted rule
charges the enclosing invocation attempt first, then creates the zeroed step budget. Its
permanent regression must distinguish that boundary from the first body charge.

## Public witness

The small readable witness uses a bounded List of exact integers, an explicit threshold,
and package-owned pure filter/count/order steps. An Event commits the filtered List,
count and ordered numeric reduction through the existing public Source/Experiment path.
For input `[1,2,3,4]` and threshold `3`, declared outputs are `[1,2]`, `2` and `1234`.
Changing the last item to `5` changes the reduction to `1235`; reversing the input changes
it to `4321`. There is no fixed-index expansion or pre-authored expected output state.

Filter step has three instructions; count step has two; order step has three. Two initial
constants, three folds and three state writes give the four-item scenario a static bound
of `52` and actual work of `46` steps. Production and the independent consumer agree on
the complete result and work. A second public candidate multiplies each accepted item by
two before append: the same input produces `[2,4]`, count `2` and ordered value `1234`,
using `54` actual attempts. It adds no map opcode or permanent wrapper Operation.

## Implemented boundaries

The shared lexical judgment now checks ordinary pure calls and fold steps in the same
Operation language. It derives each fold bound from the selected List type, checks the
whole pure call closure, and enforces one call-site namespace through transparent guards.
The compiler projects call identities only after that judgment. Formula charge copies use
fresh local names, and Snapshot declarations enter lexical checking through selected
Operation value contracts; Formula domain checking retains the declared numeric intervals.

Production executes pure calls, nested folds and ordinary Event bodies through one frame
walker. Every attempt charges the run, Event and all already active Operation frames.
An iteration attempt precedes its new zeroed step frame. Pure steps create no synthetic
Event call/outcome rows. The independent artifact walker reconstructs dynamic refusal
positions and exact first faults from actual values. Static path parsing alone cannot
prove an iteration existed.

The old `attempted_operation_charge` Boolean reconstruction and unused static invocation
path projection were deleted. There is no legacy charging mode, compatibility interpreter
or fallback when a fold is unavailable. Independent conformance code deliberately owns
its own admission, lowering, execution and metering judgments.

Two public Formula-slot cases establish a narrower, explicit front-end boundary. A pure
step may call a parameter-bound scalar Formula and observe successive accumulator values
`0,1,2,3`; a Formula restricted to `[0,0]` cannot accept the full iteration domain. Existing
numeric Formula notation still refuses Operation bodies that its scalar interval inference
cannot represent, including the probed nested invoke/fold forms. This slice does not claim
that every Formula notation function can express the full Operation language.

## Resource observations

Measurements use unchanged run/Event limits, independently varied selected List bounds,
and the corresponding declared Operation bound. They separate three fresh uninstrumented
CLI runs from one full-command cProfile/tracemalloc run for each case.

| Input bound | All selected: actual attempts | Last item rejected: actual attempts | Two growing-prefix construction paths: derived slots |
| --- | --- | --- | --- |
| 4 | 52 | 49 | 16 |
| 8 | 96 | 93 | 64 |
| 16 | 184 | 181 | 256 |
| 22 | 250 | 247 | 484 |

At `N=23`, the first disallowed Event attempt is `257`; execution refuses and rolls back.
The boundary is the unchanged Event budget, not List capacity. The last rejected filter
item still executes eager append before the branch chooses the previous accumulator.

The input admission copy contributes `sum(k)`, and constructing the appended result
contributes `sum(k+1)`: those two paths alone allocate `N²` slots cumulatively. Other typed
and publication validation adds work. This is not a claim of quadratic peak live memory.
The measured full-command wall-time medians vary from 1.73 to 6.39 seconds on the shared
host; RSS is about 86.7–91.3 MiB. Instrumented Python peaks are about 46.34–46.36 MiB.
Startup, authority admission and instrumentation dominate these small cases, so they
support neither a speedup nor a timing-scaling claim. No private builder optimization
was introduced.

The [later boundary measurement](evidence/bounded-fold/final-runtime-measurement.json)
repeats both `N=22` paths and the `N=23` refusal against its pinned implementation.
It confirms `250`, `247` and first refused attempt `257`. The two successful medians
are 2.006 and 3.577 seconds; instrumented Python peaks are 48,824,861 and 48,823,902
bytes. The subsequent Model-vector oracle refresh changes neither the selected RIR
bytes nor its executable laws. The measurement names that comparison precisely;
it does not claim timings for later review fixes or replace the historical nine cases.

The production-only reverse-traversal experiment keeps Source, authorities and RIR fixed.
It changes the public result to `[2,1]`, count `2`, reduction `4321`, and publishes a failed
metric verdict instead of the required success. This independently demonstrates that the
public order assertion distinguishes the implementation. Its initial unchanged artifact
validator accepted the self-consistent wrong post-state; this exposed a missing comparison
of the final state already computed by the independent walker. Exact artifact-state
validation now compares that state at the existing complete-Event evidence boundary.
Two real wrong-order producers, one success and one metric verdict, pass individual member
encoding checks but fail full-set validation. A legitimate business alternative after three
state writes still passes with the required rollback. No second walker was added.

## Execution identity follow-up

Adding six permanent execution vectors exposed a missed #875 case: selected Operation
definitions still copied their `vectors` references into both direct RIR Operations and
mirrored semantic closures. The added evidence changed executable identity although the
body did not change. Those references belong to Package conformance ownership and Build
provenance, not Runtime dependencies.

The correction physically removes the declared top-level evidence member during the one
runtime collection projection, before either RIR copy is produced. Closed RIR wire
admission and exact projection recomputation reject reinsertion. Package and Lock evidence
references retain their existing ownership and coverage checks. All maintained execution
inputs must be rebound once to the corrected current RIR; subsequent pure evidence-reference
changes must leave RIR bytes and execution unchanged.

## Acceptance map

| Issue AC | Required evidence | Current state |
| --- | --- | --- |
| 1: closed laws and bounds | Machine contracts; wrong form/type/effect/capture/cycle refusal; nested multiplication; exact actual attempts | Focused admission and Runtime cases pass; complete CI disposition is recorded on the PR |
| 2: public traversal | Actual Source build/check/run; empty/single/max/over-bound, order and later-item mutations; numeric and eager refusal | Fold subprocess build/check/run passes; nine maintained Experiment bindings are refreshed |
| 3: compositional basis | Filter/count/map/reduce witnesses; typed construction; no redundant traversal host nodes | Public map/filter/count/reduction and Formula-slot witnesses pass |
| 4: independent consumers | Separate admission, execution and metering; mutually consumed artifacts; counterfeit dynamic audit refusal | All 31 Operation vectors agree, including six fold vectors; post-state and exact-refusal counterexamples pass |
| 5: honest resource cost | All-selected and eager rejected construction; copied cells, cumulative slots, elapsed time and peak live memory at declared limits | Nine original variants and three later boundary runs; source-pinned results and quadratic cumulative copy cost recorded |
| 6: bounded extension handoff | Permanent reusable assets for #878; no sorting/zone/effect-request or full genre claim | Maintained Source/Experiment and reusable cases exist; #878 owns the extension validation |

Every public or independent result must record its exact source/head, command, observation
and scope. Failed intermediate integration remains explicit. Test totals do not replace
clause-level witnesses or prove deletion of existing contracts.

## Integrated review and CI

The first complete CI run at `1ab3e3909` failed. It exposed stale exact expectations
for the append export, capacity refusal catalog, dependency witnesses and projection
charges. The new reason and diagnostic each add one existing catalog-row charge:
the simple Model preparation boundary is now 375, and the progression example uses
508. The once-only preparation and complete refusal checks remain in place.

The old publication-recovery test injected an arithmetic fault that a correct independent
replay cannot reproduce. Its Runtime case now supplies an admitted critical-damage
overflow and still checks recovery after publication commit without rerunning evaluation.
The existing successful and metric-verdict recovery cases remain unchanged.

The combined composition shard also exceeded its unchanged 480-second process bound.
The new fold cases now run in a separate required shard. The inventory must still
partition every collected test exactly once; neither the timeout nor an existing
test obligation was relaxed.

Independent review found two further gaps: a typed fold result could not feed the
existing integer state-subtraction operation, and an audit could forge its starting
work ledger to shift the alleged first refusal. Runtime and independent Replay now
use their existing numeric projections. The audit derives initialization, completed
Event and observation work from checked inputs and the existing independent walkers.
It distinguishes the committed Snapshot ledger from the next execution's total,
preserves the cumulative charge across scenarios, and checks the next legal dispatch.
The old hand-counted Formula traversal and duplicate completed-Event replay pass are
deleted. Formula refusals also bind the actual root or scheduled dispatch context and
the correct attempted-call prefix. Twenty permanent ledger regressions pass.

The separately reproduced roguelike publication failure comes from confusing
guard-expanded audit positions with authored Formula positions in Replay. Correcting
that lookup restores the two affected public paths while retaining post-state checks.

A legal external-input Event could also fail during observation with a missing
Operation call-site key. Its diagnostic now uses the existing input label and canonical
Event identity, without selecting a Model entrypoint. Two public regressions cover
logical-time and terminal observation boundaries; these and three existing lifecycle
cases pass. Independent paired execution accepts the real artifact set and rejects six
individually resealed context or ledger mutations. The public Runtime refusal returns
exit 2 with a terminal audit instead of an internal error. The new tests belong to the
required composition shard.

The independent Spec recheck at `c9d70ccbf` found that a genuine Metric observation
Event-limit refusal could still claim a selected step-limit reason. The corrected
branch binds the actual next Metric, its existing observation dispatch metadata,
empty call evidence and the selected `event-limit` reason. Nine individually resealed
reason/context mutations change from accepted to refused; the valid artifact remains
accepted. The twenty ledger cases and two external-input cases pass together.

[CI at `c9d70ccbf`](https://github.com/aigengame/godot-agent/actions/runs/34129533736)
passed eight of ten test partitions. Composition had one stale assertion that compared
an execution Operation with its complete Package definition, including the retired
`vectors` member; its corrected public case passes while retaining exact equality for
every execution member. The Model partition reached its 480-second bound before JUnit
completion. Admission and preparation now form a separate required partition; the
timeout, collected test identities and outcome gates are unchanged. The local complete
inventory contains 1,967 tests and 347 package vectors. These observations do not claim
that the failed run passed; the PR records the subsequent complete run.

A [separate successful-termination defect](evidence/bounded-fold/pending-root-followup.json)
reproduces both before this slice and on its review head: a legal root Event left
pending after early scenario termination causes full-set admission to fail. The
successful journal's completeness check omits authenticated but unexecuted roots.
[#879](https://github.com/aigengame/godot-agent/issues/879) owns its correction and
the corresponding valid/forged-root consumer regressions.

## Implementation order and ownership

1. Establish Kernel/LDB and shared type/composition foundations in one isolated worktree.
   Prepare public red cases independently against the exact old baseline.
2. Integrate that foundation before Runtime, artifact replay and independent consumers
   implement its shared contracts. The primary owns compiler/selected-closure integration;
   each shared source file has one editing owner.
3. Run the real public witness, dependency mutations, dynamic refusal tests and measured
   worst-case scenarios. Reconcile affected authorities and maintained current artifacts.
4. Run complete current checks, independent Standards/Spec/DDMA review, fix and recheck,
   push the issue PR into dev and verify the integrated tree. Then proceed to #878.

Restore the complete base code/authority/source/evidence tree for a rollback drill and
execute its public build/run. No legacy fallback is retained in the delivered branch.
The [completed rollback drill](evidence/bounded-fold/rollback.json) restores the base
in an isolated checkout. Fresh CLI processes publish all eight Model members, accept
the original Experiment, and publish all six execution members. This does not claim
invalidation of an existing service session; no such session existed in the drill.
