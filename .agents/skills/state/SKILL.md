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

**Write sparingly — omit rather than mislead.** Every content bullet in the template is optional.
The updated date is required whenever the file is rewritten. Only write a content line when it is
accurate and useful to the next session. If a value is missing, stale, unverified, or not clearly
useful, leave it out. A wrong or filler line is worse than a missing one. The Backlog uses a
different removal rule; follow step 4.

## When to run

- At the **end of a working session** / wrap-up — your agent runtime may nudge this via a
  session-end hook, or you run it yourself.
- On demand, invoked as `/state`.

The primary worker updates STATE.md once per session. Parallel sub-tasks and subagents do not update
it. This rule prevents concurrent or duplicate writes.

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
4. **Reconcile the Backlog.** Apply this algorithm to unfinished cross-session items:
   - **Inherit by filtering.** Start with the previous Backlog and any "Next up" items that did not
     run. Drop an item only when evidence shows that it is done, obsolete, selected for "Next up",
     or recorded in the project's tracker. A tracker reference is evidence that the item has a new
     home. Check the conversation and corroborate with the tracker when one exists. Keep the item
     when its status is uncertain.
   - **Demote unfinished work.** Move displaced work to the Backlog only when it is not selected for
     "Next up". Work that should resume next session belongs in "Next up".
   - **Park deferred work.** Add a newly accepted item when it is deferred beyond the next session
     and has no other home.
   - **Give each item one home.** Put it in "Next up" or the Backlog, never both.
   - **Stamp each Backlog item.** Record its entry date as `since YYYY-MM-DD`.
   - **Apply the five-item budget.** When the Backlog exceeds five items, or an item is clearly
     substantive, move items to the project's tracker oldest-first. Remove an item only after the
     tracker provides a reference. If no tracker exists, keep every item. Also keep every item when
     no authorized writer can create the tracker record. The visible overflow is the signal that
     the items still need a durable home.
5. **Add pitfalls/experience only if it serves "Next up".** Include a note **only when this
   session's work is continuous with or related to the recommended next work**, so the note will
   actually get reused. If the next work is unrelated, **omit it** — experience that doesn't help
   the next task is noise, not a war-story archive.
6. **Rewrite `STATE.md` from the template.** Overwrite the file; never append. Keep it to 15 lines
   or fewer. If the no-loss rule in step 4 leaves more than five Backlog items, allow one extra line
   for each extra item. Do not drop an item to meet the line limit. Omit content bullets that are
   not accurate and useful. Re-emit the filtered Backlog as part of the new snapshot. Stamp the
   updated date.
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

(Every content bullet is optional. `_Updated` is required whenever the file is rewritten.)

## Guardrails

- Follow step 4 for every Backlog change. Never delete unfinished work to meet a budget.
- Follow step 6 for rewriting and line limits. STATE.md is a current snapshot, not a history log.
- Record only this session's delta. The Backlog is the only field that carries filtered state
  forward.
- Keep the file self-contained. Do not duplicate durable decisions or depend on a specific tracker
  or tool.
- Use the project's established vocabulary.
