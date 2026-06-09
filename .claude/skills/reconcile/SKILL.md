---
name: reconcile
description: Check and repair consistency between GitHub issues and domain docs (CONTEXT.md, docs/adr/) after a requirement or technical decision changes — mechanical cross-reference integrity plus conversation-driven semantic staleness. Use when a decision or requirement was changed or discussed in the current session, when issues/docs may have drifted out of sync, when the user says "reconcile" / "sync issues and docs" / "check cross-references", or when invoked as /reconcile.
---

# Reconcile

Keep the cross-referenced web of **issues + domain docs** (`CONTEXT.md`, `docs/adr/`) correct
and consistent so the development feedback loop stays trustworthy. A decision discussed in a
session must not silently drift out of sync with the issues and docs that record it.

**Read first:** `docs/agents/domain.md` (glossary + ADR-conflict rules), `docs/agents/issue-tracker.md`
(`gh` conventions), `docs/agents/triage-labels.md`. See [REFERENCE.md](REFERENCE.md) for the
reference-graph edge taxonomy and the full check catalog.

## Triggers

- **Manual**: invoked as `/reconcile`, or when the user asks to sync issues and docs.
- **Automatic**: a Claude Code Stop hook (and optionally a `git` pre-commit hook) may auto-invoke
  this skill — see "Hook setup" below. Hook wiring is HITL; never add it without user approval.

## Safety posture (non-negotiable)

**Report first, mutate only after confirmation.** Always present findings and proposed patches,
then wait for the user to confirm before editing any doc file or GitHub issue. Never run a
mutating `gh issue edit` / `gh issue comment` or write to a doc without explicit approval.

## Workflow

```
gather change set → build reference graph → check (mechanical + semantic) → report → confirm → apply + propagate
```

### 1. Gather the change set

The semantic layer is driven by the **current conversation context**. Identify the decision /
requirement changes discussed in-session: which terms were renamed, which decisions reversed or
refined, which scope/Phase boundaries moved. Write them down as an explicit change list. If the
session contains no such change, run the mechanical layer only and say so.

If the user states a change explicitly, use that verbatim as the change set.

### 2. Build the reference graph

Load the artifacts and extract their cross-references (see [REFERENCE.md](REFERENCE.md) for edge
types and how to read each source):

- Issues + PRDs — `gh issue list`/`view` (Parent, Blocked by, `ADR-NNNN`, `#NN`, domain terms)
- ADRs — `docs/adr/*.md` (`ADR-NNNN` cross-refs, `status:` front-matter, domain terms)
- `CONTEXT.md` glossary — canonical terms and their `_Avoid_` synonyms; `ADR-NNNN` refs

### 3. Check — two layers

**Mechanical (always runs):** dangling references (`ADR-9999`, `#999`, missing file paths),
orphans, and glossary term drift (use of an `_Avoid_` synonym instead of the canonical term).

**Semantic (runs when a change set exists):** for each change, find the issues / ADRs /
`CONTEXT.md` entries it makes stale — a change that contradicts an ADR's `Decision`, a renamed
term, a moved Phase boundary, an issue describing superseded behavior. Report each with the
reasoning that links the change to the affected artifact.

### 4. Report

Present a single consolidated report: every finding with its evidence (file/issue + line/quote)
and a **concrete proposed patch** (a diff for docs, the exact `gh` command for issues). Group by
artifact. Flag any finding that contradicts an accepted ADR per `domain.md`'s flag rule.

### 5. Confirm (HITL)

Ask the user which proposed patches to apply. Do not proceed on un-confirmed items.

### 6. Apply + propagate

For confirmed fixes, apply them, then propagate consistency across the graph:

- Edit doc files; for issues use `gh issue edit` / `gh issue comment` per `issue-tracker.md`.
- When an ADR is superseded, add a `superseded-by` link both ways and update its `status:`.
- Sync the `CONTEXT.md` glossary when a term changes (definition, `_Avoid_` list, ADR refs).
- Comment affected issues so the change is traceable in the tracker.
- Re-run the mechanical check on touched artifacts to confirm no new dangling references.

## Hook setup (optional, HITL)

To auto-invoke on a trigger, propose (do not silently add) a hook in `settings.json` — a Stop
hook for session-end reconciliation, or a `git` pre-commit hook. Review timing and behavior with
the user before writing to `settings.json`. See [REFERENCE.md](REFERENCE.md) for a sample.
