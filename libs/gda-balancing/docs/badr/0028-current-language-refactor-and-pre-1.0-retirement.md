---
status: accepted
---

# Replace internal release history with one current language and remove redundant execution bindings

> **S1b delivery (2026-09-06, #868):** the Schema 1 input stack, converter command,
> `tooling.migration` and migration-only contracts are retired after deliberate deprecation of
> the sole tracked authored fixture. [RETIREMENT.md](../refactor/current-language/RETIREMENT.md)
> records inventory, exclusions, coverage routing and rollback. This delivers source retirement,
> not the later version-selection or execution-binding deletions, Panda cutover or full validation.

Decision date: 2026-09-06. The project owner accepted the refactor direction and requested its
implementation plan, tracked work, and explicit deletion acceptance criteria. This decision adopts
that direction; it does not claim that the production schemas or Runtime already implement it.
The [implementation plan](../refactor/current-language/PLAN.md) owns sequencing, detailed
acceptance, bounded experiments, and rollback. Machine laws remain Kernel/LDB-owned.

## Context and evidence

The project owner states that gda-balancing has not had a formal product release: existing
release records, including the `gda-balancing-v0.1.0` tag, changelog and distribution version,
are internal revisions. Their existence does not establish formal release or language compatibility.
Those tags and package coordinates do not require retaining unchanged historical implementations.
That mistaken obligation
has nevertheless become concrete: bADR-0017's stat-composition amendment keeps all earlier
releases while introducing a new exact dependency chain.

Bounded experiments against `3f68bf3fb26df2ab54351a8ef4e3e167269bdc16` found:

- Merging 21 internal package releases into 14 complete current definitions admits five maintained
  Models and seven maintained Experiments. Progression plus periodic Effect, refused by the old
  dependency graph, composes without a new primitive or production Python change. The count of 14
  includes the converter package; it is not an implementation inventory to preserve after retirement.
- A versionless graph resolves the actual six-package RPG closure and rejects duplicate ownership,
  absent/cyclic dependencies, and capability ambiguity. Its source hydration shim means it does
  not prove that the production compiler is already versionless.
- A compiler build-label change preserves the tested runtime values but invalidates the old
  Experiment and changes six runtime artifact identities after rebinding. Producing provenance
  unnecessarily influences execution eligibility. Runtime also reads reasons and a rule-match
  limit outside RIR, so removing the binding before closing those inputs would be unsound.
- Request-local compiler preparation preserves the tested compilation artifacts while avoiding
  repeated work, but exposes specialization's reliance on object aliasing. Primitive trials also
  distinguish mathematical equivalence from overflow, refusal, and resource-charge equivalence.

These are narrow observations, not full conformance or proof of a globally minimal primitive set.
The plan preserves scripts, results, limitations, and the full requirements mapping. Line and test
counts do not authorize deletion of behavior.

## Decision

1. **No internal release-retention promise before formal release.** The earliest formal
   gda-balancing product release is toolkit v1.0; automated internal release records and
   distribution metadata are distinct. At that point a separate decision must identify actual
   consumers, supported contracts, and the compatibility promise; reaching that version does not
   automatically freeze every internal coordinate. Current internal definitions may be changed or
   withdrawn. Distribution versions remain useful for installation and bug reports.
2. **One current definition per package namespace.** Merge the complete maintained capability
   union before removing old copies. Then remove historical package, Type, and Operation version
   selection and its resolver machinery from authored inputs, machine contracts, projections,
   examples, and public surfaces. Namespace ownership, explicit declarations, capability checks,
   dependency closure, and deterministic ambiguity/cycle refusal remain. There is no historical
   registry, version-range solver, or old-language fallback. A retention-only cleanup is an interim
   checkpoint, not the accepted final outcome.
3. **Separate actual execution inputs from producing provenance, then delete the redundant
   binding.** First make the admitted executable closure sufficient for all consumed rules,
   reasons, types, Numeric/RNG policies, scheduler/effect behavior, and resource limits. Then remove
   whole-LDB and Build-receipt requirements that do not affect that execution, including their
   obsolete wire fields, equality gates, propagation, compatibility branches, and fallback reads.
   Completion of closure alone does not satisfy this decision. Source, build, and publication
   receipts may retain truthful provenance without acting as unnecessary execution prerequisites.
4. **Keep exact integrity and in-flight stability.** Changed bytes cannot keep a false content
   identity. An admitted request or session uses consistent rules for its lifetime; replacing the
   installed language cannot silently rewrite an active execution. Actual execution-policy and
   authored-input changes remain distinguishable. Old evidence is not relabeled as a new run, and
   withdrawn internal artifacts need not remain executable or retrievable forever.
5. **Delete dead and historical mechanisms early.** Remove the unused CLI artifact sink. Resolve
   each known 1.x source input by rewrite, explicit retirement, or bounded one-time conversion,
   then delete the converter and its command, schemas, packaged resources, imports, and obsolete
   tests in S1b. Unknown hypothetical external inputs do not justify indefinite support. Panda's
   separate embedded pipeline is removed only after its own source-faithful consumer cutover;
   that obligation does not keep the toolkit converter alive.
6. **Deepen current owners and validate the primitive basis.** Materialize request-owned Typed HIR
   preparation once and make specialization's outputs explicit. Keep independent imported-artifact
   validation independent of the producer. Adopt a smaller primitive basis only after precise
   type, overflow, refusal, effect, order, and resource laws and discriminating permanent cases.
   Bounded collection traversal/construction remains subject to that promotion gate; prospective
   constructors and all genre requirements remain open until proved. Run the small non-RPG
   extension witness in S6b before committing to broad genre delivery. The witness must execute
   reusable admitted Operations and demonstrate specified input-dependent state transitions under
   unchanged core/host semantics; a prescribed trace cannot satisfy [#878](https://github.com/aigengame/godot-agent/issues/878).
7. **Preserve established responsibility and claim boundaries.** Keep the existing
   `interfaces → application → domain → infrastructure` dependency direction, one balancing
   context, protocol-neutral execution sessions, typed outcomes, deterministic Event transactions,
   and atomic artifact publication. Existing evidence-verification activation limits remain:
   `candidate`/open verification does not become authenticated independent Claim closure through
   this refactor. No new signing, credential, revocation, or aggregation system is authorized by
   this decision; a concrete application must supply the separate need and trust boundaries.
   The [2026-08-21 PRD amendment](https://github.com/aigengame/godot-agent/issues/534#issuecomment-5369084517)
   and #542–#544 retain that activation authority. Functional local comparisons, Replay, S6b and
   deletion slices can finish with `candidate`/open results before authenticated claim closure.
   #509 separately retains the unresolved simulation-policy decision and its human acceptance.

Tracked delivery: [#865](https://github.com/aigengame/godot-agent/issues/865);
[issue index](../refactor/current-language/ISSUES.md). Dependency closure is #874;
mandatory binding deletion is #875.

## Exact supersession scope

The following earlier records remain accepted outside these clauses. Their reciprocal dated notes
distinguish retained historical/current-wire descriptions from the new target. No machine schema
changes merely because this decision is accepted.

| Earlier decision | Superseded target or obligation | Retained boundary |
| --- | --- | --- |
| bADR-0012 | Historical immutability of internal LDB releases; whole-build binding as a permanent execution requirement | Kernel/LDB and authored authority domains, content integrity, derived artifacts |
| bADR-0013 | Exact whole-LDB Resolved Model tuple as the final execution boundary; redundant preparation or implicit specialization state | AST/HIR/RIR/EIR meanings, independent admission, diagnostics, separate provenance |
| bADR-0014 | Reproduction eligibility tied to irrelevant build or whole-bundle identity | Actual execution-policy closure, determinism, atomicity, explicit refusal/resource laws |
| bADR-0016 | Strict package SemVer, version-coordinate selection/locking, compatibility-major type identity, historical release retention | Unique nominal owner, closed dependencies/capabilities/types, deterministic refusal |
| bADR-0017 | The 2026-08-26 old-release-retention and exact release-lineage mandate; historical template compatibility selection | Complete current capability union, template member ownership, all genre rows |
| bADR-0018 | Build/whole-bundle provenance as a mandatory semantic comparison or execution input | Authored evaluation intent, truthful observations, comparison scope, approval and claim activation boundaries |
| bADR-0019 | Ongoing converter availability and rejection of converter removal as the target | Explicit source disposition, no lossy success or dual Runtime, honest evidence |
| bADR-0021 | The migration command as a permanent forward command; propagation of retired version/execution-binding fields | Descriptor ownership, outcomes, diagnostics, idempotent atomic publication |
| bADR-0022 | Internal version-coordinate meta-formats and a pre-v1.0 frozen-Kernel commitment | Machine-owned laws, deterministic admission, independent conformance; every replaced law is reidentified |
| bADR-0023 | Versioned collection descriptors and irrelevant whole-LDB identity propagation into execution | Closed declared membership, canonical bytes/digests, no ambient discovery, selected semantic closure |
| bADR-0024 | Historical version selectors and the whole-LDB wrapper as the permanent notation identity boundary | Pure Formula semantics, canonical reversible notation, body/expression validation |
| bADR-0026/0027 | Inherited obsolete Standard Schema bindings in nested payloads | Shared application owner, local process capability, active-session stability; no cosmetic `/v1` rename |

bADR-0015's outcome contract, bADR-0020's scoped external-source adoption, and bADR-0025's layering
remain in force. Historical 1.x decisions remain readable provenance rather than renewed input
support obligations.

## Acceptance and rollback

Implementation issues must name the removed surface and its negative proof. In particular, the
execution-closure slice is followed by a required deletion slice: it must prove the old whole-LDB
and Build-receipt fields/gates/fallback reads are absent; provenance-only changes preserve execution
eligibility and semantic observations; changed actual execution laws or forged content still
refuse or change the appropriate execution identity. New outputs retain honest build provenance;
no test may achieve equality by erasing relevant execution inputs.

Each main-branch integration lands with a complete public path and coordinated current authorities, examples,
descriptors, independent vectors, and installed-resource checks. Old test IDs may retire only with
an explicit behavior disposition. Neither this ADR nor a smaller test total closes a product gate.
Wide wire changes may share an expand/migrate/contract integration branch; incomplete intermediate
revisions cannot merge to main. Detailed gates and linked requirement rows belong to the
implementation plan and tracker.

Rollback restores code, machine authorities, current sources, and their regenerated bindings from
one known revision together. It does not write changed bytes under an old digest, mix old and new
readers, reinstate historical compatibility as the final target, or claim that withdrawn evidence
proves the restored execution. Process-local sessions are invalidated explicitly when their
required implementation is replaced. Full conformance, genre support, and consumer acceptance
remain open until their own evidence passes.

## Alternatives

- Removing only the old-file retention rule is a useful first checkpoint, but leaves needless
  version selection and execution-binding machinery. It cannot close this refactor.
- Keeping version history and adding adapters compounds an obligation without a released consumer.
- Removing every identity immediately would lose real execution inputs and evidence integrity.
  Closing dependencies first is sequencing, not permission to postpone deletion indefinitely.
- Replacing the language or Runtime wholesale discards working boundaries without evidence that a
  new engine is needed. Bottom-up changes proceed through verifiable complete paths instead.
