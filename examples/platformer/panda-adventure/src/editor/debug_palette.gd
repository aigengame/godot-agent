extends Node

## The Panda Adventure Editor's DEBUG PALETTE (gADR-0012, #441): the minimal set
## of live debug affordances for reproducing playtest findings in the editor's
## play mode — wave jump, god-mode, spawn-on-demand — plus the edit<->play toggle.
##
## DOGFOODS gda live ops (gADR-0012): the palette's whole control surface is
## drivable runtime state — settable script properties an agent (or the e2e gate)
## reaches with `gda game set <DebugPalette> --property <op> --value <v>` and reads
## back with `gda game get`. The editor overlay's HITL buttons write the SAME
## properties, so a human click and a `gda game set` converge on one path. The
## palette manipulates the running game exactly as gda's live layer does — via the
## runtime node tree, not a private back-channel — so nothing new is reinvented:
##
##   - play_active (bool)   -> enter/exit play mode (the edit<->play switch)
##   - god_mode (bool)      -> keep the Player topped up each frame while on
##   - jump_to_wave (int)   -> clear live enemies + (re)start that 1-based wave
##   - spawn (bool, pulse)  -> spawn one `spawn_kind` at `spawn_position` on demand
##   - last_action (String) -> read-back proof an op landed (via `gda game get`)
##
## The palette node lives in the EDITOR scene, so the export exclude_filter
## (`scenes/editor.tscn, src/editor/*`) strips it from player builds with the rest
## of the editor (gADR-0012). It acts on the play instance the EditorController
## hosts (main.tscn under PlayHost) — a debug tool's tight coupling to runtime
## internals, confined to the dev-machine editor. Every op no-ops (with a log)
## when not playing, so a stray set in edit mode is inert, not a crash.
##
## preload() over class_name (the project-wide convention): no global class cache
## exists, so bare type names would not resolve in the headless daemon session.

const GameLogScript := preload("res://src/util/game_log.gd")
const EnemyControllerScript := preload("res://src/controllers/enemy_controller.gd")
const EnemyScene := preload("res://scenes/enemy.tscn")

# The per-kind derived EnemyConfig path (matches LevelController's convention) —
# structural wiring, not a config number.
const ENEMY_KIND_TRES := "res://data/generated/enemy_%s.tres"
# Spawn-on-demand's default drop point: the S2/S5 shooting-lane position, a spot
# on the Rampart in view of the resting Player. A structural default, overridable
# via `gda game set … --property spawn_position` (or the overlay).
const DEFAULT_SPAWN_POS := Vector2(640.0, 452.0)

# The owning EditorController (untyped: no global class cache — the EnemyWarpDriver
# precedent). Set by the controller in its _ready. The palette reads its play
# state and play instance through it.
var _editor

# --- The drivable op surface (gda game set / get; the overlay writes these too) ---

## Enter (true) / exit (false) play mode — the edit<->play switch, delegated to
## the controller (which owns the save+derive-before-play guard).
var play_active := false:
	set(value):
		play_active = value
		if _editor != null:
			_editor.request_play(value)
		last_action = "play" if value else "edit"

## While on, the Player is invulnerable (its take_hit skips the whole hit, so no
## death latch ever fires), so a finding can be probed without dying. Driven onto
## the Player through its set_debug_invulnerable API each frame (below). Logged on
## the toggle edge only.
var god_mode := false:
	set(value):
		god_mode = value
		last_action = "god_mode:%s" % value
		GameLogScript.emit("info", "debug_god_mode", {"on": value})

## The 1-based wave to jump to: clears the live enemies, then (re)starts that wave
## through the game's OWN wave director (no re-implemented spawn logic) — so the
## jumped-to wave behaves and advances exactly as a real one.
var jump_to_wave := 0:
	set(value):
		jump_to_wave = value
		_do_wave_jump(value)

## The Enemy Kind id spawn-on-demand instances; empty falls back to the schedule's
## first wave's first kind. Plain data (no side effect until `spawn` pulses).
var spawn_kind := ""

## Where spawn-on-demand drops the enemy. Plain data; defaults to the shooting lane
## in _ready.
var spawn_position := DEFAULT_SPAWN_POS

## A spawn trigger: setting it TRUE spawns one enemy on demand. It latches the
## set value rather than self-resetting — the gda harness's live-set write-verify
## rejects a script variable that reads back unchanged, so a self-reset-to-false
## would look like a failed set. The setter runs on every assignment (Godot fires
## setters even when the value is unchanged), so a repeated `gda game set … spawn
## true` (or button click) spawns again; set it false to disarm.
var spawn := false:
	set(value):
		spawn = value
		if value:
			_do_spawn()

## The last op the palette performed — a read-back surface (`gda game get … --property
## last_action`) proving an op landed, alongside the structured gda_log records.
var last_action := "idle"

# Monotonic suffix so successive on-demand spawns get unique, addressable names
# (the schedule's uniqueness contract, gADR-0005).
var _spawn_seq := 0


func _ready() -> void:
	spawn_position = DEFAULT_SPAWN_POS


## Sync god-mode onto the live Player each frame while playing: drive its
## set_debug_invulnerable API so a lethal hit is refused at the SOURCE (take_hit),
## not patched up after the death latch already fired. Per-frame (not just on the
## toggle) so a Player replaced by a Retry reload re-inherits the current god-mode.
## Reaches the Player through the runtime group lookup (the game's own idiom).
func _process(_delta: float) -> void:
	if not _is_playing():
		return
	var player := _find_player()
	if player != null and player.has_method("set_debug_invulnerable"):
		player.set_debug_invulnerable(god_mode)


# --- Ops -----------------------------------------------------------------------

## Jump to a 1-based wave: clamp to the schedule, clear the live enemies, then hand
## off to the LevelController's own `_start_wave` (0-based) — the SAME director the
## boot path drives, so the jumped wave spawns, counts, and advances identically.
func _do_wave_jump(wave_one_based: int) -> void:
	var level := _play_root()
	if level == null:
		last_action = "wave_jump_skipped"
		GameLogScript.emit("info", "debug_wave_jump_skipped", {"reason": "not_playing"})
		return
	var schedule: Variant = level.get("_schedule")
	if schedule == null:
		last_action = "wave_jump_skipped"
		GameLogScript.emit("info", "debug_wave_jump_skipped", {"reason": "no_schedule"})
		return
	var count: int = (schedule.waves as Array).size()
	var index := clampi(wave_one_based - 1, 0, count - 1)
	_clear_enemies(level)
	level._start_wave(index)
	last_action = "wave_jump:%d" % (index + 1)
	GameLogScript.emit("info", "debug_wave_jump", {"wave": index + 1, "total": count})


## Spawn one enemy of `spawn_kind` (or the schedule's first kind) at `spawn_position`
## on the running level. Reuses enemy.tscn + setup() — the spawner contract every
## wave enemy is built with (gADR-0003) — so a debug spawn behaves like a real one;
## it is a free-standing target (no wave-fold / reward wiring), addressable by a
## unique DebugSpawn<n> name for a live-op assert.
func _do_spawn() -> void:
	var level := _play_root()
	if level == null:
		last_action = "spawn_skipped"
		GameLogScript.emit("info", "debug_spawn_skipped", {"reason": "not_playing"})
		return
	var kind_id := spawn_kind if spawn_kind != "" else _default_kind(level)
	if kind_id == "":
		last_action = "spawn_skipped"
		GameLogScript.emit("info", "debug_spawn_skipped", {"reason": "no_kind"})
		return
	var kind: Resource = load(ENEMY_KIND_TRES % kind_id)
	if kind == null:
		last_action = "spawn_failed"
		GameLogScript.emit("error", "debug_spawn_failed", {"kind": kind_id})
		push_error("DebugPalette: unknown enemy kind '%s' for spawn-on-demand." % kind_id)
		return
	var enemy := EnemyScene.instantiate()
	enemy.setup(kind)
	enemy.name = "DebugSpawn%d" % _spawn_seq
	_spawn_seq += 1
	enemy.position = spawn_position
	level.add_child(enemy)
	last_action = "spawn:%s" % kind_id
	GameLogScript.emit("info", "debug_spawn", {
		"kind": kind_id,
		"name": enemy.name,
		"x": spawn_position.x,
		"y": spawn_position.y,
	})


# --- Runtime access helpers ----------------------------------------------------

func _is_playing() -> bool:
	return _editor != null and bool(_editor.is_playing)


## The running level root (main.tscn's LevelController) the controller hosts, or
## null when not playing.
func _play_root() -> Node:
	if not _is_playing():
		return null
	return _editor.get_play_instance()


func _find_player() -> Node:
	return get_tree().get_first_node_in_group("player")


## Free every live Enemy under the level (identified by the EnemyController script,
## not a group the game does not define). queue_free() emits no `died`, so clearing
## has no reward/wave-fold side effect — a clean slate for the jumped-to wave.
func _clear_enemies(level: Node) -> void:
	for child in level.get_children():
		if child.get_script() == EnemyControllerScript:
			child.queue_free()


## The schedule's first wave's first kind — spawn-on-demand's fallback when no
## `spawn_kind` was set. Empty when the schedule is unreadable (guarded by caller).
func _default_kind(level: Node) -> String:
	var schedule: Variant = level.get("_schedule")
	if schedule == null:
		return ""
	var waves: Array = schedule.waves
	if waves.is_empty():
		return ""
	var spawns: Array = waves[0]["spawns"]
	if spawns.is_empty():
		return ""
	return String(spawns[0]["kind"])
