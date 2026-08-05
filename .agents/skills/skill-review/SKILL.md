---
name: skill-review
description: Review skill documents and skill-focused changes for correctness, consistency, completeness, orthogonality, DRY, terminology accuracy, and clear prose. Use when reviewing a new or changed skill, checking whether its workflow and companion resources are usable, reviewing a PR that adds or renames skills, or re-checking claimed fixes.
---

# Skill Review

## Goal

Decide whether a skill can do its declared job with accurate instructions and the smallest sufficient structure. Report only actionable issues supported by the artifact or verifiable evidence. Scale the review to the skill's size, risk, and intended use.

## Workflow

### 1. Pin the Target and Intent

- Determine whether the target is a whole skill, a local change, a pull request, a merged change, or a re-review.
- For a pull request, record the exact head, base, merge base, and changed files. For a local change, identify the files and comparison point.
- For a merged change, record the merge commit and its comparison point. Review the merge-time diff when the user asks about the change; review the current artifact when the user asks about the skill as it exists now.
- Read the user request, repository rules, and any issue, specification, or pull-request description that defines the intended result.
- Follow higher-priority requirements when sources disagree. Treat a local convention as a constraint only when the user or project has accepted it and its trade-offs are documented; otherwise review it as a proposal.
- Treat historical pull-request text as context, not as a required fix, unless it is authoritative or the user asks to review it.
- State material assumptions or missing evidence instead of filling gaps with guesses.

### 2. Inspect Relevant Materials

- Read the complete `SKILL.md` and agent metadata.
- Inventory companion references, examples, scripts, and assets. Read only those relevant to the skill's declared behavior or the change under review.
- Inspect a companion script when a claim depends on what the script accepts, produces, or validates.
- For a change, inspect both the full current skill and the relevant diff.
- Confirm that the frontmatter description gives accurate skill-selection triggers and that the body fulfills them.

### 3. Review the Skill

#### Correctness and Usability

- Instructions are executable, ordered where sequence matters, and refer only to available tools and resources.
- Verify technical, domain, or terminology claims against authoritative evidence whenever a finding depends on them. Prefer the project's glossary and current primary documentation.
- The workflow covers its inputs, required decisions, output, and important failure or exception paths.
- The amount of prescribed procedure matches the task: constrain fragile operations, but leave judgment where several valid approaches exist.
- Forward-test brittle or non-trivial workflows with a representative task. If that is not practical, disclose the untested behavior.

#### Consistency and Completeness

- Use one name for each concept. Frontmatter, body, metadata, filenames, and companion resources agree.
- Answer the first practical questions raised by every declared use case; do not add speculative cases merely for completeness.
- When reviewing a change, verify that its description matches the files and behavior actually changed.
- Do not let a skill contradict its own guidance.

#### Orthogonality and DRY

- Give each rule one authoritative home. Elsewhere, include only a concrete reminder needed at the point of use.
- Separate unrelated concerns and remove recaps, filler, and repeated prohibitions that add no decision or action.
- Keep the skill self-contained: remove hidden assumptions about sibling skills and unexplained private vocabulary.
- Extract shared material only when it has the same meaning and the same reason to change in every use site.

#### Terminology and Prose

- Prefer established domain terms. If a local convention deliberately broadens one, label the convention, explain the trade-off, and handle its practical consequences.
- Use one meaning per term within the skill.
- Prefer plain, concrete instructions. Remove formulaic or stilted prose, long abstract noun chains, slogans, empty bullets, and legal or procurement language.
- Keep concrete domain examples when they teach a non-obvious distinction; remove examples that merely repeat a rule.
- Describe observable text and behavior. Do not infer who or what produced the prose.

### 4. Validate When Applicable

- Run the repository's skill validator and check frontmatter, directory naming, and agent metadata.
- After a rename or move, search for stale references and verify skill discovery paths.
- For a pull request, verify the exact head, merge base, current base, CI status, naming conventions, and validation claims in the description.
- Treat a passing validator or green CI as structural evidence, not proof that the workflow is correct.
- Test scripts or resources whose behavior is required for the skill to work.

### 5. Report

Start with one conclusion:

- **Pass**: no substantive issue prevents the skill from fulfilling its declared purpose.
- **Changes required**: one or more substantive issues must be resolved.

Then group actionable findings under **Required changes**, **Terminology and prose**, or **Minor** as appropriate. For each finding, give the location, evidence, impact, and the smallest practical alternative that preserves the intent. Keep optional improvements separate and include them only when they materially help. If there are no substantive findings, state **Pass** and stop.

Return the review in the medium the user requested. Edit files, post comments, or perform other remote writes only when the user explicitly authorizes them.

## Re-review

- Pin the previous and current versions.
- Verify every claimed fix in the artifact and relevant tests; a reply is not evidence by itself.
- Review new scope introduced since the previous review.
- For an item declined by design, verify that the accepted constraint and necessary mitigations appear in the authoritative material.
- Report with the same conclusion and finding format as the initial review.
