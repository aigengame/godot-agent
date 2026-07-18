---
status: proposed
---

# Determinism and seed surfacing: explicit seeds, echoed effective seed, version-scoped reproducibility

No randomness exists in the v1 surface — Monte-Carlo estimation is Phase-2 territory
(#509/#510) — but the seed convention already has consumers: #518 places "how seeds
surface on the CLI" in this gate, and #504's acceptance requires seeded, deterministic
tests. This bADR reserves the surface convention so Phase-2 issues inherit one rule
instead of inventing per-command conventions. It designs no simulation.

## Decision

*(New ground for the family — gda has no determinism/seed decision; every point below
is this toolkit's own, assembled from verified external precedent.)*

- **Stochastic commands take an explicit `--seed <int>`; deterministic commands never
  do.** A command's descriptor (bADR-0011) declares whether it is stochastic; the
  flag exists exactly on the stochastic ones. Passing `--seed` to a deterministic
  command is a usage error (bADR-0008) — the flag's presence is itself surface
  truth about the command's nature, and the conformance harness asserts it both ways.

- **An omitted seed is drawn fresh, and the result always echoes the effective
  seed.** When `--seed` is absent, the toolkit draws fresh entropy; either way the
  structured result reports the seed that actually drove the run, alongside the
  toolkit version, so the reproduction key `(seed, input, toolkit version)` is
  self-contained in every stochastic result. (Precedent: pytest-randomly's
  unconditional `Using --randomly-seed=<int>` header; NumPy's documented
  `SeedSequence` best practice — default `None` in, read `.entropy` back out.)
  **Recorded deviation from SUMO's fixed-default-seed model**: a fixed default makes
  nominally independent runs silently share one random stream — a statistics hazard
  for Monte-Carlo estimation. Determinism-on-demand comes from passing `--seed`;
  reproducibility-always comes from the echo.

- **The reproducibility contract is version-scoped:** same seed + same input + same
  toolkit version → identical output, within bADR-0003's two-tier determinism
  boundary (bit-exact arithmetic core, including bounded integer exponents;
  non-integer/large exponents and `exponential` ULP-loose, with the versioned
  evaluator as reference). **Cross-version seed replay is explicitly
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
- **Defer the convention entirely to Phase 2** (rejected) — #504's seeded tests
  consume the convention now, and deferral invites divergent per-issue conventions
  that would each be a public ABI by the time Phase 2 consolidates.

## Consequences

- #509/#510 deliver the first stochastic commands under this convention and may not
  redesign it; their design gate treats this bADR as fixed contract.
- The command descriptor (bADR-0011) carries the stochastic marking from v1, even
  though no v1 command sets it; the conformance harness's seed assertions activate
  with the first stochastic command.
- Test suites (from #504 on) pass explicit seeds and assert on the echoed seed field,
  satisfying the "seeded and deterministic" acceptance mechanically.

## References

- bADR-0003 (two-tier evaluation determinism) — the boundary this contract is scoped
  within.
- Research provenance (non-normative): issue #518 comment (2026-07-18) —
  pytest-randomly, NumPy SeedSequence, SUMO, QuickCheck/proptest/Hypothesis, all
  primary-source verified.
