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

## Next validation gates

1. A **Semantic-authority conformance prototype** must include two independently implemented
   bootstrap interpreters covering the complete fact/premise/binding/rule ontology. It must then run
   the same Language Definition Bundle, RIR, and Experiment Specification through two independent
   evaluators that share no host RPG primitive implementation. Both levels must agree on positive,
   refusal, limit, semantic-law mutation, RNG, and Replay comparison vectors.
2. An **Orthogonality/extensibility prototype** must add discriminated resource outcomes,
   interruption/refund, and effect stacking/reapplication/removal through Language Definition
   Bundle, Domain package, Model Source Package, and normative-vector data without RPG-specific
   branches in the core compiler or runtime.
3. A Roguelike cross-genre tracer follows only after both gates pass; it must reuse the same kernel,
   package, runtime, artifact, and evidence contracts rather than creating parallel semantics.

PRD #534 remains open until a later implementation/specification PR supplies and validates:

1. the closed Schema-major Kernel Specification, Language Definition Bundle bootstrap schema, and
   canonical bundle;
2. exhaustive machine rules for grammar, resolution, types/effects, evaluation, runtime steps, and
   HIR-to-RIR lowering;
3. RIR semantic normal form with a separately identified Debug Map and independent-lowerer vectors;
4. closed AST, Typed HIR, RIR, package/lock/capability, Runtime profile definition, Resolved Runtime
   profile, Experiment, Metrics,
   Evaluation run, Replay comparison, Evidence, artifact-envelope, receipt, and publication schemas;
5. exact Numeric-profile and RNG/stream/sampling laws, including draw consumption and bias policy;
6. descriptor-derived closed decoding/default/channel contracts and refusal-stage/code membership;
7. executable fixture inputs with canonical outcomes/refusals for every required vector; and
8. public-CLI closure of every `Tracer` row before broader RPG/Roguelike support claims.

Free-text operation descriptions, lists of node names, or vectors containing only expected prose do
not satisfy those gates. They must not be presented as an executable or content-addressed bundle.
`math.equation` is reserved and refused until its separate continuous-runtime contract is accepted.
