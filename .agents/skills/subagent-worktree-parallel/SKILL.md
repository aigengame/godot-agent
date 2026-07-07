---
name: subagent-worktree-parallel
description: Orchestrates parallel development by fanning out independent feature slices to subagents in isolated git worktrees, then merging them serially under an orchestrating agent — covers dependency decomposition, wave sizing, dispatch prompts, merge-conflict hazards, and the integration-test gate. Use when planning to parallelize implementation across multiple subagents/worktrees, split a task for concurrent agents, fan out feature slices, or merge several feature branches back together; or invoked as /subagent-worktree-parallel.
---

# Subagent + Worktree Parallel Development

**Parallelize the *doing*; serialize the *merging*.** Worktree isolation removes
write conflicts *during implementation* but only *defers* integration conflicts to
shared "hotspot" files. Whether the model pays off depends almost entirely on how
much your slices touch shared code — so fan out independent work, but treat merging
as an ordered, serial, verified step.

See **[REFERENCE.md](REFERENCE.md)** for the full recipes (dispatch prompt template,
merge configurations, the silent-merge-hazard catalog, the pre-launch checklist, and
the cost/benefit table).

## When to use

- **Fan out** across genuinely independent modules/subsystems whose code is disjoint.
- **Serialize instead** when slices are tightly coupled — two slices that both extend
  the same component, or both append to the same shared file, will collide at merge.
  Coupled work is sequenced, not parallelized.

## Core principles (non-negotiable)

- **Group-external parallel, group-internal serial.** Only independent modules run in
  parallel. Within one module, land the foundational "tracer" first and merge it, then
  fan out its round-outs — parallel siblings duplicate-scaffold and collide.
- **Small batches (≤ ~5), merge before the next wave.** Each rebase then lands on a
  stable base; large waves create a merge *treadmill* (every merge re-conflicts the
  rest) and raise the odds a subagent is truncated at a run limit.
- **The integration-tier test is the Definition of Done — and so is the rest of the
  PR-CI gate list.** A fast tier that stubs the integration boundary passes even on a
  broken merge: DoD must run the tier that really exercises the boundary (integration /
  e2e / compile or a parse `--check-only`). Beyond the test tiers, DoD must also mirror
  the repo's non-test PR-CI gates — read the gate list off the CI workflow itself, not
  from memory: typically the formatter *check*, linter, typecheck, and build/packaging —
  invoked exactly as CI invokes them. A green test run with a red format check still
  bounces the PR (every slice of one real wave tripped this). (REFERENCE §3, §6)
- **The orchestrator (the "lead") independently re-verifies before merging.** Subagent implements and
  **commits** (its own branch, in its worktree); the lead re-runs tests and spot-checks the
  diff. "Done but no artifact" = needs takeover.
- **PR creation and its body are the orchestrator's, not the subagent's.** A PR is a
  *merging* artifact, not a *doing* one: the subagent commits **and pushes** its branch but
  does **not** open the PR — the lead opens every PR and owns its body, base, labels, and the
  close-vs-reference keyword. That applies PR conventions in one place and lets the lead
  re-verify a slice against its spec *before* the PR exists. Subagent-authored PRs reliably
  omit or misplace the close keyword even when the brief demands it, so owning PR creation
  closes that gap by construction rather than by a fragile after-the-fact check.
- **`Closes #N` is a per-PR decision the lead makes after verifying — not a default.** Tag a
  PR `Closes #N` only when it *fully* satisfies the linked issue (all acceptance criteria,
  verified). A tracer, a round-out, or a stacked/multi-wave slice that only *advances* an
  issue must use a non-closing `Refs #N`, or the first partial merge closes the issue
  prematurely. The subagent reports whether its slice fully satisfies the issue; the lead
  decides the keyword.
- **Stacked PRs are live dependencies until merged.** When a base PR receives review fixes
  or is squash-merged, every dependent PR must be re-evaluated: rebase/retarget it, update
  stale PR body text and close-vs-reference keywords, then rerun the real gates on the new
  head. Old green CI on the stacked base is not merge evidence.
- **Public docs and agent-facing docs are integration surfaces.** If a slice changes a
  user/agent-visible behavior or public shape, verify the whole surface chain for that
  slice and its dependents — CLI/help, schemas, user docs, generated or translated docs,
  and bundled skills/agent guidance. Code tests alone can miss a documentation contract
  gap or a stale generated marker.
- **Disjointness is a merge-cost heuristic, not an architecture goal.** Never let "keep
  slices disjoint / avoid the append hotspot" suppress a sound design decision — a
  legitimate shared-module edit, deep-module *reuse*, or a single source for a public
  shape. When they conflict, **serialize that slice's merge** rather than degrade the
  architecture; and make "did this slice *reuse* the existing deep module (not
  re-implement it in isolation)?" part of each subagent's DoD — wired into the
  dispatch-prompt DoD and the pre-launch checklist, not just prose. (REFERENCE §1, §3, §9)

## Workflow

```
decompose + dependency analysis → plan waves → fan out (implement) → verify + open PRs (per slice) → merge serially (dependency order)
```

1. **Decompose + analyze dependencies.** Split the work into vertical slices. Mark which
   are independent (parallel-safe) vs. coupled (must serialize). Up front, identify the
   **append hotspots** — central registries, enums, dispatch tables, render/plugin maps,
   shared test files that *every* slice edits — that is where merge cost concentrates —
   and give each hotspot exactly **one owner slice** for the wave; the others flag needed
   changes instead of editing. (REFERENCE §1)
2. **Plan waves.** Group independent slices into waves of ≤ ~5; sequence coupled slices
   tracer-first. Decide the merge order now. (REFERENCE §2)
3. **Fan out to implement.** Launch one subagent per slice in its own git worktree, each
   with a dispatch prompt that pins it to its worktree, tells it to commit early and push its
   branch but not open the PR (the orchestrator does), and bakes the integration-tier test
   into its DoD. (REFERENCE §3)
4. **Verify, open PRs, take over.** As each implementer finishes — and before anything
   merges — re-run the integration tier yourself; run shared-global-resource tests
   serially; audit any public docs/agent docs surface; treat any "completed but no
   commit/push" report as needs-takeover, not success. **You** (not the subagent) open
   each PR, choosing `Closes #N` only when the slice fully satisfies its issue (else
   `Refs #N`). (REFERENCE §6, §7)
5. **Merge serially in dependency order.** Tracer first → rebase followers onto the new
   base → independent groups can merge in any order; a *clean* rebase still gets the
   integration gate. Re-poll mergeability after each merge. For stacked PRs, retarget
   followers after the base lands and update any stale `Refs`/`Closes` or recorded
   verification text before merging. Watch for the two marker-free conflict traps.
   (REFERENCE §4, §5)

This path is **not one-shot**: independent review sends merged-ready slices back, and
remediation reshapes the plan. A review/fix round is a **re-dispatch** — resume the
original implementer with its context where possible, restate the full dispatch
discipline (worktree pinning, commit-early, the full DoD gates — integration tier plus
the PR-CI gate list), and require **one commit
per finding** so a mid-round kill is cheap to take over. The lead then re-verifies and
closes the loop on the review channel — e.g. a reply mapping each finding → resolution —
keeping the PR/change description current where the host supports it.
Re-derive the overlap map and merge order as fixes land, verify each slice against its
*originating spec* (not just its own green tests), and fix a finding at the altitude of
its true cause, not where it surfaced. (REFERENCE §1, §6, §7)

When append hotspots keep dominating merge cost, the durable fix is architectural —
split them into per-module fragments that auto-aggregate (REFERENCE §8). Run the
**pre-launch checklist** (REFERENCE §9) before every wave.
