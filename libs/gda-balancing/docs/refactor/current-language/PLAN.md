# gda-balancing: bottom-up refactor proposal

Tracker: [#865](https://github.com/aigengame/godot-agent/issues/865) · documentation: [#866](https://github.com/aigengame/godot-agent/issues/866) · [implementation owners](ISSUES.md).

Baseline: `3f68bf3fb26df2ab54351a8ef4e3e167269bdc16` (local HEAD and live main), 2026-09-06.
Lifecycle: accepted refactor direction and implementation plan; implementation and claim gates remain open. Decision owner: project owner. bADR-0028 owns the adopted policy and deletion obligations; this document owns the delivery sequence. Six bounded research tasks and independent adversarial review support the direction. It does not claim that the current host already implements it.

## 1. Decision and scope

**Simplify the existing architecture by removing historical obligations and duplicate authority, then close demonstrated primitive gaps. Retain the typed language, compilation, explicit effects, deterministic Runtime and evidence model.** Do not start a new engine, package manager or parallel DSL.

Here, formal release means the owner’s public product-release decision, not an automated internal tag, changelog entry or distribution version. Existing internal records, including `gda-balancing-v0.1.0`, do not create that decision or a language-compatibility promise.

The user has accepted four drivers, recorded here as report-local IDs (not new product vocabulary):

| Driver | Required result | Owner and falsifier |
| --- | --- | --- |
| R1 | Required mechanics compose from a necessary, non-overlapping semantic basis. | Kernel/LDB owners; a new supported domain needs a host dispatch branch, or two owners decide one rule. |
| R2 | Delete before simplifying; simplify before optimizing. | Every subsystem owner; a retained mechanism has no current consumer or protection that fails when removed. |
| R3 | No promise that internal releases remain immutable or supported; formal release is no earlier than toolkit v1.0. | Product/release owner; any gate requires keeping an old internal implementation solely because it once existed. |
| R4 | High-risk changes have bounded discriminating trials and permanent promotion gates. | Implementation owner plus independent verifier; a prototype is cited as completed conformance. |

Preserve the full product vision in #501 and #534, including known RPG/Roguelike breadth, future bounded deterministic genre extension, numerical design, simulation-backed validation, observed metrics and tuning. The current small Kernel is not the full vision. `requirements-matrix.json` and `.md` map all 55 user stories, 20 #534 acceptance clauses and 34 genre rows to owners, stages and verification. The linked delivery matrix adds 55 exact acceptance clauses from #509/#510/#512–#517/#745, for 164 routed items in total. Mapping granularity is story, acceptance clause and genre row; it is not a claim to have independently proved every sentence of the existing architecture. Open implementation is kept open rather than excluded to make a smaller basis appear complete.

The owner authorized recording this plan, updating superseded ADR and issue clauses, and publishing the documentation PR. The owner further requires actual deletion after execution dependency closure: a temporary broad binding is a migration state, never a final outcome. This PR records the accepted direction and work; production code and machine contracts still change only through the tracked implementation slices. It does not authorize a formal product release or activation of deferred features.

Non-goals: permanent compatibility for withdrawn internal content; a range/SAT dependency solver; a registry of historical releases; a new generic Simulation context; a second Runtime for each mode or genre; dynamic host callbacks; remote/distributed service infrastructure; speculative caches; implementing all future type constructors at once; importing MLIR/Wasm as a dependency.

## 2. Sources and authority

Requirement matrices preserve the captured source text and links at the pinned baseline; the live linked issues and bADR-0028 own subsequent amendments. #501 and #534 remain open. #509, #510, #512–#517 and #745 remain open; #545, #546 and #789 are closed at the captured baseline. Closed issue status alone is not full architecture conformance. Every genre row currently says `open`. Root STATE is a coordination note, not acceptance authority.

| Fact | Owning source | Treatment |
| --- | --- | --- |
| Product purpose, feature acceptance, scenario scope | #501, #534 and linked feature issues | Preserve IDs and complete scope; explicitly revise historical obligations under R3. |
| Shared balancing meanings | `BALANCING-CONTEXT.md` | Keep local to this package; do not write to parent CONTEXT/ADRs. |
| Macro topology, subsystem boundaries, validation order | `docs/ARCHITECTURE.md` | Retain topology; apply the accepted identity, preparation and pre-1.0 direction; retain current-wire descriptions until implementation. |
| Decision rationale | `docs/badr/` | Supersede specific claims explicitly; one new decision may replace several obsolete release-retention clauses. Do not duplicate complete semantics in it. |
| Bundle interpretation and irreducible execution/admission laws | Kernel Specification | Machine-consumable laws remain authoritative. Current content may be replaced; an admitted run cannot silently change laws. |
| Language constructors, operations, packages, profiles and cases | One exact LDB | One current definition per namespace. Package content owns domain compositions. |
| Model design, experiment intent and human approval | Model Source, Experiment Specification, Approval Record respectively | Authored authority is not replaced with host defaults or generated output. |
| Implementation, compiled projections, receipts | Python host, RIR/Resolved Model, evidence artifacts | Implementations/projections/provenance, not peer specifications. |

R3 specifically reopens #534 US08/10/12/22/24/25/27 and AC04/06/07/19 where historical naming, retention or exact build binding appears. Preserve the purpose of namespace ownership, exact integrity, reproducibility and independent tool release; remove unneeded historical selection promises. #534's former freeze gate must not trigger a pre-1.0 compatibility commitment. A fixed conformance input is a test identity, not a published release contract.

## Delivery and formal-claim boundary

The current #534 amendment and #542–#544 retain explicit activation conditions for authenticated Verifier trust, receipt-backed claims and cross-evaluator conformance issuance. This refactor does not activate them. Exact validation, local Replay, ordinary comparison and early extension witnesses may complete with candidate/open claims. Requirements matrices retain those long-term obligations as deferred, not silently removed or required solely to finish deletion. #509 remains the human decision owner for unresolved simulation policies; #512 may explicitly accept or reject continuous support. The linked implementation issues distinguish these states.

## 3. Evidence that changes the decision

All probe claims below are **confirmed-narrowly**; their artifact source and adapted harness provenance are recorded in [EVIDENCE.md](EVIDENCE.md). The count of passing cases is not a proof of complete language coverage. Raw scripts, charters, results and limits are preserved under `evidence/` with a file manifest. This is a curated portable subset of the investigation, not an archive requirement for all internal outputs. Reports from agents were treated as leads; synthesis inspected the governing code and structured results.

| Evidence | Observation | Design consequence | Not proven |
| --- | --- | --- | --- |
| E1 unified LDB | 21 releases become 14 current definitions; 42 exported Operation entries become 28. Five maintained Models compile and self-admit; all seven maintained Experiments succeed. 41 execution vectors agree between existing two consumers and expected results. | Merge old/new Build and Effect capabilities before deleting older files. Use one current language graph. | Full CLI/HTTP/Godot, all negative vectors, or SemVer field deletion. |
| E1 composition | Current progression plus periodic Effect fails baseline dependency resolution; unified graph executes progression-derived threshold 5×17=85 and reaches periodic terminal health 70. Missing dependency and wrong typed port refuse. | Version fragmentation obstructs actual cross-capability composition. No new primitive or host code is needed for this witness. | All domain cross-products. |
| E2 versionless graph | Real six-package RPG closure and 30 ordering permutations resolve without version selection; duplicate owners, missing/cyclic dependencies and capability/name ambiguity refuse. | Namespace selection inside one exact graph can replace independent SemVer selection. | Production source trial uses a coordinate-restoring shim; recursive semantic identities and a truly versionless compiler are not implemented. |
| E2 identity | Vector-only and unselected package edits leave RIR unchanged. Compiler-label change changes only Build receipt at compile time. Old Experiment refuses; after rebinding, six runtime identities change while six metrics and nine snapshot value states stay identical. | Build provenance re-enters execution identity through Experiment. Separate the two purposes. | All semantic equivalence or permission to mislabel regenerated runs as old Replay. |
| E2 closure | Runtime reads LDB reasons and max_rule_match_steps outside RIR (`runtime/execution.py:233,1011,1624`). | Close all actual execution inputs before narrowing identity. | RIR-only execution is currently sufficient. |
| E3 primitive reductions | 70,585 int64 pairs preserve maximum result via compare+select. Charge changes 1→2; limit 1 changes success to refusal. copy/value laws are identical; value is absent from package manifests. | Delete exact value alias; move maximum to composition only with a deliberate current charge reset. | Safe semantic deletion of subtract, state subtraction, guards or cancellation. |
| E3 counterexamples | MIN−MIN=0 but MIN+(0−MIN) overflows; List equality cannot replace is-empty in 28 actual projections. | Exact numerical and type laws outrank algebraic opcode minimization. | A globally minimal instruction set. |
| E4 collections | Disposable bounded pure left-fold+snoc prototype: 35 named cases, 3,906 numeric enumerations, 364 filter enumerations; two execution strategies agree. Left fold gives 123 where naive regrouping gives 33. | Add bounded traversal/construction as a candidate gap-closing extension; specify order and cost. | Production integration, independent admission/meter, sort/shuffle/zones/effect reduction or nested priority completeness. |
| E5 preparation | Five maintained Models produce byte-identical eight-class compilation outputs after request-local preparation reuse; resource budgets 196/197/198 straddle an unchanged 197-step boundary; lowering 3→1, Formula resolution 2→1, runtime projection 3→2 including retained imported-artifact validation. Initial naive freeze failed because specialization relies on shared object aliases. | Materialize existing Typed HIR preparation once; make specialization return complete explicit projections, not rely on alias side effects. | Persistent cache safety, total performance improvement or removal of independent admission. |
| E6 retirement | No registered artifact_sink consumer. After deletion, 60 CLI observations are byte-identical. 289 common testcase outcomes unchanged; 77 obsolete cases retire; extra 17 publication/alias/layer/parity tests pass. Historical CI rejects 53 retired IDs. | Delete unused sink and replace historical inventory obligations with current capability coverage. | Full CI or deleting active artifact publication protections. |

The E1 count of14 includes tooling.migration and describes that experiment only. The implementation inventory is derived after S1b; it must not preserve or reintroduce a retired package to match a historical count.

Retirement inventory also isolates 4,951 Python lines of toolkit old-input support. Only a tracked test fixture is a committed authored 1.x input. Outside-repo inputs are unknown; this is a bounded inventory, not evidence that none exist. Panda has a distinct real embedded implementation and adapter; #517 requires a source-faithful replacement and comparison before that code is deleted. Toolkit converter removal and Panda cutover are separate decisions.

The evidence shows multiple sources of drag: historical capability branching, redundant wrappers/projections, hidden mutable aliases, dead interface policy and incomplete collection expressiveness. It does not show a second old/new compiler or genre-specialized Runtime. Preserve the parts that already separate concerns well.

## 4. What versioning is for, and what to remove

| Current purpose | Decision before v1.0 | Minimum retained mechanism |
| --- | --- | --- |
| Announcing compatibility to external users | Defer formal promise; do not infer it from internal tags. | Toolkit version/build label for distribution and bug reports; truthful content receipts. |
| Selecting multiple historical package/Operation releases | Remove after capability convergence. | Unique package namespace and local declaration name inside one admitted graph; exact semantic closure. |
| Distinguishing syntax/format families | Simplify to the currently supported format identifier; keep a discriminator only where it prevents actual misinterpretation. | One active decoder per supported artifact family; typed refusal for old/unknown formats. No historical router. |
| Detecting changed bytes / corruption / stale evidence | Keep. | Canonical content hash, declared artifact kind, complete validation. |
| Distinguishing nominal types with equal shape | Keep. | Namespace + declaration identity under selected semantic definition/closure. Never replace nominal meaning with shape equality. |
| Pinning actual laws for deterministic execution | Keep; narrow the dependency cut only after closure proof. | Selected semantic program plus runtime policies, inputs, assignments, named RNG and resource law. |
| Explaining who built/executed a result | Keep once as provenance. | Existing Build/run receipts; do not feed compiler labels into numerical experiment intent. |
| Keeping an active request internally stable | Keep. | Immutable admitted snapshot for the request/session lifetime. Replacement affects subsequent requests. |

Decision D1: remove independent SemVer coordinates from packages, Operations, requirements, imports, template selections and capability names wherever the suffix exists solely for historical selection. Do not replace them with monotonically increasing epochs or another compatibility registry. Stable capability names still denote a checked contract in the exact current graph. Renaming `schema2/` or HTTP `api_v1` solely for aesthetics is deferred; remove a semantic dispatch dimension, not every digit in a filename.

Decision D2: one whole-LDB integrity identity for lookup/build provenance; one canonical selected semantic closure for program meaning. Reuse the existing RIR semantic identity and wrapper concepts. Do not hash the entire LDB identity into every nominal name, which would reproduce change amplification. Recursive types and transitive Operation calls require a canonical closure algorithm with cycle/type refusal, not the flat probe's scalar hash. Lock becomes a derived record of the selected dependency/capability/definition graph; it does not choose versions or negotiate compatibility.

Decision D3: Experiment intent binds semantic model and actual execution settings. Build receipt is referenced by run provenance rather than used to determine intent identity. Exact artifact integrity remains separate from semantic comparison. Close selected reason definitions, structured-value resource rules, numeric laws, scheduling, RNG and external-input policy before removing full-authority execution binding. Until that gate passes, the broader binding may remain only as an enumerated transition. After closure, deletion is mandatory: remove obsolete required fields/references, execution admission checks, identity derivation edges, Replay/session gates and compatibility fallback. Closure alone cannot close the deletion issue or the refactor. Content integrity and actual execution dependencies remain.

When internal semantics change, reauthor/rebuild known inputs and regenerate current evidence. Old outputs may be withdrawn. If retained, they retain their true hashes and provenance; never overwrite bytes under an old hash or describe a fresh run as historical Replay. No archival service is required. At v1.0, decide which authored/source/artifact interfaces have a public stability contract, identify actual consumers, and publish a bounded compatibility policy. v1.0 is the earliest allowed formal release, not evidence that every internal representation must then be frozen forever.

## 5. Candidate semantic basis

“Orthogonal basis” here means independently necessary semantic concerns, not a mathematical proof that the opcode set is smallest. The observable contract includes admitted type, result/outcome/refusal, state and alias effects, RNG draws, event identity/order, resource charging and rollback. A reduction must preserve these or explicitly replace the current unreleased law and its evidence.

| Concern | Irreducible responsibility | Composed content | Why it remains / next falsifier |
| --- | --- | --- | --- |
| Typed values and identity | Quantity facets/numeric policy; closed structured constructors; nominal declarations and references; canonical values | Health, currency, damage kinds, cards, domains and components | Without it, equal-shaped values acquire incorrect meaning; wrong unit/type/ownership must refuse. |
| Pure finite computation | Exact arithmetic, equality/order, literal/binding/projection, pure selection, typed refusal | Damage/healing/scaling/formula policies, min/max/caps | Extreme values, eager refusal and charge accounting distinguish necessary laws. No implicit host arithmetic. |
| Bounded composition | Statically resolved calls, finite acyclic closure; proposed ordered pure fold and bounded construction | Filter/map/count/ordered reductions, dynamic target query | Current fixed lookups require expansion proportional to a chosen maximum N rather than a generic bounded traversal. Reject unknown bound/effects/foreign locals; preserve source order. |
| Explicit effects | Named sampling, transaction-local state write, event schedule/cancel, typed signal | Costs, effects, action policy, reward policy, progression | Pure calculations cannot represent RNG/state/event lifecycle. Aliased writes and canceled events are decisive witnesses. |
| Atomic event transition | Read/write snapshot law, conflict policy, total order, commit/rollback, bounded progress | EffectRequestSet and reaction policies expressed through explicit ordered programs | Without atomicity, partial cost/damage/effects leak on refusal. Domain packages must not choose host scheduler phases. |

Admit no unnecessary second Formulas engine. Source notation projects to one typed pure representation; Formula slots are statically bound policy inputs; both feed the same semantic execution basis. Formal binding, assignability and transitive effect/refusal/resource closure have one production knowledge owner.

The machine baseline has five constructors (Quantity, Enum, List, Record, Ref), with Quantity currently exact-int64 scalar unit 1. The architecture's prospective constructor set is an envelope, not present support. Add a constructor only when a mapped scenario cannot be expressed faithfully using current constructors and content. Keep #512 continuous-equation/solver policy explicitly open; do not sneak floating-point or unbounded integration in under arithmetic cleanup.

Fold candidate law: finite typed input List, declared upper bound, fixed initial accumulator, left-to-right body, body is pure and closed, accumulator type preserved, exact charge/refusal order, bounded output construction. Snoc supplies dynamic variable-length output; empty List is already a literal. Current probe rejects nested folds and effectful calls; it does not establish their impossibility or final language policy. Promotion must specify allowed static composition and its bound recurrence rather than inherit the harness restriction accidentally. Naive immutable snoc costs O(N²) copied cells. A private builder can optimize representation later only after it preserves public values, refusal order and charging. No dynamic closure/callback API is justified.

State/event reduction is deliberately more conservative. Keep subtract-state and precondition until current-value versus captured-value, aliasing, outcome and rollback witnesses settle replacement. Keep cancel unless an alternative preserves event accounting, trace and RNG. Avoid adding List equality solely to eliminate emptiness. Maximum can become LDB composition with changed declared charge; do not build a special compatibility charge exemption to make its deletion look behavior-preserving.

## 6. Concrete module ownership and communication

Retain one balancing Bounded Context and the existing physical macro rule `interfaces → application → domain → infrastructure`, with acyclic same-layer dependencies. Here infrastructure means domain-neutral technical byte/file/package services. Domain owns canonical identity and publication policy; infrastructure owns filesystem operations. Do not import the parent gda domain or invert the established graph to imitate a generic DDD folder diagram.

```text
src/gda_balancing/
  interfaces/
    cli/                    # argv, descriptor projection, envelope and channels
    http/                   # local HTTP protocol/transport
    execution_service_language.py # adapter contract projection
  application/
    model_*.py              # source→check/build/inspect use cases
    experiment_*.py          # prepare/run/replay orchestration and publication
    execution_sessions.py   # protocol-neutral session lifecycle
    evidence_verify.py      # verification use case
  domain/
    authority/              # one admitted Kernel/LDB and derived indexes
      admission.py          # ordered admission facade; delegate cohesive judgments
      graph.py              # unique ownership + dependency/capability closure
      *_validation.py       # distinct authority contracts, not duplicate owners
    structured_values.py    # canonical type/value interpretation
    formula/                # notation, pure typing and source diagnostics
    model/                  # resolved bindings; request-owned Typed HIR; semantic RIR
    operation_program.py    # static calls/effects/refusals/bounds
    operation_call_domains.py # one call-domain assignment judgment
    runtime/
      execution.py          # explicit execution and atomic transitions
      scheduler.py          # event order/lifecycle
      projections.py        # Runtime artifacts and closed semantic profile
    experiment.py           # scenario/intent/assignment admission
    experiment_artifacts.py # existing artifact contracts
    experiment_artifact_replay.py # independent replay interpretation
    comparison.py           # typed comparable observations
    evidence_verification.py # evidence eligibility/authentication semantics
    publication*.py         # invocation artifact-set consistency policy
    template/               # authored package composition / instantiation
    canonical.py, wire_schema.py, diagnostics.py
  infrastructure/           # actual filesystem/distribution/package-resource IO
  schema2/authorities/       # Kernel + one current definition per package
```

This is a responsibility target using current names, not an instruction to retain oversized files intact. `module-disposition.md` assigns every one of the 143 current production Python files. Deepen `authority/admission`, `model/_lowering`, and `runtime/execution` only along the responsibilities above. Do not split one file per opcode or create a port for every function. Later Metrics/Calibration policy modules are added only with their first end-to-end use case, under domain, with application orchestration.

| Module decision | Owns | Public downward contract / isolation | State/lifetime |
| --- | --- | --- | --- |
| D4 authority | Bundle admission, graph, interpretation and immutable indexes | Admit exact bytes→AuthorityContext or typed diagnostic; no model/game dispatch | Snapshot per request/session; new bundle means new context. |
| D5 compiler | Source resolution/typing and semantic-preserving lowering | prepare→private Typed HIR; compile→RIR/artifacts; import→independent admission | Prepared immutable request-owned value; no persistent cache/global mutable model. |
| D6 Runtime | Actual transition, event transaction, scheduler/RNG | Closed admitted program+explicit inputs→committed trajectory/artifacts or typed terminal audit | One Runtime instance owns all mutable state; no package-owned parallel engine. |
| D7 evaluation | Experiment replication, Metrics/Comparison/Calibration/Evidence | Application composes Runtime calls; domain policies consume typed outputs | Replicas isolated; metrics do not mutate Runtime; approval is separately authored. |
| D8 delivery | CLI/HTTP, sessions, artifact publication | Adapters call application; publication delegates only byte operations | Session owner closes/invalidates; artifact-set commit separate from event commit. |

Prepare stores the already designed Typed HIR result, not a new public artifact family. Reuse lowering inputs, Formula binding and unspecialized runtime projection. After Formula specialization, explicitly derive every affected operation and package-closure projection. The prototype preserved aliases to demonstrate feasibility; production must remove correctness dependence on alias identity. Retain post-specialization entrypoint/callsite checks and imported-artifact validation. Do not share production evaluators with independent conformance consumers merely to obtain DRY.

Direct returns handle ordinary upward results. Domain defines typed signals and terminal audits; application/adapter chooses presentation. No global bus, service locator or implicit mutable callback registry. CLI and HTTP use the same application sessions and execution path. #745 incremental execution extends this lifecycle with create/advance/observe/close, state continuity and invalidation; it does not create a new Experiment revision for every advance or re-run from a guessed seed. Process loss invalidates a session unless a separately specified recovery contract exists.

## 7. Domain breadth and simulation-backed evaluation

Packages own decisions such as target policy, cost lifecycle, damage stages, immunity/stacking, resource regeneration, build constraints, progression, reward policies, economy conservation and collection zones. They compose the common basis; names do not trigger host branches. Explicit immutable Action plans, EffectRequestSet order/reducers and scope/reset rules remain needed semantics. Removing release history does not remove the need to specify these interactions.

Development waves close actual rows: values/stat/build/progression; dynamic targets and ordered damage; cost/action/cooldown/heal/defense; full effect lifecycle and reactive order; generation/build/economy/encounters; run/meta/turn/spatial/decision/deck and non-RPG priority. Each uses admitted operations and public artifacts. Shared primitives are promoted only from an expressiveness witness; a package-specific failure is fixed in that package unless the lower abstraction is demonstrably insufficient.

Simulation is composition of existing owners, not another Bounded Context. Runtime produces a single trajectory; Experiment declares replicas, seed allocation, initial/externally supplied inputs, horizon, stopping/censor policy, policy/skill assumptions and correlation/replication units. Metrics define estimands, units, undefined/missing cases, uncertainty and provenance. Comparison/targets declare eligibility and thresholds. Calibration explores authored parameter domains and writes proposed Model Source, not hidden runtime overrides. Evidence and Approval remain separate from scores.

#509's unanswered policies must be decided with their specified evidence before #510/#512–#516 claim completion. #512 may add an explicitly bounded equation capability only after solver, numeric representation, error/tolerance, unit, initial condition, snapshot, zero-crossing, deterministic and resource policies are settled. Existing exact discrete Runtime remains the path for current scenarios. A refusal for an unsupported continuous feature is honest interim behavior, not satisfaction of the long-horizon product requirement.

Panda #517 supplies a real consuming-game cutover: author a current Model/Experiment over the declared old scope, compare outputs using its explicit metric tolerances and source-fidelity fixtures, maintain its gate through the migration, then delete the embedded implementation and adapter. Current static inventory does not prove that an RK4-based old pipeline has current semantic parity. Full new genre examples and Panda are different witnesses and neither substitutes for the other.

## 8. Entropy disposition

| Mechanism | Action and benefit | Essential protection / smaller alternative |
| --- | --- | --- |
| Historical package release copies | Remove after current capability union; fewer graphs and duplicate vectors | Keep unique namespace ownership and current behavior vectors. Never simply choose latest Build/Effect and lose old functions. |
| Internal SemVer and exact-version branches | Remove once grammar/closure gate passes | Current namespace graph+content identity; no range solver, shim or epoch replacement. |
| Whole-source evaluator identity and provenance amplification | Simplify only after dependency closure | Complete installed implementation provenance once; selected semantic inputs for equivalence. No hand-written incomplete source allowlist. |
| Repeated lowering/formula/projection preparation | Reuse request-owned semantic preparation | Keep specialization-stage and external admission boundaries; no global cache. |
| Shared alias mutation during specialization | Remove implicit dependence | Explicit derived result and ownership; old alias-breaking counterexample becomes a regression. |
| Assignability/role-total copied in admission/lowering | One production judgment owner | Same rule, callers adapt diagnostics; independent verifier implements separately. |
| copy/value | Remove value alias | Keep actual binding semantics and active vector coverage. |
| maximum | Compose and reset current resource law | Preserve exact values/extreme cases; delete old charge promise, not resource accounting. |
| Unused artifact_sink | Remove now | Existing Artifact Set publication and input/path alias checks remain. |
| Toolkit Schema1 converter | Remove after one-time named-source disposition | Temporary offline tool only if an actual named input remains; expiry is that input's disposition, no indefinite runtime support. |
| Panda embedded stack | Replace then remove under #517 | Public current-source path and explicit tolerated comparison, not a permanent adapter. |
| Frozen test-ID/release inventory | Replace | Current contract coverage, collection partition, unexpected skip/xfail gate, active vectors, mutation and independent consumers. |
| Type/semantic admission, exact integrity, independent replay | Keep | Required to reject malformed/tampered artifacts and avoid self-verification. |
| Event atomicity, publication atomicity, verifier authentication | Keep distinct | Different failure/lifecycle boundaries; do not merge to reduce class count. |
| Prospective constructors, generalized interfaces/caches | Defer implementation | Preserve requirement ownership and explicit gaps; add only when a mapped witness needs them. |

Alternative A (interim checkpoint only): change the retention policy and unify content while coordinate fields temporarily remain. E1 supports this independently useful checkpoint. Under the accepted deletion requirement it is not a final stopping point; the contracted graph and obsolete-binding deletion still must finish. Alternative B (recommended): A plus current-graph selection, reduced identity amplification, one prepared compiler path, dead mechanism deletion and scenario-driven primitive closure. Alternative C: rewrite all host layers or introduce a more general engine/package resolver. Reject C now: it adds mechanisms without evidence and delays observable progress. A's temporary coordinate fields and broad bindings must have named deletion owners and terminal acceptance criteria; they cannot become permanent compatibility machinery.

## 9. Ordered process and gates

Dependencies are sequential where authority changes; independent research/tests can fan out. Production implementation slices use isolated worktrees only once authorized. Each slice must compile and run a vertical witness before the next foundation grows. Stages are completion gates, not time estimates; no fabricated delivery dates.

| Stage | Change / permanent assets | Required observable exit | Stop/reopen / rollback |
| --- | --- | --- | --- |
| S0 decision reconciliation | Record the accepted policy; update #534/#501 affected clauses, glossary, architecture and bADRs once per owner; current input inventory | No normative rule requires retaining withdrawn internal versions; each old artifact/input has keep/rebuild/withdraw decision | If a real external contract is found, identify exact consumer and scoped policy; do not infer universal compatibility. Revert decision patch as one unit if declined. |
| S1 independent deletion | Remove artifact_sink and dead tests; rebaseline only obsolete obligations in CI | Current complete CLI observations and retained behavior outcomes match (probe baseline: 60 observations, 289 outcomes); publication/path safeguards and current shard/outcome gate pass | Any live consumer/changed result blocks deletion. Restore bounded patch. |
| S1b old-input retirement | After S0 named-input disposition, delete toolkit Schema1 converter/command/resources and migration-only tests; retain only a temporary offline tool for a concrete unresolved source | Current source path and active wire/catalog/CLI/wheel inventory pass; no migration-only production imports/resources or unfinished named-source/offline-converter disposition remains | Independent of Panda. Do not adapt this soon-to-be-deleted converter to S3. If a real input remains, isolate its bounded offline conversion and retire it on disposition. |
| S2 current language convergence | Union Build/Effect; consolidate quantity profiles; refresh all derived identities/vectors/examples | One current definition per post-S1b retained namespace (13 expected if only tooling.migration is retired), full active capability union, five Models/seven Experiments, progression+periodic witness; complete current positive/negative/mutation corpus and CLI/HTTP public path | Lost capability, duplicate semantic owner or unexplained conflict reopens merge. Revert content+fixtures+derived artifacts together. |
| S3 remove selection versions | Rewrite source/import/template/operation/capability contracts and graph; remove version parser/history branches; derive Lock | No shim; all maintained paths versionless; order permutations, missing/cycle/duplicate owner, nominal same-shape/different-meaning, recursive/transitive identity mutations refuse/identify correctly | Flat graph proof is insufficient. If closure fails, reopen the implementation slice and keep the parent open; Alternative A is only the last coherent checkpoint, not completion. |
| S4 semantic preparation | Single Typed HIR preparation, explicit specialization outputs, one production assignment rule | Eight artifact classes unchanged where semantics unchanged; invalid diagnostics, low resource limits, old-request stability/new-request freshness; alias-breaking mutation caught; imported artifact tamper still rejected | Any skipped stage or mutable alias leaks blocks reuse. Revert compiler slice independently. |
| S5a execution dependency closure | Resolve every Runtime-consumed reason/resource/numeric/scheduler/RNG/input rule into the selected execution contract | Mutation of every consumed dependency changes semantic identity or refuses; public result/refusal/rollback paths use the closed inputs | Any undeclared dependency reopens closure. All broad transition bindings are enumerated for S5b; this stage cannot satisfy deletion. |
| S5b mandatory binding deletion | Remove obsolete whole-LDB, exact-build wrapper and Build-receipt prerequisites from Experiment intent, runtime/replay/session eligibility and semantic execution identities; remove related fields, branches, fallbacks and unrelated-source fingerprint dependencies | Provenance-only mutations leave semantic execution unchanged; real semantic mutations change identity or refuse. Code/schema/call-graph scans and public CLI/HTTP/Replay tests prove every enumerated obsolete binding is gone | Partial deletion, compatibility fallback or a promise of later cleanup cannot close the issue or parent. Restore a coherent prior code/authority/source/evidence baseline on rollback. |
| S6 minimal basis promotion | Delete value; derive maximum with explicit new charges; formalize bounded collection law and static composition; add permanent two-consumer cases | Source→RIR→run filter and ordered damage/reduction; empty/max/overflow/cardinality/order/eager refusal/resource cases; old helper counterexamples converted to public tests | Do not claim all genres or effectful fold. O(N²) copy/latency exceeds declared scenario budget: change private representation or reopen primitive, not weaken limit. |
| S6b early extension falsifier | Promote a minimal non-RPG nested-priority source→RIR→run witness against the candidate fixed Kernel and unchanged host dispatch; independent builds fixed before a closed reachable token inventory, exhaustive bijective non-Kernel renaming, mutual artifacts and missing-token refusal | Reusable priority-window Operations execute the proposal/counter-to-counter/pass-or-cancel/final-resolution path plus a discriminating input variant with specified per-boundary state/outcomes; independent inventory/mutual-artifact checks establish the narrow witness before broad RPG content investment | If it needs a genre switch/new fixed scheduler phase, reopen the basis now. This is not closure of every priority row variant; full breadth remains S8. |
| S7 core RPG verticals | Target/cost/action/resource/check/damage/heal/defense and full effect/reactive interactions | Each mapped genre row has operations, scenario, positive/negative/boundary/interaction vectors and public observations; rollback/order/cancellation/alias cases | Core/host changes for a package policy reopen attribution. No metadata-only closure. |
| S8 remaining breadth and extension | Reward/build/progression/economy/encounter/run/meta/turn/spatial/decision/deck; non-RPG nested priority | Every remaining genre row closes, including fixed-core non-RPG nested response/counter witness and independent Extension Invariance evidence | A genre needs fixed new scheduler phase/host callback: reopen claimed core extension invariance. |
| S9 evaluation and tuning | #509 decisions; #510/#512–#516 end-to-end increments; shared observed/simulated Metrics | MC reproducibility, censor/correlation/replication; transparent scores; supported curve/distribution; target verdict; bounded search/identifiability; continuous capability only after its decision gate | No solver/metric approximation hidden as exact semantics; unmet long-horizon goal stays open. |
| S10 delivery and consumer cutover | #745 incremental lifecycle; #517 Panda public source path; complete any named residual offline input disposition and remove the separate demo old stack after verified replacement | Complete-run and incremental equivalence where declared; process-loss refusal; source-fidelity/tolerance comparison; wheel contents and CLI/schema/help/HTTP parity; actual Godot consumer acceptance | Toolkit converter removal does not close Panda. Keep old demo gate green until replacement verified, then remove old implementation. |
| S11 full closure and v1 decision | All mapped requirements/gates, package CI and real consumer validation; current docs and release artifacts | Acceptance is evidence-backed; operational budget, recovery, security, install and rollback gates pass. Explicit owner chooses v1.0 public contract | Not automatically achieved by this plan, line deletion, green unit tests or internal tag. |

S6b must demonstrate input-dependent behavior through admitted reusable priority-window Operations, not a Model or fixture that prescribes the expected trace. Under the same rules and fixed builds, a baseline sequence and a discriminating responder-order, counter-target or pass/close variant must produce the specified per-input-boundary stack, priority and stable pending identities, followed by the expected different final outcome or typed refusal. Kernel laws, constructors, phases and compiler/evaluator dispatch remain unchanged. [#878](https://github.com/aigengame/godot-agent/issues/878) owns this acceptance criterion.

The minimal S6b extension tracer runs before broad S7 work. It exercises independently fixed builds, complete reachable token inventory/renaming and mutual artifacts for the narrow witness. Functional results remain candidate/open; authenticated Extension Invariance or other formal claims do not close until their existing application/trust activation conditions are met. S8 retains the complete #575 scenario family and final-graph invariance obligations.

The [issue index](ISSUES.md) separates S3 into expand, migrate and final contract/integrate work on one bounded integration branch. Intermediate wire migrations do not merge to main alone; the final contract issue deletes all temporary forms and owns the green public integration result. S5a is blocked by both that result and S4; S5b must then complete actual deletion.

The current refactor parent closes only after its final public-consumer and deletion verification. S7–S10 and the complete-product S11 release/claim decisions remain on their existing product issues; they are routed here to preserve scope, not silently required to close the narrower refactor or claimed complete by it. The early S6b functional tracer remains candidate/open and feeds the later complete #575 scope.

Some order can shorten: S1 is independent; S4 can follow S2 without waiting for semantic cleanup if its identity baselines stay pinned. S9 decision research can begin during S7, but cannot introduce a second semantic authority. S1b follows S0 and runs independently of Panda; it should precede S3 so obsolete code is not adapted to the new graph. S10 consumer source inventory starts at S0. Deliver narrow cross-layer results rather than holding everything for S11.

Every implementation PR records: current problem and requirement IDs; one authority change; removed obligations; exact before/after observation contract; required tests and negative mutation; source migration and evidence disposition; rollback. No permanent dual writers/readers are needed for internal history. A one-time source transformer has an enumerated input set and is deleted when that set is resolved. Changes to toolkit and Panda/root release surfaces must be split according to the repository release scope guard.

## 10. Permanent validation contract

The matrix is a routing ledger, not a complete row-level oracle. Before closing any row, enumerate every clause in its unchanged source text and preserve the genre row’s declared golden/vectors/observables, with positive, negative, boundary and interaction expectations. A G-X label or one passing happy path cannot close the row.

Each promoted case contains source requirement ID, exact law/selected definitions, input artifact graph, expected admission/outcome/refusal, expected result/state/RNG/event/resource observations, independent-consumer expectation, and tamper/deletion/behavior mutations. Negative cases must fail for the intended reason, not merely fail somewhere earlier. A counterfactual old implementation or deliberate mutation must distinguish a regression case.

| Gate | Concrete cases and owner | Evidence state now |
| --- | --- | --- |
| G-A admission/identity | Old-hash tamper; reidentified rule deletion/behavior change; renamed authority tokens; unknown grammar; missing/cyclic/ambiguous graph; recursive nominal types. Authority + independent bootstrap consumer | Current subset exists; new grammar/closure open. |
| G-C compiler | Source order/notation vs semantics; Formula specialization; explicit closure; extreme values; assignment domains; alias isolation; post-specialization admission; mutually produced artifacts | Preparation probe narrow; new production path open. |
| G-R Runtime | Scheduler order, named draw consumption, immutable plans, signal order, partial-event refusal/rollback, low bounds, state aliases, cancel/expiry, same-event request reducers | Existing selected scenarios; expanded basis/interactions open. |
| G-E evaluation/evidence | Exact replay vs cross-evaluator semantic comparison; metric schema roundtrip; untrusted receipt/tamper; eligibility/approval; independent observed provenance; seed/horizon/censor changes | Existing replay/evidence slices; expanded metrics/MC/calibration open. |
| G-I interfaces/publication | All descriptor schemas/help/manifest/argv outcomes; CLI/HTTP shared semantics; output framing; atomic set failure; symlink/direct alias; source disappearance; status/refusal channels | Sink probe narrow; final changed inventory/publication open. |
| G-X extension/consumer | All 34 genre rows; generic attribute plus existing laws; non-RPG nested priority with unchanged Kernel/host; Panda declared source fidelity and comparison | Unified mixed-package witness passes; full breadth/non-RPG/consumer open. |

Use the existing package runtime, not a globally installed CLI. Verified command shapes at this baseline include:

```sh
# Package cwd; substitute a writable path for <scratch>. Use a task-scoped UV_CACHE_DIR if needed.
.venv/bin/python -m pytest tests/test_layer_dependencies.py -q -p no:cacheprovider
.venv/bin/python -m pytest tests/test_cli_conformance.py tests/test_schema2_model_cli.py tests/test_http_service.py -q -p no:cacheprovider
.venv/bin/python tools/ci.py required-test-shards
.venv/bin/python tools/ci.py verify-inventory --report <scratch>/current-inventory.json
.venv/bin/python tools/ci.py verify-outcomes --junit <scratch>/current-tests.xml --report <scratch>/current-outcomes.json
```

S1/S3 legitimately change the inventory; the existing historical inventory command initially fails until its required IDs are reconciled. Do not label that expected obsolete-policy failure a product regression, and do not suppress an unexplained missing active test. Actual full CI must use the repository's current shard commands, lint/type/packaging jobs and timeout/outcome policy. The commands above are gates to execute during implementation, not claims that this task ran full CI. Source collection IDs, definitions/parametrization, assertions and skip dispositions must explain any count decrease; independent conformance consumers must remain independent.

Performance/capacity: record five current model check/build times and peak memory, a maximum declared target List, maximum encounter queue, event rate and evidence volume on one specified environment. Measure before/after; semantic work counters are correctness, elapsed time is performance. No speedup percentage follows from fewer lowering calls. Establish scenario budgets before production acceptance, reject unknown/unbounded sizes, and include one-below/exact/one-above resource cases. Do not add caching unless measured repeated work still dominates after deletion/reuse.

Reliability/security: preserve no host callbacks/imported game code, strict input limits/capabilities, typed refusals, filesystem alias protections, authenticated verifier receipts, per-event rollback and per-invocation publication failure handling. This is input robustness and artifact integrity, not a new security product. Recovery distinguishes recoverable published source/artifacts from an invalidated in-memory session; no fictional distributed restoration. Observability binds diagnostic stage/code/source pointer and terminal audit to exact content, while provenance and semantic comparison remain distinct.

Deployment/rollback: build/install the package's wheel in an isolated environment, verify resource inclusion and engine/game isolation, run the same public fixtures through source and installed wheel, then an actual local consuming example. A rollback restores code, Kernel/LDB, source examples and current expected evidence as one coherent checkout/distribution. It never merges old/new authorities within a run. Withdraw affected claims when evidence is regenerated. No rollout fleet, historical storage service or global migration manager is justified by this internal installed base.

## 11. Research grounding, disagreements and proof limits

| Mechanism | Primary provenance | Adopt / exclude | Owner and upgrade rule |
| --- | --- | --- | --- |
| Typed validation before explicit execution | WebAssembly Core 2.0 release 2025-09-16, structure/validation/execution/numerics: https://webassembly.github.io/spec/versions/core/WebAssembly-2.0.pdf | Adopt complete rules and embedding separation. Exclude its overflow/division choices, unrestricted control/memory and compatibility/runtime dependency. | Kernel/compiler/Runtime; local laws and tests decide changes. |
| Distinct authoring, typed meaning, semantic IR and private execution | MLIR Rationale, retrieved 2026-09-06: https://mlir.llvm.org/docs/Rationale/Rationale/ | Corroborates staged representations; not justification for every phase becoming a public artifact or for MLIR dependency. Source is not commit-pinned and is non-load-bearing corroboration. | Compiler; local preparation/artifact counterexamples carry the decision. |
| Compatibility labels vs pre-release evolution | SemVer specification 2.0.0: https://semver.org/spec/v2.0.0.html | Adopt truthful public compatibility communication when there is a public contract. Do not infer a need for an internal graph solver or permission to misidentify changed content. | Product/release owner; reconsider for real v1 consumers. |
| Exact build attribution | Reproducible Builds definition, retrieved 2026-09-06: https://reproducible-builds.org/docs/definition/ | Adopt explicit inputs/environment and reproducible output scope; it does not require permanent retention of every internal artifact. Current-page corroboration, not local authority. | Build/provenance; no new dependency. |

Local semantic arguments are more specific than these analogies. Exact-int64 counterexamples disprove unsafe algebraic elimination. Noncommutative fold disproves unspecified parallel regrouping. Compiler alias breakage disproves treating frozen containers as sufficient preparation isolation. Changed-build-label Runtime evidence shows a binding cost, not a current correctness bug. The versionless probe's shim prevents a claim of completed production version removal. Two collection evaluators share admission/meter, so agreement is not independent bootstrap evidence.

## 12. Claims, axes and completion boundaries

| Claim | Evidence state | Structural decision and falsifier | Remaining gate |
| --- | --- | --- | --- |
| C1 current graph removes observed composition obstruction | confirmed-narrowly | D1/E1; one current capability disappears or conflict persists | S2 full current corpus/public path. |
| C2 SemVer selection is not essential to the selected dependency problem | confirmed-narrowly | D1/E2; versionless nominal/recursive closure admits ambiguity | S3 no-shim production gate. |
| C3 semantic/provenance split reduces unnecessary change amplification | confirmed-narrowly | D2/D3/E2; an excluded dependency changes behavior without identity/refusal | S5a complete runtime dependency cut, followed by mandatory S5b deletion. |
| C4 one semantic preparation can replace repeated work | confirmed-narrowly | D5/E5; specialization or mutation changes artifacts/diagnostics | S4 explicit alias-free projection and artifact admission. |
| C5 proposed basis is sufficient for all current product requirements | open | R1/D6; any mapped row requires hidden host semantics | S6–S9 plus full G-X, not the small prototype. |
| C6 current four-layer one-context topology remains appropriate | theory-supported plus current layer tests | D4–D8; distinct model authority or reciprocal dependency needed | Updated layer/subsystem gate and real change-surface review. |
| C7 dead sink removal preserves current public observations | confirmed-narrowly | D8/E6; actual user or registered result changes | S1 CI and installed resource check. |
| C8 full new architecture is conformant/production proven | non-claim | No disposable probe can establish this | S11 and the applicable explicit acceptance/activation gates. |

Abstraction: typed source/semantic/public/private boundaries survive; hidden host defaults/aliases are targeted. Completeness: all captured requirements have owners and observable gates, while actual genre/continuous/evaluation coverage remains open. Orthogonality: current-graph composition and provenance mutation provide local evidence; full state/event/collection cross-products remain gates. Extensibility: progression+periodic demonstrates package composition, not the promised out-of-family nested-priority invariant. Consistency: one authority map and an explicit reconciliation ledger replace duplicate versions. Reliability: necessary integrity/atomicity/independent verification remain. Operability: public CLI/HTTP, installed wheel, source migration, session invalidation and consumer rollback are explicit gates.

This plan is the accepted execution record under bADR-0028, not a peer machine specification. `reconciliation.md` identifies the affected owners and completed documentation amendments; the tracker index identifies implementation owners. [Evidence](EVIDENCE.md) preserves bounded conclusions and reproduction receipts. A complete plan can enumerate open production gates; implementation and formal claim completion require their actual evidence and activation conditions.
