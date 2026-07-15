---
name: state
description: Update STATE.md — the lightweight cross-session "daily report" of project progress. Rewrite (never append) the current milestone/phase, what this session completed or changed, pitfalls worth reusing, the recommended next issues/tasks, and the filtered-and-inherited backlog of unfinished cross-session items. Use at the end of a working session, when wrapping up, or when invoked as /state.
---

# State

Maintain `STATE.md` at the repo root: a lightweight **cross-session daily report** so the next
worker learns in ~15 lines where the project is, what the last session did, which pitfalls to
reuse, what to pick up next, and which unfinished items must not be forgotten. This is the
feedback loop that makes development experience **compound** instead of re-discovering project
status every session.

`STATE.md` is **transient** ("where are we now / what next", overwritten each session) and
**self-contained** — it is not the place for durable decisions, architecture, or a glossary, and
must not duplicate them. It is **lazily created**: if it doesn't exist yet, the first run creates it.

Where the project keeps a planning authority (an issue tracker, milestones), that authority owns
**what** the work is; it does not prescribe the **order and manner** of execution — issues run in
parallel, one issue spans sessions, inserted work preempts planned work. STATE.md is the
**worker's report on execution**: results, plus the current orchestration of tracked work (what
to start next, what was interrupted and parked). It records execution state; it never becomes a
second planning authority.

This skill is **self-sufficient and orthogonal** to whatever else a project happens to use (version
control, an issue/task tracker, design docs). It assumes such tools *may* exist but depends on no
particular one — read whatever sources the project has, skip the rest.

**Write sparingly — omit rather than mislead.** Every field in the template is **optional**. Only
write a line when you have something **accurate** and **useful to the next session**. If a value is
missing, stale, unverified, or you can't judge whether it helps, **leave it out** — a wrong or
filler line is worse than a missing one. STATE.md must orient the next worker, never misdirect
them. (The Backlog inverts this default for *removal* — see the workflow.)

## When to run

- At the **end of a working session** / wrap-up — your agent runtime may nudge this via a
  session-end hook, or you run it yourself.
- On demand, invoked as `/state`.

Update STATE.md **once per session, by the primary worker** — not once per parallel sub-task or subagent — so
the file is written a single time and never double-written.

**No-op guard:** if the session did no material work (e.g. a trivial Q&A turn), leave `STATE.md`
unchanged — at most refresh the date. Don't churn the file with non-progress.

## Workflow

1. **Gather what this session actually completed or changed.** The primary source is the **current
   conversation**. If the project has supporting tools, corroborate lightly (recent version-control
   history, the issue/task tracker) — treat them as optional, not required.
2. **State the macro phase only if you know the *current* one.** Do **not** carry the previous
   STATE.md's phase forward by default — if it may have moved on, or you can't confirm the current
   stage this session, **omit the line** rather than assert a stale one. (A finished phase written
   as if current is misdirection.) Use the project's own terms.
3. **Pick the recommended next work** — the open items a fresh session should start with, in
   execution order. Promote Backlog items here when they are the right next start.
4. **Reconcile the Backlog** — the unfinished cross-session items that must survive the rewrite:
   - **Inherit by filtering**: start from the previous STATE.md's Backlog (and any Next up items
     that never ran). Drop an item **only with evidence** — it is done, obsolete, promoted into
     "Next up", or newly homed in the project's tracker (its reference is the evidence) — check
     the conversation, corroborate with the tracker when one exists. When unsure, **keep it**:
     this is the one section where uncertainty preserves a line instead of deleting it.
   - **Demote**: unfinished work — typically displaced by inserted tasks — moves here **only when
     it is not selected for "Next up"**. Interrupted work that should simply resume next session
     belongs in "Next up" (step 3), not here.
   - **Park**: a newly discovered or accepted item deliberately deferred to a later session —
     never started, not selected for "Next up" — also enters here, so it cannot fall between the
     two lists.
   - **One home per item**: an item appears in "Next up" *or* the Backlog, never both.
   - **Stamp, and promote oldest-first**: each item carries the date it entered
     (`since YYYY-MM-DD`) — the snapshot's only observable age. When the Backlog exceeds its
     budget, or an item is clearly substantive, move items into the project's tracker
     **oldest-first**; the filed reference is what lets the entry leave. With no tracker, or no
     authorization to write it, the budget yields: keep every item (staying visibly over budget
     is the signal to get them homed) — silent truncation is never allowed.
5. **Add pitfalls/experience only if it serves "Next up".** Include a note **only when this
   session's work is continuous with or related to the recommended next work**, so the note will
   actually get reused. If the next work is unrelated, **omit it** — experience that doesn't help
   the next task is noise, not a war-story archive.
6. **Rewrite `STATE.md`** from the template — **overwrite, never append**; ≤15 lines, except
   when step 4's no-loss fallback leaves the Backlog over its own budget: then the file grows by
   exactly those Backlog lines — the line budget yields with the item budget, it is never
   rebalanced by dropping an item. Terse; drop any field you have nothing accurate and useful
   for (the Backlog re-emits its *filtered inheritance* — a fresh rewrite, not an append).
   Stamp the date.
7. **Do not auto-commit.** Just leave the rewritten `STATE.md` in the working tree. Whether it is
   tracked or kept as a local-only working aid is the project's choice — this skill never commits it.

## Template

```markdown
# STATE — <project>

_Cross-session daily report (~15 lines, rewritten each session via `/state`). Durable decisions live elsewhere, not here._

- **Phase/milestone:** <current stage, in the project's own terms — omit if you can't confirm the *current* one>
- **Last session:** <what was completed/changed; one line, e.g. issue #N>
- **Pitfalls/experience:** <only if it helps "Next up"; otherwise omit this line>
- **Next up:** <recommended items to START next, in execution order, e.g. issue #N>
- **Backlog:** <unfinished cross-session carry-over NOT selected for "Next up"; one line per item>
  - <interrupted or parked item, anchored to a tracker ref (#N) where one exists> _(since YYYY-MM-DD)_
  - <item not yet in the tracker — promote it there oldest-first when the list overflows> _(since YYYY-MM-DD)_

_Updated: <YYYY-MM-DD>_
```

(Every bullet is optional — omit any you have nothing accurate and useful for.)

## Guardrails

- **≤15 lines** of content; keep it scannable. One exception: when the Backlog's no-loss
  fallback keeps items past its own budget, the file grows by exactly those lines — a
  line-budget breach is never resolved by dropping a Backlog item.
- **Omit rather than mislead** — every field is optional; drop any line that is stale, unverified,
  or not useful to the next session. Never carry a phase forward just because it was there before.
- **Backlog drops need evidence** — the inverse of the rule above, so unfinished work cannot
  silently vanish in a rewrite: carry an item forward unless you can point at its completion,
  obsolescence, promotion into "Next up", or its new tracker home.
- **Backlog budget: 5 items, one line each, each stamped `since YYYY-MM-DD`** — overflow is
  resolved by promoting the OLDEST items into the project's tracker, never by truncation; with
  no tracker or no authorization to write it, keep the items and stay visibly over budget —
  losing work is worse than breaking the budget. The Backlog is execution carry-over anchored
  by reference, never a second plan.
- **One home per item** — "Next up" (ordered, what to start) or Backlog (parked, must not be
  lost), never both.
- **Pitfalls only when they serve "Next up"** — record experience only when this session's work is
  continuous with / related to the recommended next work; otherwise leave it out.
- **Overwrite, never append** — STATE.md is a current handoff snapshot, not a session-history log;
  keep only the latest state. The Backlog is no exception: it is re-emitted each rewrite from its
  filtered inheritance, not accreted.
- Record only **this session's delta** — not a running journal. The Backlog is the one field that
  carries filtered state forward.
- Keep it **self-contained**: don't duplicate the project's durable decision/architecture docs, and
  don't hard-depend on any particular tracker or tool.
- Use the **project's own vocabulary** consistently.
