# Standard Schema 2.0 specification work

This directory holds acceptance artifacts for the Standard Schema 2.0 specification tracked by
PRD #534. The architecture and authority decisions are bADR-0012…0022. They do not make the 2.0
language, runtime, CLI, or genre templates implemented.

The current artifact is [`genre-coverage.md`](genre-coverage.md): the open RPG/Roguelike
requirements-to-operations matrix used to judge the future Language Definition Bundle and vertical
tracer. Every row is open. It is a completeness contract, not evidence that the package operations,
Golden scenarios, or vectors already exist.

PRD #534 remains open until a later implementation/specification PR supplies and validates:

1. the closed Language Definition Bundle bootstrap schema and canonical bundle;
2. exhaustive machine rules for grammar, resolution, types/effects, evaluation, runtime steps, and
   HIR-to-RIR lowering;
3. closed AST, Typed HIR, RIR, package-manifest, profile, experiment, Metrics, Evaluation-run, and
   evidence artifact schemas;
4. exact Numeric-profile and RNG/stream/sampling laws;
5. executable fixture inputs with canonical outputs/refusals for every required vector; and
6. public-CLI closure of every `Tracer` row before broader RPG/Roguelike support claims.

Free-text operation descriptions, lists of node names, or vectors containing only expected prose do
not satisfy those gates. They must not be presented as an executable or content-addressed bundle.
`math.equation` is reserved and refused until its separate continuous-runtime contract is accepted.
