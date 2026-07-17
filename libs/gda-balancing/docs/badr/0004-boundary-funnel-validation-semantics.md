---
status: accepted
---

# Validation at one boundary funnel: two layers, element-level typed refusals, report-all

Agents drive this toolkit (PRD #501 US8, US19); what they need from validation is a
mechanical answer to "is this Design document valid, and if not, exactly what and where".
The demo's precedent (`config.py:_typed()`, `ConfigError(code, detail)`) established
typed refusals distinct from verdicts, but it fails fast on the first error and reports
location in prose. This bADR fixes the validation semantics of the Standard Schema
(design gate #503). The CLI surface of these refusals — envelope shape, exit codes — is
#518's contract, not this document's.

## Decision

- **One boundary funnel.** Every Design document crosses a single validation boundary
  before any use; downstream code (evaluators, simulation, emission) never re-validates
  and never defends. The funnel is the only home of refusal logic. (Family precedent:
  the demo's load-time funnel and the assets pipeline's element-level boundary probes;
  also the recorded rule against `assert`-guards at external-input boundaries.)

- **Two layers, in order:**
  1. **Structural** — the document is validated against the published structural schema
     (JSON Schema 2020-12 artifact, bADR-0005): types, required fields, closed
     envelopes, enums, bounds expressible structurally.
  2. **Semantic** — rules beyond structural expressiveness, drawn from the
     machine-readable semantic rule catalog (bADR-0005): version acceptance
     (bADR-0001), reference integrity (formulas reference declared
     attributes/parameters), derivation acyclicity (bADR-0002), operator closure and
     tree limits (bADR-0003), modifier bound domains, reserved-section refusal
     (bADR-0001).

- **Element-level typed refusals.** Each violation is reported as a refusal carrying:
  a **stable refusal code**, the **instance path** as a JSON Pointer (RFC 6901) down to
  the offending element — never just the enclosing collection — and a human-readable
  detail. For semantic refusals the code **is** the semantic rule's id (one identity,
  bADR-0005); structural refusals share a stable structural code family with the
  violated JSON Schema keyword in the detail. Precedent for the error shape: JSON Schema
  2020-12 §12 defines a standard machine-readable output whose units carry the keyword
  location, the **instance location as a JSON Pointer**, and the error — the structural
  layer's refusals are a direct projection of that standard output into the toolkit's
  refusal shape.

- **Report-all, bounded.** Validation collects **all** violations (up to a sanity bound)
  instead of failing fast. An agent iterating on a generated document fixes a batch per
  round trip; fail-fast (the demo's behavior) turns N errors into N round trips.

- **Refusal ≠ verdict.** A refusal rejects invalid *input*; a balance pass/fail verdict
  judges a *valid* design against targets (Phase 2). The distinction is semantic here
  and carried to the CLI (distinct exit codes) by #518.

## Considered options

- **Single funnel, two layers, report-all** (chosen) — one home for refusal logic;
  ecosystem validators handle the structural layer; agents get batch-fixable reports.
- **Fail-fast** (rejected) — the demo's behavior; cheapest to implement, most expensive
  for the agent feedback loop.
- **Validation sprinkled at use sites** (rejected) — refusal logic fragments, codes
  drift, and downstream code grows defensive re-checks.
- **Structural layer only** (rejected) — reference integrity, acyclicity, and closure
  are exactly the failures that corrupt simulation results silently; leaving them to
  runtime errors reclassifies design errors as crashes.

## Consequences

- The refusal-code namespace is owned by the funnel: structural family + semantic rule
  catalog. #518's envelope carries these codes without minting its own.
- A conformance test walks the semantic rule catalog asserting each rule refuses its
  violation fixture — the catalog cannot drift from the validator (bADR-0005).
- Downstream engine code (#504 onward) is written assumption-free of invalid input —
  simpler, and any internal defensive check is a smell.
