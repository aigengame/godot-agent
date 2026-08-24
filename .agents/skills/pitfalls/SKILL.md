---
name: pitfalls
description: Use PITFALLS.md to prevent repeated environment, tool, permission, sandbox, and tool-invocation failures, and maintain it with verified context-dependent guidance. Use before project tool work, when a matching operational pitfall occurs, after confirming a reusable new pitfall, or when explicitly invoked. Do not use for product bugs, code or design issues, review methods, or speculative advice.
---

# Pitfalls

In this skill, `PITFALLS.md` means the tracked catalog at the repository top level.
Resolve that path before reading or writing the catalog; do not create another copy in
the current directory.

Use the catalog before and during work, and maintain it after work. The catalog helps an
agent avoid a verified tool-call failure without treating one execution environment's
limits as universal project policy.

## Workflow

### 1. Before work: load applicable guidance

1. Read the catalog if it exists so its relevant entries are in the working context.
2. Reuse an entry when the current execution environment and tool call match its context.

If the file does not exist, continue normally. Create it only when phase 3 produces a
verified, reusable entry.

### 2. During work: apply or extend the guidance

Apply a relevant entry when its situation occurs. If no entry applies, or its guidance
does not work, investigate the failure and carry it to phase 3 only after evidence
supports the cause and workaround.

### 3. After work: record new guidance

#### Recording scope

Record a pitfall when all of these conditions apply:

- It concerns the environment, a tool, permissions, a sandbox, or tool invocation.
- The symptom, cause, and workaround have useful evidence.
- The same condition can plausibly affect a later session.
- The entry can state when the workaround applies.

Keep product defects, source-code mistakes, architecture, domain design, review methods,
and general engineering advice in their existing authorities and workflows.

#### Update the catalog

1. Verify the cause and workaround in the current execution environment when that check
   is safe and useful. If the evidence comes from another environment, preserve that
   context instead of presenting it as current.
2. Search for an entry with the same root cause. Update that entry instead of adding a
   duplicate symptom.
3. State the narrow `Applies when` condition. Use guidance language such as `may`,
   `should`, and `consider`. Reserve absolute language for a demonstrated safety or
   permission boundary.
4. Record only the evidence needed to recognize, prevent, and recover from the problem.
   If the workaround is only a mitigation, state the remaining limitation.
5. Remove secrets, personal paths, and machine-specific identifiers. Use portable
   placeholders such as `<writable-temp-dir>/<task>-uv-cache`.
6. Re-read the entry as an agent in a different execution environment. It should not
   direct that agent to apply an unnecessary workaround.

Leave the document unchanged when the experience is unverified, speculative, unique to
the completed task, or already covered by an existing entry.

## Entry format

Use a stable, descriptive heading and this compact shape:

```markdown
## <Pitfall name>

- **Applies when:** <execution-environment condition>
- **Symptom:** <observable failure>
- **Cause:** <verified cause>
- **Prevention:** <pre-run guidance>
- **Recovery:** <steps after the failure>
- **Last verified:** <date and relevant tool or execution environment, when useful>
```

Omit `Last verified` when a date or version would not help a future worker. Delete or
revise an entry when current evidence shows that it is obsolete; version control keeps
the old record.

## Ownership and integration

Only the primary worker edits `PITFALLS.md`. Parallel subagents report candidate entries
to the primary worker so concurrent edits do not create duplicates.

If `STATE.md` exists, it can point to a relevant catalog entry when that entry helps the
immediate next work. It should not copy durable operational guidance from `PITFALLS.md`.
