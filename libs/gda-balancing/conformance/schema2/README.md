# Schema 2.x claim-row conformance foundation

This directory documents the permanent machine gate implemented by
`gda_balancing.schema2.conformance`. The gate answers one narrow question:

> Does this exact claim definition have an exact, passed, non-duplicated closure of admitted
> versioned Operations, positive and negative/boundary normative vectors, and public artifact
> observations under one exact Kernel/LDB/Lock/RIR/Resolved-Model/Runtime/Experiment subject?

The report is deterministic and report-all. It remains `open` for missing, extra, duplicate,
unpassed, role/disposition-drifting, package-drifting, or subject-drifting facts. Research evidence
is carried separately and never satisfies an Operation, vector, or public-observation requirement.
The report echoes the claim-definition identity and complete exact subject, so it is not a detached
verdict that can be reused for another row or build. A normative vector definition is identified by
the exact LDB identity plus its vector id; a vector id alone is not a global content identity.

The typed contract is closed. It has no host handler, dispatch, Kernel override, or bypass field.
The validation host does not execute an Operation or provide missing language meaning. Content
identities must already have been rehashed and verified by the conformance step that produced each
result; a syntactically valid `sha256:` value or `passed: true` is not independently proved by this
aggregator. Its closure diagnostics are gate-local conformance findings, not Kernel/LDB-owned typed
refusal Diagnostics and not another language diagnostic catalog.

## Explicit non-claims

A green closure report does **not** prove:

- Kernel/LDB semantic execution, type soundness, lowering correctness, Replay, or Evidence;
- completeness of the Standard Schema 2.x constructor set;
- full Schema 2.x feasibility, reliability, orthogonality, or production readiness;
- closure of PRD #534 or any Tracer, RPG, Roguelike, or Variant coverage row unless that exact row's
  authoritative machine definition and independently verified results are the inputs.

The three genre research instances currently machine-record only `Int`/`Fixed` Quantity surfaces.
Their state-slot prose mentions `List`, `Set`, `Map`, `Record`, and `EntityRef`, but does not execute
or validate those constructors. `Bool`, `Decimal`, `Float`, `Enum`, `Vector`, and `Distribution`
also remain unproven by that research. This closure gate must not turn those prose references—or a
green report over any one row—into a type-system completeness claim.

The executable positive, research-only, identity-blast-radius, outcome/refusal, duplicate, extra,
failed, and bypass-field fixtures live in
[`../../tests/test_schema2_conformance_foundation.py`](../../tests/test_schema2_conformance_foundation.py).
They deliberately use a generic synthetic claim and close no live Genre row.
