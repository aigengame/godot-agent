---
status: accepted
---

# Balancing pipeline independent of game code: isolation and reuse over code-sharing

Phase 2 builds the Balancing pipeline (Monte-Carlo encounter simulation + a
system-dynamics model of first-order nonlinear ODEs for long-term balance
prediction) and uses it for Level 1's initial tune; Phase 3 re-tunes against
playtest feedback (#325's "re-tune" presupposes this initial tune). The Phase 1
PRD (#323) had seeded the opposite architecture — "the [pure logic seam is] the
core reused by the Monte-Carlo balancing sim", i.e. the sim would drive the
shipped GDScript `CombatSystem`/`EnemyAI` statics headless. This record, settled
in the 2026-07-06 Phase 2 scoping interview, deliberately deviates from that
seeded path.

We decide four things:

- **Both engines are Python, fully isolated from game code.** The Monte-Carlo
  sim and the SD-ODE model live in the game-agnostic Tool Script framework and
  never import or invoke the game's GDScript. Rationale: isolation and
  reusability — the pipeline is a first-class reusable process asset (input-driven
  core, per-game configuration) meant to outlive this demo and apply to other
  game types, feeding the capstone skill. A hybrid (GDScript MC core driven via
  `gda script run` + Python orchestration) was considered and rejected: it
  couples the pipeline to this game's engine and code shape.
- **The single JSON authority is preserved on both ends.** The pipeline reads
  the same authoritative JSON configs the game derives its Resources from, and
  writes tuned numbers back to that JSON; it never bypasses JSON to emit `.tres`
  directly in this project. The framework's pluggable output emitters
  (JSON/XML/Resource/…) exist for reuse elsewhere, not as a second authoring
  path here (gADR-0000 intact).
- **Rule drift is pinned by golden contract fixtures, not by code reuse.** The
  known cost of reimplementing game rules in Python is silent divergence. The
  bridge lives only in tests: golden vectors (attacker/defender params → expected
  damage, TTK, …) are generated FROM the shipped GDScript logic seams via
  `gda script run` as ground truth; the Python models' tests consume the same
  fixtures (configurable tolerance). The parity suite is engine-marked in CI, so
  a rule change on either side goes red until both sides co-evolve. A pure-Python
  pipeline without a parity gate was rejected as untrustworthy for tuning.
- **The logic seam's sim role is repurposed, not deleted.** #323's
  reuse-the-seam intent survives as the parity fixtures' generator: the pure,
  clock-free statics remain the ground-truth oracle — they are no longer the sim
  engine itself.

Consequences: gameplay-rule changes now cost a dual-side update (GDScript +
Python model), surfaced by parity red rather than discovered at playtest; the
parity tests require Godot (engine tier, not the fast suite); the pipeline can
be extracted for other games without dragging engine bindings along.
