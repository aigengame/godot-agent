---
name: handle-review
description: Analyze, evaluate, and handle pull request review feedback before changing code. Verify each comment against the current PR head, requirements, project constraints, and runtime evidence; then decide with evidence whether to fully adopt, partially adopt, or not adopt it. Prevent minor inconsistencies, speculative risks, or reviewer-suggested mechanisms from causing disproportionate complexity, rigid processes, or regressions. Use when addressing PR review comments, evaluating findings, implementing accepted feedback, or drafting a reviewer reply.
---

# Handle Review

## Objective

Treat review feedback as engineering input to verify, not commands to execute.

A review can reveal a real problem while relying on an inaccurate premise, overstating its severity,
or suggesting the wrong solution. Judge separately:

- Whether the reported problem exists.
- Whether it is worth addressing now.
- Whether the suggested change is an appropriate and sufficiently small solution.

Protect correctness, existing working results, fast feedback, reversible changes, and long-term
comprehensibility. Do not introduce disproportionate software entropy merely to close a review,
eliminate a minor inconsistency, or satisfy an abstract idea of completeness.

## Core Principles

- Analyze and evaluate before making changes.
- Verify the problem and the suggested solution separately.
- Do not infer that a suggested solution is correct merely because it identifies a real local
  problem; a reviewer does not gain default authority to redesign the whole approach.
- Do not treat severity labels, forceful wording, or reviewer identity as evidence.
- Use consistency to reduce comprehension cost, not to justify new abstractions or global
  mechanisms.
- Preserve existing test, performance, compatibility, and architecture results unless evidence
  shows they should change.
- Keep complexity required to fix the current problem. Require credible risk to justify additional
  layers, state, rules, processes, or defensive mechanisms.
- Do not manufacture work so that every comment produces a change.

## Workflow

### 1. Establish the Review Baseline

Before handling feedback, confirm:

- The PR's exact current head, current base tip, merge base, and merge-base-to-head diff.
- The issue, acceptance criteria, design decisions, and project rules.
- Current observable behavior and tests that already pass.
- The baseline, target, and measurements for performance changes.
- Work explicitly outside the current PR.

Do not change code from an old head, stale documentation, or assumptions detached from the current
diff.

### 2. Separate Each Comment into Claims

For every review comment, identify:

1. **Problem claim**: What does the reviewer say is wrong?
2. **Evidence**: Which code, test, specification, measurement, or project rule supports the claim?
3. **Impact**: What observable consequence occurs if it remains unchanged?
4. **Suggested solution, if any**: What change does the reviewer propose?
5. **Uncertainty**: Which parts remain assumptions or require verification?

A comment can identify a real problem while proposing an excessive or incorrect solution.

### 3. Verify Whether the Problem Exists

Choose the minimum sufficient evidence for the type of claim:

- **Correctness or contract**: Reproduce the behavior and compare it with requirements, public
  interfaces, or the authoritative specification.
- **Testing**: Check the exercised path, assertion strength, isolation, and failure behavior.
- **Performance**: Compare repeatable before-and-after measurements and the critical path; do not
  infer performance from structure alone.
- **Architecture**: Confirm the current change boundary, dependency direction, and maintenance cost.
- **Standards**: Check the currently authoritative rule; do not treat history as a current
  requirement automatically.
- **Naming or style**: Confirm that the difference creates real comprehension or maintenance cost,
  rather than merely using near-synonyms.

Treat a failure to reproduce as unverified, not disproved. Seek alternative evidence or run a
risk-proportionate, bounded investigation before deciding. Do not convert a claim into a change
when it lacks current evidence or depends on future assumptions.

### 4. Evaluate the Entropy Cost of the Suggested Change

Ask:

- Does the change directly solve the verified problem?
- Which current behavior or hard constraint would fail without it?
- Is there a smaller, more local, or more reversible fix?
- Does it introduce new concepts, layers, state, synchronization rules, exceptions, or ongoing
  maintenance duties?
- Does it establish a permanent mechanism for a one-time minor inconsistency?
- Does it expand into adjacent problems outside the PR?
- Does it weaken existing test, performance, or maintainability results?
- Does the new mechanism require further mechanisms to explain, verify, or maintain it?

When the suggested solution costs substantially more than the problem, preserve the valid problem
claim but choose a smaller solution or do not adopt the suggestion.

### 5. Decide How to Handle Each Claim

Choose one primary decision for every independent claim or recommendation. Group them at the
comment level only when their evidence and decision match. When using **Partially Adopt** for a
mixed comment, identify the adopted and unadopted parts explicitly.

#### Fully Adopt

Fully adopt when all of the following are true:

- Current evidence confirms the problem.
- The problem should be addressed in this PR.
- When the reviewer suggests a solution, it is direct, sufficient, and free of material excess
  complexity.
- The change does not break a higher-priority constraint or an existing result.

State the supporting evidence, the change location, and the validation method.

#### Partially Adopt

Partially adopt when the problem is valid but the proposed scope is too broad, the implementation is
too heavy, or the suggestion contains a false premise.

Preserve the valid goal and use a smaller alternative. For example:

- Make a local correction instead of establishing a global mechanism.
- Isolate the actual source of contamination instead of disabling a shared optimized path.
- Correct a documentation fact without restoring an obsolete standing process.
- Preserve a measured design while fixing its demonstrated defect.

State what is adopted, what is not adopted, and why.

#### Do Not Adopt

Do not adopt when:

- Current evidence disproves the claim, or a bounded investigation finds no supporting evidence
  and the residual risk does not justify a change.
- The claim conflicts with the current specification, code, or measurements.
- The suggestion solves a problem outside the current scope.
- A minor difference creates no material comprehension or maintenance cost.
- The change would introduce substantially greater software entropy.
- The change would regress performance, coverage, compatibility, or architecture.

Do not adopt silently. Provide the evidence, explain what remains unchanged, and disclose any known
residual risk.

After making the decisions, confirm the authorized next action. Stop after evaluation when the
request is read-only. Run steps 6–8 only when changes are authorized. Run step 9 only when the user
requests a reply draft or authorizes an external response; post replies or resolve threads only with
explicit authorization.

### 6. Order the Accepted Changes

Handle accepted feedback in this order:

1. Correctness, security, data integrity, and public-contract problems.
2. Problems that fail acceptance or weaken test evidence.
3. Design problems with current maintenance cost.
4. Naming, documentation, and consistency problems that have a local fix.

Separate independent scope from the current PR. Do not use review fixes as an opportunity to
refactor the entire module.

### 7. Implement the Minimum Sufficient Change

- Change only the parts covered by an explicit decision.
- Reuse existing structures and test paths.
- Add or adjust relevant tests when behavior changes.
- Keep documentation aligned with the authoritative source and actual implementation.
- Do not introduce permanent artifacts merely to prove that the review was handled.
- Do not turn non-blocking advice into a new mandatory process.

### 8. Check for Regressions Caused by the Review Fix

After making changes, compare again:

- Is the original problem solved?
- Do the tests and contracts still hold?
- Are performance results preserved or improved?
- Did the diff expand unexpectedly?
- Did the change add unnecessary concepts, state, rules, or maintenance paths?
- Did fixing the review suggestion create a chain of fixes for the new mechanism?

For performance-related changes, compare before-and-after measurements. Revert a review-driven
change that worsens the target result unless it protects a higher-priority hard constraint.

Use independent re-review when risk or change size justifies it. Do not make independent re-review a
mandatory ritual for every small correction.

### 9. Reply to the Review

Explain the decisions and evidence instead of merely saying that the comments were addressed.

Report each independently evaluated claim in this form:

| Claim | Decision | Evidence | Change or retained behavior | Validation |
| --- | --- | --- | --- | --- |
| Brief problem statement | Fully Adopt / Partially Adopt / Do Not Adopt | Current code, specification, test, or measurement | Commit, file, or unchanged behavior | Tests, CI, measurements, or residual risk |

Also report:

- The current exact-head commit.
- Relevant tests and CI status.
- Anything not yet verified.
- Genuine disagreements that require a maintainer decision.

Do not claim that an inline thread was resolved when no such thread exists. A comment with no
valuable change can be closed with evidence; it does not need a commit.

## Output Contract

Provide:

1. **Review baseline**: Exact head, current base tip, merge base, merge-base-to-head diff,
   requirements, constraints, and verified facts.
2. **Decision for each claim**: Fully Adopt, Partially Adopt, or Do Not Adopt, with evidence.
3. **Change plan**: Only the minimum sufficient changes for adopted feedback.
4. **Validation**: Tests, CI, performance comparisons, and unverified items.
5. **Reviewer reply draft, when requested**: A concise response ready to send.

Report only findings that can change a decision or implementation approach. If no feedback warrants
a change, still provide the review baseline and a decision for every claim. For each **Do Not
Adopt** decision, state the evidence, retained behavior, and residual risk. Report that the change
plan is empty, record the validation and unverified items, and then stop. Do not manufacture
modifications.

## Boundaries

- Do not use entropy control to dismiss demonstrated correctness, security, data-integrity, or
  public-contract problems.
- Do not treat the reviewer's suggested implementation as the only solution.
- Do not introduce global abstractions, caches, manifests, protocols, gates, or standing processes
  for local consistency.
- Do not preserve a design disproved by evidence merely because work has already been invested in
  it.
- Do not replace verification with argument; declining feedback also requires evidence.
- Do not expand into a comprehensive review or architectural rewrite unrelated to the current
  feedback.
- Leave the final engineering decision to the maintainer; review supplies input and feedback.
