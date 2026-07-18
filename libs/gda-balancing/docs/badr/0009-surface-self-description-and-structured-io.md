---
status: proposed
---

# Surface self-description, structured input, and config/logic separation

bADR-0005 defined the Standard Schema's two self-description artifacts and left their
delivery channel to this gate; gda's surface conventions (`--schema`, structured params
input) are the family reference. This bADR fixes how the *toolkit's command surface*
describes itself, how the self-description artifacts are delivered, how structured
input enters, and the config/logic separation every command obeys (design gate #518).

## Decision

- **Per-command `--schema`, emit-only** *(adopted-from-gda: ADR-0004)*. Every
  **registered** command — domain commands and the registered meta command
  `version` alike (bADR-0011's meta rule) — supports `--schema`, which emits a JSON
  object with keys `input` (the command's parameter schema), `output` (its
  success-result schema), and `error` (the bADR-0008 envelope schema —
  **byte-identical across every command**). The flag only emits, never accepts;
  bare `--schema` wins over any other argument *(adopted: ADR-0015's precedence
  rule)*. `help` is the one exempt human-facing surface and carries no `--schema`
  (bADR-0007/0011).

- **Model-driven, with one deliberate division of authority** *(adopted-from-gda:
  ADR-0004; anti-drift as in bADR-0005)*. Each command's typed input and output
  models own **field names, types, validation, defaults, result serialization, and
  both `--schema` keys** — a hand-maintained schema copy is prohibited. **Argv
  presentation belongs to the Command descriptor** (bADR-0011): the binding law
  derives each option mechanically from a model field, and the descriptor's
  positional designation is binding metadata the model deliberately does not carry
  (an input schema cannot express positional-vs-option, gda ADR-0015). Two
  authorities, disjoint territories, both inside the single registration.

- **The `schema` group is the sole public delivery channel for the Standard Schema's
  self-description artifacts** *(completes bADR-0005's deferral; maintainer-adjudicated
  2026-07-18)*. `schema get structural` and `schema get catalog` emit the structural
  schema and the semantic rule catalog (bADR-0005), canonically emitted, to stdout.
  Packaged data files may exist but are an implementation detail — **no installed
  file path is a public contract** (a site-packages path is a brittle interface
  agents cannot reliably locate, and a second authority surface to guard).
  bADR-0005's "runnable by off-the-shelf validators" is a property of the artifact's
  *content*; redirecting the emission to a file serves that workflow — any emitted
  copy is the artifact, so validating "without installing the toolkit" needs only a
  copy someone emitted, not an installation of one's own. Free-standing publication
  (a hosted URL) is an explicit extension point for a future bADR; until it exists,
  the structural schema's `$id` is an *identifier*, not a dereferenceable location
  (JSON Schema's own treatment of `$id`), and the editor ambient validation
  bADR-0001/0005 describe via `$schema` requires pointing the editor at an emitted
  copy.

- **Config/logic separation.** Commands take the `Design document` as an explicit
  file-path argument — configuration is data handed to the tool, never encoded in
  flags *(family convention; PRD #501 US19)*. The typed result always stays on
  stdout (bADR-0008); where an artifact file is wanted, an explicit `--out <path>`
  receives the **artifact body** while stdout carries the result as a receipt —
  `--out` moves the artifact, never the result. The receipt is one normative
  member: **`artifact: {path, bytes}`** (resolved sink path, bytes written),
  present in the result object exactly when `--out` was used and forbidden
  otherwise; the rest of the result stays the command's own output model.
  Artifact writes are safe by law: an existing destination is overwritten; the
  write is atomic (write-then-rename), so a failed invocation leaves no partial
  file; an unwritable sink is a usage error (`unwritable_output`, bADR-0008).
  **No command ever writes to its input path** *(new ground, grounded in
  bADR-0004)*: validity is a property of a document state, and any mutated state
  must visibly re-enter the funnel — an in-place write would silently alias an
  unvalidated state over the input authority. `--out` resolving to the input
  path, directly or through a symlink alias, is therefore a usage error with the
  stable code **`argument_conflict`** (the two arguments' *values* collide).
  Derived documents (a `design format` emission, a Phase-2 tuning result) are
  always a new stream or path.

- **Structured params input: adopted in principle, deferred in delivery.**
  *(adopted-from-gda: ADR-0015 — semantics reserved verbatim; delivery deferred.)*
  The enabling architecture is mandatory from the first command: typed input models
  with argv as a thin adapter, so a structured-params channel is purely additive.
  The flag `--params-json <json | ->` (with `-` reading stdin), its mutual exclusion
  with individual arguments (a usage error, bADR-0008), and its `--schema`
  precedence rule are reserved exactly as gda ADR-0015 defines them, and are
  delivered when an adapter consumer (an MCP or similar protocol adapter) exists.
  Until then the input models are already published through `--schema`'s `input` key,
  so the ABI is visible before the channel ships.

- **The aggregate surface manifest is named `manifest` and deferred** *(shape
  adopted-from-gda: ADR-0012; name is the bADR-0007 deviation; delivery deferred)*.
  When an adapter consumer exists, a meta command `manifest` emits the whole-surface
  document — one entry per dispatchable command with `name`, `description`, `input`,
  `output`, `error`; non-dispatchable meta commands excluded at the source — walking
  the same registry the conformance harness walks (bADR-0011). Deferred on the same
  no-consumer ground as `--params-json`; the name is fixed now so nothing squats.

- **`version` self-describes both authorities** *(bADR-0007 meta command; bADR-0001)*:
  the toolkit package version and the supported Standard Schema line, as distinct
  fields in one result object — never a single conflated version string.

## Considered options

- **CLI emission as the sole artifact channel** (chosen) — one public seam,
  version-locked to the installed toolkit, canonical by construction.
- **Installed file path as a public contract** (rejected) — brittle discovery, a
  second guarded surface; every workflow it serves is covered by redirecting the
  emission.
- **Both channels** (rejected) — two authorities for one artifact with no consumer
  demanding the second; two independently served copies of one artifact is the
  drift-by-design bADR-0005's anti-drift rule exists to prevent.
- **`--params-json` delivered in v1** (rejected) — all carrying cost, no consumer;
  gda grew it *for* gda-mcp, which has no analogue here yet.
- **No reservation of the deferred surfaces** (rejected) — retrofit risk: without the
  reserved names and semantics, later delivery would be a fresh design liable to
  drift from the family ABI.

## Consequences

- #504 implements `schema get structural` / `schema get catalog` and per-command
  `--schema`; the conformance harness (bADR-0011) asserts `--schema` presence and
  validity for every registered command, and that the emitted `error` schema is the
  one bADR-0008 envelope.
- Delivering `--params-json` or `manifest` later is an additive slice: reserved
  semantics + already-typed input models mean no existing surface changes.
- The never-mutate-the-input rule is testable per command (input bytes before ==
  after) and belongs to the conformance harness.

## References

- gda ADR-0004 (`--schema`), ADR-0012 (aggregate manifest), ADR-0015 (structured
  params input) — reference input; adoption and deviations recorded above.
- bADR-0005 — the artifacts this surface delivers; bADR-0008 — the envelope its
  `error` key publishes.
- Research provenance (non-normative): issue #518 comment (2026-07-18).
