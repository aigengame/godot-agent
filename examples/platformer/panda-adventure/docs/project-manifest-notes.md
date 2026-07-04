# Manifest annotations — `project.godot` & `scenes/main.tscn`

These two files were originally hand-authored with inline `;` comments. gda now
authors both structurally (`gda project add-input-action` since #380 / PR #385,
`gda node add`/`node set` for scenes), and the engine's canonical re-serialization
(`ProjectSettings.save()`, `PackedScene` save) does not preserve `;` comments — so
the annotations were migrated here once, and the files stay comment-free. Update
this doc when the rationale behind a setting or the scene structure changes.

## `project.godot`

**File role.** The canonical project root (gda has no `project create`, so it was
bootstrapped by hand). Later slices extend it — now via gda structured ops, no
longer by hand-editing. The `data/generated/*.tres` it loads are derived artifacts
that are COMMITTED (a freshness gate keeps them byte-identical to a fresh build),
regenerated from JSON via `scripts/build_config.py` (gADR-0000).

**`[input]`.** S1 player-traversal actions plus the S2 `fire` action and the S3
weapon/consumable actions. `move_left`/`move_right`/`jump`/`fire`/
`switch_weapon`/`drink_wine` are consumed by PlayerController (`Input.get_axis`
/ `is_action_just_pressed`) and driven in the live e2e by `gda input action`.
Each movement action binds an arrow key plus a WASD/Space alternative; `fire`
binds J plus F; `switch_weapon` binds Q plus Tab; `drink_wine` binds R. `fire`
fires the CURRENT weapon — Laser Gun by default, Gravity Gun after
`switch_weapon` (gADR-0002). Originally hand-serialized (Godot's own
`var_to_str` output); since gda #380 landed, actions are authored with
`gda project add-input-action <name> --key <k>...` instead.

**`[layer_names]`.** S2+S3 collision topology — structural wiring, not balance
data (gADR-0000 governs config NUMBERS; what-can-act-on-what lives here and in
the scenes): 1 `terrain`, 2 `player`, 3 `enemy`, 4 `projectile`, 5
`gravity_field`. Layer 5 is IN USE since S3: the Gravity Field Area2D
(`gravity_field.tscn`, runtime-instanced by PlayerController) sits ON layer 5
and masks `terrain|enemy` (5) — the Player's layer is invisible to it, which is
the never-on-the-Player guarantee (gADR-0002, the Projectile's mask pattern).

**`[debug]`.** Godot's default desktop file logging is disabled so no engine
launch writes a shared `user://logs/godot.log` (the #180 RotatedFileLogger race
under concurrent launches). The `.pc` platform override is the operative one on
desktop: its default is `true` and wins over the base key at startup, so both are
set off. (The canonical save may drop the base key when it equals the engine
default — the `.pc` override is what matters.)

**`[rendering]`.** `import_etc2_astc=true`: import ETC2/ASTC compressed textures.
Required for the macOS universal/arm64 export preset (S0 smoke-test); the exporter
refuses universal/arm64 builds when this is off. Harmless for desktop running.

**`[autoload]`.** `GdaHarness` is the committed gda daemon harness — intentional,
see `AGENTS.md` ("The gda daemon harness is COMMITTED").

## `scenes/main.tscn`

Panda Adventure's main scene (S1 player traversal + S2 combat + S3 gravity),
hand-bootstrapped, now edited via gda scene ops. **Structure only**: every visual
(color/size/position) and the collision-shape sizes are applied at RUNTIME from
the derived config Resources by the controllers (gADR-0000 — no config baked into
the scene). The `RectangleShape2D` sub-resources start at a placeholder size that
`_ready` overwrites from config. Collision topology (S2+S3, see `[layer_names]`
above): Platform=`terrain`(1), Player=`player`(2) masking terrain only (passes
through the Enemy — contact damage is S4), Obstacle=`terrain`(1) masking nothing.
The Enemy is runtime-instanced by LevelController from `enemy.tscn`; Projectiles
and Gravity Fields are runtime-instanced by PlayerController (from
`projectile.tscn` / `gravity_field.tscn`).

The S3 `Obstacle` (StaticBody2D + Visual + Collision, script
`obstacle_controller.gd`) is the gravity-affectable environment prop: it floats
clear of the Laser Gun's bolt line (placement is config —
`GravityConfig.obstacle_position`, applied in `_ready`), the Player walks and
jumps under it, and only a Gravity Field moves it (gADR-0002).
