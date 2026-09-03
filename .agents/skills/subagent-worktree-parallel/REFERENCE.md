# Reference — Subagent + Worktree Parallel Development

Detailed recipes behind [SKILL.md](SKILL.md). Distilled from real fan-out-and-merge
runs. Project-agnostic: examples below say "a language without overloading", "a fast
tier that stubs the integration boundary", "an integration test that shares a global
resource" rather than naming any one stack — map them onto your own toolchain.

---

## 1. Dependency analysis & decomposition

Split the work into end-to-end slices, then classify every pair:

- **Independent (parallel-safe):** slices touching disjoint code/modules. Fan these out.
- **Coupled (must serialize):** two slices that extend the same component, or a
  **foundation slice** plus its **dependent follow-up slices**. A foundation slice
  establishes the smallest shared contract or scaffold that its follow-ups require.
  Land it first, then fan out the follow-ups. Parallel follow-ups that each scaffold the
  same foundation duplicate it and collide at merge.

**Identify the append hotspots up front.** These are the shared files *every* slice
edits, where all the integration cost concentrates:

- central registries / enums / error-code tables
- dispatch / routing tables
- renderer / plugin / handler maps
- shared model or schema registration
- shared test files / fixtures
- generated or stamped shared artifacts — checksums/markers computed over other
  content (translation-sync stamps, lockfiles, generated indexes)
- public docs, command catalogs, generated/translated docs, and bundled agent skills
  that mirror the public surface

A wave whose slices all hammer the same hotspot is *not* a good parallel candidate —
expect a conflict-heavy serial merge, or fix it structurally first (§8).

**Generated/stamped artifacts break the disjointness heuristic.** A file carrying a
checksum, stamp, or marker computed over other content (a translation-sync stamp, a
lockfile hash) conflicts even when two slices edit DISJOINT content regions — both sides
regenerate the marker to different values. Treat every such file as a guaranteed-conflict
hotspot: give it an owner like any other, expect the second slice's merge to need a
serialized rebase, and resolve by re-running the generator on the merged tree (§4) — a
hosting service's "mergeable" verdict taken before the sibling merged is not durable for
these files.

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

**Ownership is a wave-time lease, not a lock that outlives its owner — and a flagged
change must end in a landed edit.** Two real failure modes: (1) *Deferral is not
delivery.* A shared-file change parked in a report or change-request description is a
coordination message to the lead, not a shipped artifact — a reviewer will correctly fail
an acceptance criterion whose text exists only outside the artifact, especially for
user/agent-facing guidance. Every flagged change lands in a file before the flagging
slice's change request merges — pick one of the three routes above and schedule it.
(2) *The lease expires with the owner.*
When the owner slice finishes WITHOUT touching the shared file, the lead reassigns it to
the slice that needs it rather than keeping a now-pointless deferral alive.

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

- **≤ ~5 independent slices per wave, as the default.** (An early run in this skill's
  first era tried ~9 at once and hit two failure modes: subagents truncated at run
  limits, and a merge treadmill.)
- **Waves above ~5 are workable when three things hold, and are a treadmill without
  them:** every append hotspot has a named owner and each expected conflict has a
  pre-tested resolution; review rounds are batched across the wave (one round
  re-reviews every slice) instead of run per slice; and the whole wave merges in a
  single serial pass rather than one merge at a time. Waves of six and nine shipped
  this way. Below that discipline, ~5 is the ceiling.
- **Merge the whole wave before starting the next.** Each rebase then lands on a stable
  base. Skipping this creates the *treadmill*: merge one change request, every other open
  change becomes conflicting, rebase them all, merge the next, then repeat.
- Larger waves also raise the chance an agent is cut off mid-task (losing uncommitted
  work — see §7).

## 3. Planning and dispatching

Record the operating mode and permissions before creating a worktree or dispatching an
implementer:

- **Planning-only:** produce the dependency map, slice briefs, wave plan, integration order,
  validation plan, and any permission requests. Do not create worktrees or branches, edit,
  commit, push, open change requests, merge, reply to reviews, or update remote trackers.
- **Execution:** list the allowed local mutations. List each allowed remote write separately:
  push, change-request creation or update, merge, review reply, or tracker update. Permission
  to implement or commit does not imply any remote-write permission.

For planning-only work, stop after returning the plan. The rest of this section applies only
to execution mode.

Launch one subagent per slice in its own git worktree. The harness usually pre-creates
the worktree on an auto-named branch. Dispatch prompt should pin down these points:

```
You are implementing <slice> in an ISOLATED git worktree.

- Local mutation authority: <exact allowed actions and files>.
- Remote-write authority: <none, or an exact list of allowed actions>. Do not infer an
  unlisted push, change request, merge, review reply, or tracker update.
- Operate ONLY inside your own worktree directory. Before any git command, confirm
  `git rev-parse --show-toplevel` is your worktree root — NEVER run git ops against the
  shared checkout.
- To name your branch, RENAME the pre-created branch in place: `git branch -m <name>`.
  Do it BEFORE the first push: renaming a branch that already carries an open change
  request CLOSES that request on the host (`head_ref_deleted`), and reopening is
  refused — the only recovery is a successor request from the renamed branch plus
  cross-links, which scatters one slice's review trail across two.
  Do NOT use `git switch -c <name>` (your shell cwd can reset to the shared checkout
  between calls, so `switch -c` may create a stray branch there).
- If local commits are authorized, follow the repository's commit-history and checkpoint policy.
  Create reviewable durable checkpoints at safe boundaries; do not introduce work-in-progress or
  per-finding commits unless the repository or user requires them. Without commit authority, keep
  the diff reviewable and report its state at each handoff.
- Definition of Done: run every locally reproducible gate that covers the slice. Include
  the tier that exercises the real integration boundary — integration / e2e / compile /
  a parse `--check-only` — rather than only a fast tier that stubs it. Also run applicable
  non-test checks with the repository's documented commands and flags.
- Classify a gate as CI-only only when it depends on protected infrastructure, secrets,
  remote policy, or hardware unavailable locally. If any gate cannot run, report the
  reason, substitute evidence, and remaining risk. Do not report that gate as passed.
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
- When done, commit only if local commit authority was granted. Do not push or perform any
  other remote write unless the prompt lists that exact action. Report the branch, local
  commit or uncommitted diff, exact validation commands and results, CI-only/unavailable
  gates with residual risk, the source requirement, whether the slice fully satisfies it,
  and any shared module or file involved.
```

Worktree setup / cleanup:

```bash
git worktree add -b <slice-branch> <slice-worktree> <remote>/<base-branch>
# ... agent performs only the authorized local work and remote writes ...
git worktree remove <slice-worktree>  # only after its local artifacts are retained and integration is complete
```

> Create the branch *with* the worktree (`-b`). `git worktree add <worktree> <remote>/<base-branch>`
> (no `-b`) checks out in **detached HEAD**, so a follow-up `git branch -m` fails with
> "cannot rename the current branch while not on any". The in-place `git branch -m`
> above is only for the *orchestrator-pre-created* branch case, where a branch already exists.

> **Why `git branch -m`, not `switch -c`:** all worktrees share one `.git`, so refs are
> global and a branch op meant for the worktree can land on the shared checkout when the
> cwd has reset. A leaked operation can move the shared checkout's branch or HEAD, including
> through a reset. See §7 for the verification that catches it.

## 4. Merge recipe (serial, dependency order)

Merging is an ordered serial workflow, not a fan-out. Run local rebase/squash commands
only with execution authority, and run pushes or hosted merges only with the corresponding
remote-write authority.

1. **Foundation slice first**, then **rebase each dependent follow-up slice onto the new
   base**. Independent groups can integrate in any order.
2. **Re-poll mergeability after every merge** — a hosting service can recompute it
   asynchronously, so a previously mergeable change can become conflicting after a sibling merges.
3. **A clean auto-merge still gets the integration gate** (§6) — the marker-free traps
   in §5 hide precisely in conflict-free rebases.
4. **Regenerate, don't hand-merge, stamped markers — and resolve hunk-scoped, never by
   whole-file side-picking.** When the conflicting hunk is a generated checksum/stamp over
   content both sides changed, take either side's MARKER LINE only, merge the content
   normally, then re-run the project's generator on the merged tree and commit its output —
   the regenerated value is the only correct resolution (§1). A whole-file `checkout
   --theirs/--ours` for a one-line marker conflict silently erases the other side's already-
   merged content (a real run clobbered a merged sibling's translated rows this way). After
   ANY regenerate-style resolution, verify BOTH sides' content survived — grep the merged
   file for each slice's landmark content, don't trust a clean rebase.
5. **A clean rebase of disjoint files is not integration: re-test invariant handoffs.** Two
   slices can each be independently correct and collide only on the merged tree — one slice
   changes what a shared function GUARANTEES (a normalizer made total, an error path
   reshaped), the other adds a NEW CALLER relying on the old guarantee. Neither slice's own
   gates can see it; only the integrated tree can. At each serial merge, re-run the
   integration gate from item 3 and, at minimum, the consuming slice's tests on the
   REBASED tree before pushing, and
   treat a failure there as an integration defect to fix at the shared seam's altitude — as
   a commit on the branch being merged, not a band-aid in either slice.
6. **Designate the sentinel test for a known silent-sever point ahead of time.** When the
   planned rebase collision includes a hunk where one side DELETES the anchor line the other
   side's call is appended after (the wired-to-nothing trap), name — before merging — the
   single test that proves the wiring after resolution, and run it first. One test, named in
   advance, converts a silent sever into a loud check.

**Waves can land on an integration branch rather than the base branch.** When a
milestone runs several waves, slices merge into one long-lived integration branch and
that branch is promoted to the base branch per wave as its own change request. Two host
behaviours bite here. The allowed merge methods can differ between the two hops (slices
squashed, the promotion a merge commit so per-issue commits survive) — check and arrange
the method before the promotion, not during it. And a host with delete-on-merge
**destroys the integration branch when the promotion merges** (one milestone's ten
promotions deleted it ten times, seconds after each merge): recreate it from the
promoted base before dispatching the next wave, or the wave has no branch to land on.

**Base remediation invalidates dependent-change evidence.** If change A is the base for
change B, then every review fix, documentation fix, or history rewrite on A requires a
fresh B check. Rebase B onto A's updated head, rerun the gates that cover the touched
surface, and inspect B's user/agent-visible documentation before treating it as ready.
A dependent change can retain an old green result after its base has changed.

### Stacked change after its base was squash-merged

If the repository **squash-merges** and change B is stacked on change A, then once A is
squash-merged into the base branch, do **NOT** merge the base branch into B. B carries
A's individual commits via the branch point while the base now has one squash commit, so git sees divergence
and conflicts on **every file A touched** (even files B never edited).

Before any command that mutates B's index, worktree, or history, complete this local
preflight in B's worktree:

```bash
git -C <B-worktree> rev-parse --show-toplevel             # must be <B-worktree>
git -C <B-worktree> branch --show-current                 # must be <B-branch>
git -C <B-worktree> status --porcelain=v1                 # must be empty: index + worktree
git -C <B-worktree> fetch <remote>
git -C <B-worktree> rev-parse --verify <remote>/<base-branch>
original_tip=$(git -C <B-worktree> rev-parse <B-branch>)
test -n "$original_tip"
```

Stop if the root, branch, clean-state, base-refresh, or local-tip check fails. Keep `original_tip`
as the recovery reference. The fetch makes `<remote>/<base-branch>` current for both local-only and
published-branch rebases. A local-only rebase does not require B to have a remote branch.

When a push is authorized and planned, inspect B's remote state before rewriting history:

```bash
remote_result=$(git -C <B-worktree> ls-remote <remote> refs/heads/<B-branch>) || exit 1
expected_remote_sha=$(printf '%s\n' "$remote_result" | awk '{print $1}')
if test -n "$expected_remote_sha"; then
  git -C <B-worktree> merge-base --is-ancestor "$expected_remote_sha" "$original_tip" || exit 1
fi
```

An empty `expected_remote_sha` means that B is unpublished; it does not block the local rewrite.
If another process can touch the worktree, repeat the branch and clean-state checks immediately
before the rewrite. For a published branch, keep the recorded expected SHA until the push. Never
replace it with the post-rewrite local SHA.

Replay only B's own commits onto the base branch. If B contains only its own commits after
A, preserve its commit structure:

```bash
git -C <B-worktree> rebase --onto <remote>/<base-branch> <old-A-tip> <B-branch>
# resolve only genuine A/B overlap; run applicable locally reproducible gates; then verify:
git -C <B-worktree> branch --show-current                 # must still be <B-branch>
git -C <B-worktree> status --porcelain=v1                 # must be empty
# only with explicit push authority; force only when the branch was already published:
if test -n "$expected_remote_sha"; then
  git -C <B-worktree> push \
    --force-with-lease="refs/heads/<B-branch>:$expected_remote_sha" \
    <remote> HEAD:refs/heads/<B-branch>
else
  git -C <B-worktree> push <remote> HEAD:refs/heads/<B-branch>
fi
```

If B has messy local history and you want a single merge commit's worth of B content,
squash B first, then replay it:

```bash
# Complete the same preflight above first. Scope every mutation with `-C <B-worktree>`.
base=$(git -C <B-worktree> merge-base "$original_tip" <old-A-tip>)
git -C <B-worktree> reset --soft "$base"
git -C <B-worktree> diff --cached --check
git -C <B-worktree> commit -m "<B title>"
git -C <B-worktree> rebase --onto <remote>/<base-branch> "$base" <B-branch>
# resolve only genuine A/B overlap; run applicable locally reproducible gates; then verify:
git -C <B-worktree> branch --show-current                 # must still be <B-branch>
git -C <B-worktree> status --porcelain=v1                 # must be empty
# only with explicit push authority; force only when the branch was already published:
if test -n "$expected_remote_sha"; then
  git -C <B-worktree> push \
    --force-with-lease="refs/heads/<B-branch>:$expected_remote_sha" \
    <remote> HEAD:refs/heads/<B-branch>
else
  git -C <B-worktree> push <remote> HEAD:refs/heads/<B-branch>
fi
```

> The portable rule is: **replay only B's own commits with `git rebase --onto`; never
> merge the squash-merged base into B.** Preserve the original local tip, bind any history
> rewrite push to the exact remote SHA observed before the rewrite, and stop on drift.

After the replay, update the hosted change record before merging, but only with authority
for those remote writes:

- retarget the change to the real base branch if the host did not already do it
- remove stale text about its former stacked base
- mark the source work item complete only if B now fully satisfies it
- refresh any verification evidence recorded in the change description to the commands
  actually run on the post-rebase head
- wait for required CI-only gates on the new head before a hosted merge; old green checks
  belonged to the stacked base

If the required remote writes are not authorized, report each pending update and the
remaining merge risk without performing it.

## 5. The silent merge hazards (no conflict marker; fast tests still pass)

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

A third trap appears on MULTI-COMMIT rebases resolved keep-both: a later commit in the
same branch may REWORD the hunk an earlier commit introduced, so the keep-both you applied
at the earlier commit leaves the superseded version sitting beside the final one — stale
prose/bullets or an outdated definition that no conflict marks. Audit the FINAL tree, not
each resolution: grep for duplicated headings/bullets/definitions after the rebase
completes.

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

### Gate classification and reporting

Classify every required gate before execution:

- **Locally reproducible:** the required dependencies and environment are available without
  protected secrets or remote-only infrastructure. Run these gates locally with the authoritative
  commands and flags before integration.
- **CI-only:** the gate requires protected infrastructure, secrets, remote policy evaluation, or
  hardware that is not available locally. Do not simulate a pass. Record why it cannot run locally,
  the substitute evidence gathered, and the remaining risk. When remote execution is authorized,
  require its result on the exact candidate head before merge.

An unavailable local dependency does not automatically make a gate CI-only. First determine whether
the documented environment can be reproduced safely. If it cannot, record the limitation as above.

- **Re-run the locally reproducible integration tier yourself before merging.** A clean rebase is
  exactly where the §5 marker-free traps hide; do not let mergeability substitute for the gate.
- **Beware the test-tier blind spot.** A fast tier that stubs the integration boundary
  (fakes/mocks/in-memory doubles) never executes the merged artifact, so it passes on a
  broken merge. After touching an integration point, run the real tier (integration /
  e2e / compile / parse-check).
- **Report gate numbers you measured, and name the environment that produced them.** A count
  written from memory ("1899 passed") differed from the run ("1898 passed, 538 deselected"),
  and a display-capable host's "N passed" is not the CI line when tests are capability-gated
  (CI: "N-2 passed, 2 skipped" for the same selection). Reviewers re-run the gate, so a
  mismatched count reads as a defect in the claim and costs a round. Quote the tool's own
  summary line, distinguish selected/passed/skipped, and say which host ran it.
### Integration and cross-slice checks

- **A green DoD is not requirement conformance — re-read each slice against its source
  requirement.** Passing its own tests and hosted gates shows what the implementation does, not what
  the spec/decision required; the author's tests inherit the author's blind spot. Before
  merging, the orchestrator re-reads each slice against its source requirement and looks
  for contract gaps that its tests do not cover. This complements independent review; it
  does not replace it. The orchestrator selects review depth from the slice's risk.
- **Public-surface consistency is part of integration.** When a slice changes a public
  shape or user/agent-observable behavior, audit every mirrored surface before merge:
  command/help text, schema/model descriptions, public documentation, generated or
  translated artifacts, and bundled agent guidance. Rerun the project's applicable
  consistency checks. Do this again after base review fixes in a stacked change, because
  the dependent change can carry stale generated surfaces even when its code tests pass.
- **Run shared-global-resource tests SERIALLY across worktrees.** If the integration
  tier contends on a global resource — a shared log directory, a fixed port, a fixed
  on-disk fixture/path — concurrent runs across worktrees race and produce spurious
  failures (or crashes) that look like product bugs. Serialize those runs; keep only the
  isolated fast tier parallel.
  A working mechanism is a shared lock DIRECTORY in a scratch path every dispatch prompt
  names: `mkdir` to acquire (atomic), `rmdir` to release, bounded retries while held. Two
  hygiene rules keep it live: acquire immediately BEFORE the serialized run and release
  immediately after it returns (also on failure) — never pre-acquire ahead of other work,
  and never hold the lock across the agent's own pause or handoff (a real run stranded a
  pre-acquired lock for half an hour when its holder was suspended, starving every
  sibling). The lead arbitrates staleness on evidence, not patience: no relevant process
  running anywhere plus an old lock mtime ⇒ reclaim it. And a bounded retry must
  FAIL on exhaustion — report and stop, never fall through to running anyway: a real
  agent's retry loop proceeded lock-less after its attempts ran out and then released
  a lock a sibling held, silently unserializing both suites. Exhaustion is a signal
  for the lead (likely a stale lock), not permission to skip the protocol.
- **Guard against silent skips.** A test that *skips* when a precondition is unmet (a
  missing binary, absent templates, a feature-detect that quietly returns false) leaves
  CI green while coverage silently drops. Turn on your runner's skip-reason reporting
  (so every skip and its reason is visible) and add a **hard assertion** that when the
  resource *is* present on disk, the precondition must be true — so a broken detector
  goes red, not silently skipped.
  The capability-split variant of the same trap: a test gated on an environment capability
  (a display server, a device, an external binary) can pass on a developer machine yet
  skip in EVERY enforced CI tier — the suite stays green while the guard protects nothing.
  Split such a test: the core behavior ungated so the enforced tiers execute it, and only
  the capability-dependent leg behind the gate; then confirm each new test actually runs
  in at least one enforced tier, or record it as CI-only with substitute evidence.
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
  blocker (but record it honestly in the change evidence).
- **Scale the heaviest gate to the wave, not each change request (a cost decision the lead sets).**
  When the full integration tier is expensive (long CI runs, real engines/devices), a
  workable economy is: per-branch risk covered by the lead's local serial runs (above),
  per-change hosted validation running only the cheap tiers, and one full-tier run on the
  integrated base after the wave's last merge. The trade is deferred detection on the integrated base —
  make it deliberately, not by default.
### Review rounds and guard design

- **Fix a wording/model finding by the CLAIM, not the reviewer's site list.** When a review
  says a statement or mental model is wrong and cites locations, the citations are examples,
  not the boundary: sweep the whole repo (code comments, docs, tests, sibling packages) for
  the claim and fix every instance. Two real rounds re-opened because the fix was scoped to
  the enumerated sites while the same falsified sentence survived elsewhere.
- **Close the review loop.** For actionable review comments, implement the fix,
  rerun the relevant gates, then push and reply or resolve only when those remote writes
  are authorized. Follow the host's convention. Review remediation can touch shared surfaces, so
  update the overlap map and dependent-change plan after each review fix.
- **Fix an admission/validation predicate by its full grammar, not by the reproduced bypass.**
  An adversarial reviewer's next round is the NEIGHBORHOOD of the last fix: a prefix test was
  bypassed by a longer name, the next-character fix by an unclosed header — three rounds for one
  predicate. When a guard is falsified, enumerate the bypass family (prefix, unterminated,
  same-line trailing junk, …), close it in one round, and pin each neighbor as its own
  regression on the reviewer's exact fixture shape.
- **A claimed fallback must hold on every path the fix takes.** "The loader has the final word"
  was cited as the safety net for a lenient admission check — but the very code under review
  skips that loader when an earlier scan finds problems, so the net did not exist on the path
  that mattered. Before citing mechanism B as the backstop for a weakened mechanism A, trace
  that B actually runs in A's failure arms; a reply's every claim gets checked verbatim.
- **The rendered surface is the contract, not its source text.** Published help dropped its
  bracketed file-format tokens because they parse as Rich style tags; the docstring read fine
  while the shipped output said `no complete  header` (two spaces where the dropped token
  was — kept in a code span so rendering preserves the evidence). Pin agent-facing text at the rendering
  boundary (CLI help output, emitted schema descriptions), not at the source string — and
  red-proof the pin against the unescaped text.
- **Serial waves inherit this discipline unchanged.** A wave whose every slice touches the same
  hotspots (one op-dispatch file, one error registry, one skill manifest) is correctly run as
  wave size ONE: same worktree isolation, same per-slice adversarial review and independent
  re-verification, same merge-before-next-slice — parallelism is the only thing removed (§1's
  serialization rule; §8's cure applies when the conflict tax justifies the split). A five-slice
  serial wave shipped this way with zero merge conflicts and no cross-slice contamination.
- **Red-proof a fix round against the head that was REVIEWED, from committed state.**
  (Red-proof: run the new regression before the fix and confirm it fails.) Two
  rules, both learned the hard way. (a) Commit first. The red-proof swaps the source tree for
  another revision's (`git checkout <other-head> -- <src>`), which silently destroys an
  uncommitted fix. One round lost its edits that way, and the manual replay then dropped a
  file (a bundled agent-guidance doc) that the next review caught as "the response claims a
  change absent from the diff". (b) Check the regression against the REVIEWED head, not the wave
  base: red on the base only proves the feature is new, while red on the reviewed head proves
  the test would have caught the reported defect. Honest corollary: a guard that prevents
  FUTURE drift (a rename guard, a mirror check) does not go red on the reviewed head — say so
  instead of listing it as regression coverage.
- **A drift guard must be anchored to an authority the same change cannot rewrite.** An
  "append-only" version/hash history kept inside the test file was defeated in one edit —
  change the artifact, update the current pin, rewrite the last history row, and both guard
  tests still passed. The replacement compares the merge base against the head in CI, so the
  authority is git history rather than data the change can touch. Ask of every guard: what
  stops this change from editing the evidence?
- **A hand-transcribed mirror of another system's rules is a second authority — pin it with
  that system as the ORACLE.** A conversion table copied by hand from an engine's source
  rejected inputs the engine actually accepts (two rows missed), and the misses were invisible
  because the test compared the table to itself. The fix extracted the rows mechanically AND
  added a differential matrix whose reference is the system itself: the target reports whether
  it really ran, and the guard must agree with it on every case. Where you cannot avoid
  mirroring, make the mirror falsifiable by the original.

## 7. Resilience & takeover

- **A reviewing or re-verifying agent works in its own detached scratch worktree.**
  Never run a checkout, rebase, or gate inside an implementer's worktree or the shared
  checkout: an implementer's uncommitted work does not survive a revision swap (§6),
  and it is not the reviewer's to lose. Create the scratch worktree at the pinned
  head, and remove it when the round closes.
- **Create durable local artifacts at safe boundaries when authorized.** Follow the repository's
  commit-history and checkpoint policy. Without commit authority, keep the diff reviewable and
  report its state at each handoff.
- **A review/fix round is a re-dispatch — restate the whole discipline.** Prefer
  resuming the ORIGINAL implementer (its context is intact), but do not assume it
  remembers the rules it followed last round: restate worktree pinning, checkpoint policy,
  permissions, and the §3 DoD gates in the round's dispatch brief. Require one commit per finding
  only when the repository or user explicitly requires that granularity. Otherwise map findings to
  their resolutions in the handoff. Kills
  strike mid-round too (session/usage limits, not just truncation) — one real agent
  finished an entire review/fix round and died with all of it uncommitted.
- **Takeover recipe for uncommitted work:** review the whole uncommitted diff yourself
  against the findings it claims to fix, run the same gates the dispatch DoD requires
  (§3: the locally reproducible gates plus the recorded CI-only gates), then commit or
  push only when each action is authorized. Don't re-dispatch what a diff review can
  verify — and don't commit what you haven't read.
- **Trivial mechanical validation failures are the lead's to fix in place when authorized.** A formatter diff or
  an import sort on an otherwise-verified branch is cheaper to fix, test, and push
  yourself than to re-dispatch an agent for.
- **Two missed rounds on one finding flips the fix to the lead.** Re-dispatching a review
  finding to its implementer is right the first time — its context is warm. When a second
  round still misses the finding's essence, a third dispatch costs more than doing the
  work: the lead implements the fix directly (same worktree, same gates, same report duty)
  and tells the implementer what changed. Complements the takeover recipe above; the
  trigger is repeated misunderstanding, not a missing artifact.
- **"Completed but no artifact" = needs-takeover.** Never trust a completion claim —
  independently verify with `git status` (clean?), `git log` (recent commits?), and
  remote-tracking when a push was authorized and expected. An agent report with no
  completed validation result, or with an expected push absent, needs takeover and verification.
- **The orchestrator owns hosted integration records when remote writes are authorized.**
  Once a slice's published commits verify, create or update its change request according
  to the host's convention. Mark a source work item complete only when that slice satisfies
  every acceptance criterion. A foundation slice, dependent follow-up slice, or stacked
  partial change must remain non-closing. Without remote-write authority, report the
  required record and do not create or update it.
- **Worktree scripting: derive git state paths with `git rev-parse --git-path`.** In a
  linked worktree `.git` is a FILE, so a hardcoded `.git/rebase-merge` (or MERGE_HEAD etc.)
  existence check silently reports "no rebase in progress" mid-rebase — a real automation
  loop exited early on exactly that. `git rev-parse --git-path rebase-merge` resolves
  correctly in both layouts.
- **Verify the shared checkout after every worktree agent.** Confirm the shared checkout is
  still on its branch and clean (`git -C <shared-checkout> branch --show-current`, `git status
  --short`, no stray branches) before relying on it — worktree agents have leaked git
  ops to it (§3).
- **A history-rewrite push of a published branch requires explicit authority and an explicit
  lease.** Use the exact expected remote SHA recorded by §4; bare `--force-with-lease` is not
  enough for this recipe. An unpublished branch uses a normal initial push. Never rewrite a shared
  or protected branch.

## 8. Architectural fix: kill the hotspots

The durable cure for append conflicts is to stop appending to shared files: **split each
central registry / dispatch table / map so every module owns its own fragment that is
auto-collected** (one file per module, discovered/aggregated at build or load). Then
independent slices stop colliding at all, and per-change conflict count drops from "many
files, many regions" toward 1–2. When the conflict tax is high, this is worth a dedicated
design decision record.

## 9. Pre-launch checklist

- [ ] Slices in this wave are independent (no shared module/group); coupled ones serialized.
- [ ] Wave ≤ ~5, or above it only with the §2 lifting discipline (owned hotspots with
      pre-tested resolutions, wave-batched review rounds, one serial merge pass); the plan
      integrates it before the next wave when execution is authorized.
- [ ] Every slice branch carries its final name before its first push (§3).
- [ ] Operating mode is explicit: planning-only stops after the plan; execution lists allowed local mutations.
- [ ] Every push, change-request write, merge, review reply, and tracker update has separate explicit authority or is marked pending.
- [ ] Every append hotspot has exactly ONE owner slice this wave; sibling prompts say "flag, don't edit" (§1).
- [ ] Each subagent's DoD includes every applicable locally reproducible gate, including the real integration boundary.
- [ ] Each CI-only or unavailable gate records the reason, substitute evidence, remaining risk, and exact-head requirement (§3, §6).
- [ ] Each subagent's DoD includes deep-module reuse — no re-implementing shared logic, and no dodging a legitimate shared-file edit, to fake disjointness (§1).
- [ ] Review/fix rounds restate worktree, permission, and gate requirements; remote review replies occur only when authorized (§6, §7).
- [ ] Agents are pinned to their worktrees; local artifacts follow the granted commit authority; "done but no artifact" = takeover.
- [ ] Merge order decided (foundation slice before dependent follow-up slices); after each resolution, audit for the marker-free traps.
- [ ] Stacked followers have an explicit retarget/rebase plan for after the base change lands
      or receives review fixes; the original local tip is recorded before mutation, and the expected
      remote SHA is recorded when a published branch will be rewritten and pushed.
- [ ] Shared-global-resource tests will run serially across worktrees.
- [ ] Review/verification agents have their own scratch worktrees; none enters an
      implementer's worktree or the shared checkout (§7).
- [ ] If waves land on an integration branch: the promotion's merge method is arranged,
      and the branch is recreated from the promoted base after each promotion merge (§4).
- [ ] Orchestrator will independently re-verify before each merge.
- [ ] Any public-surface change has the applicable documentation/schema/help/generated-artifact consistency gates in the orchestrator's verification plan.
- [ ] Hosted integration records are orchestrator-owned when authorized; partial slices do not close their source work item.
- [ ] If append hotspots keep causing conflicts, consider splitting them through a design decision.

## 10. Cost / benefit

| | |
|---|---|
| **Wins** | implementation wall-clock (large); context isolation (each agent's tool output stays out of the orchestrator); independent-perspective quality (adversarial review surfaces hidden issues — one slice even found a latent bug in neighboring code) |
| **Costs** | merging is serial and can be conflict-heavy; duplicated scaffolding; verification burden on the orchestrator; truncation risk at large batch sizes |
| **Net** | strongly positive for independent, modest-sized waves with applicable locally reproducible and CI-only gates; neutral-to-negative for tightly-coupled slices hammering shared files |
