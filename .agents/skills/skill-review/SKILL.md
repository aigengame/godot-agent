---
name: skill-review
description: Review skill documents (SKILL.md and companion files) for consistency, completeness, orthogonality, and terminology accuracy — flagging coined terms, generated-prose patterns, and legalistic phrasing, each with a smaller concrete alternative. Use when reviewing a new or changed skill document, reviewing a PR that adds or renames skills, or re-checking an author's claimed fixes after a skill review.
---

# Skill Review

## Goal

Review whether a skill document is **accurate** (terminology), **complete** (for its audience), and **economical** (orthogonal structure, no filler). Report only findings that can change a decision or an implementation; when nothing substantive is wrong, pass the document and stop — do not manufacture findings. Keep the review cost proportionate to the document's size. This skill holds itself to its own standards.

## Before Reviewing

- Read the whole skill directory: frontmatter, body, companion files (such as REFERENCE and EXAMPLES), and agent metadata files.
- Learn the skill family's collaboration model first — for example, skills that are deliberately uncoupled, self-contained, and orchestrated by the user. Review against that model, not against personal preference.
- Accept design decisions the author explicitly owns — labeled as a local convention, with the trade-off stated and its consequences handled. Review how well the decision is executed; do not reopen the decision itself.

## Checks

### Consistency

- One name per concept throughout. (Anti-example: the same hard-constraint idea phrased four different ways in one document.)
- Frontmatter and body corroborate each other: `name` matches the directory; the `description`'s scope matches the body's boundary. The description is the routing surface — agents select skills by it, so drift there is routing drift. (Anti-examples: "scope drift" in the description but "scope creep" in the body; a rename that broadens the name while the body's stated boundary is unchanged.)
- The document does not violate its own principles. (Anti-examples: mandating a fixed set of project roots while preaching the smallest sufficient architecture; a document about simplicity that is itself repetitive.)
- The change description (PR body) matches the actual content. (Anti-example: claiming to "clarify the one-way boundary" between two skills that never reference each other.)

### Completeness

- The first questions a practitioner hits when applying the document have answers. (Anti-examples: forbidding upward dependencies on the UI layer without saying who composes the UI; naming a known hazard three times without ever giving a rule for it.)
- Verdict and output vocabulary fit every declared input. (Anti-example: "Adopt as is" cannot apply to an already-merged change — that case needs keep, simplify, or revert.)
- New capabilities are reflected in the description's triggers.

### Orthogonality

- One authoritative home per rule; restatements elsewhere are at most concrete reminders, never a second authority. (Anti-example: a one-way dependency rule stated in five places.)
- One theme does not reappear in costume in every section. (Anti-examples: the same you-aren't-gonna-need-it theme in seven places; an anti-pattern catalog nearly 1:1 with an earlier checklist.)
- Recap-only closing sections and do-not pileups that add no information are deleted.
- When the family model keeps skills uncoupled: do not ask for cross-references, but do not tolerate anonymous ones either — a sentence that only makes sense against another, unnamed skill must be deleted or rewritten as a self-contained statement. (Anti-example: an ordering sentence that, read in its own document, can only refer to that document's own workflow step and contradicts it.)
- Private vocabulary from sibling skills does not leak in. (Anti-example: one skill family's house jargon appearing in an unrelated skill.)

### Terminology

- Never coin a term for a concept that already has an established name; report each coinage with its established replacement. (Anti-example: a private "X entropy" taxonomy standing in for scope creep, premature abstraction, needless indirection, duplicated state, special-casing, change amplification, and speculative generality; "complete up-front planning" for Big Design Up Front.)
- Never silently widen a domain-reserved word. A justified widening must be labeled a local convention, state its trade-off, and handle the consequences. Needing a paragraph to redefine an established word is itself the signal. (Example: widening Godot's `addons/` to mean any reusable library obliges the document to handle mixed first-/third-party ownership.)
- When the domain has a canonical maxim, name it — that anchors readers better than any restatement. (Example: Godot's "call down, signal up".)
- One word does not carry two meanings in one document. (Anti-example: "model" as both domain model and 3D model in a game-development document.)
- Remove non-standard terms and mixed-sense spellings. (Anti-example: "dialog cards"; "dialog" the window and "dialogue" the conversation mixed in one list.)

### Prose

- Generated-prose patterns: abstract noun chains of three or more items (cut to the two or three that matter), rhetorical flourish ("under the banner of …"), coined slogan headings, circular or empty bullets. Distinguish these from concrete domain example lists, which are content — keep those.
- Legalistic patterns: a defined term cited over and over (define once, then use natural references), case-file vocabulary ("Decide the Disposition"), verdict language mismatched to the object (procurement tone for a technical document), several phrasings coexisting for one concept.

## Environment Checks

- After a rename or move: a repo-wide search finds no stale references, and discovery mechanisms (such as symlinks into the skills directory) still resolve.
- The skill validation tool passes, when one exists.
- The change is based on the current main branch, CI is green, and commit and branch naming follow repository convention.
- Verify every validation claim in the PR body individually — especially "independent review found no findings" claims, which are often overstated.

## Output

1. **Verdict first**: pass, pass after revision, or do not recommend — with the primary basis in one paragraph.
2. **Findings in tiers**: must fix / terminology and prose / minor. Each finding states the location, the claim, quoted evidence, and a smaller concrete alternative that preserves the goal.
3. When the author's stated intent dissolves a finding's remedy, re-derive the remedy from that intent instead of withdrawing the finding. (Example: a deliberate no-cross-references model invalidates "add a cross-reference" but sharpens the finding into "delete the anonymous ordering sentence".)
4. Positive suggestions are findings too. (Example: recommending the domain's canonical maxim by name.)

## Re-review

- Verify every claimed fix in the text itself; never accept the reply as evidence. (A "consolidated" duplicate pair has been observed to survive its own fix claim.)
- Re-read the full diff: identify scope added since the review that the reply does not mention, review it to the same standard, and require the change description to record it. (A whole new section has been observed to appear on a branch while the reply cited only the fix commit.)
- For items declined "by design": confirm the rationale and its mitigations actually appear in the text.
- Post the re-review result back to the PR: the residual list plus a merge recommendation. The human decision owner merges.
