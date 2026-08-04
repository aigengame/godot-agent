---
name: entropy-review
description: Review software designs, implementation plans, and implemented changes from an agile perspective to determine whether their software entropy is proportionate to current goals. Identify scope drift, overengineering, excessive defensive design, premature generalization, and hard-to-maintain mechanisms whose costs outweigh their value; provide smaller, more reversible alternatives with faster feedback. Use when the user asks for an entropy review, design simplification, complexity control, an overengineering review, or whether a mechanism is worth introducing, retaining, or expanding.
---

# Entropy Review

## Objective

Review whether the software entropy introduced by a software design, implementation plan, or implemented change—the work under review—is proportionate to the problem it solves.

Do not optimize for the fewest lines of code, and do not reject architecture, testing, or defensive design. Distinguish between:

- Essential complexity inherent in the problem and its non-negotiable constraints.
- Accidental complexity introduced by implementation, technology, or representation choices rather than by the problem itself. Pay particular attention to speculation, a drive for completeness, premature planning, and mechanism-first thinking.

Protect working software, fast feedback, reversible evolution, and long-term comprehensibility.

Treat software entropy as the tendency of accumulating concepts, structures, states, rules, and coordination obligations to make a system increasingly difficult to understand, verify, and change.

Seek the minimum sufficient complexity for the current goal. Preserve necessary structure while preventing extra mechanisms from expanding under the banner of completeness or robustness.

## Workflow

### 1. Pin the Current Goal

Establish:

- What specific problem must be solved now?
- What facts prove that the problem exists?
- What observable outcome proves that the problem is solved?
- Which constraints must not be violated?
- Which adjacent problems are explicitly out of scope?

Mark judgments without evidence as assumptions. Do not use assumptions as reasons to expand the solution.

### 2. Describe the Minimum Sufficient Solution

Describe the smallest end-to-end solution that satisfies the current goal:

- Cover only currently specified behavior.
- Reuse existing concepts, structures, and paths where possible.
- Produce observable and verifiable results early.
- Preserve indispensable constraints.
- Do not require one change to solve future stages.

Use this solution as a comparison baseline, not as a predetermined final answer.

### 3. Inventory New Obligations

Identify every concept, layer, state, rule, process, role, exception, and long-term maintenance responsibility introduced by the work under review.

Ask for each one:

1. Which current goal does it directly serve?
2. What current evidence shows that it is needed now?
3. Which specified behavior or constraint would break if it were removed?
4. Is there a smaller, more direct, or more reversible alternative?
5. Can it be deferred until more feedback is available?
6. Does it exist only to support another newly introduced mechanism?
7. What ongoing understanding, synchronization, maintenance, and change costs does it create?

Do not retain mechanisms by default when these questions cannot be answered.

### 4. Identify Sources of Entropy

Check:

- **Goal entropy**: Check whether the work under review starts solving problems outside the current acceptance scope.
- **Concept entropy**: Check whether the expressive power of a new term or abstraction is proportionate to its cost.
- **Structural entropy**: Check whether added layers and indirection exceed what the problem requires.
- **State entropy**: Check whether the same fact has multiple representations that must remain synchronized.
- **Rule entropy**: Check whether a small number of exceptions causes broad, persistent constraints.
- **Coordination entropy**: Check whether a simple change starts requiring more knowledge, steps, or coordination.
- **Temporal entropy**: Check whether the work under review incurs certain costs now for benefits that depend on unverified future assumptions.

Use these dimensions to find problems. Do not turn them into a mechanical score.

### 5. Distinguish Essential from Accidental Complexity

Keep complexity that:

- Directly supports behavior that must be delivered now.
- Protects a known constraint that cannot be ignored.
- Prevents a significant loss demonstrated by current evidence.
- Remains necessary after a smaller solution has been shown to be insufficient.
- Reduces overall duplication, divergence, or long-term maintenance burden despite being locally complex.

Simplify, defer, or remove complexity that:

- Is justified mainly by “we may need it later.”
- Substitutes “more complete,” “more advanced,” or “commonly done” for current evidence.
- Builds general capability when only one concrete use case exists.
- Requires more mechanisms to explain, verify, or maintain the new mechanism.
- Adds certain recurring costs to cover speculative risks.
- Solves adjacent problems without satisfying the current goal more directly.
- Plans multiple future stages before the first working result exists.

### 6. Run the Agility Check

Check whether the work under review:

- Can be delivered in small increments instead of waiting for overall completeness.
- Produces observable progress at every step.
- Obtains feedback about use, operation, or maintenance early.
- Allows local modification, reversal, or replacement.
- Makes decisions from current learning instead of trying to enumerate the future in advance.
- Focuses effort on working results rather than structures that exist only to support the work itself.
- Avoids work that the current goal does not require.

If the work under review requires a long investment before its core judgment can be tested, split it into smaller increments or run an experiment first.

### 7. Decide the Disposition

Choose one primary disposition for each mechanism:

- **Keep**: Keep mechanisms that are currently necessary and whose evidence is proportionate to their cost.
- **Simplify**: Simplify mechanisms whose goals are valid but whose implementation creates unnecessary obligations.
- **Reuse**: Reuse existing capabilities when the need is valid and current capabilities are sufficient.
- **Defer**: Defer decisions that may have value but lack current evidence.
- **Remove**: Remove mechanisms that drift from the goal or cost substantially more to maintain than their current value.
- **Experiment**: Test the key assumption cheaply before deciding whether to build the mechanism.

Do not merely label something “overdesigned.” Provide a smaller alternative that still satisfies the current goal.

### 8. Order the Lean Implementation

Organize the work in this order:

1. Remove content that drifts from the current goal.
2. Define the minimum verifiable outcome.
3. Reuse existing capabilities.
4. Deliver the smallest end-to-end slice.
5. Obtain feedback and test key assumptions.
6. Add the next layer of complexity only after evidence appears.

Stop expanding when the current goal is satisfied and the next step is driven only by future assumptions.

## Common Anti-patterns

- **Multiple representations for one fact**: When several representations, rules, or synchronization duties protect one outcome but create no independent value, prefer one source of truth and verify observable results directly.
- **A general system before a confirmed problem**: When the work under review adds broad coordination or control capabilities before confirming the bottleneck, measure and narrow the problem first.
- **Generalization for one use case**: Implement the current slice first; extract common behavior only after another real use case reveals a stable difference.
- **Self-reproducing defenses**: When one protective mechanism creates further verification and maintenance mechanisms, return to the original risk and choose protection proportionate to its probability and impact.
- **Complete up-front planning**: Deliver the smallest slice that tests the core judgment before enumerating future stages, exceptions, and extension points.
- **Opportunistic scope expansion**: Record adjacent problems as later options instead of obscuring the current acceptance goal or expanding the change and regression surface.
- **Sophistication over fitness**: Require current evidence and observable outcomes; do not accept the work under review merely because it appears systematic, advanced, or complete.

## Output Contract

Provide:

1. **Verdict**: Choose **Adopt as is**, **Adopt after simplification**, or **Do not recommend**. Explain the primary basis in one paragraph.
2. **Current goal and minimum sufficient solution**: State the problem, observable completion outcome, non-negotiable constraints, and minimum sufficient solution.
3. **Review findings**: For each actionable finding, state the mechanism, goal relationship, evidence, entropy cost, disposition, and a smaller alternative that preserves the same goal.
4. **Essential complexity**: Identify what must remain and why.
5. **Lean implementation order**: Provide independently verifiable steps with fast feedback.
6. **Assumptions to test**: List unsupported assumptions and the cheapest way to test each one.

Report only findings that can change a decision or implementation approach. If no substantive issue exists, return **Adopt as is** and stop; do not manufacture findings to fill the format.

## Boundaries

- Preserve essential complexity; do not treat all complexity or every new abstraction as harmful.
- Do not remove checks that an architecture still needs merely to reduce complexity. Keep the checks, or clearly reduce or postpone what the design is expected to do.
- Treat architecture findings as advice. Leave approval, next steps, and changes to the agreed design to the designated human decision owner.
- When reviewing architecture, first clarify what the design must do and how it will be checked. Then compare the cost of the approach with simpler options.
- Do not use agility as a reason to ignore known risks, safety, integrity, or explicit external constraints.
- Do not replace engineering judgment with pseudo-precise scoring.
- Do not require extra artifacts merely to prove that the review occurred.
- Do not expand this skill into a comprehensive correctness, security, or style review.
- Do not redesign the whole system in the name of review unless the current goal requires it.
- Do not let the review cost exceed the scale of the decision being reviewed.
