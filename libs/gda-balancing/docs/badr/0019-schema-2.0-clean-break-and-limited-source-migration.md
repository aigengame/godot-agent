---
status: accepted
---

# Make Schema 2.0 the clean baseline and limit migration to safe source conversion

The initial migration proposal covered saves, active effects, scheduled events, replays, old
rulesets, shadow execution, cohorts, rollback, and reverse migration. Those mechanisms are justified
when published artifacts or live games depend on the old contract. The maintainer confirmed that
gda-balancing has published no Standard Schema product artifacts and carries little historical
compatibility burden. Designing a production compatibility subsystem now would spend complexity on
states that do not exist and would constrain the 2.0 model before its tracer is implemented.

Standard Schema 1.x remains useful design history and current implementation input, but it is not a
released compatibility line. PRD #534 therefore adopts 2.0 as the sole forward standard and keeps
only a narrow, semantics-preserving source-conversion opportunity.

## Decision

- **Standard Schema 2.0 is a clean forward baseline.** New templates, models, experiments,
  evaluators, metrics, evidence, and approvals target 2.x. There is no promise that a 2.x compiler
  or runtime accepts a 1.x Design document, report, save, event log, or ruleset. This Schema-major
  decision remains independent from the `gda-balancing` package version.

- **Compatibility work is limited to authored 1.x Design-document source.** A deterministic,
  one-shot converter may map declarations whose 2.x meaning is demonstrably equivalent into a new
  Model Source Package. Repository fixtures and unfinished template sources may use the same path.
  The converter is a convenience for pre-release work, not an acceptance prerequisite for 2.0.

- **A source construct has only two outcomes: migrated or deprecated.** `migrated` requires a
  semantics-preserving mapping with explicit destination identities. Anything ambiguous, lossy,
  dependent on removed defaults, or lacking an equivalent type/operation is a Deprecated 1.x
  construct. There is no automatic lossy tier, interactive patching inside the converter, or
  “mostly migrated” success.

- **Unsupported conversion is a typed `migration` refusal.** The converter emits a Migration report
  that binds input identity, the complete LDB-validated `source-converter-specification` artifact,
  Language Definition Bundle identity, successful mappings, deprecated constructs, stable
  diagnostics, and remediation text. The embedded converter artifact makes its identity
  independently retrievable and rehashable; an opaque digest is insufficient. If any construct is
  deprecated, the command emits no authoritative 2.x Model Source Package. The user
  re-authors/removes the construct and runs normal 2.x validation. The successful
  `migration-report` and Model Source are one atomic success artifact set. The refusal form is a
  separately typed, LDB-validated `migration-refusal-report` carried in the exit-2 envelope; it is
  not a command success artifact, partial Source, or post-runtime terminal-audit set.

- **Exact source identity has an explicit bounded observation contract.** Migration accepts only a
  regular file whose complete byte stream is at most 16 MiB. One pass hashes that complete stream
  while retaining only the Standard Schema 1.x funnel's bounded parse prefix. Non-regular inputs
  and files beyond the observation cap fail as `unreadable_input` before any exact input identity
  or migration report is claimed. A source above the 1.x 10 MiB document cap but within the
  observation cap still receives the normal typed migration refusal bound to its exact bytes.
  The generated candidate is canonicalized before success and must fit both LDB target bounds:
  `max_source_bytes` and `max_symbols`. Exceeding either is a typed migration refusal, never an
  internal error or partial Model Source publication.

- **Migration never mutates input or invents provenance.** A successful conversion emits a new
  Model Source Package identity plus its Migration report. Original source remains byte-identical.
  Missing authorship, units, kinds, roles, package dependencies, or operation semantics cannot be
  inferred from evaluator behavior and recorded as fact.

- **Runtime compatibility artifacts are explicitly out of scope.** No 1.x save-state migration,
  active-effect mapping, scheduled-event conversion, replay/event-log conversion, old-ruleset
  runtime adapter, dual authoritative state, shadow/gray rollout machinery, reverse migration, or
  rollback protocol is designed. No such published artifact exists to preserve. If a real consumer
  appears before 2.0 implementation, that new evidence requires a separate decision rather than
  speculative hooks in this design.

- **1.x evidence cannot satisfy 2.x gates.** Existing test output or unpublished reports may be
  retained as historical provenance, but they cannot become a 2.x Metric dataset, Evaluation run,
  Calibration report, Evidence assertion, or Approval Record without re-execution under exact 2.x
  artifacts and contracts.

- **The implementation transition is replace-then-remove, not dual-stack compatibility.** The first
  2.x RPG tracer lands end to end alongside only the minimum current code needed to compare and
  replace it. Once the tracer covers the public path, superseded 1.x implementation and fixtures are
  removed or rewritten rather than maintained as a permanent compatibility runtime.

- **Historical bADRs remain provenance, not competing forward requirements.** New 2.x bADRs state
  exactly which 1.x decisions they retain or supersede. The old records remain readable so the
  design evolution is auditable, but implementation issues must target the 2.x decisions and may
  not invoke 1.x compatibility as an unstated acceptance criterion.

## Considered options

- **Clean break plus best-effort source conversion** (chosen) — preserves cheaply recoverable
  authored work without imposing runtime compatibility for artifacts that were never published.
- **Full source/save/replay/ruleset migration** (rejected) — solves a nonexistent deployed-state
  problem and hardens premature runtime interfaces.
- **No converter at all** (rejected as a blanket rule) — some simple declarations can be mapped
  deterministically at low cost; allowing that convenience does not create a compatibility promise.
- **Lossy conversion with warnings** (rejected) — produces a valid-looking 2.x model whose behavior
  may have changed and transfers an unreviewable burden to later evidence.
- **Permanent 1.x/2.x dual runtime** (rejected) — doubles authority and conformance surfaces before
  the product has external consumers.
- **Schema 2.0 implies package 2.0.0** (rejected) — Schema and product release versions remain
  independent under bADR-0001/0012 and repository release policy.

## Consequences

- The 2.0 specification can choose coherent type, package, runtime, and evidence contracts without
  reserving compatibility holes for unpublished 1.x runtime artifacts.
- Migration acceptance tests cover exact source mappings and explicit deprecation/refusal only.
- Save, effect-instance, replay, gray-rollout, and reverse-migration tests are not required by #534.
- Existing template/simulation implementation issues must be re-triaged against the 2.x tracer and
  may be closed or rewritten rather than adapted mechanically.
- A future compatibility demand requires evidence of a real published consumer and a new bADR; it
  is not smuggled into Domain packages or evaluators as an optional fallback.

## References

- PRD #534 — Standard Schema 2.0 language, runtime, and evidence architecture.
- bADR-0012 — Model Source Package authority and artifact identities.
- bADR-0015 — `migration` refusal stage and diagnostics.
- bADR-0017 — template instantiation and explicit future template upgrades.
- bADR-0018 — 2.x evidence-chain identity requirements.
