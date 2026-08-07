---
name: skill-review
description: Review skill documents and skill-focused changes for correctness, consistency, completeness, orthogonality, DRY, terminology accuracy, and clear prose. Use when reviewing a new or changed skill, checking whether its workflow and companion resources are usable, reviewing a PR that adds or renames skills, or re-checking claimed fixes.
---

# Skill Review

## Goal

Decide whether a skill can do its declared job with accurate instructions and the smallest sufficient structure. Report only actionable issues supported by the artifact or verifiable evidence. Scale the review to the skill's size, risk, and intended use.

Treat terminology and prose as a required review pass. Do not conclude **Pass**
until this pass is complete and its result is reported.

## Workflow

### 1. Inspect Relevant Materials

- Read the complete `SKILL.md` and agent metadata.
- Inventory companion references, examples, scripts, and assets. Read only those relevant to the skill's declared behavior or the change under review.
- Inspect a companion script when a claim depends on what the script accepts, produces, or validates.
- For a change, inspect both the full current skill and the relevant diff.
- Confirm that the frontmatter description gives accurate skill-selection triggers and that the body fulfills them.

### 2. Review the Skill

#### Correctness and Usability

- Instructions are executable, ordered where sequence matters, and refer only to available tools and resources.
- Verify technical, domain, or terminology claims against authoritative evidence whenever a finding depends on them. Prefer the project's glossary and current primary documentation.
- The workflow covers its inputs, required decisions, output, and important failure or exception paths.
- The amount of prescribed procedure matches the task: constrain fragile operations, but leave judgment where several valid approaches exist.
- Forward-test brittle or non-trivial workflows with a representative task. If that is not practical, disclose the untested behavior.

#### Consistency and Completeness

- Use one term for each concept and one meaning for each term. Frontmatter, body, metadata, filenames, and companion resources agree.
- Answer the first practical questions raised by every declared use case; do not add speculative cases merely for completeness.
- When reviewing a change, verify that its description matches the files and behavior actually changed.
- Do not let a skill contradict its own guidance.

#### Orthogonality and DRY

- Give each rule one authoritative home. Elsewhere, include only a concrete reminder needed at the point of use.
- Separate unrelated concerns and remove recaps, filler, and repeated prohibitions that add no decision or action.
- Keep the skill self-contained: remove hidden assumptions about sibling skills and unexplained private vocabulary.
- Extract shared material only when it has the same meaning and the same reason to change in every use site.

#### Terminology and Prose — Required Pass

- Review terminology and prose independently of other findings. Inspect all prose in
  the complete `SKILL.md` and agent metadata. Inspect explanatory prose in companion
  resources when it is relevant to the skill's behavior or the change under review.
- Search for established terms, alternate names, undefined terms, and changes in
  meaning. Do not limit this pass to passages already selected for other findings.
- Prefer established project and domain terms. Do not introduce a second name for an
  existing concept.
- Introduce a new term only when existing language cannot express the concept
  accurately, and define it at first use.
- If a local convention broadens an established term, state the convention and its
  practical effects.
- Use ASD-STE100 Simplified Technical English as the default reference for technical
  prose unless the project specifies another writing standard. Preserve established
  project, domain, and tool terms as technical nouns or technical verbs.
- Unless the project specifies another writing standard, check word choice and
  meaning, technical nouns and verbs, and sentence structure against ASD-STE100.
  Apply its procedural or descriptive writing rules according to the passage. Record
  the checks performed.
- Prefer plain, concrete instructions. Remove formulaic or stilted prose, long abstract noun chains, slogans, empty bullets, and legal or procurement language.
- Check that sentences express causal, dependency, scope, and ordering relationships
  accurately.
- Keep concrete domain examples when they teach a non-obvious distinction; remove examples that merely repeat a rule.
- Describe observable text and behavior. Do not infer who or what produced the prose.

### 3. Validate When Applicable

- Run the repository's skill validator and check frontmatter, directory naming, and agent metadata.
- After a rename or move, search for stale references and verify skill discovery paths.
- For a pull request, verify the exact head, merge base, current base, CI status, naming conventions, and validation claims in the description.
- Treat a passing validator or green CI as structural evidence, not proof that the workflow is correct.
- Test scripts or resources whose behavior is required for the skill to work.
- Record the terminology sources, writing reference, inspected scope, and prose checks
  used in the review. For technical prose, use ASD-STE100 or the project-specified
  alternative as the writing reference.

### 4. Report

Start with one conclusion:

- **Pass**: no substantive content, terminology, or prose issue prevents the skill
  from fulfilling its declared purpose, and the required terminology and prose pass
  is complete and reported.
- **Changes required**: one or more substantive content, terminology, or prose issues
  must be resolved.

Always include a **Terminology and prose assessment**, even when it produces no
finding. State:

- The project, domain, or tool terminology sources used.
- The writing reference used. For technical prose, name ASD-STE100 or the
  project-specified alternative.
- The scope inspected and prose checks performed.
- The result and the location of any related findings.
- Important checks that were not performed.

If no substantive terminology or prose issue was found, say so explicitly. The
assessment documents review coverage; it does not require a finding.

Group actionable findings under **Required changes** or **Minor** as appropriate.
Classify them by impact, not by issue type. A terminology or prose problem that
affects correctness, understanding, selection, or execution belongs under
**Required changes** rather than being downgraded as wording feedback. For each
finding, give the location, evidence, impact, and the smallest practical alternative
that preserves the intent. Keep optional improvements separate and include them only
when they materially help.

If new context invalidates a proposed fix but not the underlying problem, revise the fix instead of dropping the finding. For example, if a proposed cross-reference conflicts with a self-contained skill, keep the finding that an instruction relies on missing context and propose a self-contained rewrite.

If there are no substantive findings, report **Pass** with the reviewed target,
include the required **Terminology and prose assessment**, and give a one- or
two-sentence summary of the material checks performed. Mention any important
validation that was not performed, then stop.

Return the review in the medium the user requested. Edit files, post comments, or perform other remote writes only when the user explicitly authorizes them.

## Re-review

- Pin the previous and current versions.
- Verify every claimed fix in the artifact and relevant tests; a reply is not evidence by itself.
- Repeat the terminology and prose pass for changed text and report its assessment,
  even when previous findings concerned only behavior or structure.
- Review new scope introduced since the previous review.
- For an item declined by design, verify that the accepted constraint and necessary mitigations appear in the authoritative material.
- Report with the same conclusion and finding format as the initial review.
