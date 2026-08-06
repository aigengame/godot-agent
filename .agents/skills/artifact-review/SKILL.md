---
name: artifact-review
description: Review project documents such as issues, ADRs, architecture documents, specifications, plans, and documentation changes for correctness, usability, consistency, completeness, orthogonality, DRY, terminology accuracy, and clear prose. Use only when the user explicitly asks for a review of such a document or a re-review of claimed fixes to one.
---

# Artifact Review

## Goal

Decide whether a project document fulfills its purpose with accurate, coherent,
sufficiently complete, and non-duplicative content, so its intended readers can
understand it, make decisions, or act on it reliably.

Review both content and language:

- Is the content correct, usable, and clearly bounded?
- Are terms accurate, stable, and consistent with project or domain usage?
- Is the prose concrete and natural, and does it express conceptual relationships
  accurately?

Report evidence-backed, actionable problems that affect factual accuracy,
understanding, decisions, implementation, maintenance, terminology, or clarity.
Terminology misuse, changes in a concept's meaning, and prose that materially
impedes understanding are findings in their own right. Do not report personal
stylistic preferences.

Scale the review to the artifact's size, risk, and purpose.

## Workflow

### 1. Inspect Relevant Materials

- Read the complete artifact. For a change, inspect both the full current artifact
  and the relevant change.
- Include status, labels, version, or other attached information when it changes the
  artifact's meaning.
- Trace key facts, constraints, and references to the nearest authoritative source.
  Read only material relevant to the artifact's purpose or the change under review.
- Inspect code, configuration, scripts, project state, or external-system behavior
  when a claim depends on them.
- Base conclusions on the artifact, the user's request, and observable evidence. Do
  not infer unwritten author intent.

Relevant material may include:

- For an issue: its goal, constraints, acceptance criteria, related work, and the
  current implementation state.
- For an ADR: its context, decision, rationale, consequences, alternatives, and later
  amendments.
- For an architecture document: the boundaries, responsibilities, dependency
  directions, interfaces, and current system structure it describes.
- For a specification or plan: its requirements, constraints, deliverables, and
  validation approach.

These are examples of relevant evidence, not mandatory templates for every
artifact.

### 2. Review the Artifact

#### Correctness and Usability

- Facts, technical descriptions, domain claims, and terminology agree with
  verifiable sources.
- Decisions, requirements, constraints, and guidance support the judgment or action
  the artifact is meant to enable.
- When the artifact contains procedures, their order, inputs, outputs, and required
  capabilities are workable.
- When the artifact defines behavior or an implementation process, it covers
  important assumptions, boundaries, and failure paths.
- Detail and constraint match risk and purpose: constrain fragile operations while
  preserving judgment when several approaches are valid.
- Validate critical, non-obvious claims with a representative check. Disclose what
  was not tested when validation is impractical.

#### Consistency and Completeness

- Use one term for each concept and one meaning for each term.
- Claims, definitions, requirements, constraints, and conclusions agree internally
  and with the material on which they depend.
- Descriptions of current state, existing behavior, or proposed change match the
  relevant sources.
- Cover the first practical questions raised by the artifact's purpose. Do not omit
  information readers need to understand or use it.
- For an implementation-oriented artifact, readers can determine what must be done,
  what constrains the work, and how completion will be established.
- For a decision record, readers can determine what was decided, why, where it
  applies, and its important consequences.
- Do not add speculative cases or detail merely to appear complete.

#### Orthogonality and DRY

- Give each rule, fact, or decision one authoritative home. Elsewhere, keep only the
  reminder or reference needed for understanding or use.
- Organize the artifact around a coherent purpose. Split unrelated concerns only
  when they obstruct understanding, ownership, or independent change.
- Remove recaps, filler, and repeated constraints that add no decision, action, or
  necessary context.
- Include enough context to understand the core conclusion without copying an
  authoritative source in full.
- Extract shared material only when it has the same meaning and the same reason to
  change at every use site.
- Do not fragment content that must be read together merely to remove surface-level
  repetition.

#### Terminology and Prose

- Prefer established project and domain terms. Do not introduce a second name for
  an existing concept.
- Introduce a new term only when existing language cannot express the concept
  accurately, and define it at first use.
- When a local convention broadens an established term, state the convention and its
  practical effects.
- Use ASD-STE100 Simplified Technical English as the default reference for technical
  prose unless the project specifies otherwise. Preserve established project and
  domain terms as technical nouns or technical verbs.
- Prefer plain, concrete prose. Remove formulaic wording, abstract noun chains,
  slogans, empty bullets, and legal or procurement language.
- Check that sentences express causal, dependency, scope, and ordering relationships
  accurately.
- Keep examples that explain a non-obvious distinction; remove examples that merely
  restate a rule.
- Describe observable text, state, and behavior. Do not speculate about who or what
  produced the prose.

### 3. Validate When Applicable

Choose the smallest sufficient validation for the artifact's actual claims:

- Open cited material and confirm that it supports the claim.
- Compare claims with current implementation, configuration, project documentation,
  or issue-tracker state.
- Search for conflicting or drifting terminology, responsibilities, relationships,
  or prior decisions.
- Run document checks, link checks, scripts, or tests directly relevant to a claim.
- For a versioned change, identify the reviewed revision, relevant baseline, and
  actual scope of the change.
- When the artifact cites CI, validation results, or runtime evidence, verify that the
  evidence supports the stated conclusion.

A passing format check or green CI proves only that its checks passed; it does not by
itself establish that the content, terminology, or prose is correct.

Disclose important validation that was not performed and could affect the conclusion.

### 4. Report

Start with one conclusion:

- **Pass**: no substantive content, terminology, or prose issue prevents the artifact
  from fulfilling its purpose.
- **Changes required**: one or more substantive content, terminology, or prose issues
  must be resolved.

Group findings under **Required changes**, **Terminology and prose**, or **Minor** as
appropriate. Classify by impact, not by issue type. A terminology or prose problem
that affects accuracy, understanding, decisions, or use belongs under **Required
changes** rather than being downgraded as wording feedback.

For each finding, give:

- The location.
- Verifiable evidence.
- The impact on accuracy, understanding, or use.
- The smallest practical alternative that preserves the intent.

Report only actionable issues. Keep optional improvements separate from required
changes and include them only when they materially help.

If new context invalidates a proposed fix but not the underlying problem, revise the
fix rather than dropping the finding.

If there are no substantive findings, report **Pass**, identify the reviewed target,
and summarize the main content, terminology, and prose checks in one or two
sentences. Mention important validation that was not performed, then stop.

Return the review in the medium the user requested. Edit files, post comments, or
perform other remote writes only when the user explicitly authorizes them.

## Re-review

- Pin the previous and current versions.
- Verify every claimed fix in the artifact and relevant evidence; a reply is not
  evidence by itself.
- Review scope added or changed since the previous review.
- For an item declined by design, verify that the accepted constraint, rationale, and
  necessary mitigations appear in the appropriate authoritative material.
- Use the same conclusion and finding format as the initial review.
