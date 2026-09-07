# Composed extrema and Formula interval inference

This record implements the accepted S6a direction in [#876](https://github.com/aigengame/godot-agent/issues/876)
and [bADR-0028](../../badr/0028-current-language-refactor-and-pre-1.0-retirement.md).
The baseline is `6a32d8ced05e4dcd6c02e59d7053144500528b83`, which integrates
#612 through PR #910. GitHub owns live acceptance. Implementation and conformance
remain open until the complete slice passes its public tests and independent review.

## Decision and ownership

Delete the unused `value` synonym of `copy`. Delete the irreducible `maximum`
Kernel node and its host interpretation. Keep the useful `quantity.maximum`
Operation and notation, implemented by existing comparison and selection.
All current consumers must move together; no compatibility reader, dispatch case,
test-only interpreter or old charge exemption may retain the removed primitives.

The owner delegated engineering decisions under orthogonality, DRY, architectural
consistency and control of unnecessary complexity. This slice uses the existing
validation-driven design contract in [PLAN.md](PLAN.md), with the bounded
refinement below. It does not reopen the deletion endpoint or introduce another
human approval gate. Final accumulated dev review remains separate.

| Authority or owner | Responsibility |
| --- | --- |
| #876 | Required deletion, current numerical/resource expectations and completion |
| Kernel | Remaining instruction meanings, types, exact charges and refusal order |
| LDB Operations | Extrema composition and complete declared Operation bounds |
| `standard.compiler` | Formula inference policy interpreted by the existing Formula owner |
| Runtime and independent replay | Execute the selected current laws; no extrema-specific branch |
| Tests and evidence | Independent expected values, bounds, charges and public outcomes |

## Discriminating evidence

The original result-equivalence probe did not establish that the existing typed
compiler could admit a composed extremum. A new
[negative probe](evidence/primitive-composition/receipt.json) replaces only
`quantity.floor-zero` and `quantity.maximum` with `less-than` plus `if`, and
increases each declared bound by one. The candidate authority admits successfully.
All six maintained Models compile at the baseline; four RPG/progression Models
refuse under this candidate, while the other two still compile.

The smallest observed case is `floor_zero` over `[-1000, 4040]` in
`rpg-stat-composition`. The original result interval is `[0, 4040]`; the generic
selection rule instead joins both full operand intervals and returns
`[-1000, 4040]`. Model admission reports `language.formula_type_mismatch` at
`/modules/0/formulas/4/expression`. Nominal Quantity, representation, unit and
numeric policy are unchanged. This is a compiler inference gap, not evidence
that comparison and selection need another Runtime primitive.

The maximum-only maintained example still compiles, but both operands currently
have the same contextual interval. That observation does not prove precision for
different input intervals. The permanent cases must discriminate those intervals.

## Selected refinement and alternatives

Use the existing Formula inference owner to retain a comparison's operand
relationship. For selection, restrict each branch to values that can satisfy its
condition, then join the reachable result intervals. The compiler policy owns
the transfer rule. The rule must follow instruction meaning and operand identity,
not the name `maximum`, `floor_zero`, a package name or a game identity.

The invariant is sound over-approximation: every possible selected value belongs
to the inferred interval. Restricting values to those that satisfy a comparison
against **every** value of the other operand would be unsound; possible-value
restriction is required. Predicate inversion, strict endpoints, identical operands,
empty branches and signed Int64 extrema must have explicit expected cases.

This uses established interval analysis. LLVM 18.1.8's
[`ConstantRange` predicate-region contract](https://github.com/llvm/llvm-project/blob/3b5b5c1ec4a3095ab096dd780e84d7ab81f3d7ff/llvm/include/llvm/IR/ConstantRange.h)
distinguishes possible-value regions from regions guaranteed to satisfy a
predicate. It supplies design provenance, not local semantic authority or a
dependency. Do not import LLVM's modular wrapped ranges, poison rules, optimizer,
arbitrary-width arithmetic or analysis framework. Local bounds remain inclusive
signed Int64 intervals governed by Standard Schema.

| Alternative | Decision and consequence |
| --- | --- |
| Retain maximum or recognize an extrema-specific host pattern | Reject: leaves the redundant semantic mechanism under another name. |
| Join whole branches and widen authored output contracts | Reject: loses an already required composition capability and weakens the source contract to hide the failure. |
| General symbolic/relational solver | Reject for this slice: no demonstrated need justifies its state space, dependencies or maintenance cost. |
| Comparison-aware restriction in the current interval owner | Selected, subject to independent soundness cases and real Model admission. |

Selection still evaluates already-declared operands eagerly. Narrowing an inferred
result does not remove an unselected arithmetic instruction, its overflow/refusal,
or its charge. It creates no lazy evaluation, callback, extra phase or stateful
Runtime policy.

## Implementation and validation

1. Promote the smallest generic inference rule, delete `value` and `maximum`, and
   migrate all five current Operation bodies. Keep Kernel, LDB, compiler and Runtime
   interpretations coherent in one foundation change.
2. Recompute declared charges and all affected authority, source and artifact
   identities. A maximum instruction previously cost one step; its comparison and
   selection cost two. Composed program bounds must include every actual call and
   instruction, rather than reusing a former receipt or assuming an unchanged budget.
3. Refresh authored expression/body pairs only where the new exact inference changes
   their derived contract. The same generic rule can sharpen existing `minimum`
   bounds; preserve exact round-trip checks and document those changes explicitly.
4. Independently check each permanent expected value, inferred domain, refusal and
   charge. Include differently bounded operands, cross-zero floor, min/max Int64,
   equal/singleton/disjoint intervals, operand order, inverse conditions and unreachable
   branches. Finite enumeration must test soundness without importing the production
   inference or metering implementation.
5. Run actual public initialization, Event and observation Formula paths through
   the #612 seam at below/exact/above limits. Retain permanent unsafe-reduction
   counterexamples: `MIN - MIN` versus intermediate negation, and comparison versus
   overflowing subtraction. Preserve eager unselected refusal.
6. Rebuild and run all maintained Models/Experiments, inspect their declared
   result/resource differences, then run inventory, seal, static, source/wheel and
   complete CI checks. Verify deletion in machine contracts, production and independent
   consumers, resources and active tests. Record independent Standards, Spec and
   domain-architecture reviews before integration into dev.

The primary uncertainty is now `gap-opened`: direct composition is insufficient
under current inference. An independent interval oracle compares one-predicate
branch projections with concrete enumeration in 100,352 cases over `[-3, 3]`,
including direct, copied and independent origins. It narrowly confirms the
proposed restriction model and separately checks Int64 boundary witnesses.
Its [script and results](evidence/primitive-composition/receipt.json) import no
production inference or admission. This is `confirmed-narrowly` design evidence,
not proof of production integration, nested predicates, arithmetic correlation,
nominal admission or final conformance. Unrelated equal intervals must never be
treated as aliases, and empty strict branches must be detected before clamping.
Record measured work and latency where the new inference or changed resource
bounds affect a maintained scenario; do not infer a speedup from node deletion.

## Reproduction, rollback and limits

The two archived probe scripts and their raw logs are listed with hashes in the
evidence receipt. Run them from a package checkout at the baseline, using that
checkout's `src` and `tests` on `PYTHONPATH` and an interpreter with the package
dependencies. The scripts modify only in-memory authority candidates. Their `.txt`
storage keeps disposable evidence outside production and the active test inventory.

Rollback restores the entire slice to the baseline: implementation, Kernel/LDB,
current source pairs, generated bindings, tests and documentation. Verify the
complete reverse patch and execute the restored public baseline. Do not keep
old readers or duplicate execution branches as a rollback mechanism.

This slice does not remove subtraction, state writes, guards or cancellation. It
does not establish full collection traversal, genre coverage, a formal release or
authenticated claim activation. #877 and #878 retain their own required witnesses.
