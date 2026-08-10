# Reconcile reference

This companion defines the reference-graph taxonomy, artifact discovery, check catalog, report
format, and optional reminder contract for [SKILL.md](SKILL.md).

## Discover repository authorities

Start with repository and directory guidance. Use it to locate:

- context routing and ownership rules;
- the issue or task tracker, if one exists;
- requirements, specifications, and decision records;
- the glossary or other terminology authority;
- schemas for identifiers, statuses, links, and supersession;
- local validation and editing rules.

A repository may have one context or several. Do not infer a global context from a root glossary or
one decision-record directory. Follow the repository's routing mechanism. If no routing mechanism
exists, infer the smallest relevant scope from authoritative links and disclose the assumption.

## Reference-graph edge taxonomy

Use repository-native names for concrete artifacts. The generic edge types are:

| Edge | Typical source -> target | Mechanical check | Semantic check |
| --- | --- | --- | --- |
| tracked work -> tracked work | parent, dependency, or related-work link | target exists | relationship and target state still mean what the source claims |
| tracked work -> authority artifact | requirement or decision reference | target exists | tracked work agrees with the authority |
| artifact -> artifact | file, section, identifier, or explicit relationship | target exists; required reciprocal pointer exists | relationship and affected scope remain accurate |
| artifact -> term | use of an established domain term | explicitly prohibited synonym is absent | term is established, correctly scoped, and used with its defined meaning |
| terminology authority -> artifact | source or decision behind a term | target exists | definition and cited authority agree |

Status fields, reciprocal links, and supersession metadata are graph data only when repository
guidance defines them. Never assume field names, allowed values, or link directions.

## How to read sources

- **Repository guidance:** identify artifact ownership, context boundaries, editing authority, and
  validation commands. Apply more specific nested guidance within its scope.
- **Tracked work:** use the configured tracker and its documented fields. Read linked records when
  their relationship affects the change. A closed state is not inherently inconsistent.
- **Decision records and specifications:** use the repository's locations, identifiers, statuses,
  and relationship schema. Read the normative sections and any stated scope.
- **Terminology authorities:** use the project's declared glossary or domain documentation. Only an
  explicit rule, such as a prohibited-synonym list, supports a mechanical terminology finding.
- **Other artifacts:** include tests, implementation docs, examples, or configuration when the
  changed fact governs them.

## Check catalog

### Mechanical checks

Run only checks with a deterministic result under the repository's declared syntax and schema:

1. **Missing reference target:** an explicit artifact, tracker, section, or file reference does not
   resolve.
2. **Explicit terminology violation:** text uses a synonym that the terminology authority explicitly
   prohibits.
3. **Required pointer asymmetry:** one side of a relationship is missing when the repository schema
   requires reciprocal pointers.

Do not treat a closed tracker record, a term absent from a glossary, or an unreferenced artifact as
a mechanical failure. These cases require context and belong in the semantic candidate set.

### Semantic checks

For each change, find overlapping artifacts and judge staleness from their meaning:

1. **Contradicted decision:** a statement conflicts with an accepted authority.
2. **Renamed or new term:** text uses an old name, or a candidate term may require definition in the
   terminology authority.
3. **Moved boundary:** an artifact still describes the old scope, phase, ownership, or dependency.
4. **Superseded behavior:** tracked work, docs, tests, or examples still require obsolete behavior.
5. **Supersession mismatch:** a record is marked as fully superseded when part remains valid, or a
   partial refinement is presented as a complete replacement.
6. **State mismatch:** a tracker state or relationship conflicts with its repository-defined meaning.
7. **Unreferenced artifact:** an artifact appears detached from the graph and repository rules make
   that detachment significant.

Use term and topic overlap to find candidates, then inspect their meaning. Do not report a semantic
finding from keyword overlap alone.

### Discount illustrative references

An identifier or path token is not always a graph edge. Exclude syntax examples, templates, and
other illustrative placeholders unless they claim to point to a real artifact.

## Supersession

First classify the change:

- **Complete supersession:** the new decision replaces the old decision throughout the old scope.
- **Partial supersession or refinement:** part of the old decision remains valid, or the new decision
  applies only to a narrower scope.

Then apply the repository-native schema. Update statuses, links, or inline statements only when its
guidance defines them. For partial supersession, preserve the valid scope and identify the replaced
scope precisely. If no schema exists, report the relationship and propose a convention separately.

## Reporting format

Group findings by artifact:

```text
### <artifact>
- [mechanical | semantic] <finding>
  evidence: <location and relevant text or state>
  impact: <consistency or execution effect>
  proposed: <local patch or exact repository-native remote edit>
```

When a proposal conflicts with an accepted authority, name that authority and state whether the
proposal should be dropped or the decision should be reopened.

## Optional reminder contract

A reminder may suggest reconciliation after a session or before a version-control operation. It
must:

- be visible through the host's documented output channel;
- say that reconciliation is only suggested, not completed;
- remain non-blocking;
- avoid editing local or remote artifacts;
- require approval before its configuration is added or changed.

A reminder is not automatic reconciliation. Describe it as automatic only if the host has a
documented invocation mechanism, the mechanism has been tested, and the workflow still preserves
the confirmation gate for mutations.
