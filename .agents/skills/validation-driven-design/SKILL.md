---
name: validation-driven-design
description: >-
  Design, audit, and iteratively validate architecture direction under material
  uncertainty. Use explicit requirements, mature theory, external-system research,
  executable prototypes, dogfooding, and cross-artifact reconciliation. Use when a
  decision is novel, disputed, broad, hard to reverse, or insufficiently supported.
  Also use this skill to write an architecture specification or decision record, or to audit a
  fixed architecture and its evidence.
---

# Validation-Driven Design

## Purpose and boundary

Design an architecture under explicit requirements and specifications, then strengthen it through
evidence-bearing iterations. This skill is for architecture creation, redesign, or architecture
audit, not routine codebase refactoring, interface styling, generic review, or UI prototyping.

Produce an evidence-bounded architecture direction. Include drivers, constraints, load-bearing
mechanisms, semantic boundaries, claims, and validation gates. Do not expand into detailed module
decomposition unless a claim under test requires it.

Treat applicable context, glossary, requirements, and other domain artifacts as current inputs.
Preserve their sources and established meanings. When they are absent or contradictory, record an
explicit assumption or open question and coordinate with the user. Do not infer domain knowledge
from technical theory, external systems, or a prototype.

Preserve the stated product vision as a falsifiable requirement. If evidence contradicts it, reopen
the architecture or requirement explicitly; never make the work “pass” by silently narrowing the
promise.

Use this skill to establish that the architecture meets its requirements, important design
decisions have enough support, and the necessary checks are clear. Establish these before judging
whether the architecture's complexity is proportionate to the current goal.

Scale validation work to the importance of the design decision and a concrete risk or open
question. If more validation is not justified, simplify or postpone that part of the design instead
of weakening its checks. Follow the selected mode's limits in [REFERENCE.md](REFERENCE.md).

[REFERENCE.md §1](REFERENCE.md#1-engagement-modes-and-authority-map) defines an executable
conformance case and its minimum fields.

## Quick start

1. Choose `lightweight`, `full-design`, or `audit-only` mode; name the artifact owners and human decision owner.
2. Write goals, non-goals, invariants, quality attributes, and production constraints. Keep artifact and decision lifecycle status separate from claim evidence state.
3. Map load-bearing mechanisms to mature theory and external systems; fan out independent research
   when justified, then verify, synthesize, and record adoption and proof gaps.
4. Rank architecture uncertainties and run only the smallest discriminating validation.
5. Feed dogfooding back into requirements, decisions, terms, specifications, executable conformance cases, and gates.
6. Audit the four design axes and cross-cutting quality attributes; keep non-claims explicit.

See [REFERENCE.md](REFERENCE.md) for templates and proof obligations, and [EXAMPLES.md](EXAMPLES.md).

## Workflow

The sections below define the `full-design` route. In `lightweight` mode, execute only the mode minimum
and add a step when its falsifier or risk requires it; do not generate full matrices or portfolios by
default. In `audit-only` mode, pin the baseline, evaluate the claimed scope, report gaps, and stop
without redesign or edits unless the user requests them.

For `full-design`, after section 1 establishes the design contract, run sections 2 and 3 as a bounded
research fan-out followed by primary-agent synthesis when subagents are available and the research
questions can be separated. Before fan-out, set a task-specific charter count or time budget and
state when to stop or defer research. Derive non-overlapping research charters from the design
contract. Define a distinct design question, hypothesis, or evidence angle for each charter. For
each load-bearing question, include one charter that seeks counterevidence or a credible alternative.

Treat subagent reports as research leads, not as evidence or authority. Let subagents identify
candidate theories, external systems, and primary sources within their charters unless the design
contract or pinned scope names the research target. The primary agent must inspect the load-bearing
primary sources, compare their provenance, and identify shared upstream sources and coverage gaps.
Open targeted follow-up research only for a named gap in source provenance or coverage; keep other
questions open and defer them. The primary agent must reconcile duplicate findings and conflicts
and own the integrated conclusion. Keep unresolved conflicts open; do not settle them by vote. If
subagents are unavailable or the questions cannot be separated, run separate sequential research
passes and disclose the missing independence.

In `lightweight` mode, use research fan-out only when the selected falsifier requires independent
evidence. In `audit-only` mode, use it only to verify evidence within the pinned scope. Do not let
research fan-out expand either mode or replace the independent adversarial review required by
[REFERENCE.md §5](REFERENCE.md#5-validation-portfolio).

### 1. Establish the design contract

- Read repository guidance and current authoritative artifacts before proposing structure.
- Turn outcomes into traceable requirements, scope, non-goals, invariants, failures, and quality attributes.
- Build one authority map, which can include a one-way reference graph. Give every normative fact
  one owner; derived artifacts reference it.
- Preserve each supplied claim's source and identifier. Keep artifact or decision lifecycle status
  separate from claim evidence state. Reuse the repository's claim evidence field when its meaning
  matches the distinctions below; do not add a second field for claim evidence state. Record an explicit mapping when the names differ.
- If no claim evidence field exists, start a claim evidence ledger: `proposed`, `theory-supported`,
  `confirmed-narrowly`, `conformance-proven`, `production-proven`, `open`, and `non-claim`.
- For iterative work or handoff, give each new driver, claim, and decision a stable identifier that
  follows repository conventions. Report added, changed, and retired identifiers.

### 2. Ground the abstractions

- Select mature theory for the actual design question, not for prestige or vocabulary.
- When research is fanned out, divide theory research by design question, hypothesis, or evidence
  angle. Name a specific theory in a charter only when it is already in scope.
- State the mechanism, invariant, representation boundary, proof boundary, and a disconfirming case.
- When semantics and execution differ, separate authoring form, typed/validated meaning, canonical
  public semantics, and implementation-private execution.

### 3. Research external systems

- Prefer pinned primary specifications and mature implementations.
- When research is fanned out, divide external-system research by problem, mechanism, or evidence
  angle. Name a specific system in a charter only when it is already in scope or synthesis reveals
  a coverage gap. Require pinned primary sources and explicit counterevidence or exclusions.
- Record each influence's problem, adoption, owner, exclusions, dependency, evidence, and upgrade.
- External systems are provenance unless the local contract explicitly makes one normative. Never
  create peer authorities or unsupported “compatible with” claims.

### 4. Design seams and alternatives

- Compare at least the selected design, a credible alternative, and the simplest non-adoption path.
- Design only enough structure to discriminate the load-bearing claim. Treat detailed
  responsibility and module placement as separate structural decisions unless they are under test.
- Define ownership, lifecycle, identity, extension, failure, and observability boundaries.
- Ask whether two independent implementations could both satisfy the prose yet produce different
  observable behavior. If yes, the contract is incomplete.
- Distinguish configuration/content additions, extension modules, framework semantics, and truly
  irreducible core changes.

### 5. Validate the highest-risk uncertainty

- Charter one question, falsifier, smallest slice, discriminating cases, time box, and deletion plan.
- Choose the evidence form from the uncertainty: prototype, permanent executable conformance case,
  or independent review. Architecture semantics usually need executable or independently interpreted artifacts.
- Treat prototype/review results as design evidence, never conformance, production authority, or human acceptance.

### 6. Synthesize dogfooding and iterate

- Classify design effect as `confirmed-no-change`, `refined-adopted`, `gap-opened`, or
  `no-design-effect`; then update claim evidence state separately.
- Attribute defects to the narrowest honest layer: instance/configuration → template/profile →
  extension module/package → framework/schema → irreducible kernel.
- Update each owning artifact once; remove duplicated normative restatements. Preserve research at a
  fixed reference and promote only durable scenarios, executable conformance cases, or decisions into authority.
- For each adopted refinement or open gap, report the effect on architecture drivers, constraints,
  and structural decisions. This lets later work revisit only the affected scope.
- Stop disposable prototyping when the risk class is resolved. Move remaining proof into permanent
  conformance assets and end-to-end production slices.

### 7. Run design-axis and quality-attribute gates

Treat specialized criteria supplied by a candidate architecture as structural evaluation criteria,
not acceptance criteria. Bind each criterion to an authoritative requirement, specification,
decision record, or explicitly scoped architecture contract before using it. Requirements retain
ownership of acceptance criteria. Use the generic axes below to assess evidence coverage and
unresolved interactions, not to replace the bound criteria.

- **Abstraction:** theory-grounded boundaries hide implementation choices without hiding semantics.
- **Completeness:** every known requirement, refusal, interaction, and operational concern maps to a
  mechanism plus an observable verification path.
- **Orthogonality:** use an **orthogonal basis** as a system metaphor for the load-bearing concerns.
  Completeness checks whether these concerns cover the current claim scope. Orthogonality checks
  whether each concern is necessary and non-overlapping. Each concern must have a distinct meaning
  and reason to change, and it must vary independently. Test their composition for hidden shared
  state, cross-product effects, and unspecified precedence.
- **Extensibility:** declared variation enters through extension contracts; an out-of-family witness
  must not require core or host-dispatch changes.
- Use REFERENCE.md's detailed delivery gates, including migration, security, observability, recovery,
  rollout, and rollback proportional to the real installed base.

## Output

Select the output contract by mode:

- For `full-design`, include all applicable items below.
- For `lightweight`, return the mode minimum and only the items produced by the selected bounded
  check. Do not add alternatives, structural-placement decisions, or adopted refinements unless the
  check required them.
- For `audit-only`, return the pinned baseline and scope, authorities, observed architecture direction
  and claims, evidence gaps, design-axis findings, findings about cross-cutting quality attributes, completion
  gaps, and recorded human decision outcome. Do not propose alternatives, structural placements,
  refinements, or edits unless the user requests redesign or edits.

The `full-design` output includes:

1. Authority sources, assumptions, and open input conflicts.
2. Goals, non-goals, architecture drivers, invariants, and quality attributes.
3. The selected architecture direction and the alternatives considered.
4. Load-bearing mechanisms, semantic boundaries, claims, claim evidence states, evidence, and non-claims.
5. Decisions that require concrete structural placement, with stable identifiers for iterative work or handoff.
6. Validation results, adopted refinements, open gaps, and affected authoritative artifacts.
7. Remaining gates and the required human decision.

## Completion

Do not declare the architecture complete from prose quality, a green build, framework analogies, or
passing disposable prototypes. Complete the audit in [REFERENCE.md](REFERENCE.md): trace every
requirement and decision, verify each quality axis with appropriately scoped evidence, reconcile
live artifacts, preserve explicit non-claims, and leave production gates executable.
Apply the full completion checklist only in `full-design` mode. For other modes, satisfy the selected
mode's minimum and record excluded checks as out of scope or non-claims, not as missing deliverables.
The designated human decision owner must accept, reject, or condition the architecture and explicitly
authorize or withhold the next gate; evidence and agents cannot self-approve.
