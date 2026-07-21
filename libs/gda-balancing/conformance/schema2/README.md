# Schema 2.x verified-artifact claim aggregation

`gda_balancing.schema2.conformance` is one permanent **Gate 2 sub-slice**. It answers a bounded
structural question:

> Do these exact canonical artifact bytes form a complete, non-duplicated candidate for one exact
> claim definition and Kernel/LDB/Lock/RIR/Resolved-Model/Runtime/Experiment subject?

It does not close the claim. A diagnostic-free report is `candidate`, never `closed`. Content
addressing proves payload integrity and exact binding; it does not prove that an independent
Kernel/LDB conformer produced or verified the artifact. Final claim closure therefore still needs
the permanent authoritative Kernel/LDB artifacts, executable normative vectors, and an independently
verifiable validator/receipt authenticity contract required by PRD #534 Gate 2.

## Contract

- Every consumed result is a bounded canonical artifact envelope containing exact payload bytes,
  artifact kind, wire-schema identity, and content identity. Consumption recalculates identity and
  strictly parses duplicate-free, finite canonical JSON with deterministic byte/depth/count caps.
- Operation admission and normative-vector results use closed local wire payloads. Their operation,
  package, vector role/disposition, exact subject, refusal Diagnostic, and verification-failure facts
  are parsed from artifact bytes. There is no caller `passed` field or detached result hash.
- A public-observable requirement binds its source vector, artifact kind, wire-schema identity, and
  JSON pointer. The source vector, exact subject, and observed field are derived from the public
  artifact payload.
- Positive vectors end in `success`; negative vectors end in `outcome` or `refusal`; boundary
  vectors may use any declared disposition. A refusal requires a typed Diagnostic and its public
  observation must be a `terminal_audit`. Evaluation, Metric, Replay/Cross-evaluator comparison, or
  Evidence-success artifacts cannot satisfy a refusal.
- The report is deterministic and report-all for independently observable missing, extra,
  duplicate, verification-failure, identity, package, role, disposition, kind, schema, source, and
  pointer defects. Research records are carried separately and satisfy none of those facts.
- The typed inputs contain no host handler, dispatch, Kernel override, or semantic bypass field.

## Explicit non-claims

A `candidate` report does **not** prove:

- artifact provenance/authenticity or independent verifier agreement;
- Kernel/LDB semantic execution, type soundness, lowering, Replay, Evidence, or publication safety;
- the unused-package metamorphic identity contract (whole LDB/Resolved Model/profile change while
  selected Lock/RIR bytes remain stable and Replay becomes ineligible);
- completeness, reliability, orthogonality, genre coverage, or production readiness of Schema 2.x;
- completion of Gate 2, PRD #534, or any Tracer/RPG/Roguelike/Variant row.

The executable candidate, tamper, semantic-failure, exact-binding, outcome/refusal, resource-cap,
report-all, research-only, and bypass fixtures live in
[`../../tests/test_schema2_conformance_foundation.py`](../../tests/test_schema2_conformance_foundation.py).
They use a generic synthetic claim and close no live Genre row.
