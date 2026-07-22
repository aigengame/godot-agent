# Standard Schema 2.0 specification work

This directory holds acceptance artifacts for the Standard Schema 2.0 specification tracked by
PRD #534. [`../ARCHITECTURE.md`](../ARCHITECTURE.md) is the human-readable macro architecture
authority; bADR-0012…0022 own the binding detailed decisions; and PRD #534 owns requirements,
acceptance criteria, and live completion status. These documents do not by themselves make the 2.0
language, runtime, CLI, or genre templates implemented. Issue #538 now supplies the first permanent
machine authority and public discovery slice described below; all broader delivery claims remain
bounded by PRD #534 and the coverage matrix.

The current artifact is [`genre-coverage.md`](genre-coverage.md): the open RPG/Roguelike
requirements-to-operations matrix used to judge the future Language Definition Bundle and vertical
tracer. Every row is open. It is a completeness contract, not evidence that the package operations,
Golden scenarios, or vectors already exist.

## Permanent authority foundation (#538)

The first production foundation replaces the disposable authority mechanism for one admitted
Quantity slice:

- `src/gda_balancing/schema2/authorities/kernel.json` is the versioned, content-addressed,
  non-self-hosted Kernel Specification for canonical encoding, identity, admission, closed
  fact/term/rule/reason formats, unique rule selection, binding/substitution, Diagnostic closure,
  and deterministic resource bounds.
- `src/gda_balancing/schema2/authorities/language-bundle.json` binds that exact Kernel and owns the
  seven Quantity symbol roles, selected representation/kind/unit/domain/Numeric policy, one complete
  package release, two executable Quantity rules, post-admission Diagnostic reasons, one Model
  Source wire schema, and their normative vectors.
- The production bootstrap consumer and a separately implemented conformance consumer agree on
  exact identities, law/rule/reason inventories, generated projection identities, positive vectors,
  and old-identity/reidentified deletion/behavior/token mutations. Neither contains a Quantity host
  dispatch fallback.
- `schema get language-bundle|wire-schema|diagnostic-catalog`, `manifest`, per-command `--schema`,
  and `--params-json <json|->` expose the admitted slice through the descriptor-owned 2.x surface.
  Admission failures use bounded, ordered, deduplicated, stage-aware Diagnostics.

This foundation proves only its admitted authority and command loop. It publishes no Model, Package
Lock, RIR, Resolved Model, Runtime profile, Experiment, Metric, Replay, Evidence, template, or Genre
success artifact, and it closes no Genre row. Issue #539 is the first consumer that may extend the
same permanent authority into a Model-build vertical slice.

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

The third disposable
[orthogonality/extensibility probe](https://github.com/aigengame/godot-agent/commit/b81d8ec)
passed 40 executable groups, the 1.x regression suite, lint/type checks, and repeated independent
Standards/Spec mutation review after four repair rounds. In the selected slice it demonstrated an
admitted generic Quantity attribute through Model Source only; complete content-addressed package
releases for resource, interruption/refund, and effect lifecycle; closed Operation/result/effect/
bound projections; exact Experiment input/selector/acceptance execution; selected-Lock runtime
admission; prior-commit audit; descriptor-owned outcomes; and anchored local publication without
RPG-specific compiler/runtime dispatch.

This is an **Orthogonality/extensibility mechanism PASS, not a Schema, Semantic-authority, Genre,
Replay, or Evidence PASS**. The probe exposed one identity ambiguity in the specification; the
design authority adopts the matrix below, which still requires a normative metamorphic vector
before acceptance:

| Added unused package, selected closure unchanged | Required result |
| --- | --- |
| exact whole LDB identity | changes |
| selected Package Lock | byte-identical |
| RIR semantic payload | byte-identical |
| exact-build Resolved Model wrapper | changes |
| Resolved Runtime profile | changes |
| old exact Experiment binding | becomes ineligible; a new Experiment identity or declared compatibility resolution must select the new wrapper |

The probe did not establish a global package-release history. The accepted specification now avoids
that unowned subsystem: duplicate id/version content is refused within one LDB, while different LDB
identities define distinct non-interchangeable release worlds. Executable selector/acceptance and
Kernel/LDB judgments, general dependency solving, complete Effect breadth, portable publication,
independent Evidence validation, and every coverage row remain open.

The fourth disposable
[executable Kernel/LDB authority gate](https://github.com/aigengame/godot-agent/pull/537)
was reviewed and then closed without merge because prototype code is evidence, not specification.
Its immutable source commit is
[`1f0f3e9`](https://github.com/aigengame/godot-agent/commit/1f0f3e99d83cfa96c94f8672c352cc7a8e81f565),
with the path-bound evidence index refreshed in
[`c34d2bb`](https://github.com/aigengame/godot-agent/commit/c34d2bb8bf6681a8ff5028026dd0e07f02c9b6bb).

Two independent Python/JavaScript stacks executed machine-readable Kernel laws and LDB-owned
Source → Typed HIR → RIR judgments, consumed each other's sealed artifacts, and passed the bounded
Replay/Cross-evaluator, mutation, Diagnostic, Numeric/RNG, scheduler/effect, and refusal slice. The
dogfooding tightened five permanent contracts: law parameters/results/transitive effects/refusals/
resources are enforced; authority mutation needs tamper/deletion/behavior witnesses; Diagnostic
authority needs exact reverse closure and behavior coverage; Comparison is not Evidence; and
artifact-set manifests bind typed member names and identities.

This is a **bounded architecture-authority mechanism PASS**. It does not close a #534 acceptance
criterion or Genre row and does not prove a complete Kernel/LDB, general package solving, full
Numeric/Effect/Genre breadth, portable publication, independent Evidence issuance, or production
readiness. No further disposable architecture prototype is planned unless a later permanent
decision introduces a new semantic root, open host extension, or cross-artifact authority boundary.

## Next validation gates

1. The bounded disposable authority mechanism has been replaced for #538's admitted Quantity
   foundation by permanent versioned Kernel/LDB artifacts and normative bootstrap/rule/reason
   vectors. Disposable code remains non-authoritative and closes no acceptance criterion.
2. Issue #539 must consume that exact foundation to build one Model Source through selected Lock,
   canonical RIR, Resolved Model, independent lowerers, and atomic public artifact publication.
   Later tracers extend the same authorities with Operation, Experiment, audit, comparison, and
   Evidence contracts only when their vertical paths exercise them.
3. A production RPG tracer must then close its required
   vertical coverage rows and public artifact path.
4. A Roguelike cross-genre tracer follows only after those gates pass; it must reuse the same kernel,
   package, runtime, artifact, and evidence contracts rather than creating parallel semantics.

PRD #534 remains open until a later implementation/specification PR supplies and validates:

1. the closed Schema-major Kernel Specification, Language Definition Bundle bootstrap schema, and
   canonical bundle;
2. exhaustive machine rules for grammar, resolution, types/effects, evaluation, runtime steps, and
   HIR-to-RIR lowering;
3. RIR semantic normal form with a separately identified Debug Map and independent-lowerer vectors;
4. closed AST, Typed HIR, RIR semantic payload, Resolved Model wrapper, package/lock/capability,
   Runtime profile definition, Resolved Runtime
   profile, Experiment, Metrics, Evaluation run, Replay comparison, Cross-evaluator comparison,
   Evidence, artifact-envelope, receipt, and publication schemas;
5. exact Numeric-profile and RNG/stream/sampling laws, including draw consumption and bias policy;
6. descriptor-derived closed decoding/default/channel contracts and refusal-stage/code membership;
7. executable fixture inputs with canonical outcomes/refusals for every required vector; and
8. public-CLI closure of every `Tracer` row before broader RPG/Roguelike support claims.

Acceptance of the architecture PR and its bADRs authorizes that permanent Gate 2/3 work. The open
#534 criteria are delivery and claim gates evaluated by the resulting artifacts and vectors; they
are not circular prerequisites that must be complete before implementation starts.

Free-text operation descriptions, lists of node names, or vectors containing only expected prose do
not satisfy those gates. They must not be presented as an executable or content-addressed bundle.
`math.equation` is reserved and refused until its separate continuous-runtime contract is accepted.
