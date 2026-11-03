---
status: accepted
---

# Use one Metrics schema and immutable evidence for evaluation, calibration, and approval

> **Partial supersession (2026-09-06, [bADR-0028](0028-current-language-refactor-and-pre-1.0-retirement.md)):**
> bADR-0028 requires removal of irrelevant whole-LDB/Build-receipt execution and
> semantic-comparison bindings after closing actual execution inputs. Truthful content and
> producing provenance, evaluation intent, observations, comparison scope, and approval
> ownership remain. This does not activate #542–#544: their existing concrete-application trust
> conditions still govern authenticated receipt-backed claims. Functional Replay, comparison,
> gameplay, and refactor slices may finish with candidate/open results. #509 retains the
> unresolved simulation-policy decision.

The balancing toolkit must compare predicted behavior with future playtest observations without
inventing two meanings for the same metric. A simulation-only report shape would force adapters,
weaken calibration provenance, and violate the product requirement that simulated and observed
results round-trip through one Metrics schema.

Calibration also needs more than an optimizer and confidence interval. Without a declared
observation model, parameter identifiability, model discrepancy, replication unit, correlation
structure, frozen holdout, multi-objective policy, and data-drift handling, two evaluators can call
different results “calibrated.” Finally, a mutable lifecycle status cannot prove which exact model,
data, runtime, and policy passed each gate. PRD #534 therefore fixes one metric contract and an
append-only evidence graph.

> **Amendment (2026-08-03, #594):** Experiment scenarios own bounded executable Event plans. Their
> observation Events are derived from exact Observation/Metric contracts, and run/evidence
> artifacts bind the admitted root-reference map, complete Event ordering keys, logical windows,
> terminal condition, and Runtime profile rather than treating an authored scenario as one step.

> **Amendment (2026-08-04, #596):** Event trace records each Runtime Formula evaluation with exact
> evaluation-site, binding, Formula and Operation identities, slot/context, ordered arguments,
> result, immutable frame identity and call path. Periodic schedule rows carry the generated child
> Event id, call-site/parent provenance, ordering key, Effect-instance value and captured arguments;
> child Events and Snapshots close the resulting state chain. A terminal audit's committed prefix
> uses the same Event schema and a refusing Formula Event identifies its exact evaluation site.
> Metric datasets and Evaluation/reproduction artifacts bind these trace/Snapshot/Runtime-profile
> identities instead of copying Effect or Formula authority into evidence artifacts.

> **Amendment (2026-08-24, #545):** The first public exact Replay slice accepts an authenticated
> producing outcome whose primary member is an `evaluation-run`. An `experiment-verdict` or Runtime
> refusal is not an Evaluation run and is not eligible for this initial Replay comparison. This is
> an initial delivery boundary, not a permanent prohibition. A future application can define an
> explicit outcome-comparison contract without relabeling a Verdict or refusal as an Evaluation run.
> The Replay comparison records the complete ordered result of `exact-replay-v1`. Its first check is
> the Evaluation outcome status: `accepted` or `rejected`. A match publishes the new Evaluation run.
> A mismatch publishes the complete Replay observations without requiring an `evaluation-run` or
> `experiment-verdict` member and without relabeling either outcome. The mismatch is a completed
> negative Verdict. A match returns `claim_state: candidate` in the command result, but the
> comparison artifact contains only comparison facts. It carries no Evidence claim.
> `standard.experiment@1.1.0` owns `exact-replay-v1` under the Kernel-admitted
> `language.replay_comparison_policies` collection. Domain Comparison semantics consumes the exact
> admitted definition, complete authenticated observation inputs, and no ambient store state. It
> produces and independently validates the Replay comparison. Artifact policy owns set publication;
> Evidence validation only consumes an already published comparison.

## Decision

- **One Metrics schema represents both simulated and observed samples.** Every Metric definition
  declares stable identity; Quantity type and unit; dimensions; observation window; aggregation;
  replication semantics; and missing/censoring behavior. Every Metric sample carries that
  definition identity, typed value or explicit missing/censored state, logical time/window,
  dimension values, replication identity, source kind, and provenance. `simulated` and `observed`
  are source-kind values only; they cannot alter type, unit, dimension, or aggregation semantics.

- **Metric datasets are immutable and content-addressed.** A dataset binds exact Metric-definition
  and Experiment-Specification identities, source/build provenance, data version, partition,
  samples, ordering/canonicalization law, and any ingestion transformation identity. A corrected or
  extended dataset receives a new identity. Sentinel values cannot stand for missingness,
  censoring, refusal, or infinity.

- **The Experiment Specification owns evaluation and statistical intent.** It declares scenarios,
  one-time model initialization, bounded external-input/transition-invocation root Event plans,
  Metric definitions, sampling plan, replication unit, correlation clusters,
  Observation model, model-discrepancy treatment, parameter space and constraints, objectives,
  acceptance rule, estimator policy, train/holdout partition, and drift policy. The Resolved Model
  exports typed state/events/outputs; it does not own targets or post-hoc acceptance criteria.

- **Experiment inputs, selectors, Event plan, and acceptance are executable contracts.** A
  one-time assignment is checked against the canonical union of the selected entrypoints' exact
  Resolved Model-symbol targets. A transition-invocation payload is checked against its separately
  derived Event-local contract, while external facts are checked against their typed source
  contract. Every authored root member has a unique `root_event_ref`; observation members are
  derived from the exact Metric/Observation contracts and cannot choose another Runtime phase. An
  assigned value is checked against the exact-bound Resolved Model symbol's representation,
  nominal kind, unit, support/domain, and Numeric profile before dispatch. Metric selectors and
  acceptance use closed LDB-governed expressions with normative typing, ordering, empty-selection,
  missing-Metric, and identity laws. An empty selector set is legal only when the Experiment permits
  zero Metrics and acceptance does not depend on a missing observation. A host scenario branch,
  post-hoc selector, or fixed `satisfied` result cannot replace these authored semantics.

- **An Evaluation run records execution facts without deciding success.** It binds the exact
  Resolved Model, Experiment Specification, Resolved Runtime profile, evaluator build, effective seed and
  Named random streams, external-input identity, root-reference admission map, ordered
  trace/snapshots with complete ordering and parent/child/cancellation provenance, declared logical
  windows and terminal condition, terminal status, and produced Metric dataset. A runtime refusal
  instead produces bADR-0014/0015's separately typed,
  atomically published terminal-audit artifact set; it cannot produce a completed Evaluation-run
  success artifact or Metric dataset.

- **Calibration requires an explicit Observation model.** The model specifies how latent simulated
  metrics map to observed data, including measurement error/noise, missing and censoring mechanism,
  replication unit, within/between-cluster correlation, and model discrepancy. These choices are
  fixed before fitting and identified in every Calibration report; an evaluator cannot infer a
  favorable model silently from the observed dataset.

- **A Calibration report is complete even when the conclusion is negative or inconclusive.** It
  records exact model, experiment, training data, Evaluation runs, estimator and version,
  parameter constraints/priors, identifiability analysis, discrepancy/noise assumptions,
  correlation handling, convergence diagnostics, parameter uncertainty, sensitivity, objective
  values, and candidate identities. Failure to meet predeclared statistical acceptance is a
  negative Verdict, not missing output.

- **Identifiability and replication are first-class gates.** A policy states acceptable structural
  or practical identifiability, effective sample size, convergence, and uncertainty thresholds.
  Samples sharing a declared player, session, encounter seed, run, or other replication cluster are
  not treated as independent. If required information is absent or computation is undefined, the
  command returns an `evaluation` refusal; if analysis completes but evidence is inadequate, it
  returns an exit-1 Verdict.

- **Multi-objective acceptance is predeclared and deterministic.** The Experiment Specification
  chooses conjunctive thresholds, a versioned scalarization, or a versioned Pareto acceptance rule,
  including direction, weights/tolerances, uncertainty treatment, and tie-breaks. Objectives cannot
  be selected, dropped, or reweighted after seeing candidate or holdout results without producing a
  new Experiment Specification identity.

- **Holdout partitions are frozen before calibration.** Partition membership is content-addressed
  and cannot participate in fitting, hyperparameter selection, stopping, or objective choice.
  Holdout verification references the chosen candidate and reports every declared objective under
  the same Observation model. Passing produces a `holdout_verified` Evidence assertion; failing or
  inconclusive verification is a Verdict and produces no positive assertion.

- **Data drift affects eligibility through a typed Evidence assertion, never mutation.** A Drift
  assessment is an Evidence-assertion subtype whose policy declares
  compared distributions/metrics, windows, tests, multiplicity/tolerance, and action threshold. A
  new data version or beyond-policy Drift assessment does not rewrite a historical Calibration
  report or Holdout-verification assertion; it makes that assertion ineligible as a prerequisite
  for a later approval and requires recalibration/reverification under new identities.

- **Progress is an immutable evidence graph, not a mutable state field.** Claims such as
  `well_typed`, `resolved`, `evaluable`, `reproducible`, `cross_evaluator_conformant`, `calibrated`,
  and `holdout_verified` are separate Evidence assertions. Each names the exact subject artifacts,
  policy, tool/evaluator, and prerequisite assertions. A later assertion can depend on earlier ones
  but cannot upgrade them in place. `approved` exists only as an Approval Record in its governance
  authority domain.

- **Evidence claim kinds form a closed LDB-owned registry.** The Evidence assertion schema names an
  admitted claim-kind identity whose LDB entry fixes subject types, required prerequisite graph,
  eligibility judgment, permitted issuer/verifier class, and positive/negative vectors. Domain
  packages may provide subject artifacts and package-specific policies, but they cannot mint new
  claim labels or weaken a registered prerequisite. Adding or changing a claim kind is a versioned
  LDB change; unknown strings and package-local aliases are `evaluation` refusals. `approved` remains
  excluded because governance belongs only to Approval Record authority.

- **Evidence issuance is a validated judgment, never a side effect of successful serialization or
  execution.** Before issuing an assertion, its command validates the closed Experiment, Metric,
  dataset, Evaluation-run, evaluator/tool, policy, and prerequisite-assertion schemas plus their
  identity graph and semantic compatibility. `well_typed` requires the exact successful static
  judgment and language identity; `resolved` additionally requires a closed Package Lock,
  Capability manifest, and RIR; `evaluable` requires a valid Experiment/Metric contract and admitted
  Runtime/evaluator profile. Missing dimensions, type/unit mismatch, unknown policy, unverified
  subject identity, or absent prerequisite is an `evaluation` refusal and emits no positive
  assertion.

- **`reproducible` requires a Replay comparison.** A positive comparison that is eligible for this
  claim binds at least two exact Evaluation runs with the same complete reproduction identity,
  including an identical Resolved Runtime profile. It also binds the ordered policy check keys, the
  policy-wide comparator, ordered check results, and comparison-tool identity.
  One successful run, a replay request, cross-evaluator agreement, or byte-equality observed only
  inside a test cannot issue `reproducible`. The assertion is emitted only when the comparison
  completed positively and all prerequisite `resolved`/`evaluable` assertions verify; mismatch is a
  completed negative Verdict, while missing/incompatible inputs are an `evaluation` refusal. A
  negative comparison can bind one original Evaluation run and the complete observations from a
  Replay that ended with `rejected`; it cannot issue `reproducible`.

- **Independent-evaluator agreement is a separate Evidence claim.** A Cross-evaluator comparison
  binds two or more evaluator/platform-specific Resolved Runtime profiles, their exact common Kernel
  Specification, Language Definition Bundle, Package Lock, Resolved Model/RIR semantic payload,
  Runtime profile definition,
  Experiment Specification, external inputs, effective seed, exact LDB-owned Portable Observation
  Policy, generated Resolved Portable Observation Plan,
  observations, mismatches, and comparison-tool identity. Only a positive, independently validated
  comparison may qualify a separately issued `cross_evaluator_conformant` assertion. It never
  satisfies `reproducible`; incompatible
  authority/profile/policy inputs are an `evaluation` refusal and observed mismatches are a completed
  negative Verdict.

- **Portable observation has one policy and one resolved plan.** The exact LDB-owned Portable
  Observation Policy defined by bADR-0014 owns the selector grammar, mandatory classes,
  projection/comparator mapping, and deterministic closure/order algorithm. That algorithm derives
  a Resolved Portable Observation Plan from the common profile, selected Lock/RIR, exact Experiment,
  and selected vectors; the plan enumerates every required semantic selector without copying or
  replacing Experiment authority. The comparison binds both identities plus both complete
  observation sets and emits ordered field-level match, mismatch, missing, and unexpected results.
  Empty or under-covering policies/plans, widened tolerances, unknown selectors, and caller-selected
  subsets are refusals; actual value disagreement is a negative Verdict. A positive comparison is
  therefore impossible when a required outcome, state, ordering, RNG, Effect, Metric, refusal, or
  terminal-audit observation was omitted.

- **Comparison artifacts are Evidence inputs, never Evidence assertions.** A Replay comparison
  binds its original Evaluation run and either the matching new Evaluation run or the complete
  observations from a mismatch. A Cross-evaluator comparison binds its exact Evaluation runs. Both
  comparison kinds bind the applicable profiles, authorities, model, Experiment, Scenario/external
  inputs, policy, observations, and typed result. They do not embed `reproducible`,
  `cross_evaluator_conformant`, or another positive Evidence claim. A separate Evidence-eligibility
  judgment validates the comparison and every prerequisite before issuing an assertion;
  serialization success or a matching boolean cannot bypass that judgment.

- **Approval binds exact evidence.** An Approval Record references the precise Resolved Model,
  Experiment Specification, Resolved Runtime profile/evaluator, Metric datasets, Evaluation runs,
  Calibration report, Holdout-verification and Drift-assessment assertions, approval policy, and
  attestation.
  A naked `approved: true`, branch label, or mutable dashboard state is not approval evidence.

- **Outcome classification follows bADR-0015.** Missing required metrics, incompatible dimensions,
  invalid dataset shape, undefined observation mapping, or non-computable evaluation is an
  `evaluation` refusal. A completed evaluation that misses targets, lacks sufficient evidence, is
  non-identifiable under policy, or fails holdout is an exit-1 Verdict. Evidence assertions are
  emitted only for positive gates.

- **Live telemetry ingestion is deferred, not forked.** This decision fixes the observed-data
  artifact and statistical contract. Transport, consent/privacy, collection SDKs, and live
  ingestion operations are outside this design slice. When ingestion lands, its canonical output
  must be the same Metric dataset shape and carry transformation provenance.

## Considered options

- **One typed Metrics schema plus source provenance** (chosen) — comparisons and calibration operate
  on identical metric meaning without adapters.
- **Separate simulation and telemetry reports** (rejected) — duplicates type/aggregation semantics
  and moves reconciliation into unversioned ingestion glue.
- **Mutable calibration/approval status on the model** (rejected) — loses exact evidence and lets a
  data or policy change rewrite history.
- **Optimizer output as Calibration report** (rejected) — omits observation noise, identifiability,
  discrepancy, correlation, uncertainty, holdout, and acceptance semantics.
- **Random holdout selected after fitting** (rejected) — leaks model-selection information and
  cannot be audited independently.
- **Treat inadequate evidence as refusal** (rejected when analysis completed) — the judgment is a
  valid negative/inconclusive answer; refusal is reserved for inability to perform it.
- **Treat historical evidence as deleted by drift** (rejected) — destroys audit history; eligibility
  changes through a new linked assessment instead.

## Consequences

- Metric definitions, datasets, Evaluation runs, Calibration reports, Drift assessments, Evidence
  assertions, and Approval Records need canonical schemas and content-identity laws.
- The RPG/Roguelike tracer can close its final coverage rows by emitting an Evaluation run and the
  same Metric dataset shape future observed playtests will use.
- Calibration implementations must expose statistical assumptions and diagnostics rather than
  returning only tuned parameters.
- Approval tooling becomes graph validation over immutable artifacts and current policy, not a flag
  update.
- Migration must state whether and how 1.x reports or future legacy telemetry become 2.x datasets;
  unproven provenance cannot be invented.

## Validation

- Validate closed Experiment, Metric definition/sample/dataset, Evaluation run, evaluator/tool,
  Evaluator Capability Manifest, policy, Evidence assertion, Replay comparison,
  Cross-evaluator comparison, and prerequisite-graph
  fixtures before issuing any assertion; add negative vectors for extra/missing fields,
  kind/unit/dimension mismatch, bad aggregation, unknown policy, identity mismatch, and absent
  prerequisite.
- Bind one Experiment exactly to a Resolved Model and refuse it against a different wrapper even
  when both wrappers carry the same RIR semantic payload. Exercise input support boundaries,
  selector ordering and empty selection, missing selected Metrics, acceptance type/result changes,
  and every identity mutation before Evaluation issuance.
- Run an exact replay under one identical Resolved Runtime profile. Assert its positive Replay
  comparison can qualify a separately issued `reproducible` assertion, mismatch returns a Verdict
  with field diagnostics, and a single run or mere replay intent cannot issue it.
- Run a second independent evaluator under its distinct Resolved Runtime profile. Assert only a
  positive Cross-evaluator comparison under the exact LDB-owned Portable Observation Policy and its
  Resolved Portable Observation Plan can
  qualify a separately issued `cross_evaluator_conformant` assertion, and that it cannot issue
  `reproducible`.
- Attempt `cross_evaluator_conformant` with an empty policy/plan, an omitted required observation,
  an unknown/duplicate selector, a widened Float tolerance, a caller-filtered observation set, or
  an Evaluator Capability Manifest that lacks one required law. Evidence issuance must refuse;
  observed semantic mismatch must remain a negative Verdict with no positive assertion.
- Attempt to issue an unknown, package-invented, or incompletely registered Evidence claim kind.
  Require a typed `evaluation` refusal; adding a claim kind must change the owning LDB identity and
  supply its complete eligibility and vector contract.
- Forge or omit a comparison binding, reidentify the artifact, or add an inline Evidence claim.
  Independent validators must refuse the comparison or Evidence issuance; only a separately issued
  assertion may carry `reproducible` or `cross_evaluator_conformant`.
- Inject a runtime refusal after committed events; assert only the terminal-audit artifact set is
  atomically visible and no Evaluation run, Metric dataset, or positive Evidence assertion exists.
- Mutate an evaluator, Resolved Runtime profile, Experiment, Metric definition, seed/stream, policy, or input
  identity and assert the evidence graph rebinds to the new identity or refuses stale reuse.

## References

- PRD #501 — shared simulated/observed Metrics schema requirement.
- PRD #534 — Standard Schema 2.0 language, runtime, and evidence architecture.
- bADR-0012 — authored authority domains and Approval Record.
- bADR-0014 — Runtime profile definitions, Resolved Runtime profiles, and deterministic identity.
- bADR-0015 — invocation outcomes, refusals, and Verdicts.
- bADR-0017 — genre coverage and Golden scenarios.
