---
status: accepted
---

# Scope Standard Schema 2.0 authority by language, model, experiment, and approval domains

Standard Schema 1.x deliberately made one root Design document the authored authority and
required a versioned validator beside structural and semantic self-description artifacts
(bADR-0001, bADR-0005). That topology kept a small data schema coherent, but it does not close the
authority chain for Standard Schema 2.0's proposed language, package, compiler, runtime, and
evidence system. Grammar, type rules, operation definitions, schemas, rule catalogs, registries,
evaluator behavior, dependency resolution, scenarios, and approvals could otherwise become peer
sources that disagree while each still appears authoritative.

At the other extreme, calling a Model Source Package the sole authority for everything would be
false. A scenario author, an evaluator, and a governance approver own facts that are not model
definitions. Reproducibility needs those facts independently identifiable without allowing any of
them to redefine another domain. PRD #534 makes closing this chain the first human decision gate.

## Decision

- **The Language Definition Bundle is the sole machine authority for Standard Schema 2.x language
  semantics.** One immutable, versioned bundle defines:
  - grammar and wire-shape definitions;
  - type constructors, name-resolution and typing rules;
  - versioned operation specifications and their semantic contracts;
  - stable diagnostic-code definitions;
  - package manifests, capabilities, dependencies, and compatibility rules.
  bADR-0022 fixes the canonical bundle, structured-rule meta-format, Semantic kernel, and
  conformance boundary; field-level wire projections remain generated implementation artifacts,
  not another authority.

- **Every other language-description surface is a projection or a conforming implementation.**
  Structural schemas, semantic rule catalogs, registries, evaluator tables, documentation
  projections, and CLI self-description are generated from the Language Definition Bundle where
  practical. Where direct generation would distort the target representation, a conformance test
  proves agreement with the bundle. A hand-maintained peer definition is prohibited. An evaluator
  implements the bundle; its source code is not an alternative language specification.

- **Authored facts are divided into three non-overlapping authority domains:**
  1. The **Model Source Package** is the sole editable authority for a game's model definitions and
     declared dependency requirements. It contains an authored manifest and model modules.
  2. The **Experiment Specification** is the authority for scenarios, model inputs, metrics,
     targets, observation/calibration policy, and other evaluation intent. It references an exact
     resolved-model identity or an explicit compatibility contract and cannot redefine the model.
  3. The **Approval Record** is the immutable governance authority for one approval decision. It
     binds the exact model, experiment, evidence, evaluator, policy, and attestation identities and
     cannot mutate or copy their owned facts.
  “Sole authority” is always qualified by one of these domains; there is no honest global authored
  source of truth.

- **Generated build artifacts have execution authority, not authoring authority.** A **Package
  Lock** is the generated result of resolving the Model Source Package's requirements under the
  Language Definition Bundle's compatibility rules. A **Resolved Model** is the immutable,
  content-addressed result of compiling that source with that lock and language bundle. The
  Resolved Model is the execution authority for the exact build it represents, but neither it nor
  the lock may be edited as a substitute for source.

- **References cross domains by identity, never by copied mutable data.** Package locks, resolved
  models, experiments, evidence, and approvals carry content identities for every upstream
  artifact needed to reproduce or audit them. If compatibility-based binding is allowed instead
  of an exact identity, the compatibility contract and the final bound identity are both recorded.
  Downstream artifacts may cache projections for transport, but identity and conflict checks make
  the owning upstream artifact decisive.

- **Schema and product versions remain independent.** “Standard Schema 2.0” identifies the
  language/specification major. It does not imply a `gda-balancing` 2.0.0 release; product version
  changes continue to follow the repository release policy.

- **This decision supersedes only the conflicting 2.x authority portions of earlier bADRs.** For
  Standard Schema 2.x, it supersedes bADR-0001's one-root Design document as the authored model
  authority and bADR-0005's validator-centered semantic-authority topology. Their 1.x contracts
  remain normative for 1.x inputs and migration. bADR-0005's anti-drift principle, structural vs
  semantic honesty, stable rule identifiers, and canonical artifact discipline are retained and
  generalized. Other accepted bADRs remain in force until an explicit 2.x decision supersedes
  them.

## Considered options

- **One language bundle plus scoped authored authority domains** (chosen) — closes machine
  semantic drift while keeping model, experiment, and governance ownership honest and separately
  auditable.
- **Model Source Package as the global sole authority** (rejected) — would either make scenarios
  and approvals hidden model fields or falsely claim that independently authored facts are derived.
- **Validator implementation as the language authority** (rejected for 2.x) — makes semantics an
  implementation detail and prevents independent compilers/runtimes from proving conformance.
- **Peer schemas, registries, operation tables, and evaluator definitions** (rejected) — creates no
  deterministic answer when two descriptions disagree.
- **Resolved Model as editable canonical source** (rejected) — collapses authoring and lowering,
  loses provenance, and makes dependency resolution irreproducible.
- **One combined model-and-experiment package** (rejected) — permits scenario-specific values and
  targets to become accidental model authority, preventing reuse and independent evidence.

## Consequences

- bADR-0022 defines the Language Definition Bundle's machine-readable rule/kernel contract;
  language registries or schemas must now be generated from it or reverse-conformance checked.
- The compiler boundary becomes explicit: Model Source Package plus Language Definition Bundle
  resolves dependencies, emits a Package Lock, and builds an immutable Resolved Model.
- Experiment, evidence, calibration, and approval artifacts must identify exact upstream content;
  mutation produces a new identity rather than changing prior evidence in place.
- bADR-0019 limits Standard Schema 1.x migration to semantics-preserving source conversion and
  explicit deprecation; it creates no rollout/compatibility runtime.
- bADR-0013…0022 close the formal-semantics, package, CLI, runtime, evidence, migration, external-
  mapping, and command-surface decisions gated by #534.

## References

- PRD #501 — balancing toolkit product requirements.
- PRD #534 — Standard Schema 2.0 language, runtime, and evidence architecture.
- bADR-0001 — Standard Schema 1.x Design document structure and versioning.
- bADR-0005 — Standard Schema 1.x self-description and anti-drift contract.
