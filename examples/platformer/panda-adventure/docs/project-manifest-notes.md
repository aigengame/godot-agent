# Manifest annotations — `project.godot` and runtime composition scenes

These files were originally hand-authored with inline `;` comments. gda now
authors the project and scenes structurally (`gda project add-input-action` since
#380 / PR #385, `gda node add`/`node set` for scenes), and canonical re-serialization
(`ProjectSettings.save()`, `PackedScene` save) does not preserve `;` comments — so
the annotations were migrated here once, and the files stay comment-free. Update
this doc when the rationale behind a setting or the scene structure changes.

## `project.godot`

**File role.** The canonical project root (gda has no `project create`, so it was
bootstrapped by hand). Later slices extend it — now via gda structured ops, no
longer by hand-editing. The `content/data/generated/*.tres` it loads are derived artifacts
that are COMMITTED (a freshness gate keeps them byte-identical to a fresh build),
regenerated from JSON via `scripts/build_config.py` (gADR-0000).

**`[input]`.** S1 player-traversal actions plus the S2 `fire` action, the S3
weapon/consumable actions, and the S7 `eat_bun`. `move_left`/`move_right`/
`jump`/`fire`/`switch_weapon`/`drink_wine`/`eat_bun` are consumed by
PlayerController (`Input.get_axis` / `is_action_just_pressed`) and driven in
the live e2e by `gda input action`. Each movement action binds an arrow key
plus a WASD/Space alternative; `fire` binds J plus F; `switch_weapon` binds Q
plus Tab; `drink_wine` binds R; `eat_bun` binds E. `fire` fires the CURRENT
weapon — Laser Gun by default, Gravity Gun after `switch_weapon` (gADR-0002).
Both consumable verbs are supply-gated on the S6b item counts since S7
(gADR-0008). Originally hand-serialized (Godot's own `var_to_str` output);
since gda #380 landed, actions are authored with
`gda project add-input-action <name> --key <k>...` instead.

**`[layer_names]`.** S2+S3 collision topology — structural wiring, not balance
data (gADR-0000 governs config NUMBERS; what-can-act-on-what lives here and in
the scenes): 1 `terrain`, 2 `player`, 3 `enemy`, 4 `projectile`, 5
`gravity_field`, 6 `pickup`, 7 `time_field`. Layer 5 is IN USE since S3: the Gravity Field Area2D
(`gravity_field.tscn`, runtime-instanced by PlayerController) sits ON layer 5
and masks `terrain|enemy` (5) — the Player's layer is invisible to it, which is
the never-on-the-Player guarantee (gADR-0002, the Projectile's mask pattern).
Layer 6 is the S6b Pickup (`pickup.tscn`, an Area2D runtime-instanced by
LevelController per resolved drop, gADR-0006): ON layer 6, masking `player` (2)
ONLY — nothing but the Player can touch a drop, and a drop blocks nothing.
Layer 7 is the Boss's Time Field (`time_field.tscn`): ON layer 7, masking
`player|projectile` (10), so it slows the Player and opted-in Player bolts but
never enemies.

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

## `ui/game_shell.tscn`

The project main scene is the UI-owned composition root (gADR-0020). It instances
three siblings: `Gameplay`, `Hud`, and `EndScreen`. `GameShell` binds the HUD to
Gameplay's explicit Player entry, observes Gameplay's `run_ended` signal, and
submits the End screen's retry request to Gameplay. When Content accepts that
intent, the shell reloads the composition scene. UI depends on Content;
Gameplay does not load or locate UI.

## `content/scenes/gameplay.tscn`

The concrete gameplay scene contains the LevelController, Player, and Obstacle;
all runtime-spawned platforms, enemies, Projectiles, Gravity Fields, and Pickups
remain Content. Visual dimensions and positions are applied at runtime from the
derived configuration Resources (gADR-0000), not baked into the scene.

Collision topology remains unchanged: Platform=`terrain`(1); Player=`player`(2)
masking terrain only; Enemy=`enemy`(3) masking terrain only, so Player and Enemy
bodies pass through one another and attacks use the range-gated combat rules;
Obstacle=`terrain`(1) masking nothing. Enemies are runtime-instanced by
LevelController. Player Projectiles mask terrain|enemy; Enemy Projectiles mask
terrain|player; Gravity Fields sit on `gravity_field`(5) and mask terrain|enemy;
Pickups sit on `pickup`(6) and mask player only; Time Fields sit on
`time_field`(7) and mask player|projectile.

The Obstacle is a gravity-affectable environment prop. Its position comes from
`GravityConfig.obstacle_position`; it floats clear of the Player's bolt line,
and only a Gravity Field moves it. The `gravity_affectable` and
`time_dilatable` groups remain open capability contracts. The unique Player
reference is injected or obtained from Gameplay's public entry instead of a
global `player` group.
