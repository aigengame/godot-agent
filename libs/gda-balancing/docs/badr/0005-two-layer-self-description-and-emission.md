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
     without installing the toolkit.
  2. **Semantic rule catalog** — a machine-readable **index** of the semantic phase's
     rules: rule id (**identical to the refusal code**, bADR-0004), the document scope
     it applies to (a JSON Pointer template), a human description, and the schema
     version it appeared in. The catalog inventories the rules; it does not execute
     them.

     > **Amendment (2026-07-20, #527 recheck):** a rule's catalog `scope` is one
     > **or more** JSON Pointer templates — the field is a JSON array with one
     > template per site the rule can report (multi-site rules exist: shared
     > formula rules fire at attribute bases and effect magnitudes; temporal rules
     > at duration and period). The array shape and full-site enumeration are
     > enforced by a behavioral anti-drift test (every emitted refusal path matches
     > one of its rule's templates).

- **Honest division of labor — the validator is itself a required artifact.** The
  structural schema makes structure mechanically validatable by any ecosystem
  validator. Semantic validity (acyclicity, reference integrity, cross-facet
  predicates) is **enforced by the toolkit's versioned validator**, which is a required,
  versioned artifact of every schema release alongside the two self-description
  documents; the catalog is its machine-readable index. US8's "mechanically
  validatable" is delivered by validator + artifacts together — the self-description
  documents alone answer "what is structurally well-formed and which semantic rules
  exist", not "run all semantic rules yourself".

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
  semantic phase, enforced by the versioned validator and indexed by the catalog,
  closes the gap.

- **Delivery channel is out of scope here.** Whether the artifacts are exposed via a CLI
  command, an installed file path, or both is #518's (surface) and #504's
  (implementation) territory. This bADR defines the artifacts' existence, content, and
  versioning binding only.

- **Emission is JSON-first, format-extensible** (PRD #501). Design documents and
  toolkit reports serialize to JSON as the first and authoritative format; additional
  formats may be added without changing the semantic model. The structural schema
  describes the semantic model as rendered in JSON.

- **Canonical emission and the round-trip equality contract.** The toolkit emits
  canonical JSON: UTF-8, stable (sorted) object key order, LF line endings,
  shortest-round-trip number rendering, and optional fields with defined defaults
  materialized explicitly. Round-trip acceptance is **parsed-JSON semantic equality** —
  key order and whitespace are insignificant, numbers compare by value, and **an absent
  optional field is semantically equal to its defined default materialized
  explicitly** (so valid non-canonical input round-trips through canonical emission
  without a semantic change) — never byte equality of arbitrary input; canonical
  emission makes byte-stable output an emergent property for toolkit-emitted
  documents.

  > **Amendment (2026-07-20, #527 review):** "optional fields with defined defaults
  > materialized explicitly" means genuine **domain** defaults (an empty `accepts`,
  > the empty designed sections). An **optional member without a domain default is
  > absent-or-typed, never `null`**: it is omitted from canonical emission, and the
  > published structural schema drops the `X | None` null arm so an explicit `null`
  > refuses structurally. Round-trip equality reads accordingly: an absent optional
  > equals its materialized domain default, or its own omission when it has none.

## Considered options

- **JSON Schema + semantic rule catalog** (chosen) — ecosystem validators for free on
  the structural layer; the semantic layer machine-readable with refusal-code identity;
  no invented meta-format.
- **JSON Schema only** (rejected) — semantic rules fall back to prose and validator
  source; US8's "mechanically validatable" is only half-true and agents learn the
  semantic rules by trial refusal.
- **Executable semantic-rule DSL** (rejected) — publishing rules in a form third
  parties can execute would require designing and versioning a rule *language*: a
  second spec surface with its own operators, semantics, and drift risk, duplicating
  what the versioned validator already enforces. The catalog-as-index plus
  validator-as-artifact division delivers the same guarantee with one enforcement
  authority.
- **Bespoke self-description format** (rejected) — reinvents JSON Schema, abandons
  ecosystem validators, and violates the family's reuse-mature-solutions rule.
- **Custom JSON Schema keywords for semantic rules** (rejected) — nonstandard keywords
  are silently ignored by ecosystem validators, producing documents that "validate"
  under weaker semantics than the toolkit enforces — quiet drift by design.

## Consequences

- #504 implements artifact generation plus the conformance tests; the catalog and the
  funnel's refusal codes stay one namespace by construction.
- A Design document can carry `$schema` pointing at the versioned structural schema
  `$id`, giving editors and agents ambient structural validation; `$schema` must agree
  with `schema_version` (the envelope rule, bADR-0001).
- Each schema evolution (bADR-0001 minor/major bumps) republishes all three artifacts
  (structural schema, rule catalog, validator) in lockstep. Artifact `$id`s carry the
  full schema version; a document's declared `major.minor` resolves to the validator's
  shipped patch of that line (bADR-0001's patch normalization). A published version's
  self-description is immutable. **Historical minors need no separate distribution**:
  because minors are strictly additive (bADR-0001), a validator supporting `X.Y` ships
  the definitions of **every minor `X.0 … X.Y`** within its own artifact set — serving
  an older declared minor means validating against that minor's (subset) envelope, not
  fetching an older artifact.

## References

- Research provenance (non-normative): issue #503 comments — main report and supplement.
  Components verified against primary sources: JSON Schema 2020-12 core §12 (standard
  output formats); Spectral ruleset docs (stable rule ids, JSONPath targeting). Not to be
  confused with the TypeScript ecosystem's unrelated "Standard Schema" project (naming
  collision noted on #503).
