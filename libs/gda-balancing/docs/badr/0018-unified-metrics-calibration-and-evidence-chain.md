---
status: accepted
---

# Use one Metrics schema and immutable evidence for evaluation, calibration, and approval

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
  model inputs, Metric definitions, sampling plan, replication unit, correlation clusters,
  Observation model, model-discrepancy treatment, parameter space and constraints, objectives,
  acceptance rule, estimator policy, train/holdout partition, and drift policy. The Resolved Model
  exports typed state/events/outputs; it does not own targets or post-hoc acceptance criteria.

- **An Evaluation run records execution facts without deciding success.** It binds the exact
  Resolved Model, Experiment Specification, Resolved Runtime profile, evaluator build, effective seed and
  Named random streams, external-input identity, ordered trace/snapshots, terminal status, and
  produced Metric dataset. A runtime refusal instead produces bADR-0014/0015's separately typed,
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
  `well_typed`, `resolved`, `evaluable`, `reproducible`, `calibrated`, and `holdout_verified` are
  separate Evidence assertions. Each names the exact subject artifacts, policy, tool/evaluator, and
  prerequisite assertions. A later assertion can depend on earlier ones but cannot upgrade them in
  place. `approved` exists only as an Approval Record in its governance authority domain.

- **Evidence issuance is a validated judgment, never a side effect of successful serialization or
  execution.** Before issuing an assertion, its command validates the closed Experiment, Metric,
  dataset, Evaluation-run, evaluator/tool, policy, and prerequisite-assertion schemas plus their
  identity graph and semantic compatibility. `well_typed` requires the exact successful static
  judgment and language identity; `resolved` additionally requires a closed Package Lock,
  Capability manifest, and RIR; `evaluable` requires a valid Experiment/Metric contract and admitted
  Runtime/evaluator profile. Missing dimensions, type/unit mismatch, unknown policy, unverified
  subject identity, or absent prerequisite is an `evaluation` refusal and emits no positive
  assertion.

- **`reproducible` requires a Replay comparison.** The immutable comparison binds at least
  two exact Evaluation runs or independent-evaluator observations, their complete reproduction
  identities, the declared comparable fields, canonicalization/tolerance policy, field-level
  matches/mismatches, and comparison-tool identity. One successful run, a replay request, or
  byte-equality observed only inside a test cannot issue `reproducible`. The assertion is emitted
  only when the comparison completed positively and all prerequisite `resolved`/`evaluable`
  assertions verify; mismatch is a completed negative Verdict, while missing/incompatible inputs are
  an `evaluation` refusal.

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
  policy, Evidence assertion, Replay comparison, and prerequisite-graph fixtures before issuing any
  assertion; add negative vectors for extra/missing fields, kind/unit/dimension mismatch, bad
  aggregation, unknown policy, identity mismatch, and absent prerequisite.
- Run an exact replay and a second independent evaluator, producing a Replay comparison
  that names every compared field. Assert positive comparison can issue `reproducible`, mismatch
  returns a Verdict with field diagnostics, and a single run or mere replay intent cannot issue it.
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
