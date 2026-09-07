---
status: accepted
---

# Bounded pure fold and typed List construction

Decision date: 2026-09-07. This refines the collection promotion in
[bADR-0028](0028-current-language-refactor-and-pre-1.0-retirement.md) for
[#877](https://github.com/aigengame/godot-agent/issues/877). The project owner delegated
implementation decisions through the [implementation workflow](../refactor/current-language/IMPLEMENTATION.md).
Acceptance of this design does not establish implementation or conformance. The
[delivery record](../refactor/current-language/BOUNDED-FOLD.md) tracks those gates.

## Problem and scope

The current language admits bounded ordered Lists and element lookup. It cannot express
general stable filtering, counting and ordered reduction without a fixed number of authored
lookups. The existing disposable fold experiment supports the candidate value laws, but its
two evaluators share admission and metering. That agreement cannot prove independent conformance.

Preserve nominal typing, deterministic eager refusal, finite static bounds, explicit actual
execution dependencies, Event atomicity and independent artifact validation. Complete targeting,
damage policy, arbitrary Record construction, sorting, shuffle, zones and effect-request
traversal remain with their existing requirement owners. The early non-RPG witness in #878
must test this basis before broad dependent work; #877 does not prove genre completeness.

## Selected design

**Use one bounded left fold whose step is a statically referenced pure Operation.** A step
uses the existing instruction language, formal ports, result source, refusal set and acyclic
Operation graph. It does not introduce a lambda format, ambient lexical capture, callback,
suspended Event or new scheduler phase.

The fold instruction declares `node`, `site`, `target`, `value`, `initial`, `operation`,
`accumulator_port`, `item_port` and `arguments`. The first two distinguished formals are
different and bound once. The explicit arguments bind every remaining read-only formal once,
in declaration order, using the existing port/local/literal forms. The selected List type
provides the element type and finite maximum length; the instruction does not duplicate them.
The initial value, accumulator formal, successful step result and fold result have one
compatible canonical value contract, including nominal ownership, unit and Numeric policy.

The step and its complete synchronous call closure have `operation_kind=pure-expression`,
`purity=pure`, no effects, no Event outcomes and only read-only formals. Calls, including nested
folds, must form a finite DAG. Snapshot values can enter through explicit arguments; a pure
frame cannot acquire ambient snapshot operands. Empty input returns the initial accumulator.
Otherwise each successful result becomes the next accumulator, in input order. The first
refusal stops traversal. No later item or instruction executes after that refusal.

**Use one typed `list-append` instruction for construction.** Its fields are `node`, `target`,
`value` and `item`. It preserves the selected List type, order and duplicates, and requires a
compatible element. At capacity it returns the selected structured-capacity refusal. This is
a fallible operation, as exact integer addition is fallible at overflow; successful result
typing is not a promise of totality for every legal input.

Stable filter composes comparison, append and eager selection. Its storage capacity must
cover the input bound when starting empty. A smaller business cardinality is checked after
filtering, not substituted for construction capacity: a rejected item still evaluates the
append branch. Count, relevant map and reduction compose this basis. No separate host
length/count/map/filter/reduce primitive is added. Existing emptiness is not removed merely
because count can produce an equal value: its validation, refusal and charge contract needs
an explicit disposition before any such deletion.

## Ownership and execution

The Kernel owns instruction interpretation, closed-call restrictions, order, refusal context
and the resource recurrence. The LDB owns the selected constructor, element/capacity law,
reason definitions and reusable Operations. Source and Experiment retain authored inputs and
observation intent. RIR selects the entire transitive semantic closure, including step types,
instructions, reasons and resource rules. No whole-LDB execution lookup or old binding returns.

The existing Operation composition judgment derives fold input bounds from its lexical type
environment. Static projection consumes this derived information; it does not grow a second
type checker or an authored bounds registry. Specialized programs and independently imported
artifacts must be checked at their own admission boundaries.

Runtime uses one pure Operation execution boundary inside its existing execution owner, for
both ordinary pure invocation and fold steps. It creates a fresh explicit-argument frame and
uses the common value-instruction evaluator. The Event executor retains state, scheduling,
outcomes and rollback. Pure calls return a value or refuse; they do not fabricate Event
outcome trace rows. Independent consumers implement value execution, admission and metering
separately. The current scalar Formula syntax and reserve-before-cache contract remain
distinct; this slice's public structured witness enters through an Operation entrypoint.

## Static bounds and actual charges

An ordinary instruction, including append, retains its declared base charge. Fold has base
charge 1 and one invocation-attempt charge per item, followed by actual attempted step work.
With `N` from the input List type and `B` the derived synchronous bound:

```text
B(sequence) = sum(B(instruction))
B(invoke)   = 1 + B(callee)
B(fold)     = 1 + N * (1 + B(step))
B(guard)    = 1 + B(body)
```

Nested finite folds multiply their bounds. Admission compares the complete derived bound
with the declared Operation limit. Runtime charges actual attempted work, including a
refusing attempt, against the same run, Event and active Operation budget owners. Fold does
not reserve every possible iteration at runtime. A guard shares its enclosing Operation
budget; entering a pure call creates a call budget, not another run/Event counter.

Step counts are not a claim about constant-time host work. Immutable append copies prior
elements: successful all-selected construction from empty copies `N*(N-1)/2` prior cells
and allocates `N*(N+1)/2` element slots cumulatively. Eager rejected candidates also incur
their attempted construction. Existing structured validation limits still apply. Measure
copy work, elapsed time and peak live memory separately at declared scenario limits. If a
scenario budget fails, change the private representation or reopen the primitive; do not
raise the limit merely to hide the failure. A private builder must preserve public values,
first refusal and the declared charge sequence.

## Refusal location and independent reconstruction

Keep the existing `call_path`, `operation`, `instruction_index` and nullable
`call_site_identity` carriers. Encode each static root/site segment by replacing `~` with
`~0` and `/` with `~1`. After a fold site, append exactly one `@` plus a canonical zero-based
decimal iteration index. The admitted Operation determines whether that next segment is an
iteration or a static invocation site; ordinary names such as `@0` remain legal. Require
canonical escaping and unique static sites in each Operation frame.

Validation derives the root from the actual entrypoint or scheduled Event, then follows
the admitted instruction graph. It must not trust a root copied from the reported path.
Independent value replay proves that a fold index is within this execution's actual input
length, not just its type bound. The final frame determines the Operation and instruction
position. Entering through an ordinary invocation binds the existing static call-site
identity; entering an intrinsic fold step uses `null`. The iteration invocation-attempt
charge is attributed to that step frame at instruction index 0, before its first body
instruction; the independent charge sequence distinguishes those consecutive attempts.

Independent validation reconstructs the exact first refusal, reason, location and counters.
It consumes every genuine Event call row exactly once and rejects additional or fabricated
rows. Pure invocation requires no synthetic Event outcome evidence. This replaces any
assumption that a static successful prefix alone can establish dynamic fold work.

## Alternatives and supporting evidence

A lexical body using the same IR is a credible alternative, not inherently a second DSL.
It still adds another binding, result and capture representation. Static Operations already
provide those boundaries, and no public witness currently demonstrates a need for lexical
closures. Retaining fixed unrolled lookups is the simplest non-adoption option, but cannot
satisfy #877's bounded traversal and reusable-composition requirement.

The algebraic left-fold recurrence preserves accumulator type and sequence order; neither
associativity nor a monoid identity is required. The explicit initial value supplies the
empty case. [Rust 1.89 `try_fold`](https://github.com/rust-lang/rust/blob/29483883eed69d5fb4db01964cdf2af4d86e9cb2/library/core/src/iter/traits/iterator.rs#L2418-L2429)
provides a mature example of ordered accumulator replacement and stopping at first failure.
Its mutable callbacks, unbounded iterators and resumable iteration are excluded; they do not
prove this language's purity or finite bound.

[Octez v12.3 Michelson `ITER`](https://github.com/tezos/tezos-mirror/blob/6e2037c907606587041136834cf7de16049412da/docs/012/michelson.rst#L1696-L1705)
supports the credibility of a same-IR lexical body with preserved stack typing. Its ambient
stack and runtime gas do not provide this language's explicit-argument and static-bound
guarantees. Both sources are provenance, not semantic authorities or dependencies. Changes to
them cannot change the accepted Kernel/LDB laws.

## Acceptance, falsifiers and rollback

The delivery record maps all six #877 AC to permanent public and independent cases. Required
falsifiers include reversed input order, changed later elements, nested-bound multiplication,
wrong nominal element/accumulator, capacity, eager unselected overflow, first-refusal prefix,
forged paths/indices/call identities and semantic-dependency mutations. An implementation
that only passes a shared prototype, hardcodes the short example, or hides quadratic copying
does not satisfy this decision.

The same typed basis must support independently varied input length, accumulator shape,
predicate and explicit captured arguments. This checks abstraction and orthogonality within
#877's scope. Completeness requires its declared public outcomes and refusals, not every
future constructor. #878 separately challenges extension with unchanged candidate core and
host dispatch. Full conformance, operational performance and delivery remain open until
their evidence passes.

Rollback restores the whole issue's code, Kernel/LDB, current sources and regenerated
evidence to dev baseline `970f0323e259769fdc45dc363a1baf28081a8ef6`. Verify that restored
public build/run still works and invalidate affected live process handles explicitly.
Do not keep old/new readers, a compatibility charge mode or an alternate evaluator as
rollback machinery. The completed refactor still waits for final dev review; no main merge,
formal release or authenticated claim activation is implied.
