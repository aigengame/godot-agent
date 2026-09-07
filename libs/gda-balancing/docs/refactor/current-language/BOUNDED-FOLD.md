# Bounded fold delivery (#877)

Base: reviewed dev `970f0323e259769fdc45dc363a1baf28081a8ef6` after #876.
The [accepted decision](../../badr/0029-bounded-pure-fold-and-list-construction.md) owns the
design rationale. [#877](https://github.com/aigengame/godot-agent/issues/877) owns acceptance;
the Kernel/LDB will own executable laws. This record tracks implementation and evidence.
Design is accepted under the owner's implementation delegation; production acceptance is open.

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

## Public witness

The small readable witness uses a bounded List of exact integers, an explicit threshold,
and package-owned pure filter/count/order steps. An Event commits the filtered List,
count and ordered numeric reduction through the existing public Source/Experiment path.
For input `[1,2,3,4]` and threshold `3`, declared outputs are `[1,2]`, `2` and `1234`.
Changing the last item to `5` changes the reduction to `1235`; reversing the input changes
it to `4321`. There is no fixed-index expansion or pre-authored expected output state.

Filter step has three instructions; count step has two; order step has three. Two initial
constants, three folds and three state writes give the initial four-item scenario a static
bound of `52` and baseline actual work of `46` steps. These are derived expectations to
verify independently, not measured results. Larger declared scenario limits need their
own worst-case work/time/memory evidence; the readable example is not a performance proof.

## Acceptance map

| Issue AC | Required evidence | Current state |
| --- | --- | --- |
| 1: closed laws and bounds | Machine contracts; wrong form/type/effect/capture/cycle refusal; nested multiplication; exact actual attempts | Open |
| 2: public traversal | Actual Source build/check/run; empty/single/max/over-bound, order and later-item mutations; numeric and eager refusal | Open |
| 3: compositional basis | Filter/count/map/reduce witnesses; typed construction; no redundant traversal host nodes | Open |
| 4: independent consumers | Separate admission, execution and metering; mutually consumed artifacts; counterfeit dynamic audit refusal | Open |
| 5: honest resource cost | All-selected and eager rejected construction; copied cells, cumulative slots, elapsed time and peak live memory at declared limits | Open |
| 6: bounded extension handoff | Permanent reusable assets for #878; no sorting/zone/effect-request or full genre claim | Open |

Every public or independent result must record its exact source/head, command, observation
and scope. Failed intermediate integration remains explicit. Test totals do not replace
clause-level witnesses or prove deletion of existing contracts.

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
