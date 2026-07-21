# Executable Kernel/LDB Authority Gate

This disposable prototype tests the remaining Standard Schema 2.0 semantic-authority risk. It is
not a product implementation, a reusable runtime, or a substitute for the permanent conformance
suite.

The probe has three deliberately isolated layers:

- `authorities/` contains only authored JSON: one Kernel Specification, one Language Definition
  Bundle, two semantically equivalent Sources, refusal Sources, an Experiment, and scenarios.
- `impl_a/engine.py` independently implements canonical identity, bootstrap admission, a recursive
  Kernel VM, LDB rule selection, lowering, evaluation, and comparison in Python.
- `impl_b/engine.mjs` independently implements the same contracts in JavaScript. It imports no
  code from implementation A and has its own canonical identity, bootstrap, VM, compiler, runtime,
  and comparison code.
- `harness/` may materialize fixture identities, launch processes, exchange bytes, mutate
  authorities, and compare authority-selected fields. It contains no compiler or evaluator
  semantics.

The only host dispatch permitted in either implementation is the fixed non-self-hosted Kernel
meta-VM, its wire-type recognizers, and its closed irreducible effect boundary. Those primitives
are a Schema-major root, not an LDB extension point. Package ids, Operation ids, rule ids,
Diagnostic codes, Source symbols, scheduler phase data, Runtime profile data, and comparison
artifact names come from the exact Kernel/LDB bytes.

## Gate contract

The run is successful only when all seven hard gates pass:

1. every required and consulted Kernel law has an executable instruction body, and its parameters,
   result, effects, refusals, and resource contract are enforced;
2. LDB rules perform parse, resolution, type, effect, Diagnostic, and lowering judgments;
3. two implementations share no semantic implementation;
4. the full `2 bootstrap × 2 lowerer × 2 evaluator` exchange matrix succeeds using sealed,
   content-addressed admission receipts rather than caller-asserted identity pairs;
5. the required bounded identity, Diagnostic, RIR, Numeric/RNG, scheduler/effect, and refusal
   vector slice passes, including reverse deletion of every post-admission Diagnostic mapping and
   behavioral observation of every authoritative Diagnostic code;
6. identical evaluator-bound profiles produce Replay while different profiles produce only a
   Cross-evaluator comparison;
7. every consulted Kernel law and LDB rule survives an old-identity tamper, reidentified deletion,
   and reidentified behavior mutation; every consulted law also survives a result-contract
   mutation, while representative vectors cover its other contract surfaces. A source-level
   authority-token rename must work without engine changes. Bundle graph, transitive effect,
   wire-type, and embedded Runtime-profile projections must also close without host fallback.

Run from the repository root:

```sh
python3 libs/gda-balancing/prototypes/schema2_authority_gate/harness/run_gate.py
```

The harness writes canonical artifacts plus an evidence index to `evidence/`. The index binds each
evidence member digest, the committed implementation revision, and a canonical
`relative source path → file digest` manifest so file names and boundaries are covered.

## Scope boundary

`PASS` means the Kernel/LDB authority architecture is implementable without a hidden RPG/domain
semantic peer, and the tested authority chain is reliable under cross-language execution and
mutation. It does not mean that the repository already contains the complete Standard Schema 2.0
Kernel, LDB, package catalog, RPG coverage corpus, proof set, publication store, or production
runtime. In particular, the probe does not claim full Fixed/rounding, unbiased RNG, cancellation,
subscriber ordering, reducer, exhaustive-match, or hostile Source coverage. Those remain permanent
implementation/conformance deliverables governed by the accepted bADRs and PRD #534.
