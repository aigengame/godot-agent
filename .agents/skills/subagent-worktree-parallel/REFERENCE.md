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

A wave whose slices all hammer the same hotspot is *not* a good parallel candidate —
expect a conflict-heavy serial merge, or fix it structurally first (§8).

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
  just the fast tier that stubs it. Do not satisfy DoD with `-m "not <integration>"`.
- When done: open the PR (or commit + push). Report the branch, the PR URL, and the
  exact test command + its result counts.
```

Worktree setup / cleanup:

```bash
git worktree add ../wt-<slice> origin/main      # new worktree off main
git -C ../wt-<slice> branch -m feat/<slice>      # rename in place (inside the worktree)
# ... agent implements, commits, pushes, opens PR ...
git worktree remove ../wt-<slice>                # ONLY after its PR is merged
```

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

### Stacked PR after its base was squash-merged

If the repo **squash-merges** and PR-B is stacked on PR-A, then once A is squash-merged
into main, do **NOT** `git merge origin/main` into B: B carries A's *individual* commits
via the branch point while main now has A as *one* squash commit, so git sees divergence
and conflicts on **every file A touched** (even files B never edited).

Replay only B's own commits onto main instead:

```bash
base=$(git merge-base B-branch A-branch)                 # branch point where B forked off A
git -C <B-worktree> reset --soft "$base" && git commit -m "<B title>"   # squash B → 1 commit
git -C <B-worktree> rebase --onto origin/main "$base" B-branch          # 1 commit → ONE conflict pass
# resolve only the genuine A↔B overlap, run fast + integration tiers, then:
git push --force-with-lease
gh pr edit B --base main && gh pr merge B --squash
```

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
git diff --check                       # whitespace/merge-marker leftovers
grep -nE '^\s*(def|func|function) ' <file> | sort | uniq -d   # duplicate definitions
# + grep for duplicate registrations / enum entries / map keys in the hotspots
```

## 6. Verification & Definition of Done

- **Re-run the integration tier yourself before merging.** A `mergeable=CLEAN` rebase is
  exactly where the §5 marker-free traps hide; do not let CLEAN substitute for the gate.
- **Beware the test-tier blind spot.** A fast tier that stubs the integration boundary
  (fakes/mocks/in-memory doubles) never executes the merged artifact, so it passes on a
  broken merge. After touching an integration point, run the real tier (integration /
  e2e / compile / parse-check).
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

## 7. Resilience & takeover

- **Commit early.** Truncation/kill only loses *uncommitted* work; an agent cut off
  before committing can leave a broken, unsaved file in its worktree.
- **"Completed but no artifact" = needs-takeover.** Never trust a completion claim —
  independently verify with `git status` (clean?), `git log` (recent commits?), the PR
  list (opened?), and remote-tracking (pushed?). Also seen: an agent reports done while
  its test run is "still settling" (no counts), or committed but never pushed — both are
  takeover, re-run and finish it yourself.
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
- [ ] Each subagent's DoD includes the integration tier (not just the stubbed fast tier).
- [ ] Agents pinned to their own worktree; will commit early; "done but no artifact" = takeover.
- [ ] Merge order decided (tracer first); after each resolution, audit for the marker-free traps.
- [ ] Shared-global-resource tests will run serially across worktrees.
- [ ] Orchestrator will independently re-verify before each merge.
- [ ] If append hotspots keep causing conflicts, consider splitting them (ADR).

## 10. Cost / benefit

| | |
|---|---|
| **Wins** | implementation wall-clock (large); context isolation (each agent's tool output stays out of the orchestrator); independent-perspective quality (adversarial review surfaces hidden issues — one slice even found a latent bug in neighboring code) |
| **Costs** | merging is serial and can be conflict-heavy; duplicated scaffolding; verification burden on the orchestrator; truncation risk at large batch sizes |
| **Net** | strongly positive for independent, modest-sized waves **with an integration-tier test gate**; neutral-to-negative for tightly-coupled slices hammering shared files |
