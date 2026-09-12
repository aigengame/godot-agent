---
name: subagent-worktree-parallel
description: Plans and, when authorized, orchestrates parallel development by fanning out independent feature slices to subagents in isolated git worktrees, then integrating them serially under an orchestrating agent. Covers permission boundaries, dependency decomposition, wave sizing, dispatch prompts, merge hazards, and validation gates. Use when planning concurrent work, running parallel implementation across worktrees, or integrating dependent feature branches; or invoked as /subagent-worktree-parallel.
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

## Choose the operating mode and permissions

- **Planning-only:** produce the dependency map, slice briefs, wave plan, merge order,
  validation plan, and permission requests. Do not create worktrees or branches, edit files,
  commit, push, open change requests, merge, or write to a remote tracker.
- **Execution:** perform only the local mutations that the user authorized. Worktree creation,
  file edits, and commits do not imply permission to push, open or update a change request,
  merge, reply to reviews, or change remote tracker state. Record remote-write permissions
  separately and stop at a local handoff when they are absent.

## Core principles (non-negotiable)

- **Group-external parallel, group-internal serial.** Only independent modules run in
  parallel. Within one module, land the **foundation slice** first, then fan out its
  **dependent follow-up slices**. A foundation slice establishes the smallest shared
  contract or scaffold that its follow-ups require; parallel follow-ups before it lands
  duplicate that foundation and collide.
- **Small batches (≤ ~5 by default), merge before the next wave.** Each rebase then
  lands on a stable base; large waves create a merge *treadmill* (every merge
  re-conflicts the rest) and raise the odds a subagent is truncated at a run limit.
  Bigger waves are workable only with the REFERENCE §2 lifting discipline (owned
  hotspots with pre-tested resolutions, wave-batched reviews, one serial merge pass).
- **The real integration boundary is part of Definition of Done.** A fast tier that stubs
  that boundary can pass on a broken merge. Run every locally reproducible gate that covers
  the change, including the real integration/e2e/compile/parse path and relevant non-test
  checks. Classify gates that require protected infrastructure, secrets, policy evaluation,
  or unavailable hardware as **CI-only**. If a gate cannot run, record why, the substitute
  evidence, and the remaining risk; never report it as passed. A capability-gated test must
  demonstrably execute in at least one enforced tier — split the core behavior out of the
  gate. Report the numbers you MEASURED, quoting the tool's own summary line and naming the
  host: a count from memory, or a capability-rich host's total presented as CI's, reads as a
  defect in the claim. (REFERENCE §3, §6)
- **The orchestrator (the "lead") independently re-verifies before merging.** Subagent implements and
  produces the authorized local artifact in its worktree; the lead re-runs locally
  reproducible gates and spot-checks the diff. "Done but no artifact" = needs takeover.
- **Remote writes need explicit authority.** Pushes, change-request creation or edits,
  merges, review replies, and tracker updates are separate permissions. When authorized,
  the orchestrator owns the integration record and its completion semantics. Mark a work
  item complete only when the slice satisfies all of it; a foundation slice, dependent
  follow-up slice, or other partial slice remains non-closing.
- **Stacked change requests are live dependencies until merged.** When a base change receives
  review fixes or is squash-merged, every dependent change must be re-evaluated: rebase or
  retarget it, update stale descriptions and completion semantics, then rerun the applicable
  gates on the new head. Old validation on the stacked base is not merge evidence.
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
choose mode/permissions → decompose + dependency analysis → plan waves
  planning-only → return the plan
  execution → fan out → verify locally → publish/merge only when separately authorized
```

1. **Choose mode and permissions.** Record planning-only or execution, the allowed local
   mutations, and each allowed remote write. Do not infer execution from a planning request
   or remote authority from local implementation authority. (REFERENCE §3)
2. **Decompose + analyze dependencies.** Split the work into end-to-end slices. Mark which
   are independent (parallel-safe) vs. coupled (must serialize). Up front, identify the
   **append hotspots** — central registries, enums, dispatch tables, render/plugin maps,
   generated/stamped artifacts (translation stamps, lockfiles), shared test files that
   *every* slice edits — that is where merge cost concentrates — and give each hotspot
   exactly **one owner slice** for the wave; the others flag needed changes instead of
   editing. A flagged change still lands in a file before that slice merges, and
   ownership expires when the owner finishes without it. (REFERENCE §1)
3. **Plan waves.** Group independent slices into waves of ≤ ~5; sequence each foundation
   slice before its dependent follow-up slices. Decide the integration order now. In
   planning-only mode, return the plan here. (REFERENCE §2)
4. **Fan out to implement.** In execution mode, launch one subagent per slice in its own
   git worktree. Its dispatch prompt pins the worktree, states local and remote permissions,
   requires early durable local artifacts when authorized, and includes the applicable
   validation gates. (REFERENCE §3)
5. **Verify, hand off, or publish.** As each implementer finishes, run locally reproducible
   gates, serialize shared-global-resource tests (REFERENCE §6: lock-directory protocol and
   stale-lock arbitration), red-proof each fix round's regression against the head that was
   reviewed — from COMMITTED state, since the red-proof swaps the source tree — audit
   affected public surfaces, and record
   every CI-only or unavailable gate with substitute evidence and remaining risk. If remote
   writes are not authorized, return the local artifact and stop. If they are authorized,
   the orchestrator performs only the listed remote actions. (REFERENCE §6, §7)
6. **Merge serially in dependency order when authorized.** Foundation slice first → rebase followers onto the new
   base → independent groups can merge in any order; a *clean* rebase still gets the
   applicable integration gate — including re-running the consuming slice's tests on the
   rebased tree, because two independently-green slices can collide only there (one changes
   what a shared function guarantees, the other adds a caller relying on the old
   guarantee). Re-poll mergeability after each merge. For stacked changes,
   retarget followers after the base lands and update stale descriptions, completion
   semantics, or verification text before merging. Watch for the marker-free conflict traps.
   (REFERENCE §4, §5)

This path is **not one-shot**: independent review sends merged-ready slices back, and
remediation reshapes the plan. A review/fix round is a **re-dispatch** — resume the
original implementer with its context where possible, restate the full dispatch
discipline (worktree pinning, permissions, and the applicable local and CI-only gate
inventory). Follow the repository's commit-history policy. Require one commit per finding
only when the repository or user explicitly requires it; otherwise map each finding to its
resolution in the handoff. The lead then re-verifies and
closes the loop on the review channel only when that remote write is authorized — e.g. a
reply mapping each finding → resolution — keeping the change description current where
the host supports it.
Re-derive the overlap map and merge order as fixes land, verify each slice against its
source requirement (not just its own green tests), and fix a finding at the altitude of
its true cause, not where it surfaced. (REFERENCE §1, §6, §7)

When append hotspots keep dominating merge cost, the durable fix is architectural —
split them into per-module fragments that auto-aggregate (REFERENCE §8). Run the
**pre-launch checklist** (REFERENCE §9) before every wave.
