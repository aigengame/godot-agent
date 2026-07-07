# Reference — Subagent + Worktree Parallel Development

Detailed recipes behind [SKILL.md](SKILL.md). Distilled from real fan-out-and-merge
runs. Project-agnostic: examples below say "a language without overloading", "a fast
tier that stubs the integration boundary", "an integration test that shares a global
resource" rather than naming any one stack — map them onto your own toolchain.

---

## 1. Dependency analysis & decomposition

Split the work into vertical slices, then classify every pair:

- **Independent (parallel-safe):** slices touching disjoint code/modules. Fan these out.
- **Coupled (must serialize):** two slices that extend the same component, or a
  foundational *tracer* plus its *round-out*. Land the tracer and **merge it first**,
  then fan out the round-outs. Parallel siblings that both scaffold the same thing
  duplicate it and collide at merge.

**Identify the append hotspots up front.** These are the shared files *every* slice
edits, where all the integration cost concentrates:

- central registries / enums / error-code tables
- dispatch / routing tables
- renderer / plugin / handler maps
- shared model or schema registration
- shared test files / fixtures
- public docs, command catalogs, generated/translated docs, and bundled agent skills
  that mirror the public surface

A wave whose slices all hammer the same hotspot is *not* a good parallel candidate —
expect a conflict-heavy serial merge, or fix it structurally first (§8).

**Assign each hotspot exactly one owner slice per wave.** When two slices *could*
legitimately touch the same shared file (one refactors a module, another instances it),
name the owner in both dispatch prompts: the owner edits; every other slice must **flag
the needed change in its report instead of editing** (the orchestrator — the "lead" — then serializes
or folds it into the owner's slice). Ownership converts a probable merge conflict into
an explicit coordination point: it **routes** a legitimate shared-file edit through one
slice — never suppresses it (the disjointness guardrail below still holds) — so a
non-owner's needed change lands via the owner, a lead-reassigned ownership, or a
serialized follow-up. One real wave ran a view-layer refactor in parallel with a
consumer of those same files at zero conflicts this way.

**Guardrail: disjointness is a merge-cost heuristic, not an architecture goal.** When
slicing for disjointness would suppress or distort a sound design decision, the design
wins:

- **Don't avoid a shared file just to keep a slice disjoint.** If a legitimate change
  belongs in a registry, a model module, or a *deep module* (a unit with a small
  interface over substantial implementation that is meant to be reused), put it there and
  **serialize that slice's merge** — don't sacrifice reusability (or bend scope) to
  manufacture disjointness. "I deliberately kept this out of `models.py` to decouple the
  slices" is the smell.
- **Don't let isolation hide a re-implemented deep module.** Worktree isolation defers
  duplicated/forked logic to merge or review, so parallel fan-out actively tempts each
  subagent to re-build shared logic in its own worktree. Before calling a slice's
  addition "new", confirm it isn't a thin projection of an existing deep module — *reuse
  the module*; a thin per-slice data shape (a DTO/wrapper) layered over it is fine, a
  second copy of its logic is not. Bake "did this reuse the existing deep module?" into
  the subagent DoD and the review — wire it into the operational surfaces, not just this
  prose (the dispatch-prompt DoD in §3 and the pre-launch checklist in §9).

This is the **complement of §8**: §8 *splits* hotspots so slices stop colliding; this
guardrail stops you from *degrading* a deep module to fake disjointness in the first
place. Splitting a shared file is a structural fix; suppressing a sound change to dodge
it is not.

**Re-run this analysis after any review-driven change — pre-flight disjointness expires.**
Fan-out disjointness is not merge-time disjointness. A correct remediation (a review fix
or a follow-up) often *must* touch a shared surface the slice originally avoided — a
central registry, an ABI, a doc table — creating **new** cross-slice overlap after the
pre-flight already said "disjoint". Recompute the overlap map after any such change; the
pre-flight verdict is not durable.

## 2. Wave sizing

- **≤ ~5 independent slices per wave.** (A run that tried ~9 at once hit two failure
  modes: subagents truncated at run limits, and a merge treadmill.)
- **Merge the whole wave before starting the next.** Each rebase then lands on a stable
  base. Skipping this creates the *treadmill*: merge one PR, every other open PR goes
  `CONFLICTING`, rebase them all, merge the next, they all re-conflict again.
- Larger waves also raise the chance an agent is cut off mid-task (losing uncommitted
  work — see §7).

## 3. Dispatching an implementer subagent (with a worktree)

Launch one subagent per slice in its own git worktree. The harness usually pre-creates
the worktree on an auto-named branch. Dispatch prompt should pin down these points:

```
You are implementing <slice> in an ISOLATED git worktree.

- Operate ONLY inside your own worktree directory. Before any git command, confirm
  `git rev-parse --show-toplevel` is your worktree root — NEVER run git ops against the
  shared main checkout.
- To name your branch, RENAME the pre-created branch in place: `git branch -m <name>`.
  Do NOT use `git switch -c <name>` (your shell cwd can reset to the shared checkout
  between calls, so `switch -c` may create a stray branch there).
- Commit early and often, even WIP — a truncated/killed run only loses UNcommitted work.
- Definition of Done: the INTEGRATION-tier test passes (the tier that actually exercises
  the integration boundary — integration / e2e / compile / a parse `--check-only`), not
  just the fast tier that stubs it. Do not satisfy DoD by deselecting the integration
  tier (e.g. a pytest-style `-m "not <integration>"` filter — or your runner's equivalent).
- Also part of DoD — beyond the test tiers, mirror the repo's NON-TEST PR-CI gates: read
  the gate list off the CI workflow itself (do not recite it from memory) and run each
  gate exactly as CI invokes it (same commands/flags) — typically the formatter CHECK,
  linter, typecheck, and build/packaging. A green test run with a red format check still
  bounces the PR.
- If a shared file is OWNED by a sibling slice this wave (the prompt names the owners),
  do NOT edit it — flag the needed change in your report and let the orchestrator route it.
- Also part of DoD — deep-module reuse: if your change belongs in a shared/deep module (a
  central helper, model, or a spawn/launch primitive), REUSE it — do NOT re-implement its
  logic in your worktree. A thin per-slice wrapper over an existing module is fine; a
  second copy of its logic is not. If the right change belongs in a shared file, don't
  dodge it to stay disjoint: when YOU own that file this wave (or it has no owner), make
  the change there and flag it in your report; when a SIBLING slice owns it, flag it for
  the owner/orchestrator instead of editing (previous line) — the lead reassigns
  ownership or serializes the slice, but the change still lands.
- When done: **commit and push your branch — do NOT open the PR.** The orchestrator opens
  every PR so the close-vs-reference keyword and PR conventions are applied in one place.
  Report the branch name, the commit SHA, the exact test command + its result counts, the
  linked issue/spec and **whether your slice fully satisfies it or only advances it** (so the
  lead can choose `Closes #N` vs `Refs #N`), and any deep module you reused or shared file
  you had to touch.
```

Worktree setup / cleanup:

```bash
git worktree add -b feat/<slice> ../wt-<slice> origin/main   # worktree on a FRESH branch off main
# ... agent implements, commits, pushes; the orchestrator opens the PR ...
git worktree remove ../wt-<slice>                            # ONLY after its PR is merged
```

> Create the branch *with* the worktree (`-b`). `git worktree add ../wt origin/main`
> (no `-b`) checks out in **detached HEAD**, so a follow-up `git branch -m` fails with
> "cannot rename the current branch while not on any". The in-place `git branch -m`
> above is only for the *harness-pre-created* branch case, where a branch already exists.

> **Why `git branch -m`, not `switch -c`:** all worktrees share one `.git`, so refs are
> global and a branch op meant for the worktree can land on the shared checkout when the
> cwd has reset. Observed leaking to the parent's `main`/HEAD (even via `git reset
> --hard`) more than once — see §7 for the verification that catches it.

## 4. Merge recipe (serial, dependency order)

Merging is an ordered serial workflow, not a fan-out:

1. **Tracer first**, then **rebase each follower onto the new base**, then independent
   groups can merge in any order.
2. **Re-poll mergeability after every merge** — the host (e.g. GitHub) recomputes it
   asynchronously, so a `CLEAN` PR can flip to `CONFLICTING` once a sibling merges.
3. **A clean auto-merge still gets the integration gate** (§6) — the marker-free traps
   in §5 hide precisely in conflict-free rebases.

**Base remediation invalidates dependent PR evidence.** If PR-A is the base for PR-B,
then every review fix, doc fix, or force-push on A requires a fresh B check. Rebase B
onto A's updated head, re-run the gates that cover the touched surface, and inspect B's
user/agent-visible docs before treating it as merge-ready. A dependent PR can be green
and still be stale because the base changed after its CI run.

### Stacked PR after its base was squash-merged

If the repo **squash-merges** and PR-B is stacked on PR-A, then once A is squash-merged
into main, do **NOT** `git merge origin/main` into B: B carries A's *individual* commits
via the branch point while main now has A as *one* squash commit, so git sees divergence
and conflicts on **every file A touched** (even files B never edited).

Replay only B's own commits onto main instead. If B is a normal branch with only B's
commits after A, preserve its commit structure:

```bash
git -C <B-worktree> fetch origin
git -C <B-worktree> rebase --onto origin/main <old-A-branch-or-sha> B-branch
# resolve only genuine A↔B overlap, run fast + integration tiers, then:
git -C <B-worktree> push --force-with-lease
```

If B has messy local history and you want a single merge commit's worth of B content,
squash B first, then replay it:

```bash
# Scope EVERY mutating git command with `-C <B-worktree>` (per §3/§7 — never let a
# command run against the shared checkout because cwd reset). Don't chain with `&&`,
# which hides an unscoped second command.
base=$(git -C <B-worktree> merge-base B-branch A-branch)        # branch point where B forked off A
git -C <B-worktree> reset --soft "$base"                        # squash B → 1 commit ...
git -C <B-worktree> commit -m "<B title>"                       # ... (scoped: lands in B, not main)
git -C <B-worktree> rebase --onto origin/main "$base" B-branch  # 1 commit → ONE conflict pass
# resolve only the genuine A↔B overlap, run fast + integration tiers, then:
git -C <B-worktree> push --force-with-lease
```

> The portable lesson is host-agnostic: **replay only B's own commits with `git rebase
> --onto`; never merge the base in.** The `main` / `origin/main` names are just this
> example's base branch and remote — substitute your own.

After the replay, update the PR metadata before merging:

- retarget the PR to the real base branch if the host did not already do it
- remove stale "stacked on PR-A" text
- change `Refs #N` to `Closes #N` only if B now fully satisfies the issue
- refresh any verification evidence recorded in the PR description to the commands
  actually run on the post-rebase head
- wait for CI on the new head; old green checks belonged to the stacked base

## 5. The two silent merge hazards (no conflict marker; fast tests still pass)

Resolve append conflicts **keep-both**, but watch for these — neither leaves a marker,
and a stubbed fast tier passes anyway. **Only the integration tier catches them.**

1. **Shared-trailing-context trap.** Both sides of a conflict depend on lines *after* the
   `>>>>>>>` marker — a closing bracket that ends a builder/struct/field, a shared
   function-call tail, a shared final assertion. Naive "delete the markers, keep both
   halves" truncates the earlier (HEAD) side or fuses two definitions. **Fix:** give the
   HEAD side its **own** complete closing so both sides are independently whole.
2. **Silent same-name auto-merge.** In a language without overloading, git textually
   auto-merges two *semantically different* definitions that happen to share a name into
   adjacent duplicates — **with no conflict marker**. It fails at compile/parse, not at
   merge. Seen: two slices each defining a same-named helper, merged into a duplicate
   definition that broke every integration run.

**After resolving, always audit:**

```bash
git diff --check                       # whitespace / leftover merge markers
# duplicate definitions: extract the def NAME (do NOT keep line numbers — a `grep -n`
# prefix makes identical defs differ, so `uniq -d` would miss them):
grep -oE '(def|func|function)[[:space:]]+[[:alnum:]_]+' <file> | sort | uniq -d
# + grep the hotspots for duplicate registrations / enum entries / map keys
```

The grep is a fast pre-filter; the **authoritative** catch for a silent duplicate is the
parse/compile check in §6 (a `--check-only` / build step), which fails on the duplicate
the grep heuristic might miss in another language.

## 6. Verification & Definition of Done

- **Re-run the integration tier yourself before merging.** A `mergeable=CLEAN` rebase is
  exactly where the §5 marker-free traps hide; do not let CLEAN substitute for the gate.
- **Beware the test-tier blind spot.** A fast tier that stubs the integration boundary
  (fakes/mocks/in-memory doubles) never executes the merged artifact, so it passes on a
  broken merge. After touching an integration point, run the real tier (integration /
  e2e / compile / parse-check).
- **A green DoD is not spec conformance — re-read each slice against its *originating
  spec*.** Passing its own tests + CI proves a slice does what its author built, not what
  the spec/decision required; the author's tests inherit the author's blind spot. Before
  merging, the orchestrator adversarially re-reads each slice against the spec that
  spawned it and hunts the contract gap those tests can't see. This *front-runs* the fixed
  external per-PR review — it complements that review, never replaces or duplicates it —
  and how deep to go is the orchestrator's call.
- **Public-surface consistency is part of integration.** When a slice changes a public
  shape or user/agent-observable behavior, audit every mirrored surface before merge:
  CLI/help text, schema/model descriptions, command catalogs, README-style user docs,
  generated or translated docs and their sync markers, and bundled agent skills or
  playbooks. Re-run the repo's doc/skill/schema sync tests. Do this again after base
  review fixes in a stacked PR, because the dependent PR may carry stale help text or
  regenerated docs even when its code tests pass.
- **Run shared-global-resource tests SERIALLY across worktrees.** If the integration
  tier contends on a global resource — a shared log directory, a fixed port, a fixed
  on-disk fixture/path — concurrent runs across worktrees race and produce spurious
  failures (or crashes) that look like product bugs. Serialize those runs; keep only the
  isolated fast tier parallel.
- **Guard against silent skips.** A test that *skips* when a precondition is unmet (a
  missing binary, absent templates, a feature-detect that quietly returns false) leaves
  CI green while coverage silently drops. Turn on your runner's skip-reason reporting
  (so every skip and its reason is visible) and add a **hard assertion** that when the
  resource *is* present on disk, the precondition must be true — so a broken detector
  goes red, not silently skipped.
- **Fix a finding at the right altitude.** A defect that surfaces on one slice may be a
  *cross-cutting cause*. Fix it in a shared follow-up rather than band-aiding the one
  slice — especially when sibling slices each grew their own *partial* handling that the
  shared fix should later absorb (otherwise the duplication is what ships).
- **Sibling worktrees double as flake controls.** When a test fails in one worktree's
  full run, check the same test across the siblings before blaming the slice: the
  worktrees differ only by each slice's diff, so the same failure appearing in a sibling
  whose diff cannot touch that path points at infra, not the change. Adjudicate with:
  re-run the single test standalone, then demand one fully green full run — an
  intermittent display/timing-dependent test that passes both is a flake to note, not a
  blocker (but say so honestly in the PR).
- **Scale the heaviest gate to the wave, not the PR (a cost decision the lead sets).**
  When the full integration tier is expensive (long CI runs, real engines/devices), a
  workable economy is: per-branch risk covered by the lead's local serial runs (above),
  PR CI running only the cheap tiers, and ONE full-tier run on the merged trunk after
  the wave's last merge as the wave gate. The trade is deferred detection on the trunk —
  make it deliberately, not by default.
- **Close the review loop.** For actionable PR review comments, implement the fix,
  re-run the relevant gates, push, and reply or resolve the thread according to the
  repo's convention. Review remediation can touch shared docs or other hotspots, so
  update the overlap map and dependent PR plan after each review fix.

## 7. Resilience & takeover

- **Commit early.** Truncation/kill only loses *uncommitted* work; an agent cut off
  before committing can leave a broken, unsaved file in its worktree.
- **A review/fix round is a re-dispatch — restate the whole discipline.** Prefer
  resuming the ORIGINAL implementer (its context is intact), but do not assume it
  remembers the rules it followed last round: restate worktree pinning, commit-early,
  and the §3 DoD gates in the fix brief, and require **one commit per finding**. Kills
  strike mid-round too (session/usage limits, not just truncation) — one real agent
  finished an entire review/fix round and died with all of it uncommitted.
- **Takeover recipe for uncommitted work:** review the whole uncommitted diff yourself
  against the findings it claims to fix, run the same gates the dispatch DoD requires
  (§3: the integration tier plus the PR-CI gate list read off the CI workflow), then
  commit and push it under an honest message. Don't re-dispatch what a diff review can
  verify — and don't commit what you haven't read.
- **Trivial mechanical CI failures are the lead's to fix in place.** A formatter diff or
  an import sort on an otherwise-verified branch is cheaper to fix, test, and push
  yourself than to re-dispatch an agent for.
- **"Completed but no artifact" = needs-takeover.** Never trust a completion claim —
  independently verify with `git status` (clean?), `git log` (recent commits?), and
  remote-tracking (pushed?). Also seen: an agent reports done while its test run is "still
  settling" (no counts), or committed but never pushed — both are takeover, re-run and
  finish it yourself.
- **The orchestrator opens the PR — and decides `Closes #N` vs `Refs #N`.** PR creation is
  the lead's, not the subagent's (§3). Once a slice's pushed commits verify, open its PR
  yourself. Use the closing keyword `Closes #N` **only when that PR fully satisfies the
  linked issue** (all acceptance criteria, verified); for a tracer, round-out, or
  stacked/multi-wave slice that only *advances* the issue, use a non-closing `Refs #N` so a
  partial merge does not close it prematurely. Do not delegate the keyword to the subagent
  and spot-check it after: even when the brief demands it, subagent-authored PRs reliably
  bury or omit it — owning PR creation removes the failure mode.
- **Verify the shared checkout after every worktree agent.** Confirm the main checkout is
  still on its branch and clean (`git -C <main> branch --show-current`, `git status
  --short`, no stray branches) before relying on it — worktree agents have leaked git
  ops to it (§3).
- **Force-pushing a *feature* branch after a rebase is normal** (`--force-with-lease`).
  Distinguish it from touching shared/protected branches; don't let a generic
  "dangerous git" guardrail block the legitimate rebase → force-push of a PR branch you own.

## 8. Architectural fix: kill the hotspots

The durable cure for append conflicts is to stop appending to shared files: **split each
central registry / dispatch table / map so every module owns its own fragment that is
auto-collected** (one file per module, discovered/aggregated at build or load). Then
independent slices stop colliding at all, and per-PR conflict count drops from "many
files, many regions" toward 1–2. When the conflict tax is high, this is worth a dedicated
design decision (an ADR) of its own.

## 9. Pre-launch checklist

- [ ] Slices in this wave are independent (no shared module/group); coupled ones serialized.
- [ ] Wave ≤ ~5; will merge before the next wave.
- [ ] Every append hotspot has exactly ONE owner slice this wave; sibling prompts say "flag, don't edit" (§1).
- [ ] Each subagent's DoD includes the integration tier (not just the stubbed fast tier).
- [ ] Each subagent's DoD covers the PR-CI gate list read off the CI workflow itself — the test tiers plus the non-test gates (formatter check, lint, typecheck, build), invoked as CI invokes them (§3).
- [ ] Each subagent's DoD includes deep-module reuse — no re-implementing shared logic, and no dodging a legitimate shared-file edit, to fake disjointness (§1).
- [ ] Review/fix rounds restate the dispatch discipline (resume the original agent; one commit per finding); actionable review comments are closed with code/tests plus a finding→resolution reply or thread resolution on the review channel — by the lead, who re-verifies and keeps the PR/change description current where the host supports it (§6, §7).
- [ ] Agents pinned to their own worktree; will commit early; "done but no artifact" = takeover.
- [ ] Merge order decided (tracer first); after each resolution, audit for the marker-free traps.
- [ ] Stacked followers have an explicit retarget/rebase plan for after the base PR lands
      or receives review fixes; old base branch/SHA is recorded for `rebase --onto`.
- [ ] Shared-global-resource tests will run serially across worktrees.
- [ ] Orchestrator will independently re-verify before each merge.
- [ ] Any public-surface change has a docs/schema/help/agent-skill/i18n sync gate in the
      orchestrator's verification plan.
- [ ] PR creation is the orchestrator's: subagents commit + push only; the lead opens each PR and chooses `Closes #N` (only if the slice fully satisfies its issue) vs `Refs #N`.
- [ ] If append hotspots keep causing conflicts, consider splitting them (ADR).

## 10. Cost / benefit

| | |
|---|---|
| **Wins** | implementation wall-clock (large); context isolation (each agent's tool output stays out of the orchestrator); independent-perspective quality (adversarial review surfaces hidden issues — one slice even found a latent bug in neighboring code) |
| **Costs** | merging is serial and can be conflict-heavy; duplicated scaffolding; verification burden on the orchestrator; truncation risk at large batch sizes |
| **Net** | strongly positive for independent, modest-sized waves **with an integration-tier test gate**; neutral-to-negative for tightly-coupled slices hammering shared files |
