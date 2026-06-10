# Reconcile — reference

Detailed companion to [SKILL.md](SKILL.md): the reference-graph edge taxonomy, how to read each
source, the full check catalog, and a hook sample. This repo is single-context (`CONTEXT.md` +
`docs/adr/` at the root) per `docs/agents/domain.md`.

## Reference-graph edge taxonomy

| Edge | Source → target | How it appears | Mechanical failure |
| --- | --- | --- | --- |
| issue → issue | issue body | `## Parent` section, `## Blocked by` section, bare `#NN` | target issue missing/closed unexpectedly |
| issue → ADR | issue body | `ADR-NNNN` | no `docs/adr/NNNN-*.md` |
| issue → term | issue title/body | domain noun | term absent from glossary, or an `_Avoid_` synonym |
| ADR → ADR | ADR body | `ADR-NNNN` (supersedes / contradicts / builds-on) | target ADR file missing |
| ADR → term | ADR body | domain noun | `_Avoid_` synonym used |
| ADR → CONTEXT | ADR body | references a glossary concept | concept not in glossary |
| CONTEXT → ADR | glossary entry | `ADR-NNNN` (e.g. gda-mcp → ADR-0004) | target ADR file missing |
| CONTEXT → term | `_Avoid_` lines | canonical term ↔ banned synonyms | — (this is the rule source) |

`status:` front-matter on an ADR (`accepted`, `superseded`, …) is graph metadata: a `superseded`
ADR should have a `superseded-by: ADR-NNNN` pointer, and the superseding ADR should point back.

## How to read each source

- **Issues** — `gh issue list --state open --json number,title,body,labels --jq '...'` to
  enumerate; `gh issue view <n> --comments` for one. Conventions in `docs/agents/issue-tracker.md`.
- **ADRs** — files `docs/adr/NNNN-*.md`; parse `status:` front-matter and inline `ADR-NNNN`.
- **CONTEXT.md** — glossary terms are `**Term**:` headed; each may list `_Avoid_: a, b` synonyms
  and inline `ADR-NNNN` refs. These define the canonical vocabulary.

## Check catalog

### Mechanical (always)

1. **Dangling ADR ref** — `ADR-NNNN` with no matching `docs/adr/NNNN-*.md`.
2. **Dangling issue ref** — `#NN` / Parent / Blocked-by pointing at a non-existent issue.
3. **Dangling file path** — a path mentioned in a doc/issue that does not exist.
4. **Orphan** — an ADR/issue nothing references and which references nothing (may be intentional;
   report, don't assume broken).
5. **Term drift** — an artifact uses a synonym the glossary lists under `_Avoid_` instead of the
   canonical term. Propose the canonical term.
6. **Status pointer asymmetry** — a `superseded` ADR missing its `superseded-by`, or a one-way
   supersede link.

### Semantic (when a change set exists)

For each change in the set, scan artifacts whose terms/topics overlap and judge staleness:

1. **Contradicted decision** — a change reverses/refines an ADR `Decision` still marked `accepted`.
2. **Renamed term** — a term changed in-session but old name still used in issues/ADRs/glossary.
3. **Moved boundary** — Phase/scope boundary changed; issues or ADRs still describe the old split.
4. **Superseded behavior** — an open issue describes behavior the change makes obsolete.

Match by domain-term overlap first (cheap), then judge each candidate's staleness with reasoning.
State the evidence linking the change to each affected artifact; do not flag on keyword overlap
alone.

### Discount illustrative references

A `#NN` or `ADR-NNNN` token is not always a real edge. Discount tokens that appear as
*illustrative examples* — e.g. a sentence listing what a dangling reference looks like
(`(ADR-9999, #999, …)`), or a template/skill doc demonstrating the syntax. Judge from context;
do not report these as broken links. (This skill's own issue contains such examples.)

## Reporting format

One consolidated report, grouped by artifact:

```
### <artifact> (e.g. ADR-0005 / issue #4 / CONTEXT.md)
- [layer] <finding> — evidence: <file:line or issue + quote>
  proposed: <unified diff for docs | exact gh command for issues>
```

Per `domain.md`: if a finding contradicts an accepted ADR, surface it explicitly
(`> Contradicts ADR-NNNN — but worth reopening because…`) rather than silently overriding.

## Hook sample (propose, never auto-add — HITL)

A Stop hook that reminds to run reconciliation at session end. Review timing/behavior with the
user before writing to `settings.json`.

For a `Stop` event, exit-0 stdout goes to the **debug log**, not the transcript — a plain
`echo 'reminder'` fires invisibly. To surface a message to the user, emit JSON with a
`systemMessage` field (still exit 0, still non-blocking):

```jsonc
// .claude/settings.json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": "echo '{\"systemMessage\": \"Consider running /reconcile if a decision changed this session.\"}'" }
        ]
      }
    ]
  }
}
```

(`matcher` is omitted — it has no meaning for `Stop`, which carries no tool context.)

A `git` pre-commit alternative belongs in `.git/hooks/pre-commit` or the repo's hook manager; it
should likewise only *remind*, since reconcile is HITL and must not block on un-confirmed edits.
