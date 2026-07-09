---
status: accepted
---

# View-integration hooks and the sprite-set reference model

P2-S5 (#443) is the sprite tracer of Phase-2's wave-3 asset round-outs. Beyond wiring
the Player's animated look, it establishes two patterns the rest of the phase reuses,
so they are settled here rather than re-decided per sibling slice (#444 SFX, #447 enemy
animation, #448 VFX). Built on gADR-0000 (Resource/Controller/CanvasItem layering),
gADR-0014 (the asset pipeline + id-referenced manifest), and gADR-0015 (the frames→sheet
packer + SpriteFrames deriver).

We decide two things:

- **View-integration hooks are controller SIGNALS; a controller emits, presenters
  listen — the phase-wide "one hook home".** A controller exposes its
  presentation-relevant moments as signals and holds NO reference to any presenter:
  the animation state machine (this slice), the SFX players (#444), and the VFX (#448)
  each `connect` to the subset they present. So look/sound/effect stay OUT of the
  controller and entirely out of the pure Systems — the Phase-2 closed logic-change
  list is *view-integration hooks + numeric config only*, never a `src/systems/`
  behavioral diff. The surface splits in two: a **locomotion base state**
  (`locomotion_changed(state)`, one of idle/run/jump/fall) emitted on the change edge
  only (the gda-logger no-spam convention), which the animator loops; and **discrete
  verb events** (`landed`, `fired(weapon)`, `hurt`, `consumed(item)`, `leveled_up`,
  and a death-PRESENTATION `death_started` distinct from the gameplay `died` latch),
  each carrying a minimal typed payload. The S1–S7 inline property-tween placeholders
  (landing squash, hit/level-up/consume flashes) are REPLACED by these hooks; their
  numeric config (`landing_*`, `hit_flash_*`, `level_up_flash_*`, `consume_flash_*`)
  stays authored, now consumed by presentation rather than a ColorRect tween. The
  animation state machine is a stateful view driver (the EnemyWarpDriver /
  GameFlowDirector idiom): a `RefCounted` owned by the controller with an untyped
  owner (no cyclic class reference), overlaying one-shot verb animations over the
  looping locomotion base and latching on death. A generic single `(verb, payload)`
  signal was rejected: it loses the typed per-verb payload and forces every listener
  to string-match, where a small set of named signals is self-documenting and lets a
  consumer connect only to what it presents.

- **A sprite set is ONE referenced asset: the derived `SpriteFrames`, recorded by a
  single manifest set entry (Model S).** A character's animated look is one Godot
  `SpriteFrames` an `AnimatedSprite2D` plays by name, composed from several per-state
  sheets (gADR-0015: one committed sheet per animation state). The config authority's
  asset reference is a single id, and the game loads a single resource, so the manifest
  records ONE set entry (`player`) whose `path` is the derived, committed
  `SpriteFrames.tres`; the per-state sheets (`player_<state>.png` + their `.import`)
  are its committed BACKING (their per-frame regions live inside the `.tres`), with
  provenance/license recorded once on the set — the common case being one source pack
  or one generation session per character. `ViewBuilder._apply_sprite` dispatches on
  the resolved resource kind: a `Texture2D` renders as the static "Sprite" TextureRect
  (the #439 Obstacle contract, preserved byte-for-byte so #442's texture e2e stays
  green), a `SpriteFrames` as an "AnimatedSprite2D" a controller drives via the hooks.
  The multi-state deriver `assets.spriteframes.derive_spriteframes_set` (one
  ext_resource per sheet, one named animation per state, byte-stable and uid-free) is
  the read-side extension gADR-0015 anticipated. The rejected alternative — one manifest
  entry PER state sheet plus a separate reference to the derived `.tres` — leaves the
  per-state entries as soft orphans (no authority references them) and needs a
  set-membership concept in the FK/orphan gate; Model S keeps the FK gate green with
  zero orphans and one provenance record, at the cost of not carrying each sheet's
  `frame_layout` in the manifest (the `.tres` regions carry it instead). The derived
  `.tres` is a committed asset, not a config artifact: it is NOT freshness-gated (a
  re-acquired set is not byte-reproducible — gADR-0015's versioning rule), like the
  Obstacle texture.

Consequences: #444/#447/#448 consume the SAME controller signal surface (#447 replicates
the hook pattern on the enemy controller). The animated-sprite branch of the view seam is
now live; a config asset reference resolving to a `SpriteFrames` renders animated with no
further controller edit. The sprite-set reference model is the tracer's pragmatic call and
may be revisited toward per-state manifest entries if a character ever needs mixed-source
per-state provenance or the gate grows set-membership awareness. The Player set landed for
#443 is REAL Gemini-generated art (Nano Banana Pro, one animation strip per state through the
pipeline's generation backend), recorded under its BACKEND's usage terms — not a download
license (gADR-0015 §5d), enforced by the license/acquire-mode gate; the style-config recipe
is retained to re-generate it.
