---
status: accepted
---

# Scale spec: pixel-art regime, single size authority, and presentation policy

P2-S0 (#435) authors the Scale spec — the unified size/scale standard every visual
element conforms to, the upstream standard the Asset pipelines, post-processing, and
wiring all target. This record, settled in the 2026-07-06 P2-S0 grilling interview
(HITL), fixes the three decisions the spec's anchor numbers cascade from and the
authority model they live under.

We decide four things:

- **The asset regime is pixel art.** Every produced visual asset is authored on a
  hard pixel grid. Rationale, in weight order: (1) mixed-source consistency — the
  acquire stage has two modes (search-download and generation), and pixel art gives
  the postprocess stage *mechanical* conformance checks (grid alignment, exact
  target dimensions, bounded palettes) where a high-resolution painterly style
  leaves consistency a fuzzy aesthetic judgment an agent-driven pipeline cannot
  gate; (2) the open-asset ecosystem's 2D-platformer stock is predominantly
  16/32 px pixel art, so search-download hits natively; (3) generation backends
  output high-resolution images naturally, and downscale-and-quantize to the pixel
  grid is squarely the postprocess stage's job. The GDD's "blends fantasy and
  realism" intent is carried by grounded, readable forms within the pixel regime —
  readability outranks realism.
- **`scale_spec.json` is the single authority for element dimensions.** The
  per-element size numbers migrate INTO it and OUT of their former homes — the
  Player box (player config), the per-Kind enemy boxes and enemy bolt sizes
  (enemies config), the player Projectile size (combat config), the Gravity/Time
  Field radii and Obstacle box (gravity/enemies config), the Pickup boxes and
  spacing (progression config), and the HUD margin and font sizes plus End-screen
  font sizes (hud/level config; the HUD font size was previously an *implicit*
  engine default and is first made explicit here). The builder composes these back
  into each consumer's existing derived Resource shape, so runtime code keeps
  reading its own config — one authored home, N derived projections (the
  gADR-0004 per-Tier-table pattern, widened). A "visual-dimensions-only spec plus
  cross-check gate against the gameplay configs" alternative was rejected: it
  duplicates the same quantity in two authored files, which is exactly the drift
  the one-authority convention (gADR-0008) exists to prevent. Two deliberate
  boundaries: **level segment geometry stays in the Level authority** (it is
  authored *content* — the Editor's direct-manipulation surface per gADR-0012 —
  not a scale standard; the spec constrains it only via a tile-grid-alignment
  semantic gate), and **enemy boxes stay per-Kind** (Faction body-shape variety is
  an asset expression axis; collapsing to one box per Tier would also change
  collision). The issue's "boxes per Tier" lands as a semantic *rule* — the
  builder enforces strict Tier size ordering (every Minion box < every Elite box <
  the Boss box) plus two-way kind-set integrity between the spec and the enemies
  config — not as per-Tier numbers.
- **Presentation policy: keep the authored framing and full target coverage;
  give up integer-scale purity.** The targets are PC (1080p/2K/4K, windowed and
  fullscreen) and Android (19.5:9–20:9 phones). The trilemma is mathematical:
  {the existing world framing, integer-perfect pixel scaling, full target
  coverage} — pick two. Godot's canonical pixel-art setup (base 640×360,
  `viewport` stretch, `integer` scale) would reframe the game ~1.8× tighter —
  the 1760 px Arena goes from ~1.5 to ~2.75 screens, wrecking wave/crowd
  readability and violating the PRD's "Level 1 = the same experience,
  productionized" bound; conversely no base preserving the current framing
  divides 1080 evenly. So: design base **1280×720** (up from the never-authored
  1152×648 engine default — +11% visible world, the gameplay-safe direction),
  stretch `canvas_items` + aspect `expand` (any desktop resolution scales; wide
  phones widen the view; text renders crisp at native resolution — the reason
  `viewport` stretch lost), nearest-neighbor filtering with 2D pixel snap. The
  admitted cost: fractional upscales (e.g. ×1.5 to 1080p) render pixel art
  slightly unevenly — accepted for this demo. Every policy knob (base, stretch
  mode, aspect, filter, PPU 1:1, tile 16) is **spec data**, so a later pivot to
  the integer-pure route is a spec flip plus a framing retune — no asset is
  redrawn (PPU-1:1 assets serve both routes). `project.godot`'s `[display]`
  block cannot be a derived artifact (the engine reads it directly and the gda
  harness co-writes the file), so it is the one *gate-checked mirror* of the
  spec rather than a physically single source.
- **The blockout reconciles to the spec, not the reverse.** Verified against the
  16 px tile grid, the existing blockout holds except the parapet width (140 →
  144; a ±2 px edge move with no gameplay perception), and the long-dead
  `enemy_size`/`enemy_color`/`enemy_position` block in the combat config —
  superseded by per-Kind sizes but still rendered into the derived Resource — is
  deleted rather than migrated.

Consequences: six config schemas shrink and `scale_spec.json` joins the config
gate (schema + semantic validators + freshness) like any config; asset-track
slices (S1/S3/S5/S9) read their target dimensions from one file, and the HITL
sign-off required by #435 is a review of that one file plus this record; adding
an Enemy Kind now touches two authored files (enemies config + scale spec),
enforced by the integrity gate; the pixel regime binds acquire-mode sourcing to
grid-conformant output, which postprocess must enforce mechanically.
