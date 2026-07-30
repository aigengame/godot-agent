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

- **Standard Schema 2.x has one layered machine-authority chain.** The non-self-hosted
  **Schema-major Kernel Specification** defines how Language Definition Bundles are admitted and
  interpreted, including the bundle meta-format, irreducible Semantic-kernel laws, and the
  meta-diagnostics needed to admit or reject a bundle. Under one exact Kernel Specification, the
  immutable, versioned **Language Definition Bundle** is the sole post-admission language-content
  authority and defines:
  - grammar and wire-shape definitions;
  - type constructors, name-resolution and typing rules;
  - versioned operation specifications and their semantic contracts;
  - stable post-admission diagnostic-code definitions;
  - package manifests, capabilities, dependencies, and compatibility rules.
  bADR-0022 fixes the Kernel-Specification boundary, canonical bundle, structured-rule meta-format,
  Semantic kernel, and conformance boundary. bADR-0023 fixes the LDB's physical and identity form:
  one sealed root manifest plus complete content-addressed package members constitute one exact
  artifact graph, while post-admission flat indexes are derived non-authorities. A host compiler,
  evaluator, bootstrap interpreter, or reference implementation conforms to this chain; its source
  code is never another authority.
  Field-level wire projections remain generated implementation artifacts.

- **Every other language-description surface is a projection or a conforming implementation.**
  Structural schemas, semantic rule catalogs, registries, evaluator tables, documentation
  projections, and language-bound fields referenced by Command descriptors are generated from the
  Language Definition Bundle where practical. The Command descriptor still owns command-surface
  input/outcome/artifact shape under bADR-0021. Where direct generation would distort the target
  representation, a conformance test proves agreement with the Kernel Specification and bundle. A
  hand-maintained peer language definition is prohibited.

- **Authored facts are divided into three non-overlapping authority domains:**
  1. The **Model Source Package** is the sole editable authority for a game's model definitions and
     declared dependency requirements. It contains an authored manifest, model modules, symbols
     with value policies, and Model entrypoints that bind those symbols to exact LDB Operation
     interfaces.
  2. The **Experiment Specification** is the authority for scenarios, model inputs, metrics,
     targets, observation/calibration policy, and other evaluation intent. Each scenario selects a
     Model entrypoint and totally assigns its generated Scenario Input Contract. It references an
     exact resolved-model identity or an explicit compatibility contract and cannot redefine the
     model, select a raw LDB Operation, or invent a model input.
  3. The **Approval Record** is the immutable governance authority for one approval decision. It
     binds the exact model, experiment, evidence, evaluator, policy, and attestation identities and
     cannot mutate or copy their owned facts.
  “Sole authority” is always qualified by one of these domains; there is no honest global authored
  source of truth.

- **Generated build artifacts have execution authority, not authoring authority.** A **Package
  Lock** is the generated selected-transitive-closure result of resolving the Model Source
  Package's requirements under the Language Definition Bundle's compatibility rules. A canonical
  **RIR semantic payload** is the reachable semantic normal form. A **Resolved Model** is the
  immutable wrapper binding that payload to the exact Kernel, whole LDB, and Lock identities. The
  wrapper is the execution authority for the exact build it represents, but none of these generated
  artifacts may be edited as a substitute for source. A complete content-addressed Domain package
  release is one root-declared child in the sealed LDB graph, never an ambient peer registry.

- **Artifact identity is independent of storage and transport.** Every public artifact has a closed
  envelope that binds its artifact kind, wire-schema identity, content identity, and normative
  payload. A Locator identifies a retrieval mechanism; a Receipt proves a publication and may bind
  a Locator, but neither paths nor transport metadata enter content identity. Retrieval revalidates
  the envelope, schema identity, and content hash. A consumer must rehash the exact Kernel
  Specification, Language Definition Bundle, lock, RIR, profile, and other authority artifacts it
  consumes; comparing only their claimed identity strings is non-conforming. Missing, mismatched, or
  tampered artifacts are typed refusals rather than implementation fallbacks. A host implementation,
  candidate utility, or conformance harness cannot define its own Standard Schema 2.x canonical
  encoding, identity domain/algorithm, or wire-schema identity. Those facts come from the permanent
  Kernel/LDB and applicable artifact-schema authorities, or the implementation is exhaustively
  reverse-conformance checked against those exact artifacts. Before those authorities exist, a
  locally hashed envelope is research data, not a permanent Schema artifact.
  An Artifact Contract is the sole identity-domain authority for its artifact schema. A
  non-artifact Wire-Schema definition instead owns its identity domain inline. Admission requires
  exactly one of those authority paths for every Wire Schema, so a host-derived kind-name fallback
  and two competing declarations are both non-conforming. The two irreducible root-authority
  projections have no containing LDB definition or Artifact Contract: the Kernel therefore owns
  the fixed identity domains for the exact Kernel and LDB public Wire Schemas. This root exception
  does not enumerate Domain-package or extension schema kinds in the Kernel.

- **One producing outcome publishes one artifact set.** A success or separately typed terminal-audit
  outcome may stage multiple artifacts, but none is authoritative or discoverable until one
  immutable publication receipt and publication-index anchor commit that complete set. Retrieval
  verifies the anchor, original receipt identity, complete member-identity set, and member bytes.
  The set manifest canonically binds every typed logical member name to its artifact kind,
  wire-schema identity, and content identity; hashing anonymous members or unframed concatenated
  bytes does not bind names/boundaries and is non-conforming. A coherently rewritten
  record/receipt/member set is not the originally committed outcome. A
  terminal-audit set cannot reuse or partially expose a success set. Failure before the selected
  outcome's commit point exposes no member. Store layout, retention, transfer, garbage collection,
  crash recovery, and the concrete index trust boundary are implementation or deployment policies
  only where they preserve this visibility, verification, and identity law. A CLI stdout/stderr
  envelope is emitted after publication and is not part of this cross-transport atomic boundary.

- **References cross domains by identity, never by copied mutable data.** Package locks, resolved
  models, experiments, evidence, and approvals carry content identities for every upstream
  artifact needed to reproduce or audit them. If compatibility-based binding is allowed instead
  of an exact identity, the compatibility contract and the final bound identity are both recorded.
  Downstream artifacts may cache projections for transport, but identity and conflict checks make
  the owning upstream artifact decisive.

- **This bADR owns Claim closure: a claim closes only from verified artifacts, never from a caller
  assertion.** A coverage,
  conformance, Evidence, or approval gate consumes the exact artifacts and prerequisite graph its
  policy names, revalidates their envelopes, content identities, bindings, and applicable
  Kernel/LDB judgments, and derives its result from those verified facts. A request field, research
  mapping, expected-output record, status label, fixture name, or caller-supplied boolean cannot
  declare a row or gate closed. Such data may select a judgment or provide non-authoritative input;
  it never authorizes the judgment's answer. Rehashing proves byte integrity, not that an artifact
  was produced by an independent verifier. Any policy that requires independent verification also
  requires a verifiable **Verifier receipt** whose identity binds the verifier identity, verifier
  implementation and judgment-policy identities, the exact input artifact identities and
  prerequisite graph, and the resulting judgment artifact identity. Before aggregation, the
  consumer must authenticate that receipt, verify every binding, and establish that its verifier
  satisfies the claim policy's independence and trust requirements. If those prerequisites are
  absent or unverifiable, aggregation may publish only `candidate`/open state, never `closed`.
  Concrete signature algorithms, credential systems, and deployment trust topology are left to the
  later security/deployment contract; they may vary only while preserving this identity, binding,
  authenticity, and independence law.

  “Consumes the exact artifacts” requires retrieval and byte rehash of each complete envelope, the
  canonical artifact-set manifest, the resolving publication/retrieval receipt, and every edge in
  the policy's prerequisite graph. Digest-shaped strings copied into multiple payloads are not
  artifact consumption or binding proof. bADR-0015 exclusively owns the closed member and binding
  contract for a terminal-audit artifact set. For a Runtime-refusal prerequisite, the consumer
  validates that complete contract and binds the validated set to the exact vector-result artifact;
  an artifact kind, fixture/vector label, or JSON pointer alone cannot establish that relationship.

- **Gate 2 claim work is dependency-ordered.** The permanent path is:
  1. publish the exact Kernel/LDB plus their canonical-encoding, identity, and applicable
     wire/artifact-schema authorities;
  2. implement bounded, report-all validators for individual envelopes, artifact-set manifests and
     receipts, prerequisite graphs, and complete terminal-audit sets;
  3. authenticate an independent Verifier receipt over those verified inputs and its judgment; and
  4. aggregate the resulting exact, receipt-backed judgments into a claim candidate or closure.
  Each layer consumes only artifacts admitted by the preceding layers and retains the deterministic
  caps, ordering, deduplication, and truncation laws of bADR-0015/bADR-0022. An aggregator built
  before steps 1–3 are permanent is a research utility. It may report `candidate`/open, but it is not
  a permanent Gate 2 sub-slice and cannot confer Schema, coverage, conformance, or Evidence status.

- **Experiment binding is explicit and reviewable.** Exact binding names the Resolved Model
  wrapper, not only its RIR semantic-payload identity, and never follows a rebuilt model to a new
  identity. A changed Resolved Model therefore requires a new Experiment-Specification
  identity or resolution of its declared compatibility contract. Compatibility binding must select
  exactly one Resolved Model before execution and publish a final binding receipt containing the
  selector, resolver identity, selected exact identity, and review disposition. Zero or multiple
  matches are `resolution` refusals; silent or in-place rebinding is prohibited.

- **Invocation authority is a one-way chain.** The LDB Operation is the sole authority for formal
  ports and reusable behavior. Model Source symbols are game-owned actual operands, and a Model
  entrypoint owns their explicit binding to one exact Operation interface. RIR derives the resolved
  call graph and Scenario Input Contract. Experiment assigns only those derived symbol identities.
  No layer copies a peer input declaration or infers a binding from equal names.

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

- **One Kernel Specification/LDB chain plus scoped authored authority domains** (chosen) — closes
  machine semantic drift while keeping model, experiment, and governance ownership honest and
  separately auditable.
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

- bADR-0022 defines the Kernel Specification and the Language Definition Bundle's machine-readable
  rule contract; language registries or schemas must be generated from the bundle or
  reverse-conformance checked against the authority chain.
- The compiler boundary becomes explicit: Model Source Package plus Language Definition Bundle
  resolves dependencies, emits a selected-closure Package Lock and canonical RIR semantic payload,
  and builds an immutable exact-authority Resolved Model wrapper. A Resolution receipt still records
  the exact whole LDB input even when an unused-package edit leaves the Lock unchanged.
- Experiment, evidence, calibration, and approval artifacts must identify exact upstream content;
  mutation produces a new identity rather than changing prior evidence in place.
- Public artifact schemas must define envelopes, content-identity verification, Locators, Receipts,
  and invocation-level artifact-set publication without making one store layout normative.
- Experiment tooling must surface exact rebinding as a new authored or compatibility-resolution
  decision rather than silently following a rebuilt model.
- bADR-0019 limits Standard Schema 1.x migration to semantics-preserving source conversion and
  explicit deprecation; it creates no rollout/compatibility runtime.
- bADR-0013…0022 close the formal-semantics, package, CLI, runtime, evidence, migration, external-
  mapping, and command-surface decisions gated by #534.

## Validation

- Two independently implemented Kernel Specification/LDB consumers must reject the same malformed
  bundle and agree on the same admitted bundle identity, projected inventories, and diagnostics.
- Mutate every consumed authority artifact while retaining its old claimed identity; bootstrap,
  compiler, runtime, evidence, and retrieval consumers must reject before using the changed content.
- Projection conformance enumerates grammar, types, operations, packages, diagnostics, profiles,
  and vectors back to the exact bundle and fails on missing, extra, or changed meaning.
- A multi-artifact fault-injection vector fails after every staging boundary and proves that no
  partial set is retrievable; successful cross-process retrieval verifies every envelope and hash.
  Coherently rewriting stored members plus a reidentified receipt while retaining the committed
  publication-index anchor must also be rejected.
- Reframe, rename, add, remove, or reorder an artifact-set member and independently recompute every
  remaining byte digest. The canonical typed member map and set identity must change or retrieval
  must refuse; an unframed concatenation checksum cannot satisfy this vector.
- Exact-bound Experiments refuse a changed Resolved Model identity even when the RIR semantic
  payload remains equal. Compatibility-bound Experiments cover
  unique, zero-match, and ambiguous resolution and always record the final exact binding receipt.
- Attempt to close coverage, conformance, Evidence, and approval gates with caller booleans,
  research mappings, fixture labels, or expected-output records while omitting or mutating one
  required exact artifact. Every judgment must remain open or refuse; no asserted status may bypass
  artifact retrieval, rehashing, exact binding, or prerequisite validation.
- Rehash a complete claim-input set and attach a self-issued or unauthenticated verifier receipt.
  The bytes may pass integrity checks, but aggregation must remain `candidate`/open until the
  receipt's identity and artifact bindings are verified and its authenticity, independence, and
  policy eligibility are established.
- Give a host utility locally invented canonicalization, identity-domain, or wire-schema constants
  and make every copied digest internally agree. Permanent validation must refuse or classify the
  result as research-only until the exact Kernel/LDB/schema authorities are consumed or reverse
  conformance proves the projection.
- Supply only digest-shaped prerequisite strings, or a Runtime-refusal payload with the expected
  artifact kind/fixture label/JSON pointer but without the resolving set manifest and receipt.
  Validation must report the missing exact artifacts/graph edges; for Runtime refusal it must also
  report every absent or mismatched bADR-0015 terminal-audit binding.
- Exercise the Gate 2 layers out of order. No claim aggregator is admitted as a permanent sub-slice
  until canonical/schema authorities, artifact/set/terminal-audit validators, and the independent
  Verifier-receipt path exist and pass their bounded report-all vectors.

## References

- PRD #501 — balancing toolkit product requirements.
- PRD #534 — Standard Schema 2.0 language, runtime, and evidence architecture.
- bADR-0001 — Standard Schema 1.x Design document structure and versioning.
- bADR-0005 — Standard Schema 1.x self-description and anti-drift contract.
