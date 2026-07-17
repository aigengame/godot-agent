---
status: accepted
---

# One root Design document per game, semver-versioned, with a closed section envelope

A game's numeric design needs a durable, machine-readable home. The demo's embedded
pipeline scattered one game's numbers across nine JSON files plus a separate targets file,
wired together by adapter glue, and carried **no version field anywhere** — schema
evolution was tracked only in decision-record prose (gADR-0018's rename lists). This bADR
fixes the document granularity, the top-level section envelope, and the versioning
contract for the Standard Schema (PRD #501; design gate #503).

## Decision

- **One root Design document.** A game's complete numeric design is a single JSON
  document — a `Design document`, an instance of the Standard Schema. Subsystems are
  sections *within* it; there is no multi-file document set, no include mechanism, and no
  cross-file references. Tooling may compose or emit it, but the authored authority is one
  document. (Single-authority principle, PRD #501; the demo's multi-file + adapter shape
  is the counterexample this reverses.)

- **Closed top-level envelope.** The document's top level is a fixed set of named
  sections; unknown top-level keys are refused (typed refusal, bADR-0004). v1 required
  keys: `schema_version` and `meta` (design identity: name, description, genre lineage —
  the *document* names its game; the *toolkit* stays game-agnostic). v1 designed section:
  `attributes` (bADR-0002, bADR-0003).

- **Reserved sections, refused until designed.** `combat`, `encounters`, `builds`,
  `growth`, `economy`, and `targets` are reserved section names. Their shapes are designed
  by their owning issues — `combat`/`encounters` → #520, `builds` → #506,
  `growth`/`economy` → #507, `targets` (declared balance targets) → Phase 2 (milestone
  #9). Until a section's shape lands, a document using it is **refused** with a dedicated
  refusal code — never accepted-and-ignored. Silently carrying unvalidated content would
  fork the authority the Schema exists to be.

- **The Standard Schema is semver-versioned, independently of the toolkit package.**
  Documents declare the schema version they target in `schema_version` as a full semver
  string (OpenAPI-style, e.g. `"1.1.0"` — the OpenAPI document's `openapi: 3.1.0` field
  is the precedent for instances declaring the full spec version they target). Additive
  evolution (new optional fields, a reserved section gaining its shape) bumps **minor**;
  breaking evolution bumps **major**; **patch** never affects document validity (spec
  clarifications only). The **minor = strictly additive** discipline is load-bearing: it
  is what makes a middle "may break some documents" tier (SchemaVer's REVISION)
  unnecessary here — a change that could break any valid document is by definition major.

- **Version acceptance rule.** A validator supporting schema version `X.Y.*` accepts a
  document declaring major `X` and minor `≤ Y`; anything else — unknown major, newer
  minor, malformed version — is a typed refusal, never a warning or a best-effort parse.
  An accepted document is then validated **against the definition of the
  `schema_version` it declares**, not against the newest definition the validator knows:
  a `1.0` document using a section that only gained its shape in `1.1` is refused as
  reserved *under 1.0's envelope*, even on a `1.2`-capable validator. The declared
  version pins the contract; the acceptance rule only gates whether the validator can
  serve it.

- **JSON first, format-extensible.** The document model is defined at the semantic level;
  JSON is its first and authoritative serialization. Additional formats may be added
  without changing the semantic model (PRD #501, structured-output function).

## Considered options

- **One root document** (chosen) — one boundary-funnel input (bADR-0004), no cross-file
  drift, matches the adjudicated strong-single-authority preference.
- **Multi-file document set** (rejected) — the demo's shape; requires adapter glue and
  cross-file integrity checking, and splits the authority into fragments that evolve
  independently.
- **Semver with declared `schema_version`** (chosen) — the additive/breaking split maps
  directly onto how reserved sections land (each is a minor bump); OpenAPI precedent for
  documents declaring the full version they target.
- **No document version** (rejected) — the demo's status quo; evolution becomes prose
  archaeology.
- **Integer version** (rejected) — cannot distinguish additive from breaking, so every
  consumer must treat every bump as breaking.
- **Date-based drafts** (JSON Schema's own style; rejected) — communicates recency, not
  compatibility; the toolkit's evolution cadence is additive-section-by-section, which is
  exactly what minor bumps express.
- **Registry-style compatibility modes** (Confluent Schema Registry idiom: monotonic
  integer versions + named compatibility modes, BACKWARD by default; rejected as a
  mechanism, and **flagged as the dominant data-schema idiom** by the #503 research) —
  registries mediate many independent producers and consumers and *negotiate*
  compatibility between schema versions; a Design document is an authored
  single-authority file validated at one boundary funnel with a single consumer (the
  toolkit). There is nothing to negotiate — the funnel either understands the declared
  version or refuses. Hard refusal on version mismatch follows the *protocol/API
  version-gating* shape, not the registry shape; adopting compatibility modes here would
  import machinery whose purpose (multi-party evolution negotiation) does not exist in
  this topology.
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
