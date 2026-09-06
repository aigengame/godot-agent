# Implementation and review workflow

The owner authorized sequential implementation of milestone
[refactor&delete](https://github.com/aigengame/godot-agent/milestone/13), including
issue branches, commits, pushes, pull requests, independent review and integration
into a shared development branch. The final development branch waits for review;
this authorization does not merge it into `main` or publish a formal release.

## Branches and issue completion

`codex/gda-balancing-refactor-delete-dev` starts at
`fc7bac0025fde98c183ccddc6f82eddc58a9622e` on
`codex/gda-balancing-current-language-refactor`. It already contains the decision,
plan, evidence and reconciled authorities delivered for #866 in PR #881. The #866
delivery branch adds this execution workflow and verifies that inherited scope.

For each issue, branch from the current development head. Implement its complete
acceptance scope, record validation and rollback in its pull request, then push
and open the pull request against the development branch. Pin the reviewed base
and head. Independent subagents review Standards and Spec using `review`, and
domain structure using `design-domain-modular-architecture`. Resolve findings and
recheck changed scope before merging into the development branch. Keep the issue
open until its acceptance criteria and integration are evidenced. GitHub owns
live issue status and the pull request owns its review and validation receipt.

Follow the [issue graph](ISSUES.md) in dependency order. The existing #612 Formula
Runtime seam is a required predecessor of #876 and uses the same delivery
workflow. #870 and #871 are the explicitly permitted expand/migrate intermediate
states: integrate them only into this development branch, disclose intermediate
failures, and let #872 remove every transition form and restore the complete green
contract. They never merge independently into `main`.

At #879, validate the accumulated development head, including inherited changes,
all mandatory deletions and actual public consumers. Close #865 only when its own
acceptance criteria pass. Issue closure means delivery to the reviewed development
branch; it does not claim deployment to `main`, completion of other product
milestones, or formal release. Preserve a coherent rollback commit for each slice;
restore code, authority, authored sources and current evidence together.

## Delegated decisions

The owner delegated implementation decisions to the primary agent under
orthogonality, DRY, architectural consistency and control of unnecessary
complexity. The accepted deletion endpoint and causal non-RPG witness remain
binding. Engineering detail does not require another standing approval gate.

When evidence challenges the design, first reproduce the failure, isolate the
counterexample, compare the smallest viable changes and record the decision with
its validation impact. Resolve it within the delegated scope and update the
owning authority and affected acceptance criteria. A failed test is not permission
to weaken an accepted requirement or keep obsolete mechanisms indefinitely.

The independent simulation decisions in #509, incremental delivery in #745,
Panda cutover in #517 and deferred trust work in #542–#544 remain outside this
milestone. Preserve their current ownership and activation conditions. Do not
silently claim that this refactor completes them.
