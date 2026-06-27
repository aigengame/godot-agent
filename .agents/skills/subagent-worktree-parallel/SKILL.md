---
name: subagent-worktree-parallel
description: Run parallel development by fanning out independent feature slices to subagents in isolated git worktrees, then merging them serially under an orchestrating agent — covers dependency decomposition, wave sizing, dispatch prompts, merge-conflict hazards, and the integration-test gate. Use when planning to parallelize implementation across multiple subagents/worktrees, split a task for concurrent agents, fan out feature slices, or merge several feature branches back together; or invoked as /subagent-worktree-parallel.
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
- **The integration-tier test is the Definition of Done.** A fast tier that stubs the
  integration boundary passes even on a broken merge. DoD must run the tier that really
  exercises the boundary (integration / e2e / compile or a parse `--check-only`).
- **The orchestrator independently re-verifies before merging.** Subagent implements;
  the lead re-runs tests and spot-checks the diff. "Done but no artifact" = needs takeover.

## Workflow

```
decompose + dependency analysis → plan waves → fan out (implement) → merge serially (dependency order) → verify
```

1. **Decompose + analyze dependencies.** Split the work into vertical slices. Mark which
   are independent (parallel-safe) vs. coupled (must serialize). Up front, identify the
   **append hotspots** — central registries, enums, dispatch tables, render/plugin maps,
   shared test files that *every* slice edits — that is where merge cost concentrates.
   (REFERENCE §1)
2. **Plan waves.** Group independent slices into waves of ≤ ~5; sequence coupled slices
   tracer-first. Decide the merge order now. (REFERENCE §2)
3. **Fan out to implement.** Launch one subagent per slice in its own git worktree, each
   with a dispatch prompt that pins it to its worktree, tells it to commit early, and
   bakes the integration-tier test into its DoD. (REFERENCE §3)
4. **Merge serially in dependency order.** Tracer first → rebase followers onto the new
   base → independent groups can merge in any order. Re-poll mergeability after each
   merge. Watch for the two marker-free conflict traps. (REFERENCE §4, §5)
5. **Verify + take over.** Re-run the integration tier yourself (a *clean* rebase still
   needs it); run shared-global-resource tests serially; treat any "completed but no
   PR/commit/push" report as needs-takeover, not success. (REFERENCE §6, §7)

When append hotspots keep dominating merge cost, the durable fix is architectural —
split them into per-module fragments that auto-aggregate (REFERENCE §8). Run the
**pre-launch checklist** (REFERENCE §9) before every wave.
