---
status: accepted
---

# Two-layer self-description: JSON Schema artifact plus semantic rule catalog

US8 requires the Standard Schema to be self-describing and mechanically validatable, so
agents can generate, check, and mutate Design documents programmatically. Structural
validity alone does not make a document valid (bADR-0004's semantic layer), so a
self-description that stops at structure would fulfill US8 only halfway. This bADR fixes
the self-description and emission artifacts (design gate #503). It is **distinct from
#518's CLI-surface self-description** — how the *toolkit's commands* describe themselves
is that contract; how the *Schema* describes itself is this one.

## Decision

- **Two published self-description artifacts, versioned with the Standard Schema
  (bADR-0001):**
  1. **Structural schema** — a JSON Schema 2020-12 document whose instances are Design
     documents; its `$id` embeds the Standard Schema version. Any agent can
     structurally pre-validate a document with off-the-shelf ecosystem validators,
     without installing the toolkit. (Internal precedent: the demo's hand-written
     `data/schema/*.schema.json`; the difference here is anti-drift below.)
  2. **Semantic rule catalog** — a machine-readable catalog of the semantic layer's
     rules: rule id (**identical to the refusal code**, bADR-0004), the document scope
     it applies to (JSON Pointer), a human description, and the schema version it
     appeared in. Together the two artifacts are the complete machine-readable answer
     to "what is a valid Design document".

- **Evidence status (recorded honestly, #503 research).** Each component is verified
  industry practice: JSON Schema 2020-12 is the structural layer's own standard,
  including §12's machine-readable validation output; named-rule catalogs with stable
  ids layered over structurally-valid documents are exactly the OpenAPI ecosystem's
  linting practice (Spectral rulesets — the rule's name is its stable id, JSONPath
  targeting) and the universal linter idiom (ESLint rule ids). The **composite** —
  shipping both artifacts as one versioned self-description whose rule ids double as
  refusal codes — has no single verified precedent; it is this toolkit's own assembly of
  those precedents, and this bADR is its record.

- **Anti-drift is structural, not disciplinary.** The artifacts are derived from the
  validator's own definitions (generated), or — where generation is impractical —
  guarded by a conformance test that walks the catalog asserting each rule's refusal
  behavior and walks the structural schema against golden fixtures. A hand-maintained
  second copy of either artifact is prohibited: one authority, projections and tests
  around it. (Family precedent: gda ADR-0004's model-driven schemas, reference input.)

- **Full validity = structural + semantic.** The structural schema is deliberately
  honest about its limits: passing it means structurally well-formed, not valid. The
  catalog is what closes the gap machine-readably.

- **Delivery channel is out of scope here.** Whether the artifacts are exposed via a CLI
  command, an installed file path, or both is #518's (surface) and #504's
  (implementation) territory. This bADR defines the artifacts' existence, content, and
  versioning binding only.

- **Emission is JSON-first, format-extensible** (PRD #501). Design documents and
  toolkit reports serialize to JSON as the first and authoritative format; additional
  formats may be added without changing the semantic model. The structural schema
  describes the semantic model as rendered in JSON.

## Considered options

- **JSON Schema + semantic rule catalog** (chosen) — ecosystem validators for free on
  the structural layer; the semantic layer machine-readable with refusal-code identity;
  no invented meta-format.
- **JSON Schema only** (rejected) — semantic rules fall back to prose and validator
  source; US8's "mechanically validatable" is only half-true and agents learn the
  semantic rules by trial refusal.
- **Bespoke self-description format** (rejected) — reinvents JSON Schema, abandons
  ecosystem validators, and violates the family's reuse-mature-solutions rule.
- **Custom JSON Schema keywords for semantic rules** (rejected) — nonstandard keywords
  are silently ignored by ecosystem validators, producing documents that "validate"
  under weaker semantics than the toolkit enforces — quiet drift by design.

## Consequences

- #504 implements artifact generation plus the conformance tests; the catalog and the
  funnel's refusal codes stay one namespace by construction.
- A Design document can carry `$schema` pointing at the versioned structural schema
  `$id`, giving editors and agents ambient structural validation.
- Each schema evolution (bADR-0001 minor/major bumps) republishes both artifacts in
  lockstep — a version's self-description is immutable once published.

## References

- Research provenance (non-normative): issue #503 comments — main report and supplement.
  Components verified against primary sources: JSON Schema 2020-12 core §12 (standard
  output formats); Spectral ruleset docs (stable rule ids, JSONPath targeting). Not to be
  confused with the TypeScript ecosystem's unrelated "Standard Schema" project (naming
  collision noted on #503).
