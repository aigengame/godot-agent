---
status: accepted
---

# Genre templates ship as packaged Schema instances; `template get` is instantiate

#505 ships the first `Genre template` (the RPG family) and its `Reference fixture`s.
The upstream decisions constrain most of the shape — templates are data, never code
paths (PRD #501, bADR-0002); the `template` group with `list`/`get` is declared and
"the instantiation command's shape is owned by #505/#506" (bADR-0007); genre lineage
is an optional `meta` subfield (bADR-0001); and the isolation gate (#502) forbids
stray JSON under `src/`. This bADR fixes what remains open: the template's concrete
representation and delivery channel, the instantiation command's shape, the lineage
field's shape, and what "a fixture instantiates the template" means before #508's
extend/override mechanism exists.

## Decision

- **A Genre template is one packaged canonical-JSON Design document** —
  `src/gda_balancing/templates/<id>.json`, read via `importlib.resources`, shipped in
  the wheel (build-verified). It is a plain instance of the Standard Schema: it
  validates through the boundary funnel unchanged, and its committed bytes are exact
  `design format` output (canonical-bytes discipline, enforced by test). The file is
  the **single authority** — no golden copy exists; `template get`, `design format`,
  and the committed bytes are asserted three-way identical. A template declares
  `$schema` pointing at the structural schema's `$id` (the bADR-0001 mirror), so an
  instantiated document carries ambient-validation wiring from the start.

- **`template get <id> [--out <path>]` *is* instantiation.** A Genre template already
  is a valid Design document, so instantiating one is obtaining it: `--out` writes the
  consumer's starting document (bADR-0009's artifact-sink law; receipt on stdout).
  Renaming the game and adjusting values are the consumer's edits; the *declared*
  extend/override mechanism is #508's scope. No new verb enters the bADR-0007
  vocabulary — `get`/`list` suffice. The handler parses the packaged JSON directly and
  never runs the funnel, so `template get` never refuses (mirroring `schema get`);
  template validity is the test suite's guarantee, not a per-invocation check. An
  unknown id fails `Literal` input binding → usage / exit 3, automatically.

- **Template identity has one authored home**: the `_TEMPLATES` registry (id →
  one-line summary) in the template command module. The `Literal` on `template get`'s
  input (the `--schema`-visible contract) and the packaged `<id>.json` resources are
  projections of it, held together by a consistency test. Adding a template (#506's
  Roguelike) = one JSON file + one registry entry + one `Literal` member.

- **Genre lineage is `meta.genre: {family, variant?}`** — both `IdStr`-shaped, no
  enum, purely descriptive. No toolkit code may branch on it (templates are data,
  bADR-0002); the family template declares `{family: "<id>"}`, a subtype document adds
  `variant`. The field **completes the schema line 1.0 envelope in place** rather than
  cutting a 1.1 minor: bADR-0001 already enumerates genre lineage as an optional v1
  `meta` subfield and only its implementation was deferred to #505, and the package is
  unpublished, so no external consumer can observe the change. *(This move is
  legitimate only pre-publication: the first additive field after the toolkit
  publishes must be a minor bump per bADR-0001.)*

- **Isolation-gate carve-out** (amending #502's gate, which is the constraint's single
  owner): `src/gda_balancing/templates/` is exempt from the stray per-game-config JSON
  scan — a Genre template is a genre-generic baseline, not a per-game config — while
  template JSON **and** the committed test-fixture JSON join the game-identity
  vocabulary scan, closing the gap that Design-document content was previously
  unscanned.

- **A `Reference fixture` instantiates the family template iff its `attributes.tiers`
  equals the template's `tiers` map** — the executable lineage relation until #508
  lands a declared mechanism. Fixtures remain test-suite data under
  `tests/fixtures/reference/`, never packaged.

- **A template's human documentation lives at `docs/templates/<id>.md`** — the tier
  vocabulary, each default and formula with rationale and provenance (industry-standard
  terminology, multi-source, non-normative). "Alongside the template" is this fixed
  home; #508 documents the extend/override mechanism next to it. The packaged JSON
  stays the numeric authority — the document explains, never redefines.

## Considered options

- **Template as authored Python data** (a dict literal emitted on demand): keeps the
  gate untouched, but forks the authority — the shipped artifact would no longer be
  the authored form, and "an instance of the Standard Schema" would exist only at
  runtime. Rejected: JSON is the first and authoritative serialization (bADR-0005).
- **Template as test-only fixture** (no packaged data, no `template` commands):
  cheapest, but a Genre template is shipped product an agent instantiates through the
  CLI (PRD #501 US2/US7); a test asset cannot be that. Rejected.
- **A dedicated instantiation verb** (`template instantiate`/`create`): adds a verb
  the bADR-0007 vocabulary doesn't sanction for zero semantic gain over `get --out`
  while #508 owns real customization. Rejected.
- **Schema 1.1 minor bump for `meta.genre`**: the orthodox reading of bADR-0001's
  additive-evolution rule, but disproportionate pre-publication — it would fork a
  second `VersionBundle` to describe an envelope bADR-0001 had already declared for
  v1. Rejected with the pre-publication-only caveat recorded above.

## Consequences

- The wheel carries non-`.py` payload for the first time; the build check
  (`uv build` + wheel listing) is part of the template DoD.
- `template get`'s output is covered by the same canonical-emission and conformance
  laws as every artifact-sink command; the descriptor registry sweeps it automatically.
- #506 extends the registry/Literal/resources trio and inherits the carve-out
  unchanged; #508 builds the declared extend/override mechanism on top of `get`.
- The structural schema golden regenerates once for `meta.genre`; the semantic rule
  catalog is untouched (no new rule — lineage has no computational semantics).
