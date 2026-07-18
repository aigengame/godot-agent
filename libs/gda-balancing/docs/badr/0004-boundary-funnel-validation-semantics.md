---
status: proposed
---

# Validation at one boundary funnel: phased, element-level typed refusals, report-all

Agents drive this toolkit (PRD #501 US8, US19); what they need from validation is a
mechanical answer to "is this Design document valid, and if not, exactly what and where".
PRD #501's testing decisions require element-level typed refusals at a boundary funnel,
distinct from pass/fail verdicts. This bADR fixes the validation semantics of the
Standard Schema (design gate #503). The CLI surface of these refusals — envelope shape,
exit codes — is #518's contract, not this document's.

## Decision

- **One boundary funnel.** Every Design document crosses a single validation boundary
  before any use; downstream code (evaluators, simulation, emission) never re-validates
  and never defends. The funnel is the only home of refusal logic. (Assertion guards
  are excluded on principle: an uncaught assert turns invalid input into a crash and
  disappears under optimization — a typed refusal is the only rejection path.)

- **One sanctioned downstream refusal class: the Evaluation refusal.** The funnel
  validates document *states*; result **finiteness** depends on runtime values it
  cannot see (a divisor an effect drives to zero mid-simulation). Evaluators therefore
  carry exactly one refusal class of their own — the non-finite Evaluation refusal
  (bADR-0003), with its own stable code family — and nothing else. "Never defends"
  means no re-validation of input validity downstream; it does not outlaw this one
  runtime class, which no input validation can subsume.

- **Validity is a property of a document state, not a document identity.** Any mutation
  — an agent edit, a Phase-2 tuning step — invalidates; the mutated document re-enters
  the funnel before any evaluation or emission. "Downstream never re-validates" means
  no *sprinkled* re-checking inside one validated pass — it never licenses evaluating
  or emitting a document state the funnel has not seen. The tuning loop's shape is
  mutate → funnel → evaluate, every iteration.

- **Three phases, strictly ordered, each gating the next:**
  0. **Preflight** — ingress caps (below) and version dispatch: the document parses as
     JSON within the caps, `schema_version` is well-formed, and its major.minor is
     supported (acceptance + patch normalization per bADR-0001). Preflight selects the
     versioned artifacts every later phase validates against. Preflight refusals are
     terminal (nothing else can run without a pinned version).
  1. **Structural** — the document is validated against the version's published
     structural schema (JSON Schema 2020-12 artifact, bADR-0005): envelope closure,
     types, required fields, enums, structurally expressible bounds.
  2. **Semantic** — runs only when the structural phase produced **no refusals**
     (structurally broken documents make semantic analysis ill-defined): reference
     integrity (formula `attr`/`param` nodes, effect targets, stacking types, tier labels — bADR-0002,
     bADR-0003, bADR-0006), id uniqueness per namespace (bADR-0002), formula-reference
     acyclicity, operator closure and tree limits (bADR-0003), cross-facet rules and the
     bounds obligation by domain and tier-pattern satisfaction (bADR-0002), effect
     `application`×`duration` legality, `override`-on-delta legality, the `period`
     requirement by modifier mix, temporal validity (positive finite duration/period,
     minimum granularity, tick budget), stacking declaration rules (bADR-0006),
     `$schema`-agreement and reserved-section refusal (bADR-0001).

- **Ingress caps (v1 normative; raising any is a minor bump).** Document ≤ 10 MiB;
  JSON nesting depth ≤ 64; ≤ 10 000 elements per collection; expression-tree limits per
  bADR-0003. Cap violations are typed refusals at preflight — resource exhaustion is a
  refusal class, not a crash class.

- **Element-level typed refusals.** Each violation is reported as a refusal carrying:
  a **stable refusal code**, the **instance path** as a JSON Pointer (RFC 6901) down to
  the offending element — never just the enclosing collection — and a human-readable
  detail. For semantic refusals the code **is** the semantic rule's id (one identity,
  bADR-0005); structural refusals share a stable structural code family with the
  violated JSON Schema keyword in the detail. Precedent for the error shape: JSON
  Schema 2020-12 §12 defines a standard machine-readable output whose units carry the
  keyword location, the **instance location as a JSON Pointer**, and the error — the
  structural phase's refusals are a direct projection of that standard output into the
  toolkit's refusal shape.

- **Report-all, deterministic, bounded.** Within each executed phase, validation
  collects **all** violations rather than failing fast — an agent fixes a batch per
  round trip, not one error per trip. The refusal list is deterministic: deduplicated
  on (code, instance path), ordered by instance path (JSON Pointer, lexicographic) then
  code. At most **1000** refusals are reported; when the bound truncates, the result
  carries an explicit `truncated` marker so "1000 refusals" is never mistaken for "all
  refusals".

- **Refusal ≠ verdict.** A refusal rejects invalid *input*; a balance pass/fail verdict
  judges a *valid* design against targets (Phase 2). The distinction is semantic here
  and carried to the CLI (distinct exit codes) by #518.

## Considered options

- **Phased funnel, report-all** (chosen) — one home for refusal logic; ecosystem
  validators handle the structural phase; agents get batch-fixable, deterministic
  reports.
- **Fail-fast** (rejected) — cheapest to implement, most expensive for the agent
  feedback loop.
- **Semantic phase on structurally broken documents** (rejected) — semantic rules
  presuppose well-formed shapes; running them anyway yields cascading noise refusals
  that bury the structural cause.
- **Validation sprinkled at use sites** (rejected) — refusal logic fragments, codes
  drift, and downstream code grows defensive re-checks.
- **Structural phase only** (rejected) — reference integrity, acyclicity, and closure
  are exactly the failures that corrupt simulation results silently; leaving them to
  runtime errors reclassifies design errors as crashes.

## Consequences

- The refusal-code namespace is owned by the funnel: preflight + structural families
  plus the semantic rule catalog. #518's envelope carries these codes without minting
  its own.
- A conformance test walks the semantic rule catalog asserting each rule refuses its
  violation fixture — the catalog cannot drift from the validator (bADR-0005).
- Downstream engine code (#504 onward) is written assumption-free of invalid input —
  simpler, and any internal defensive check is a smell.
- **The normative vector set is part of this design**: `docs/badr/normative-vectors.md`
  (V1–V12) gives concrete inputs and required outcomes for the minimal document,
  typed same-id references, collection-valued forms, tier-pattern satisfaction,
  stacking/`period` legality, additive and multiplicative deltas with same-instant
  semantics, global override selection, continuous re-evaluation, the non-finite
  Evaluation refusal, absent-vs-materialized default equality, and version dispatch.
  #504 implements these as executable tests (plus per-rule fixtures for every catalog
  entry) — it does not design their outcomes.
