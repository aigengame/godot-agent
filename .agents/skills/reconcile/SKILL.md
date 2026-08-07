---
name: reconcile
description: Check and repair consistency among tracked work, requirements, design records, glossaries, and other authoritative project artifacts after a requirement, decision, scope, or term changes. Use when artifacts may have drifted out of sync, when the user asks to reconcile or check cross-references, or after the current session changes an authoritative fact.
---

# Reconcile

Keep related project artifacts consistent after an authoritative fact changes. Reconcile both
structural references and statements whose meaning became stale.

Do not assume a fixed tracker, document name, directory layout, identifier format, or decision-record
schema. Read the target repository's guidance first. Use its context routing, artifact ownership,
terminology sources, and editing rules as the authority. See [REFERENCE.md](REFERENCE.md) for the
reference-graph taxonomy and check catalog.

## Triggers

- **Manual invocation:** run when the user asks to reconcile artifacts or check cross-references.
- **Optional reminder:** a session-end or version-control hook may remind the user to run this skill.
  A reminder does not run reconciliation. Call a hook automatic only when the host has a documented,
  verified mechanism that invokes the skill. Do not add or change hook configuration without the
  user's approval.

## Safety posture

Report first. Mutate only after confirmation. Present findings and proposed changes before editing
local artifacts or remote tracker records. Apply only the changes that the user confirms.

## Workflow

```text
discover authorities -> gather change set -> build reference graph -> check -> report -> confirm -> apply and propagate
```

### 1. Discover authorities and scope

Read the repository guidance that defines artifact locations, context boundaries, terminology,
tracker conventions, and decision-record rules. Follow nested guidance for the target area.

Determine whether the repository has one context or several. For a scoped change, use the owning
context and every routed context that consumes the changed fact. For a repository-wide check,
enumerate all declared contexts. If no routing authority exists, discover the relevant artifacts
from repository guidance and the artifact links themselves.

Record which artifact owns each affected fact. Treat other occurrences as references or derived
statements unless the repository declares shared ownership.

### 2. Gather the change set

Use the current conversation and authoritative artifacts to list the requirements, decisions,
terms, or boundaries that changed. Preserve an explicit user statement exactly when it defines the
change. If there is no semantic change set, run only the mechanical checks and report that limit.

### 3. Build the reference graph

Load the artifacts in scope and extract their declared references. Typical nodes include tracked
work, requirements, decision records, specifications, glossaries, tests, and implementation docs.
Use repository-native identifiers and relationships. Do not infer an edge from a shared keyword
alone.

### 4. Check two layers

**Mechanical checks always run.** Check facts that can be decided without interpreting intent:

- a declared reference target exists;
- an artifact does not use a synonym that the terminology authority explicitly prohibits;
- a reciprocal pointer exists when the repository schema explicitly requires one.

**Semantic checks run when interpretation is required.** For each change, find statements that may
now be stale. Check changed decisions, renamed or newly introduced terms, moved scope boundaries,
partly or fully superseded behavior, tracker state, and unreferenced artifacts. Use evidence to
explain why each candidate is or is not stale. Do not classify tracker state or glossary coverage
as a defect without applying the repository's meaning and rules.

### 5. Report

Present one report grouped by artifact. For every finding, provide the location, evidence, impact,
and a concrete proposed change. Use a patch for local text. For a remote record, describe the exact
edit using the target repository's tracker and tool conventions. Flag any proposal that conflicts
with an accepted authority; do not silently override it.

### 6. Confirm

Ask which proposed changes to apply. Do not proceed with unconfirmed items.

### 7. Apply and propagate

Apply confirmed changes, then update every affected reference or derived statement:

- Use the repository-native tool and editing rules for each artifact.
- For complete supersession, update the old and new decision records as the repository schema
  requires.
- For partial supersession or refinement, keep the still-valid decision active. State the affected
  scope in both records when the repository requires bidirectional traceability.
- Do not invent frontmatter fields, statuses, or link directions. If the repository has no
  supersession convention, propose one separately instead of adding an implicit schema.
- Update the terminology authority and affected uses when an established term changes.
- Add tracker traceability only when repository guidance requires it.
- Re-run the applicable mechanical checks on every touched artifact.

## Reminder setup (optional)

Propose a reminder only when it helps the repository workflow. Review its timing, visibility, and
host-specific behavior with the user before changing configuration. The reminder must remain
non-blocking because reconciliation can require confirmation. See [REFERENCE.md](REFERENCE.md) for
the reminder contract.
