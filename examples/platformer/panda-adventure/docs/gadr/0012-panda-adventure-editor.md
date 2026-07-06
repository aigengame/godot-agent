---
status: accepted
---

# Panda Adventure Editor: an in-game tool mode writing only the JSON authority

Phase 2's scope adds a visual editor for editing and debugging Level 1's content —
a component absent from every prior record (#324, gADR-0000…0011). This record
settles its form, user, scope, and authority discipline, decided in the 2026-07-06
Phase 2 scoping interview.

We decide five things:

- **Form: an in-game tool mode.** A separate entry scene of the SAME Godot
  project — launch the game into edit mode — NOT a Godot editor plugin and NOT an
  external web/GUI tool. Rationale: WYSIWYG comes free through the game's own
  rendering (View skin, Scale spec, real assets — no second renderer to drift);
  an editor plugin would put a human inside the Godot editor concurrently with
  `gda`, exactly the "Concurrent external editor" scenario the parent ADR-0018
  declines to defend; an in-game mode is just a running game, and its debug half
  can build on `gda` live ops (dogfooding).
- **Primary user: a human (HITL).** Level editing, balance debugging, playtest
  reproduction. Agents keep driving `gda` — the Editor adds no agent surface.
- **Scope.** Edit: the `Level authority`'s spatial content (platform segments,
  Arena, backdrop) and the Wave schedule / Spawn rosters by direct manipulation;
  numbers via structured forms — the hand-tune channel — never free-text JSON.
  Debug: instant edit↔play switching plus a minimal palette (wave jump, god-mode,
  spawn-on-demand). Out: asset editing (the Asset pipelines own assets),
  multi-level management (content is Level 1 only).
- **One derivation path.** The Editor writes ONLY the JSON authority, then
  re-derives Resources by invoking the SAME Python builder (`OS.execute`; the
  Editor is a dev-machine tool, so the Python toolchain is present). A GDScript
  re-implementation of the JSON→Resource derivation (defaults, reward/drop
  resolution) was rejected: a second derivation path is the same silent-drift
  failure gADR-0011 pins on the balancing side.
- **Two writers, one authority, no silent clobber.** The Editor's hand-tune and
  the Balancing pipeline write the same JSON authority (git records provenance).
  The pipeline therefore runs in **validate mode** by default (simulate against
  TTK/TTD targets, report only, write nothing); its **solve mode** writes numbers
  only through a diff report plus HITL confirmation — a pipeline run never
  silently overwrites hand-tuned values.

Consequences: the Editor inherits the game's rendering fidelity for free but is
coupled to the dev machine for derivation (acceptable: it is a dev tool, not a
shipped mode); the export pipeline must strip or gate the editor entry scene from
player builds; playtest-driven numeric feel lands as ordinary JSON diffs the
balancing pipeline can validate rather than fight.
