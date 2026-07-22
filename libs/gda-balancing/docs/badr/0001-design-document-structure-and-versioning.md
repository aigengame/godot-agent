---
status: accepted
---

# One root Design document per game, semver-versioned, with a closed section envelope

> **Standard Schema 2.x outcome (2026-07-22):** this record remains accepted for 1.x. For 2.x,
> [bADR-0012](0012-language-and-artifact-authority-domains.md) supersedes the one-root authored
> authority, [bADR-0016](0016-closed-type-core-and-versioned-package-extensions.md) supersedes the
> fixed root/reserved-section extension model, and
> [bADR-0017](0017-genre-templates-and-coverage-contract.md) supersedes a template as one Design
> instance. The independent Schema/product versioning principle is retained.

A game's numeric design needs a durable, machine-readable home. PRD #501's problem
statement records the failure mode this bADR reverses: per-game numbers scattered across
ad-hoc config files, glued together by adapters, with no version field and schema
evolution tracked only in prose. This bADR fixes the document granularity, the top-level
section envelope, and the versioning contract for the Standard Schema (PRD #501; design
gate #503).

## Decision

- **One root Design document.** A game's complete numeric design is a single JSON
  document — a `Design document`, an instance of the Standard Schema. Subsystems are
  sections *within* it; there is no multi-file document set, no include mechanism, and no
  cross-file references. Tooling may compose or emit it, but the authored authority is one
  document. (Single-authority principle, PRD #501.)

- **Closed top-level envelope.** The document's top level is a fixed set of named keys;
  unknown top-level keys are refused (typed refusal, bADR-0004). v1 keys:
  - `schema_version` (required) and `meta` (required — design identity: `name` is its
    only required subfield; `description` and genre lineage are optional; the
    *document* names its game, the *toolkit* stays game-agnostic);
  - `$schema` (optional) — see the `$schema` rule below;
  - designed v1 sections: `parameters` (bADR-0003 — the declaration home of every named
    parameter formulas reference), `attributes` (bADR-0002), and `effects` (bADR-0006);
  - reserved sections, listed next.

- **`$schema` rule.** A document may carry the JSON Schema `$schema` key pointing at the
  versioned structural-schema `$id` (bADR-0005) so ecosystem editors get ambient
  validation. When present it must resolve to the same Standard Schema version the
  document's `schema_version` declares — disagreement is a typed refusal. `schema_version`
  remains the single authoritative version declaration; `$schema` is a convenience mirror,
  never an alternative authority.

- **Reserved sections, refused until designed.** Each reserved section has a fixed name,
  a recorded purpose (its reserved *shape*), and an owning issue; a document using one is
  refused with a dedicated refusal code until the owning issue lands its shape — never
  accepted-and-ignored. Silently carrying unvalidated content would fork the authority the
  Schema exists to be.

  | Section | Reserved shape (what it will hold) | Owner |
  |---|---|---|
  | `combat` | damage resolution and combat-parameter declarations consuming attributes/effects | #520 |
  | `encounters` | encounter composition and scheduling declarations | #520 |
  | `builds` | effect pools, pool sizes, selection pressure, synergy composition | #506 |
  | `growth` | progression semantics (levels/XP curves) over progression attributes | #507 |
  | `economy` | sources, sinks, stocks | #507 |
  | `targets` | declared balance targets for validation | Phase 2 (milestone #9) |

- **The Standard Schema is semver-versioned, independently of the toolkit package.**
  Documents declare the schema version they target in `schema_version` as a full semver
  string (OpenAPI-style, e.g. `"1.1.0"` — the OpenAPI document's `openapi: 3.1.0` field
  is the precedent for instances declaring the full spec version they target). Additive
  evolution (new optional fields, a reserved section gaining its shape) bumps **minor**;
  breaking evolution bumps **major**; **patch** never affects document validity (spec
  clarifications only). The **minor = strictly additive** discipline is load-bearing: it
  is what makes a middle "may break some documents" tier (SchemaVer's REVISION)
  unnecessary here — a change that could break any valid document is by definition major.

- **Version acceptance and patch normalization.** A validator supporting schema version
  `X.Y` accepts a document declaring major `X` and minor `≤ Y`; anything else — unknown
  major, newer minor, malformed version — is a typed refusal, never a warning or a
  best-effort parse. Because patch cannot affect validity, the declared **patch component
  is ignored for acceptance and resolution**: the validator resolves the declared
  `major.minor` to the artifact patch level it ships (so a declared `1.0.999` validates
  against the supported `1.0.x` definition — there is no per-patch acceptance hole).
  An accepted document is then validated **against the definition of the
  `major.minor` it declares**, not against the newest definition the validator knows: a
  `1.0` document using a section that only gained its shape in `1.1` is refused as
  reserved *under 1.0's envelope*, even on a `1.2`-capable validator. The declared
  version pins the contract; the acceptance rule only gates whether the validator can
  serve it.

- **JSON first, format-extensible.** The document model is defined at the semantic level;
  JSON is its first and authoritative serialization. Additional formats may be added
  without changing the semantic model (PRD #501, structured-output function). Emission
  canonicalization and the round-trip equality contract are bADR-0005's.

## Considered options

- **One root document** (chosen) — one boundary-funnel input (bADR-0004), no cross-file
  drift, matches the adjudicated strong-single-authority preference.
- **Multi-file document set** (rejected) — requires adapter glue and cross-file
  integrity checking, and splits the authority into fragments that evolve independently
  (the failure mode PRD #501 records).
- **Semver with declared `schema_version`** (chosen) — the additive/breaking split maps
  directly onto how reserved sections land (each is a minor bump); OpenAPI precedent for
  documents declaring the full version they target; patch normalization closes the
  unknown-patch hole without abandoning the precedent.
- **No document version** (rejected) — evolution becomes prose archaeology.
- **Integer version** (rejected) — cannot distinguish additive from breaking, so every
  consumer must treat every bump as breaking.
- **Date-based drafts** (JSON Schema's own style; rejected) — communicates recency, not
  compatibility; the toolkit's evolution cadence is additive-section-by-section, which is
  exactly what minor bumps express.
- **Registry-style compatibility modes** (Confluent Schema Registry idiom: monotonic
  integer versions + named compatibility modes, BACKWARD by default; rejected as a
  mechanism, and **flagged as the dominant data-schema idiom** by the #503 research) —
  registries mediate many independent producers negotiating evolution with many
  consumers. This toolkit's topology is different: it is the **single validation and
  production authority** — designers and agents author documents through its one boundary
  funnel, and games consume documents the toolkit has already validated and emitted
  (PRD #501). No party ever negotiates versions at consumption time, so compatibility is
  delivered by the minor-additive discipline plus major gating at the single authoring
  funnel. Hard refusal on version mismatch follows the *protocol/API version-gating*
  shape, not the registry shape.
- **SchemaVer** (MODEL-REVISION-ADDITION, compatibility-defined; rejected, closest
  precedent) — its REVISION tier ("may prevent interaction with *some* historical data")
  exists because data-platform schemas confront pre-existing instances they do not
  control. Under this bADR's strict minor-additive discipline that tier is empty by
  construction (see above), leaving exactly semver's major/minor split — so plain semver
  is kept for family consistency (gda is semver-versioned) while acknowledging SchemaVer
  as the nearest data-schema precedent.

## Consequences

- Each downstream section-owning issue (#520, #506, #507) lands its shape as a **minor**
  schema bump; genre templates (#505, #506) declare the `schema_version` they are
  authored against.
- The closed envelope makes "what is in a Design document" mechanically enumerable — a
  prerequisite for the self-description artifacts (bADR-0005).
- Per-game customization (#508) must work *within* one document (extension points, not
  side files); that issue inherits this constraint.

## References

- Research provenance (non-normative, provenance-labeled): issue #503 comments — main
  report and supplement. Versioning precedents examined there: OpenAPI declared-version
  practice; Confluent Schema Registry compatibility modes; SchemaVer (Snowplow/Iglu).
