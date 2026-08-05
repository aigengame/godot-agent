---
status: accepted
---

# Player mount points — equipment & weapon attachment

gADR-0016's Model S renders the Player as ONE `SpriteFrames` — the spacesuit-panda, its
suit and implicit weapon baked into the frames. P2-S3 (#442) then found that several of its listed items have no data-only texture slot: the
**Spacesuit** and the **Laser Gun / Gravity Gun** *held weapons* — as opposed to the Laser
Gun's Projectile bolt, which #442 *did* wire. A monolithic sprite cannot reflect a modular
Equipment overlay or a held weapon that swaps with the Current weapon. The root cause is not a
missing texture reference — it is that the Player's on-screen figure reserves nowhere for a
swapped or held part to attach. Today the Player's **weapons switch in play** (the Current
weapon toggles between the Laser Gun and the Gravity Gun); the **Spacesuit is persistent** —
worn from spawn (gADR-0008) — but its look is a distinct layer over the body. So the body
must plan attachment points: a held-weapon sprite that swaps with the Current weapon, and an
equipment overlay. (General *Equipment swapping* beyond the Spacesuit is architectural
readiness, not current game design.)

Scope here is **phase A: reserve the attachment architecture now**; the modular art that
fills it is **phase B** (a follow-up). This record settles the reservation decisions so
phase B is purely additive. Built on gADR-0000 (Resource/Controller/CanvasItem layering),
gADR-0016 (Model S + view-integration hooks), gADR-0013 (Scale spec presentation authority),
and gADR-0008 (the Spacesuit as persistent Equipment).

We decide:

1. **A Mount point is a named `Marker2D` socket on the Player node, positioned from config
   at `_ready` — not a skeleton, not baked scene coordinates.** The Player's on-screen figure
   is its base sprite (the Model-S `SpriteFrames`, gADR-0016) plus empty `Marker2D` mount
   points authored as children of the Player node in `content/scenes/gameplay.tscn`; nothing wraps them under an
   umbrella node or name. Positions are set in `_ready` from config — mirroring how
   `player_size` is applied via `ViewBuilder.apply_box` — never baked into the scene, so the
   offset stays data-driven (gADR-0000). The **View seam stays generic and stateless** (its
   glossary contract): it builds the base sprite into `Visual`; the mounts are Player-specific
   structure alongside it, not something the shared seam knows about. `Marker2D` was chosen
   over `Skeleton2D`/`Bone2D`: the pixel-art regime (gADR-0013) and the existing
   `AnimatedSprite2D` composition do not warrant skeletal rigging. Phase A reserves **one fixed
   Player-local offset per mount**, applied once at `_ready`. Whether phase B needs per-state or
   per-frame offsets — a held weapon tracking the hand as the base animates — is a **phase-B
   decision**, not settled here; the reserved socket is the anchor either refinement builds on.
   Skeletal attachment (per-frame bone tracking) is rejected as overkill (rigged art, heavier
   runtime) for this fidelity.

2. **Mount-offset authority is `scale_spec.json`'s new `player_mounts` section** (gADR-0013).
   Offsets — relative to the `player_size` box — live beside `player_size`, `hud_margin`, and
   `pickup_spacing`; scale_spec already carries positional/spacing values, and gADR-0013 is the
   single authority for the Player's presentation geometry. They compose into the derived
   `player_config` and apply at `_ready`, one authored home. Splitting mount offsets into
   `player_config` was rejected: it would put the Player's presentation geometry under two
   authorities.

3. **Both mounts are reserved now; each names its phase-B driver contract — but phase A adds
   no signals and no art.**
   - **Weapon mount** — where the equipped weapon's **held sprite** attaches: **both** the Laser
     Gun and the Gravity Gun have one, swapped with the Current weapon. (The held gun is distinct
     from what it *fires* — the Laser Gun's Projectile/bolt, already wired by #442, and the
     Gravity Field the Gravity Gun creates — neither of which is the held sprite.) It has a live
     gameplay driver today (`switch_weapon` toggles the Current weapon). Phase B adds a
     **`weapon_switched(weapon)` controller SIGNAL**, promoting today's log-only "weapon switched"
     moment to a proper gADR-0016 view-integration hook (a sibling of `fired(weapon)`), which a
     weapon-mount presenter consumes to swap the held sprite.
   - **Equipment mount** — where a swappable Equipment overlay attaches. Forward-looking: the
     Spacesuit is worn from spawn and persistent (gADR-0008), so there is no live driver; a
     future `equipment_changed`-style hook lands when swappable Equipment is actually designed.
   Phase A materializes only the two reserved `Marker2D` nodes and the offset authority.

4. **Model S is untouched in phase A; phase B evolves it via Paperdoll + mounted sprites.**
   Phase A keeps the Player as one baked Model-S `SpriteFrames` (#443 ships as-is). Phase B is
   the modular-art round: a suit-agnostic base body, a **Spacesuit overlay `SpriteFrames`**
   (Paperdoll — shares the animation-state names, played in sync via the same hooks) at the
   Equipment mount, and per-weapon sprites hung at the Weapon mount. Those overlay/weapon assets
   become additional referenced assets — the per-state / layered manifest model gADR-0016
   anticipated ("may be revisited toward per-state entries"); that manifest model is phase B's
   decision, not settled here.

Consequences:

- **Supersedes #442's Spacesuit + weapon-sprite deferral.** #442 wired the *data-only* textures
  (pickups, the Laser Gun's Projectile bolt, the Obstacle). Three of its listed items are not
  data-only and move to phase B (#492): the **Spacesuit** → the Equipment overlay at the Equipment
  mount; the **Laser Gun** and **Gravity Gun** *held-weapon sprites* → the Weapon mount (distinct
  from the already-wired Laser bolt Projectile). The **Gravity Field** the Gravity Gun fires is a
  separate effect — today the blockout translucent circle (`ViewBuilder.apply_circle`); giving it
  a textured skin is its own future concern with **no owner assigned here**, and is explicitly
  **not** folded into #447 (enemy Faction sprites) or #448 (hit/explosion/pickup/level-up/Warp
  VFX).
- Phase A is a small slice — the two `Marker2D` nodes in `content/scenes/gameplay.tscn`, the scale_spec
  `player_mounts` section, `_ready` positioning, and tests — that does **not** touch #443's art,
  `player.tres`, or `systems/`. Phase B (Paperdoll overlay + weapon sprites + the
  `weapon_switched` hook) is a separate follow-up, blocked on phase A.
- The reserved mounts are inert until phase B fills them: an empty `Marker2D` still exists in the
  scene tree but renders nothing and has negligible runtime overhead (no rendering or gameplay
  behavior). The reservation's value is deciding the offsets and authority now, so phase B is
  purely additive rather than a view re-architecture.
