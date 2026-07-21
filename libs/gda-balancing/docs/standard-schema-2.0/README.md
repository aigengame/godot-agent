# Standard Schema 2.0 specification work

This directory holds acceptance artifacts for the Standard Schema 2.0 specification tracked by
PRD #534. The architecture and authority decisions are bADR-0012…0022. They do not make the 2.0
language, runtime, CLI, or genre templates implemented.

The current artifact is [`genre-coverage.md`](genre-coverage.md): the open RPG/Roguelike
requirements-to-operations matrix used to judge the future Language Definition Bundle and vertical
tracer. Every row is open. It is a completeness contract, not evidence that the package operations,
Golden scenarios, or vectors already exist.

## Prototype evidence

The first disposable RPG tracer recorded on PRD #534 demonstrated local connectivity across
Language Definition Bundle admission, Model Source Package, Authoring AST, Typed HIR, canonical
RIR, cross-process artifact identity, Event transactions, Metrics, Evaluation run, and
prototype-local Evidence. It also demonstrated deterministic fixture replay and
no-partial-visibility under the prototype store's injected faults.

That probe did **not** validate Language Definition Bundle semantic authority, independent
evaluator conformance, RIR normal-form agreement between lowerers, complete package resolution,
transport-independent artifact publication, normative Evidence issuance, or any RPG/Roguelike
coverage row. Passing disposable-prototype tests cannot close a specification or Genre gate.

The second disposable
[semantic-authority probe](https://github.com/aigengame/godot-agent/commit/ee5788cebafdce7cbc956cd129b5b77a9fc8b26d)
passed its 23 implementation groups and independent review. Under one shared handwritten
interpretation of a narrow kernel-node vocabulary, two bootstrap/compiler/evaluator paths consume
each other's artifacts, contain no RPG host dispatch, agree on exact Int/RNG and one buffered Event
transaction, and enforce descriptor/invocation/publication identity boundaries. This is a
**prototype-implementation PASS, not a Semantic-authority design-gate PASS**.

The probe reversed one design assumption: an exact Replay requires one identical evaluator-bound
Resolved Runtime profile, while honest independent evaluators necessarily have different profiles.
Their agreement is now a separately typed Cross-evaluator comparison that may support
`cross_evaluator_conformant`; it cannot issue `reproducible`. The probe issued neither Replay nor
Evidence. It also exposed root gaps in executable Kernel-node laws, LDB-owned Source → HIR → RIR,
Kernel-owned admission and LDB-owned post-admission Diagnostic semantics, static variant
exhaustiveness, general package solving, complete terminal-audit schemas, store-adapter trust
boundaries, and independent Evidence validation.

## Next validation gates

1. The completed semantic-authority probe remains an open **design gate** until the Kernel
   Specification provides executable laws for every admitted node/judgment, the LDB drives the
   complete Source → HIR → RIR contracts, Kernel-owned admission and LDB-owned post-admission
   Diagnostic contracts are executable, and independent implementations pass the resulting
   mutation/refusal/Cross-evaluator vectors. Hand-coordinated evaluator agreement is insufficient.
2. The next **Orthogonality/extensibility prototype** must add an ordinary Quantity attribute through
   one Model Source-only edit, then add discriminated resource outcomes, interruption/refund, and
   effect stacking/reapplication/removal through one normative package/LDB edit per reusable
   mechanic. Every projection must be generated or reverse-conformance-checked, with no RPG-specific
   core compiler/runtime branch. It is an independent design probe and cannot close the still-open
   semantic-authority gate.
3. A Roguelike cross-genre tracer follows only after both gates pass; it must reuse the same kernel,
   package, runtime, artifact, and evidence contracts rather than creating parallel semantics.

PRD #534 remains open until a later implementation/specification PR supplies and validates:

1. the closed Schema-major Kernel Specification, Language Definition Bundle bootstrap schema, and
   canonical bundle;
2. exhaustive machine rules for grammar, resolution, types/effects, evaluation, runtime steps, and
   HIR-to-RIR lowering;
3. RIR semantic normal form with a separately identified Debug Map and independent-lowerer vectors;
4. closed AST, Typed HIR, RIR, package/lock/capability, Runtime profile definition, Resolved Runtime
   profile, Experiment, Metrics, Evaluation run, Replay comparison, Cross-evaluator comparison,
   Evidence, artifact-envelope, receipt, and publication schemas;
5. exact Numeric-profile and RNG/stream/sampling laws, including draw consumption and bias policy;
6. descriptor-derived closed decoding/default/channel contracts and refusal-stage/code membership;
7. executable fixture inputs with canonical outcomes/refusals for every required vector; and
8. public-CLI closure of every `Tracer` row before broader RPG/Roguelike support claims.

Free-text operation descriptions, lists of node names, or vectors containing only expected prose do
not satisfy those gates. They must not be presented as an executable or content-addressed bundle.
`math.equation` is reserved and refused until its separate continuous-runtime contract is accepted.
