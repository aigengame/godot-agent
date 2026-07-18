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

- **Per-command `--schema`, emit-only** *(adopted-from-gda: ADR-0004)*. Every domain
  command supports `--schema`, which emits a JSON object with keys `input` (the
  command's parameter schema), `output` (its success-result schema), and `error` (the
  bADR-0008 envelope schema — **byte-identical across every command**). The flag only
  emits, never accepts; bare `--schema` wins over any other argument *(adopted:
  ADR-0015's precedence rule)*.

- **Model-driven, single source** *(adopted-from-gda: ADR-0004; anti-drift as in
  bADR-0005)*. Each command's typed input and output models are the one authority:
  argv parsing, result serialization, and both `--schema` keys derive from them.
  A hand-maintained schema copy is prohibited.

- **The `schema` group is the sole public delivery channel for the Standard Schema's
  self-description artifacts** *(completes bADR-0005's deferral; maintainer-adjudicated
  2026-07-18)*. `schema get structural` and `schema get catalog` emit the structural
  schema and the semantic rule catalog (bADR-0005), canonically emitted, to stdout.
  Packaged data files may exist but are an implementation detail — **no installed
  file path is a public contract** (a site-packages path is a brittle interface
  agents cannot reliably locate, and a second authority surface to guard).
  bADR-0005's "runnable by off-the-shelf validators" is a property of the artifact's
  *content*; redirecting the emission to a file serves that workflow. Free-standing
  publication (a hosted URL) is an explicit extension point for a future bADR.

- **Config/logic separation.** Commands take the `Design document` as an explicit
  file-path argument — configuration is data handed to the tool, never encoded in
  flags *(family convention; PRD #501 US19)*. Command output goes to stdout, or to an
  explicit `--out <path>` where a file is wanted. **No command ever writes to its
  input path** *(new ground, grounded in bADR-0004)*: validity is a property of a
  document state, and any mutated state must visibly re-enter the funnel — an
  in-place write would silently alias an unvalidated state over the input authority.
  Derived documents (a `design format` emission, a Phase-2 tuning result) are always
  a new stream or path.

- **Structured params input: adopted in principle, deferred in delivery.**
  *(adopted-from-gda: ADR-0015 — semantics reserved verbatim; delivery deferred.)*
  The enabling architecture is mandatory from the first command: typed input models
  with argv as a thin adapter, so a structured-params channel is purely additive.
  The flag `--params-json <json | ->` (with `-` reading stdin), its mutual exclusion
  with individual arguments (a usage refusal, bADR-0008), and its `--schema`
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
  demanding the second; violates the single-authority rule (RULES).
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
