# GitHub issue hierarchy and dependencies

Date: 2026-10-06. Decision for the Windows adaptation milestone: use one native parent/sub-issue level together with explicit blocked-by dependencies. The user authorized adoption if the research found useful, compatible semantics.

## Distinct responsibilities

| Relationship | Question answered | Use in this milestone |
| --- | --- | --- |
| Parent/sub-issue | Which tasks constitute this goal? | Overall design #1109 contains implementation issues #1110–#1124. |
| Blocked by | Which work must complete before this issue can proceed or finish? | Preserve the twenty implementation edges and the overall completion edge to final acceptance #1124. |
| Milestone | Which work belongs to this delivery target? | Group the overall design and fifteen implementation issues in milestone 20. |

GitHub documents sub-issues as decomposition and hierarchy, with parent navigation and progress. Projects can group/filter by parent and show the number of completed sub-issues. This gives the overall design a direct work list and progress view instead of relying on body links alone. No additional Project, nested stage issues or workflow automation is required. [Adding sub-issues](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/adding-sub-issues), [parent/progress fields](https://docs.github.com/en/issues/planning-and-tracking-with-projects/understanding-fields/about-parent-issue-and-sub-issue-progress-fields).

GitHub separately documents dependencies as blocked-by/blocking relationships and displays a Blocked indicator. Dependency APIs and hierarchy APIs are separate, and CLI machine-readable fields expose both. Hierarchy therefore must not be used to infer execution ordering. [Issue dependencies](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/creating-issue-dependencies), [hierarchy navigation](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/browsing-sub-issues).

## Application and limits

For example, #1119 (runtime game) and #1121 (observations) both belong to #1109 and both depend on #1118 (first owned headless session). They do not block each other merely because they share a parent. #1124 remains the explicit final integration gate; #1109 depends on its acceptance for completion, not the reverse. The accepted design does not add a new approval prerequisite to implementation.

Use one parent level: fifteen tasks are well within GitHub's documented limit of 100 direct sub-issues and eight hierarchy levels. More hierarchy is unnecessary for this scope. The native progress count is a closed-issue count, not elapsed effort or proof of Windows parity. Acceptance checklists and actual final e2e/Unix evidence remain authoritative. Avoid copying every containment relation into blocked-by links; declare only genuine execution/completion dependencies.

## Verification

Context7 resolved current GitHub documentation and supplied hierarchy/dependency references; exact primary pages resolved progress semantics. During the temporary blocked-by-only configuration, read-back showed #1109 with zero children and blocked-by #1124; #1111 had parent null and blocked-by #1110. The combined configuration is verified separately in the publication manifest: fifteen native parent links, the exact dependency sets, unchanged bodies/labels/milestone membership and no extra execution dependencies created by hierarchy. This is a real repository check, not a hypothetical API claim.
