# Request-owned Model preparation

Issue: [#873](https://github.com/aigengame/godot-agent/issues/873), stage S4.
The starting development commit is `645aeb9ee0375ad6cd1164998ea451aaba9bf68e`
(#872). GitHub owns final review, CI and integration status.

## Problem and retained boundary

The baseline public Model check/build path resolves Source symbols four times,
prepares lowering inputs three times, and resolves Formulas and unspecialized
Runtime projections twice within Source preparation. Independent compiled-artifact
admission additionally derives its own projection once for check and twice for a
fresh build publication. Those admission boundaries are necessary checks.

Specialization also relied on shared Python objects: equal projections with equal
canonical bytes produced different package closures after JSON serialization
broke aliases. The progression/periodic example changed Operation bodies and
instruction provenance; the Roguelike example differed in provenance alone.
Comparing only final numeric values or Operation bodies would miss that defect.

## Implementation and ownership

`ModelSourceContext` carries incomplete resolution inputs. Only successful Model
checking creates a `CheckedModel` with its admitted authority context and complete
private `_TypedHIR`. The request retains immutable Source, selected Package Lock,
declarations, lowering rules, Source rows, Formula bindings/debug entries and the
unspecialized projection. No optional preparation or re-preparation fallback remains.

The Model compiler consumes that snapshot. Template facts reuse its resolved Source
rows. Specialization separately copies each namespace/local-id Operation definition, then
explicitly derives both the Operation and package-closure views, including provenance.
It no longer relies on mutations propagating through object aliases. The existing
immutable-container utility isolates request state; writable output copies cannot
modify it. This is a private compiler representation, with no new public schema,
persisted IR, shared cache or Runtime evaluator.

Post-specialization entrypoint and callsite checks still run. Imported artifacts
independently resolve and validate their semantic closure, and publication still
validates the emitted Artifact Set. The reference consumer remains separately
implemented; it uses the incomplete input carrier without production preparation.
Old test fixtures that replaced an already checked authority now check their mutated
candidate afresh, retaining the mutations and expected observations.

## Acceptance witnesses

The permanent [preparation regressions](../../../tests/test_model_preparation.py)
provide nine cases. Of the initial eight at the pre-S4 baseline, five fail on duplicate
preparation, alias dependence or mutation leakage, while three resource-boundary cases
pass. The ninth case comes from independent review of the first S4 implementation:
a legal admitted graph contains equal Operation definitions under `game.effect` and
`test.effectcopy`. Sharing only their Python definition object leaves input values and
canonical bytes unchanged but incorrectly specializes the unbound owner too. A copy
per owner fixes that confirmed counterexample before either output view is derived.
These tests observe real public calls without replacing the compiler or admission implementation.

| Acceptance | Evidence and retained obligation |
| --- | --- |
| Single preparation | Public check/build each resolve Source rows, lowering inputs, Formulas and unspecialized projection once; independent admission remains one/two times respectively. All eight published artifact classes are compared. |
| Explicit projections | Two maintained examples and an independently admitted cross-owner clone compare entire specialization outputs after alias changes and a JSON roundtrip, including closure definitions and instruction provenance. The unbound owner's complete definition must stay unchanged. |
| Snapshot isolation | Mutating original Source, inspected request data or nested emitted artifacts cannot alter the old request; new and concurrent requests reflect their distinct inputs. |
| Diagnostics and admission | All 34 current Model vectors retain their full observations: 13 admitted eight-artifact sets and 21 complete refusal reports. Existing Model CLI/lowerer tests retain tamper, nominal/role/domain, Formula and call-closure refusals. |
| Resource and publication | The current minimal fixture consumes 233 projection steps: 232 refuses with the full recorded diagnostic, 233/234 admit through independent validation. Progression consumes 318. Existing public Experiment tests retain initialization refusal, Event rollback and Formula resource/cache accounting; Model tests retain explanation/debug publication and inspection. |
| Bounded claims | Six maintained public builds produce 48 artifact files byte-identical to the pre-S4 baseline. This is behavior and byte-preservation evidence, not a speed or memory benchmark. #612 continues to own the real Formula Runtime conformance seam. |

The earlier E5 probe's 196/197/198 observations remain historical evidence at its
own pinned graph. They are not a requirement to force the current graph back to
197 steps. S4 preserves the freshly measured 232/233/234 boundary without changing
machine laws, resource limits, authority bytes or maintained authored examples.

The nine new tests join the existing required `model` CI shard and logical inventory.
All prior required test ids, vectors, allowed skips and process bounds remain.
The full collection is 1,517 cases with no missing, overlapping or unassigned cases;
313 active package-vector obligations remain. Collection closure is not a test-pass
claim: the PR must record final required CI results and independent Standards, Spec
and domain-architecture reviews before integration.

## Rollback and following work

To undo S4, revert its integration commit after reverting dependent work, restoring
the complete package subtree at `645aeb9ee0375ad6cd1164998ea451aaba9bf68e`.
Restore code, tests, CI selection and this delivery record together. Authority,
authored source and build bytes are unchanged by S4; the six baseline builds and
34 baseline vector observations establish the coherent pre-S4 behavior. A rollback
reopens #873 and its known alias/mutation defects; it does not authorize a fallback
inside the new compiler. Final accumulated rollback verification remains #879.

S4 enables execution-dependency closure #874, followed by mandatory deletion #875.
It does not remove the remaining whole-LDB/Build execution prerequisites, complete
the non-RPG witness #878, or replace those issues' terminal acceptance criteria.
