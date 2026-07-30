# Standard Schema 2.0 specification work

This directory holds acceptance artifacts for the Standard Schema 2.0 specification tracked by
PRD #534. [`../ARCHITECTURE.md`](../ARCHITECTURE.md) is the human-readable macro architecture
authority; bADR-0012…0023 own the binding detailed decisions; and PRD #534 owns requirements,
acceptance criteria, and live completion status. These documents do not by themselves make the 2.0
language, runtime, CLI, or genre templates implemented. Issues #538, #539, #540, #553, #554, and
#592 now supply the permanent authority, Model-build tracer, first minimal Template release,
limited clean-forward source migration, sealed LDB graph, and bounded RPG loop described below.
All broader delivery claims remain bounded by PRD #534 and the coverage matrix.

The current artifact is [`genre-coverage.md`](genre-coverage.md): the open RPG/Roguelike
requirements-to-operations matrix used to judge the future Language Definition Bundle and vertical
tracer. Every row is open. It is a completeness contract, not evidence that the package operations,
Golden scenarios, or vectors already exist.

## Permanent delivered slices (#538, #539, #540, #553, #554, #592)

The first production foundation replaces the disposable authority mechanism for one admitted
Quantity slice:

- `src/gda_balancing/schema2/authorities/kernel.json` is the versioned, content-addressed,
  non-self-hosted Kernel Specification for canonical encoding, identity, admission, closed
  fact/term/rule/reason formats, unique rule selection, binding/substitution, Diagnostic closure,
  and deterministic resource bounds.
- The packaged Language Definition Bundle is the sealed multi-member graph defined by bADR-0023.
  Its small root manifest binds that exact Kernel and canonical Package Release descriptors. Each
  package occupies one hyphenated directory and is a sealed one-level aggregate of exactly two
  authority JSON members: a Package Release manifest plus its bound package-owned conformance-vector
  set, including an empty set where applicable. These releases own `core.quantity`,
  `standard.compiler`, standard runtime/experiment/template contracts, tooling contracts, and
  game-mechanic semantics/evidence without creating peer authorities. Admission derives the flat
  lookup view only after the entire graph passes manifest/vector identity, membership, coordinate,
  dependency, resource, and vector-closure checks.
- The production bootstrap consumer and a separately implemented conformance consumer agree on
  exact root/manifest/vector-set identities, law/rule/reason inventories, generated projection
  identities, positive vectors, and old-identity/reidentified
  deletion/behavior/token/member mutations. Neither contains a Quantity host dispatch fallback.
- This foundation admits the closed Quantity constructor and Model Source wire-schema envelope.
  Issue #540 exercises one bounded cast by composing `game.resource`, `game.check`, and
  `game.combat` releases over `core.quantity`; no permanent `game.rpg` type or genre umbrella enters
  the authority. Other operation and package families remain absent until a vertical slice delivers
  their declarative Kernel/LDB contracts.
- `schema get language-bundle|wire-schema|diagnostic-catalog`, `package list|get`, `manifest`,
  per-command `--schema`, and `--params-json <json|->` expose the admitted slice through the
  descriptor-owned 2.x surface. `package get` retrieves either the exact release manifest or its
  exact `conformance-vectors` member without merging the two. Admission failures use bounded,
  ordered, deduplicated, stage-aware Diagnostics.

Issue #539 extends that authority through `model check|build`: one authored Quantity Model Source
resolves to an exact Package Lock, canonical RIR, Resolved Model, provenance companions, and one
authenticated atomic publication. Issue #553 adds `template list|get|instantiate` and publishes
`standard.quantity-minimal@2.0.0`, whose content identity fixes its exact Kernel/LDB, starter
source, package dependency, defaults, compatibility, documentation, pre-build Experiment template,
coverage row,
Golden scenario, and negative/boundary vectors. Every companion payload binds an LDB-projected
wire schema and is structurally and semantically re-admitted before the release can be listed,
retrieved, or instantiated. The Kernel defines a closed Schema-major Template primitive
specification—typed arguments/result effects, evaluation and failure laws, canonical
comparison/identity behavior, and resource-charge rules—and binds LDB-facing operations to those
primitives. The LDB selects a bounded artifact-graph program over ordered role collections, every
derived identity or Model Source fact is explicitly bound, every coverage row resolves
capability/operation/package and observable identities, and every negative/boundary vector executes
through the ordinary Model Source checker. The same program admits multiple pre-build Experiment
templates, Golden scenarios, and vectors without host-selected singleton roles; metric identifiers
are scoped to their owning Experiment template. The member kind `experiment-template` is
intentionally distinct from the exact executable `experiment-specification`, whose
Model/build/RIR identities exist only after build. Concrete role names remain LDB content, so genre
extensions do not change the Kernel role contract.

Instantiation publishes a newly identified editable Model Source plus an instantiation receipt.
The source records explicit template provenance, the release remains immutable, retries are
invocation-key bound, and the resulting source can be edited and rebuilt through #539. This closes
only the minimal Quantity Template-distribution tracer: it delivers no evaluation run, Metric,
Replay, Evidence, complete RPG/Roguelike template, or Genre support claim, and it closes no row in
the normative RPG/Roguelike coverage matrix.

Issue #554 adds `model migrate` as the sole public Standard Schema 1.x entrypoint. It converts only
integral signed-Int64 parameters and unmodified integral direct-number attributes into equal
singleton Quantity domains. The conversion binds the exact input bytes, converter, Kernel, LDB,
successful mappings, explicit defaults, warnings, and output identity. Success atomically
publishes the new `model-source-package` with a `migration-report`, and that source builds through
#539. Any unsupported, lossy, or over-limit construct returns a typed migration refusal with an
inline, LDB-validated `migration-refusal-report`; it publishes no command success artifact and no
partial Model Source. This adds no 1.x runtime, reverse path, save/replay/ruleset adapter, gray
rollout, or Schema/toolkit version coupling.
The target Model Source is canonicalized before success and must fit the LDB's
`max_source_bytes` and `max_symbols` bounds; either overflow follows the same typed refusal path.

The converter binding is the complete embedded `source-converter-specification` artifact, not an
opaque digest; the report consumer can validate and rehash it against the exact LDB artifact
contract. Exact byte identity is limited to regular files no larger than the specification's
16 MiB observation cap. Non-regular or larger inputs fail at usage ingress before any identity or
migration report is claimed.

Issue #540 publishes the exact
[`rpg-combat-cast` Model Source and Experiment](../../examples/schema2/rpg-combat-cast/) and drives
them through public `model build`, `experiment check`, and `experiment run`. One authored
`base_damage` edit changes the exact Experiment identity, trace, and Metric dataset in the expected
direction. The selected exact-int64 Event program uses named SplitMix64 streams and atomically
publishes one of three descriptor-declared outcomes: Evaluation success, a negative Experiment
Verdict, or a Runtime terminal-audit set. Evaluation refusal publishes no completed outcome, and
post-commit retry recovers every published outcome by Invocation key without rerunning evaluation.
The terminal audit retains the complete original Diagnostic location and rolls back the refusing
Event. Evaluator incompatibility is a pre-dispatch `resolution` refusal and publishes no Runtime
artifact.

Permanent-slice dogfooding corrected an important prototype blind spot: node/RNG inventories were
not sufficient machine semantics. The Kernel now closes node fields, operators, results/refusals,
charges, exact-int64 bounds, and SplitMix64 derivation/sampling/vectors; the LDB closes the selected
Runtime profile and typed Operation-outcome algebra. Experiment admission requires exact selected
program closure, the evaluator manifest binds one source-build identity and advertises only the
exact authority-reachable profile/operators independently of the current model, and a separate
reference evaluator consumes the same authorities and agrees on the complete cast event. That
reference validates every node-contract vector and executes every RNG vector; it does not claim
independent execution of nodes outside the cast. Metric samples/datasets now retain their definition
identities, windows, dimensions,
replication, missing/censoring policy, provenance, data version, partition, ordering, and ingestion
binding. Canonical duplicate keys and unsupported external inputs refuse rather than being silently
collapsed or ignored.

This slice confirms one configure/build/check/run/inspect/edit/rerun loop and one independent
evaluator witness only. It closes no Genre coverage row or general evaluator-conformance claim. Its
dogfooding observations and remaining product/architecture gate are recorded in
[`ARCHITECTURE.md`](../ARCHITECTURE.md); downstream tracer work remains subject to the human
product/architecture decision on #540.

The sealed-package conformance suite also adds one non-RPG economy Event package after freezing the
Kernel and host implementation. The package resolves into the selected Lock and RIR, then the fixed
evaluator produces its Event trace, terminal Snapshot, and Metric result without a genre-selected
compiler/evaluator branch. This is a bounded Core Extension Invariance witness for #592. It is not
the independently validated public Extension Invariance Receipt required to close a genre coverage
claim.

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

1. The bounded disposable authority mechanism has been replaced by #538's permanent Kernel/LDB,
   #539's Model-build tracer, #553's minimal content-addressed Template release, and #554's limited
   clean-forward source migration. Disposable code remains non-authoritative and closes no
   acceptance criterion by itself.
2. Remaining work follows the validation and delivery order in
   [`ARCHITECTURE.md` §13](../ARCHITECTURE.md#13-validation-and-delivery-plan). PRD #534 and its
   linked issues own live sequencing and acceptance status, including product-feedback slices
   within an open architecture gate.
3. Gate completion and row status remain governed by that architecture plan and
   [`genre-coverage.md` §Closure rules](genre-coverage.md#closure-rules); this evidence index does
   not duplicate either contract.

PRD #534 remains open until a later implementation/specification PR supplies and validates:

1. the closed Schema-major Kernel Specification, Language Definition Bundle bootstrap schema, and
   canonical bundle;
2. exhaustive machine rules for grammar, resolution, types/effects, evaluation, runtime steps, and
   HIR-to-RIR lowering;
3. RIR semantic normal form with a separately identified Debug Map and independent-lowerer vectors;
4. closed AST, Typed HIR, RIR semantic payload, Resolved Model wrapper, package/lock/capability,
   content-identified Runtime profile definition, Resolved Runtime
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
