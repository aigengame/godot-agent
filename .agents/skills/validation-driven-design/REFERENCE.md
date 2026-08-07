# Validation-Driven Design Reference

Use this file for detailed templates, proof obligations, and delivery gates. `SKILL.md` exclusively
owns the design workflow; this file does not restate it.

Contents: [modes and authority](#1-engagement-modes-and-authority-map) ·
[claims](#2-claim-and-evidence-ladder) · [theory](#3-theory-support-matrix) ·
[external research](#4-external-system-research-matrix) · [validation](#5-validation-portfolio) ·
[quality gates](#6-four-design-axes-and-cross-cutting-qualities) ·
[defect attribution](#7-defect-attribution-ladder) · [delivery](#8-delivery-gates-and-production-planning) ·
[completion](#9-completion-audit)

## 1. Engagement modes and authority map

Choose mode before building the authority map:

| Mode | Use when | Required minimum |
| --- | --- | --- |
| `lightweight` | a bounded, reversible decision does not change normative public semantics, add an authoritative source, or introduce or alter an extension contract | owner, requirement/decision, falsifier, affected axes, one discriminating check, non-claims, and human gate |
| `full-design` | a framework/language/runtime or broad, hard-to-reverse claim changes authority, semantics, extension, or production boundaries | the complete workflow, matrices, proof obligations, and delivery gates |
| `audit-only` | fixed existing artifacts and claims must be evaluated without redesign | fixed baseline/scope, authority and claim audit, design-axis and cross-cutting-quality findings, completion gaps, and human disposition; no edits unless requested |

Every mode keeps explicit authority, falsifier, non-claims, and human decision ownership. Scale the
remaining evidence work to claim breadth, reversibility, novelty, and operational risk.

`lightweight` is a ceiling as well as a minimum: start with one compact decision record and
one discriminating check. Do not create theory/research matrices, a prototype portfolio, the full
delivery sequence, or a full completion audit unless the falsifier exposes a specific need; state
why before expanding. `audit-only` similarly reports only findings inside the pinned claimed scope.

An **executable conformance case** is a permanent, machine-runnable record bound to one exact
authoritative claim. Its minimum fields are the authority and version or immutable reference, input
and preconditions, operation, expected observable result or refusal, and pass/fail oracle.

Choose repository-native names, but preserve these ownership roles:

| Role | Owns | Must not become |
| --- | --- | --- |
| Requirements | user outcomes, scope, acceptance criteria, live completion | detailed architecture or evidence by assertion |
| Architecture narrative | macro topology, responsibilities, cross-cutting invariants, delivery order | duplicate detailed decisions or machine semantics |
| Decision records | one binding decision, alternatives, consequences, validation | status dashboard or broad narrative |
| Glossary/context | canonical terms and distinctions | a second architecture specification |
| Specification/standard | normative semantics, public contracts, conformance requirements, versioning, and designation of normative machine-readable artifacts | architecture rationale, implementation details, evidence, or acceptance state |
| Executable conformance assets | machine-checkable schemas, executable conformance cases, validators, and observable oracles that realize or test the specification | an independent semantic authority or proof merely because tests pass |
| Evidence record | prototype/research inputs, outputs, provenance, bounded conclusions | semantic authority or acceptance state |
| Acceptance tracker | current gates and their state | proof without required artifacts |
| Human decision owner | accept, reject, or condition the architecture and authorize or withhold the next gate | an evidence generator, automated check, or self-approving agent |
| Prototype | one disposable risk probe | production implementation or permanent authority |
| Review/change record | reviewable summary and chronological coordination | sole home of requirements, dogfooding, or decisions |

Build the authority map with a one-way reference graph such as:

`requirement → decision → term → specification/standard → executable conformance asset → implementation owner → evidence → gate`

The specification/standard declares which machine-readable assets are normative. Other executable
assets are derived conformance mechanisms; passing them becomes evidence only after their binding
to the exact specification is verified.

For each fact, mark exactly one authoritative source and every derived copy. Prefer a one-way
reference over restating a list, algorithm, count, precedence rule, or state machine. Reconcile the
pinned current artifact revision and any live coordination state after each design iteration.

## 2. Claim and evidence ladder

Use exact, bounded language:

| State | Meaning | Sufficient evidence |
| --- | --- | --- |
| `proposed` | a candidate mechanism | rationale only |
| `theory-supported` | established theory explains why the mechanism should work | explicit theory-to-invariant mapping and proof boundary |
| `confirmed-narrowly` | a selected executable slice behaved as predicted | reproducible prototype with discriminating cases |
| `conformance-proven` | independent implementations satisfy permanent authority | normative artifacts, executable conformance cases, mutation/refusal tests, mutual consumption where applicable |
| `production-proven` | deployed behavior meets operational requirements | production telemetry, failure recovery, rollout and SLO evidence |
| `open` | required evidence is absent or contradictory | an owner and next discriminating gate |
| `non-claim` | a tempting broader inference is explicitly prohibited | stated scope boundary |

Never promote a claim merely because a prototype passed, a third-party framework uses a similar
term, or tests unrelated to the property are green.

Dogfooding uses a separate disposition namespace:

| Disposition | Meaning |
| --- | --- |
| `confirmed-no-change` | bounded evidence supports the existing decision without changing authority |
| `refined-adopted` | the observation caused an accepted, reconciled design or requirement change |
| `gap-opened` | the observation exposed an unresolved defect, ambiguity, or evidence gate |
| `no-design-effect` | the observation was instance-local, out of claim scope, or required no normative change |

After recording the disposition, set the affected claim to the applicable maturity state above.
Never reuse a claim-state label as a dogfooding disposition.

## 3. Theory-support matrix

Create one row per load-bearing abstraction:

| Design question | Mature theory/model | Adopted mechanism | Invariant | Representation boundary | Proof boundary | Disconfirming case |
| --- | --- | --- | --- | --- | --- | --- |
| What meaning is public? | e.g. compiler semantics | canonical semantic representation | equivalent inputs preserve specified observations | source/typed/public/private execution | specified subset only | two conforming lowerers disagree |

Common sources include compiler construction, type/effect systems, state machines, distributed
systems, control theory, information theory, statistics, capability security, database theory, and
formal methods. Use only what explains a real constraint.

An AST/IR-style separation is useful when authoring fidelity, validated meaning, portable semantics,
and optimized execution have different owners. A typical shape is:

`wire/source → authoring form → typed/validated form → canonical public semantics → private execution`

Each arrow needs a preservation or refusal contract. Keep diagnostics/provenance separate when they
may vary without changing meaning. Do not make a serialization format or optimizer the semantic
authority accidentally.

## 4. External-system research matrix

Use current primary specifications and pin the consulted version or edition.

| System/version | Relevant problem | Adopted mechanism | Local owner | Rejected surface | Runtime dependency? | Required evidence | Upgrade effect |
| --- | --- | --- | --- | --- | --- | --- | --- |

Rules:

1. Research mechanisms, failure modes, and lifecycle/identity choices—not names to borrow.
2. Restate every adopted mechanism in the local authority map.
3. Record exclusions so a partial mapping cannot become an accidental compatibility promise.
4. Require an executable conformance case when the adopted claim is machine-checkable and observable;
   otherwise record the evidence form that can discriminate the claim.
5. Treat an external version change as a deliberate local design decision, never ambient drift.
6. Compare with non-adoption: importing a standard can cost more authority and surface than it saves.

## 5. Validation portfolio

Choose validation form by uncertainty:

| Uncertainty | Validation form |
| --- | --- |
| layer connectivity/integration | smallest end-to-end slice |
| semantic authority/portability | two independent interpreters or compilers consuming each other's artifacts |
| state/lifecycle/order | executable state-machine or scheduler harness with boundary permutations |
| orthogonality | add one independent axis, then exercise cross-products and mutation cases |
| extensibility | add an out-of-family capability through public contracts with unchanged core/builds |
| requirement breadth | research corpus mapped to the coverage matrix, explicitly non-conforming |
| human interaction/usability | visual or interactive prototype |
| authority ambiguity/contract completeness | independent adversarial review of fixed raw artifacts and claimed scope |

### Prototype charter

```md
Question:
Architecture claim under pressure:
Hypothesis and falsifier:
Smallest executable slice:
Independent implementations or consumers:
Positive / negative / boundary / mutation cases:
Public observations:
Time box and deletion plan:
Evidence location and immutable reference:
Explicit non-claims:
```

Use a shared review/change record only when collaborative review or integration is needed. Disposable
code can live at an immutable artifact revision with an evidence index. Do not promote it merely to
make it visible.

### Dogfooding ledger

| Observation | Disposition | Root layer | Design effect | Owning artifact updated | Permanent evidence promoted | Remaining gate |
| --- | --- | --- | --- | --- | --- | --- |

Keep chronological experiment details in the evidence record. Put only synthesized implications in
the architecture, decisions, requirements, glossary, specification, and executable conformance assets.

### Independent adversarial review

Use independent review to expose ambiguous prose, hidden authority, contradictions, and omitted
cases. Give the reviewer fixed raw requirements, artifacts, and claimed scope—not the desired
conclusion. Record the baseline, independence boundary, findings, and disposition. Review is design
evidence, never conformance proof or human acceptance.
Require it for `full-design`, broad or hard-to-reverse claims, and load-bearing authority ambiguity;
otherwise scale it to risk.

### Stop rule

Run another disposable prototype only when the design adds or changes normative public semantics, an
extension contract, an authority owner or binding, or a comparably high-risk uncertainty. Otherwise
move to permanent executable conformance cases and end-to-end production slices.

## 6. Four design axes and cross-cutting qualities

The four axes assess design structure. Consistency, reliability, and operability apply across every
axis; they are not additional peers in the design-axis taxonomy.

| Axis | Required questions | Strong evidence | Failure signal |
| --- | --- | --- | --- |
| Abstraction | What theory supports the model? Which semantics are public? Which implementation details may vary? | explicit semantic boundaries; preservation/refusal contracts; independent implementations | host behavior, serialization, framework, or optimizer becomes hidden authority |
| Completeness | Do all known stories, failures, variants, interactions, operations, and production concerns map to observable contracts? | requirements-to-mechanism-to-scenario-to-conformance-case-to-observable matrix | vocabulary/package inventory presented as coverage; important paths only appear in prose |
| Orthogonality | Does each concern have one owner and independent representation? Are cross-products and precedence closed? | mutation tests; pairwise/cross-product scenarios; canonical ordering/reducers | independent axes share hidden state or leave interaction order to the host |
| Extensibility | What is configuration, extension, framework evolution, or irreducible core? Can an out-of-family case use unchanged core and dispatch? | explicit extension invariance; fixed-build witness; negative capability/refusal cases | each new domain adds core fields, phases, switches, callbacks, or parallel semantics |

Also audit consistency, reliability, and operability:

- **Consistency:** one owner per fact; terminology, requirement, decision, specification, and live state agree.
- **Reliability:** deterministic scope, atomic boundaries, typed failure, recovery, audit, resource caps.
- **Operability:** public surface, versioning, diagnostics, observability, deployment and rollback.

For broad claims, ask: “Can two implementations follow every written rule yet produce different
observable results?” Construct the difference. If the answer is yes, add authority or narrow the
claim explicitly.

## 7. Defect-attribution ladder

When dogfooding fails, classify before changing the architecture:

1. **Instance/configuration:** a particular model or input is wrong.
2. **Template/profile:** defaults or composition for a product family are incomplete.
3. **Extension module/package:** a reusable domain contract or interaction is missing.
4. **Framework/schema:** extension, identity, lifecycle, or evidence semantics are inadequate.
5. **Irreducible kernel/core:** the bootstrap or universal execution model cannot express the need.

Fix the narrowest honest owner. Do not patch a template to hide a framework defect, or expand the
kernel because one instance used the wrong contract. If a required extensibility promise fails,
reopen the architecture rather than granting a special-case escape hatch.

## 8. Delivery gates and production planning

This section exclusively owns the detailed default delivery sequence:

1. **Bounded architecture feasibility:** resolve the highest-risk mechanism with disposable evidence.
2. **Permanent conformance foundation:** replace prototype-local authority with versioned rules,
   schemas, fixtures, negative/mutation conformance cases, and reusable harnesses.
3. **Production end-to-end slice:** exercise the public API/artifact path end to end.
4. **Known-domain breadth:** close the full requirements coverage matrix without parallel semantics.
5. **Out-of-family witness:** prove the extension promise against a structurally different consumer.
6. **Production rollout:** validate security, performance, capacity, observability, recovery,
   compatibility/migration, deployment, rollback, and operational ownership.

Compatibility effort must match real history. With no released artifacts, prefer a clean forward
baseline: migrate safely where semantics are known and deprecate/refuse what cannot be migrated.
Do not build speculative compatibility machinery.

## 9. Completion audit

For `full-design`, prove every item before declaring the design ready for implementation or
production. For `lightweight` or `audit-only`, apply only the selected mode's minimum and the
checklist items affected by its explicit claims; list the rest as out of scope rather than producing
ceremonial artifacts.

- [ ] Every requirement, non-goal, invariant, and production constraint has one owner.
- [ ] Every binding decision records alternatives, consequences, and a verification path.
- [ ] Every load-bearing abstraction has a theory mapping and honest proof boundary.
- [ ] Every external influence has a pinned version, adopted/rejected mapping, local owner, and evidence.
- [ ] Every prototype has a charter, immutable evidence, bounded conclusion, non-claims, and disposition.
- [ ] The selected engagement mode is justified and satisfies its required minimum.
- [ ] Required independent-review findings are dispositioned without being mislabeled as conformance.
- [ ] Every adopted dogfooding result was propagated to all affected authoritative artifacts.
- [ ] The coverage matrix includes positive, negative, boundary, interaction, and observable paths.
- [ ] The four design axes and consistency, reliability, and operability each have scoped evidence.
- [ ] Independent implementations cannot disagree within the claimed contract, or the gap is open.
- [ ] Normative details are not duplicated across architecture, decisions, glossary, requirements, and coordination records.
- [ ] Live counts, links, statuses, versions, and pinned artifact references were refreshed after the final edit.
- [ ] Remaining risks and non-claims are explicit; prototype evidence is not mislabeled as conformance.
- [ ] The human decision owner accepted, rejected, or conditioned the architecture and explicitly
      authorized or withheld the next gate; no evidence or agent self-approved it.
- [ ] The delivery plan names permanent assets, end-to-end slices, migration policy, operational gates,
      and the condition that reopens the architecture.
