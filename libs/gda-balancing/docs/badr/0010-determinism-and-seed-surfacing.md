---
status: proposed
---

# Determinism and seed surfacing: explicit seeds, echoed effective seed, version-scoped reproducibility

No randomness exists in the v1 surface — Monte-Carlo estimation is Phase-2 territory
(#509/#510) — but the convention cannot wait for Phase 2: #518 places "how seeds
surface on the CLI" in this gate, and #504's acceptance phrase "seeded and
deterministic" needs the contract-level reading this record fixes (v1 is
deterministic by construction; the seed surface activates at #510). This bADR
reserves the surface convention so Phase-2 issues inherit one rule instead of
inventing per-command conventions. It designs no simulation.

## Decision

*(New ground for the family — gda has no determinism/seed decision; every point below
is this toolkit's own, assembled from verified external precedent.)*

- **Stochastic commands take an explicit `--seed <int>`; deterministic commands never
  do.** The seed's domain is pinned: an **unsigned 32-bit integer** (0 ≤ seed <
  2³²), rendered as a JSON number wherever echoed — chosen to stay inside JSON's
  exact-integer interoperability band under bADR-0005's shortest-round-trip
  rendering (a 64-bit seed would cross 2⁵³ and corrupt silently in JSON
  consumers); out-of-domain values are a usage error (`invalid_argument`,
  bADR-0008). A command's descriptor (bADR-0011) declares whether it is stochastic;
  the flag exists exactly on the stochastic ones. Passing `--seed` to a
  deterministic command is a usage error (bADR-0008) — the flag's presence is
  itself surface
  truth about the command's nature, and the conformance harness asserts it both ways.

- **An omitted seed is drawn fresh, and the result always echoes the effective
  seed.** When `--seed` is absent, the toolkit draws fresh entropy; either way the
  structured result reports the seed that actually drove the run, alongside the
  toolkit version, so the reproduction key `(seed, input, toolkit version)` is
  self-contained in every stochastic result. The key survives failure: once the
  seed is drawn, any failure envelope the run emits carries
  `reproduction: {seed, toolkit_version}` (bADR-0008), so a refused or crashed
  stochastic run stays replayable. (Precedent: pytest-randomly's
  unconditional `Using --randomly-seed=<int>` header; NumPy's documented
  `SeedSequence` best practice — default `None` in, read `.entropy` back out.)
  **Recorded deviation from SUMO's fixed-default-seed model**: a fixed default makes
  nominally independent runs silently share one random stream — a statistics hazard
  for Monte-Carlo estimation. Determinism-on-demand comes from passing `--seed`;
  reproducibility-always comes from the echo.

- **The reproducibility contract is version- and platform-scoped:** same seed +
  same input + same toolkit version → identical output **on the same platform and
  runtime**. Across platforms the promise narrows to exactly bADR-0003's numeric
  contract — bit-identical on the exact tier (the arithmetic core, including
  bounded integer exponents), final-ULP variation permitted on the loose tier
  (non-integer/large exponents, `exponential`) — never a blanket cross-platform
  byte-equality claim. **Cross-version seed replay is explicitly
  unsupported** (QuickCheck: "saving a seed from one version … is not supported";
  Hypothesis's reproduction blob is "not intended to be stable across versions").

- **Silent degradation is named, not denied.** When generation logic evolves in a new
  toolkit version, an old seed produces a valid but *different* run with no error
  raised (proptest's documented strategy-drift behavior). Consumers must treat the
  echoed `(seed, toolkit version)` pair — not the seed alone — as the reproduction
  key; the contract never claims "seed present ⇒ reproducible forever".

## Considered options

- **Fresh-entropy default + mandatory echo** (chosen).
- **Fixed default seed (SUMO's model)** (rejected) — deterministic-by-default reads
  attractive, but correlates independent Monte-Carlo runs by default; the recorded
  deviation above.
- **Seeding via environment variable** (rejected) — hidden global state; violates
  config/logic separation (bADR-0009) and makes the effective seed's provenance
  invisible to the invocation record.
- **Defer the convention entirely to Phase 2** (rejected) — #504's acceptance
  wording already needs the contract-level reading only this record can fix, and
  deferral invites divergent per-issue conventions that would each be a public ABI
  by the time Phase 2 consolidates.

## Consequences

- #509/#510 deliver the first stochastic commands under this convention and may not
  redesign it; their design gate treats this bADR as fixed contract.
- The command descriptor (bADR-0011) carries the stochastic marking from v1, even
  though no v1 command sets it; the conformance harness's seed assertions activate
  with the first stochastic command.
- v1 satisfies "seeded and deterministic" (#504) **by construction**: no v1 command
  draws randomness, so every run is deterministic and there is no seed to pass or
  echo — the CLI seed rules above activate with the first stochastic command
  (#510). Randomness a *test suite* uses internally (e.g. property-based
  generation) is test-infrastructure state outside this contract.

## References

- bADR-0003 (two-tier evaluation determinism) — the boundary this contract is scoped
  within.
- Research provenance (non-normative): issue #518 comment (2026-07-18) —
  pytest-randomly, NumPy SeedSequence, SUMO, QuickCheck/proptest/Hypothesis, all
  primary-source verified.
