---
name: validation-driven-design
description: Designs, audits, and iteratively validates framework, platform, language, protocol, or runtime architectures by combining explicit requirements, mature theory, external-system research, executable prototypes, dogfooding, and cross-artifact reconciliation. Use when creating or redesigning an architecture, writing architecture specifications or ADRs, auditing an existing architecture against abstraction/completeness/orthogonality/extensibility, or planning a design for production implementation.
---

# Validation-Driven Design

## Purpose and boundary

Design an architecture under explicit requirements and specifications, then strengthen it through
evidence-bearing iterations. This skill is for architecture creation, redesign, or architecture
audit, not routine codebase refactoring, interface styling, generic review, or UI prototyping.

Preserve the stated product vision as a falsifiable requirement. If evidence contradicts it, reopen
the architecture or requirement explicitly; never make the work “pass” by silently narrowing the
promise.

Use this skill to establish that the architecture meets its requirements, important design
decisions have enough support, and the necessary checks are clear. Establish these before judging
whether the architecture's complexity is proportionate to the current goal.

Scale validation work to the importance of the design decision and a concrete risk or open
question. If more validation is not justified, simplify or postpone that part of the design instead
of weakening its checks. Follow the selected mode's limits in [REFERENCE.md](REFERENCE.md).

## Quick start

1. Choose lightweight, full, or audit-only mode; name the artifact owners and human decision owner.
2. Write goals, non-goals, invariants, quality attributes, production constraints, and claim status.
3. Map load-bearing mechanisms to mature theory and external systems; record adoption and proof gaps.
4. Rank architecture uncertainties and run only the smallest discriminating validation.
5. Feed dogfooding back into requirements, decisions, terms, specifications, vectors, and gates.
6. Audit the four design axes and cross-cutting qualities; keep non-claims explicit.

See [REFERENCE.md](REFERENCE.md) for templates and proof obligations, and [EXAMPLES.md](EXAMPLES.md).

## Workflow

The sections below define the full-design route. In `lightweight` mode, execute only the mode minimum
and add a step when its falsifier or risk requires it; do not generate full matrices or portfolios by
default. In `audit-only` mode, pin the baseline, evaluate the claimed scope, report gaps, and stop
without redesign or edits unless the user requests them.

### 1. Establish the design contract

- Read repository guidance and current authoritative artifacts before proposing structure.
- Turn outcomes into traceable requirements, scope, non-goals, invariants, failures, and qualities.
- Build an authority map. Give every normative fact one owner; derived documents reference it.
- Start a claim ledger: `proposed`, `theory-supported`, `confirmed-narrowly`, `conformance-proven`,
  `production-proven`, `open`, and `non-claim`.

### 2. Ground the abstractions

- Select mature theory for the actual design question, not for prestige or vocabulary.
- State the mechanism, invariant, representation boundary, proof boundary, and a disconfirming case.
- When semantics and execution differ, separate authoring form, typed/validated meaning, canonical
  public semantics, and implementation-private execution.

### 3. Research external systems

- Prefer pinned primary specifications and mature implementations.
- Record each influence's problem, adoption, owner, exclusions, dependency, evidence, and upgrade.
- External systems are provenance unless the local contract explicitly makes one normative. Never
  create peer authorities or unsupported “compatible with” claims.

### 4. Design seams and alternatives

- Compare at least the selected design, a credible alternative, and the simplest non-adoption path.
- Define ownership, lifecycle, identity, extension, failure, and observability boundaries.
- Ask whether two independent implementations could both satisfy the prose yet produce different
  observable behavior. If yes, the contract is incomplete.
- Distinguish configuration/content additions, extension modules, framework semantics, and truly
  irreducible core changes.

### 5. Validate the highest-risk uncertainty

- Charter one question, falsifier, smallest slice, discriminating cases, time box, and deletion plan.
- Choose the evidence form from the uncertainty: prototype, permanent vector, or independent review.
  Architecture semantics usually need executable or independently interpreted artifacts.
- Treat prototype/review results as design evidence, never conformance, production authority, or human acceptance.

### 6. Synthesize dogfooding and iterate

- Classify design effect as `confirmed-no-change`, `refined-adopted`, `gap-opened`, or
  `no-design-effect`; then update claim maturity separately.
- Attribute defects to the narrowest honest layer: instance/configuration → template/profile →
  extension module/package → framework/schema → irreducible kernel.
- Update each owning artifact once; remove duplicated normative restatements. Preserve research at a
  fixed reference and promote only durable scenarios, vectors, or decisions into authority.
- Stop disposable prototyping when the risk class is resolved. Move remaining proof into permanent
  conformance assets and production vertical slices.

### 7. Run design-axis and cross-cutting-quality gates

- **Abstraction:** theory-grounded boundaries hide implementation choices without hiding semantics.
- **Completeness:** every known requirement, refusal, interaction, and operational concern maps to a
  mechanism plus an observable verification path.
- **Orthogonality:** independent concerns have separate owners; their intersections and ordering are
  explicitly closed and tested.
- **Extensibility:** declared variation enters through extension contracts; an out-of-family witness
  must not require core or host-dispatch changes.
- Use REFERENCE.md's detailed delivery gates, including migration, security, observability, recovery,
  rollout, and rollback proportional to the real installed base.

## Completion

Do not declare the architecture complete from prose quality, a green build, framework analogies, or
passing disposable prototypes. Complete the audit in [REFERENCE.md](REFERENCE.md): trace every
requirement and decision, verify each quality axis with appropriately scoped evidence, reconcile
live artifacts, preserve explicit non-claims, and leave production gates executable.
Apply the full completion checklist only in full-design mode. For other modes, satisfy the selected
mode's minimum and record excluded checks as out of scope or non-claims, not as missing deliverables.
The designated human decision owner must accept, reject, or condition the architecture and authorize
the next gate; evidence and agents cannot self-approve.
