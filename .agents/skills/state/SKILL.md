---
name: state
description: Update STATE.md — the lightweight cross-session "daily report" of project progress. Rewrite (never append) the current milestone/phase, what this session completed or changed, pitfalls worth reusing, and the recommended next issues/tasks. Use at the end of a working session, when wrapping up, or when invoked as /state.
---

# State

Maintain `STATE.md` at the repo root: a lightweight **cross-session daily report** so the next
worker learns in ≤10 lines where the project is, what the last session did, which pitfalls to
reuse, and what to pick up next. This is the feedback loop that makes development experience
**compound** instead of re-discovering project status every session.

`STATE.md` is **transient** ("where are we now / what next", overwritten each session) and
**self-contained** — it is not the place for durable decisions, architecture, or a glossary, and
must not duplicate them. It is **lazily created**: if it doesn't exist yet, the first run creates it.

This skill is **self-sufficient and orthogonal** to whatever else a project happens to use (version
control, an issue/task tracker, design docs). It assumes such tools *may* exist but depends on no
particular one — read whatever sources the project has, skip the rest.

**Write sparingly — omit rather than mislead.** Every field in the template is **optional**. Only
write a line when you have something **accurate** and **useful to the next session**. If a value is
missing, stale, unverified, or you can't judge whether it helps, **leave it out** — a wrong or
filler line is worse than a missing one. STATE.md must orient the next worker, never misdirect them.

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
3. **Pick the recommended next work** — the open items a fresh session should start with.
4. **Add pitfalls/experience only if it serves "Next up".** Include a note **only when this
   session's work is continuous with or related to the recommended next work**, so the note will
   actually get reused. If the next work is unrelated, **omit it** — experience that doesn't help
   the next task is noise, not a war-story archive.
5. **Rewrite `STATE.md`** from the template — **overwrite, never append**; ≤10 lines; terse; drop
   any field you have nothing accurate and useful for. Stamp the date.
6. **Do not auto-commit.** Just leave the rewritten `STATE.md` in the working tree. Whether it is
   tracked or kept as a local-only working aid is the project's choice — this skill never commits it.

## Template

```markdown
# STATE — <project>

_Cross-session daily report (≤10 lines, rewritten each session via `/state`). Durable decisions live elsewhere, not here._

- **Phase/milestone:** <current stage, in the project's own terms — omit if you can't confirm the *current* one>
- **Last session:** <what was completed/changed; one line, e.g. issue #N>
- **Pitfalls/experience:** <only if it helps "Next up"; otherwise omit this line>
- **Next up:** <recommended next items to start, e.g. issue #N>

_Updated: <YYYY-MM-DD>_
```

(Every bullet is optional — omit any you have nothing accurate and useful for.)

## Guardrails

- **≤10 lines** of content; keep it scannable.
- **Omit rather than mislead** — every field is optional; drop any line that is stale, unverified,
  or not useful to the next session. Never carry a phase forward just because it was there before.
- **Pitfalls only when they serve "Next up"** — record experience only when this session's work is
  continuous with / related to the recommended next work; otherwise leave it out.
- **Overwrite, never append** — STATE.md is a current handoff snapshot, not a session-history log;
  keep only the latest state.
- Record only **this session's delta** — not a running journal.
- Keep it **self-contained**: don't duplicate the project's durable decision/architecture docs, and
  don't hard-depend on any particular tracker or tool.
- Use the **project's own vocabulary** consistently.
