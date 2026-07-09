---
status: accepted
---

# Player mount points — equipment & weapon attachment

gADR-0016's Model S renders the Player as ONE `SpriteFrames` — the spacesuit-panda, its
suit and implicit weapon baked into the frames. P2-S3 (#442) then found the **Spacesuit**
and **Gravity Gun** textures have no data-only slot: a monolithic sprite cannot reflect a
swappable Equipment overlay or the switchable Current weapon. The root cause is not a
missing texture reference — it is that the Player's on-screen figure reserves nowhere for a
swapped part to attach. The Player's Equipment (Spacesuit) and weapons (Laser Gun / Gravity
Gun) are swappable by design, so the body must plan attachment points.

Scope here is **phase A: reserve the attachment architecture now**; the modular art that
fills it is **phase B** (a follow-up). This record settles the reservation decisions so
phase B is purely additive. Built on gADR-0000 (Resource/Controller/CanvasItem layering),
gADR-0016 (Model S + view-integration hooks), gADR-0013 (Scale spec presentation authority),
and gADR-0008 (the Spacesuit as persistent Equipment).

We decide:

1. **A Mount point is a named `Marker2D` socket on the Player node, positioned from config
   at `_ready` — not a skeleton, not baked scene coordinates.** The Player's on-screen figure
   is its base sprite (the Model-S `SpriteFrames`, gADR-0016) plus empty `Marker2D` mount
   points authored as children of the Player node in `main.tscn`; nothing wraps them under an
   umbrella node or name. Positions are set in `_ready` from config — mirroring how
   `player_size` is applied via `ViewBuilder.apply_box` — never baked into the scene, so the
   offset stays data-driven (gADR-0000). The **View seam stays generic and stateless** (its
   glossary contract): it builds the base sprite into `Visual`; the mounts are Player-specific
   structure alongside it, not something the shared seam knows about. `Marker2D` was chosen
   over `Skeleton2D`/`Bone2D`: the pixel-art regime (gADR-0013) and the existing
   `AnimatedSprite2D` composition do not warrant skeletal rigging — a fixed socket per state
   suffices; skeletal attachment (per-frame bone tracking) is rejected as overkill (rigged art,
   heavier runtime) for this fidelity.

2. **Mount-offset authority is `scale_spec.json`'s new `player_mounts` section** (gADR-0013).
   Offsets — relative to the `player_size` box — live beside `player_size`, `hud_margin`, and
   `pickup_spacing`; scale_spec already carries positional/spacing values, and gADR-0013 is the
   single authority for the Player's presentation geometry. They compose into the derived
   `player_config` and apply at `_ready`, one authored home. Splitting mount offsets into
   `player_config` was rejected: it would put the Player's presentation geometry under two
   authorities.

3. **Both mounts are reserved now; each names its phase-B driver contract — but phase A adds
   no signals and no art.**
   - **Weapon mount** — where the Current weapon's sprite attaches. It has a live gameplay
     driver today (`switch_weapon` toggles the Current weapon). Phase B adds a
     **`weapon_switched(weapon)` controller SIGNAL**, promoting today's log-only "weapon
     switched" moment to a proper gADR-0016 view-integration hook (a sibling of `fired(weapon)`),
     which a weapon-mount presenter consumes to swap the mounted sprite.
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

- **Supersedes #442's Spacesuit/Gravity-Gun deferral.** The Spacesuit is not a data-only
  pickup texture — it becomes the phase-B Equipment overlay at the Equipment mount. The Gravity
  Gun has no player-body texture at all: its on-screen presence is the Gravity Field VFX
  (#447/#448); only *held-weapon* sprites, if any, hang at the Weapon mount in phase B.
- Phase A is a small slice — the two `Marker2D` nodes in `main.tscn`, the scale_spec
  `player_mounts` section, `_ready` positioning, and tests — that does **not** touch #443's art,
  `player.tres`, or `src/systems`. Phase B (Paperdoll overlay + weapon sprites + the
  `weapon_switched` hook) is a separate follow-up, blocked on phase A.
- The reserved mounts are inert until phase B fills them: an empty `Marker2D` renders nothing
  and adds no runtime cost. The reservation's value is deciding the offsets and authority now,
  so phase B is purely additive rather than a view re-architecture.
