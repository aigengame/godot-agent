---
name: pitfalls
description: Maintain PITFALLS.md, a concise project-scoped catalog of verified, context-dependent environment, tool, permission, sandbox, and tool-invocation problems with proven workarounds. Use after a reusable operational pitfall is confirmed, when one recurs, at wrap-up if its workaround should survive the session, or when explicitly invoked. Do not use for product bugs, code or design issues, review methods, or speculative advice.
---

# Pitfalls

Maintain the root `PITFALLS.md` as concise operational guidance for future workers.
The catalog helps an agent avoid a verified tool-call failure without treating one
harness's limits as universal project policy.

## Scope

Record a pitfall when all of these conditions apply:

- It concerns the environment, a tool, permissions, a sandbox, or tool invocation.
- The symptom, cause, and workaround have useful evidence.
- The same condition can plausibly affect a later session.
- The entry can state when the workaround applies.

Keep product defects, source-code mistakes, architecture, domain design, review methods,
and general engineering advice in their existing authorities and workflows.

## Workflow

1. Read the current `PITFALLS.md` and inspect the current environment.
2. Verify the cause and workaround in the current harness when that check is safe and
   useful. If the evidence comes from another harness, preserve that context instead of
   presenting it as current.
3. Search for an entry with the same root cause. Update that entry instead of adding a
   duplicate symptom.
4. State the narrow `Applies when` condition. Use guidance language such as `may`,
   `should`, and `consider`. Reserve absolute language for a demonstrated safety or
   permission boundary.
5. Record only the evidence needed to recognize, prevent, and recover from the problem.
   If the workaround is only a mitigation, state the remaining limitation.
6. Remove secrets, personal paths, and machine-specific identifiers. Use portable
   placeholders such as `/tmp/<task>-uv-cache`.
7. Re-read the entry as an agent in a different harness. It should not direct that agent
   to apply an unnecessary workaround.

Leave the document unchanged when the experience is unverified, speculative, unique to
the completed task, or already covered by an existing entry.

## Entry format

Use a stable, descriptive heading and this compact shape:

```markdown
## <Pitfall name>

- **Applies when:** <environment or harness condition>
- **Symptom:** <observable failure>
- **Cause:** <verified cause>
- **Prevention:** <pre-run guidance>
- **Recovery:** <steps after the failure>
- **Last verified:** <date and relevant tool or harness, when useful>
```

Omit `Last verified` when a date or version would not help a future worker. Delete or
revise an entry when current evidence shows that it is obsolete; version control keeps
the old record.

## Ownership and integration

The primary worker should edit `PITFALLS.md`. Parallel subagents should report candidate
entries to the primary worker so concurrent edits do not create duplicates.

If `STATE.md` exists, it can point to a relevant catalog entry when that entry helps the
immediate next work. It should not copy durable operational guidance from `PITFALLS.md`.
