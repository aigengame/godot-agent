class_name GameFlowDirector
extends RefCounted

signal run_ended(won: bool)

## Owns the run's End state (S9, gADR-0010), extracted from LevelController so
## the P2-S10 game shell (#449) extends ONE seam: pause is a sibling of the
## World freeze, quit-to-title a sibling of Retry. The level keeps the geometry
## and the Wave director (its primary job) and forwards the two upstream edges;
## the game-flow consequences — the World freeze, verdict log, and Retry — live
## here. UI observes `run_ended`; this Content object never loads or finds UI.
##
## Decisions stay PURE in GameStateSystem (the first-transition latch, gADR-0010
## — untouched): this director only ORCHESTRATES: it folds each edge through the
## pure state machine, logs the verdict exactly once, freezes the world at a
## frame boundary, publishes the result, and serves explicit retry requests. The
## verdict facts (the won run's wave total, the lost run's current wave) are
## Wave-director facts, so the level passes them IN through the edges rather than
## this director reaching across into the Wave director's private schedule.
##
## The owner reference is untyped on purpose (the EnemyWarpDriver precedent):
## typing it as LevelController would preload back into the controller that
## preloads this director (a cycle), and this project has no editor-generated
## global_script_class_cache, so a bare LevelController type name would not
## resolve in a headless runtime. The director only needs the level's Node2D
## surface: get_children() for the World freeze.

const GameStateSystemScript := preload("res://systems/game_state_system.gd")
const GameLogScript := preload("res://addons/game_log/game_log.gd")

# The owning level (a LevelController / Node2D); see the header for why it is
# untyped.
var _level

# The run's game-flow state (gADR-0010): playing until the schedule clears (won)
# or the Player dies (lost). The pure GameStateSystem owns the transitions, this
# director owns the consequences. Runtime state; a Retry reload resets it by
# constructing a fresh director.
var _state := GameStateSystemScript.STATE_PLAYING


func _init(level) -> void:
	_level = level


## The lose edge: the Player's S4 death latch fired (exactly once). `wave` is the
## 1-based wave the death happened on (the game_lost verdict field).
func on_player_died(wave: int) -> void:
	_enter_end_state(GameStateSystemScript.EVENT_PLAYER_DIED, {"wave": wave})


## The win edge: the SCHEDULE cleared — never "the Boss died"; the Boss slot
## stays demo composition (gADR-0005). `total_waves` is the schedule's wave count
## (the game_won verdict field).
func on_all_waves_cleared(total_waves: int) -> void:
	_enter_end_state(
		GameStateSystemScript.EVENT_ALL_WAVES_CLEARED, {"waves": total_waves}
	)


## Whether Retry is live: only an End state accepts a retry request.
func can_retry() -> bool:
	return GameStateSystemScript.can_retry(_state)


## Retry is an application entry point. UI translates input into this request;
## Content keeps the state gate and reports whether the intent was accepted.
## The UI-owned composition root performs its own scene lifecycle operation.
func retry() -> bool:
	if not can_retry():
		return false
	GameLogScript.emit("info", "game_retried", {"from_state": _state})
	return true


## Fold one game-flow event through the pure GameStateSystem (gADR-0010). On the
## FIRST transition into an End state: log the verdict (the durable observable for
## gda logger tail), then apply the consequences at the frame boundary — both
## edges arrive from physics callbacks (an enemy's attack, the last death's wave
## fold), so the freeze is deferred rather than flipping process modes
## mid-callback. The latch lives in the pure decision: a second event never
## re-enters. The verdict fields are the edge-specific facts the level passed in.
func _enter_end_state(event: String, verdict_fields: Dictionary) -> void:
	var decision: Dictionary = GameStateSystemScript.resolve_event(_state, event)
	if not decision["changed"]:
		return
	_state = decision["state"]
	var verdict := "game_won" if _state == GameStateSystemScript.STATE_WON else "game_lost"
	GameLogScript.emit("info", verdict, verdict_fields)
	_apply_end_state.call_deferred()


## Apply Content consequences at the frame boundary, then notify higher layers.
func _apply_end_state() -> void:
	_freeze_world()
	run_ended.emit(_state == GameStateSystemScript.STATE_WON)


## The World freeze (gADR-0010): disable processing on every Content child of
## the level — actors, bolts, fields, and pickups halt where they are. UI is a
## sibling in the Game Shell and remains active. NEVER get_tree().paused: the gda harness autoload
## serves the live IPC channel from _process under the default pause mode, so a
## tree pause would sever gda's live channel exactly when an e2e wants to observe
## the End state and press retry. The UI-owned Game Shell is a sibling of the
## level, remains active, and submits Retry through the explicit Content entry.
func _freeze_world() -> void:
	for child in _level.get_children():
		child.process_mode = Node.PROCESS_MODE_DISABLED
