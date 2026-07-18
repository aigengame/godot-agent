---
status: proposed
---

# One command descriptor seam: registration, projections, and the conformance harness

#518 requires the CLI contract to be structurally self-enforcing: a single seam every
command plugs into, plus a conformance test that walks the registered surface asserting
envelope and exit-code behavior — enforcement by architecture and tests, never by
per-issue prose. The family precedent is gda ADR-0023 (the descriptor whose render,
dispatch, and schema are projections). This bADR fixes the seam and the harness; the
CLI framework choice is #502's implementation territory and is deliberately not fixed
here.

## Decision

- **Every command registers exactly one frozen Command descriptor** *(pattern
  adopted-from-gda: ADR-0023; field set is balancing-local)*. The descriptor names
  everything the surface needs to run and describe one command: its tree position
  (group, command — bADR-0007), its typed input and output models (bADR-0009), and
  its execution markings — today exactly one, **stochastic** (bADR-0010). Registering
  the descriptor is the *only* way a command enters the surface; a command without
  one cannot be wired in.
  *(Recorded deviation from gda's field set: `render` — no human renderer exists,
  bADR-0008; `recipe`/`kind`/`projectless` — engine, daemon, and project channels
  have no analogue here. Fields are added when a real second channel exists, not
  speculatively.)*

- **All surface behavior is a projection of the descriptor.** Argv wiring, dispatch,
  `--schema` emission (bADR-0009), the future `manifest` aggregation, and the
  conformance harness's enumeration all read the one registry. Parallel registries —
  a render map here, a command list there — are prohibited *(adopted-from-gda:
  ADR-0023's single-registration consequence)*.

- **The registered surface is enumerable without side effects.** This is the
  harness's precondition, stated framework-agnostically: whatever CLI framework #502
  picks must expose, or be wrapped to expose, a walk of every registered descriptor
  (gda walks its live Typer tree; the mechanism is free, the walkability is law).

- **The conformance harness ships with the surface, from the first command.** It
  walks every registered descriptor and asserts, per command, every applicable row
  of the bADR-0008 contract:
  - success → exit 0, stdout is exactly one JSON document validating against the
    descriptor's output schema, canonically emitted (bADR-0005);
  - refusal (document-taking commands) → exit 2, a `refusal` envelope on stdout
    whose entry codes all resolve against the typed-refusal namespace — the funnel's
    preflight/structural families and semantic rule catalog, plus the downstream
    Evaluation refusal family (bADR-0003/0004/0005) — so the CLI can never grow a
    second refusal-code registry;
  - usage → exit 3, a `usage` envelope on stderr with a code from the CLI-usage
    registry; internal (fault injected) → exit 4, an `internal` envelope on stderr;
  - `--schema` → emits `input`/`output`/`error`, with `error` byte-identical across
    the walk (bADR-0009);
  - seed law → stochastic commands accept `--seed` and echo the effective seed;
    deterministic commands refuse it (bADR-0010);
  - input immutability → a command's input file is byte-identical before and after
    (bADR-0009);
  - reserved names → no command occupies `evaluation`/`tuning` before their owning
    issues land (bADR-0007).

- **The CLI-usage code family and the fixed `internal_error` code live in one
  registry** (bADR-0008), read by dispatch
  and by the harness, drift-tested the way the funnel's catalog is (bADR-0005's
  anti-drift rule; family precedent: gda's authoritative `error_codes` registry and
  its ADR-mirror drift test).

## Considered options

- **One descriptor + registry-walking harness** (chosen) — a conforming surface is
  the only easy path; coverage of every command is by construction, not by sampling.
- **Per-command hand-wiring plus review discipline** (rejected) — prose-enforced
  contracts drift; this gate exists to make that impossible.
- **The framework's native introspection as the contract** (rejected) — binds the
  public contract to #502's framework choice; the descriptor keeps the contract
  framework-agnostic and the framework swappable.
- **Golden end-to-end samples instead of a registry walk** (rejected) — samples prove
  the commands sampled; the walk proves the law holds for every registered command,
  including tomorrow's.

## Consequences

- #502 lands the descriptor, the registry, and the harness skeleton with `version`
  as the first registered command; #504 extends both with the `design` and `schema`
  groups.
- Adding a command without a descriptor is structurally impossible; adding one with a
  descriptor drags it under every harness assertion automatically. The harness is
  the executable form of bADR-0008/0009/0010.
- The descriptor gains fields only when a decided surface needs them (a `--format
  human` render seam, a `manifest` description field) — each addition rides its
  owning decision, keeping the seam honest about what exists.

## References

- gda ADR-0023 (descriptor single-registration) and its registration-invariant test
  suite — reference input; deviations recorded above.
- bADR-0004/0005 (refusal-code namespace and anti-drift), bADR-0007–0010 (the
  contract rows the harness executes).
- Research provenance (non-normative): issue #518 comment (2026-07-18).
