class_name GameFlowDirector
extends RefCounted

## Owns the run's End state (S9, gADR-0010), extracted from LevelController so
## the P2-S10 game shell (#449) extends ONE seam: pause is a sibling of the
## World freeze, quit-to-title a sibling of Retry. The level keeps the geometry
## and the Wave director (its primary job) and forwards the two upstream edges;
## the game-flow consequences — the World freeze, the End screen reveal, the
## verdict log, and Retry — live here.
##
## Decisions stay PURE in GameStateSystem (the first-transition latch, gADR-0010
## — untouched): this director only ORCHESTRATES: it folds each edge through the
## pure state machine, logs the verdict exactly once, freezes the world at a
## frame boundary, reveals the End screen, and serves the retry poll. The
## verdict facts (the won run's wave total, the lost run's current wave) are
## Wave-director facts, so the level passes them IN through the edges rather than
## this director reaching across into the Wave director's private schedule.
##
## The owner reference is untyped on purpose (the EnemyWarpDriver precedent):
## typing it as LevelController would preload back into the controller that
## preloads this director (a cycle), and this project has no editor-generated
## global_script_class_cache, so a bare LevelController type name would not
## resolve in a headless runtime. The director only needs the level's Node2D/
## SceneTree surface — get_children() (the World freeze), get_node_or_null()
## (the "EndScreen" overlay), and get_tree().reload_current_scene() (Retry).

const GameStateSystemScript := preload("res://src/systems/game_state_system.gd")
const GameLogScript := preload("res://src/util/game_log.gd")

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


## Whether Retry is live: only an End state accepts the retry action — mid-run,
## Enter does nothing (gADR-0010). The public flow-state read the game shell
## (#449) hooks; the retry poll gates on it.
func can_retry() -> bool:
	return GameStateSystemScript.can_retry(_state)


## The retry poll hook, called from the level's _process each frame. Retry is
## live ONLY in an End state (gADR-0010): mid-run, Enter does nothing. The level
## stays processing through the World freeze (only its CHILDREN are disabled), so
## this read survives it.
func poll_retry() -> void:
	if not can_retry():
		return
	if Input.is_action_just_pressed("retry"):
		_retry()


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


## The End state's consequences, applied at the frame boundary: freeze the world,
## then show the End screen (its fade tween runs on the un-frozen CanvasLayer).
## Split from _enter_end_state so the deferral covers both.
func _apply_end_state() -> void:
	_freeze_world()
	# _level is untyped (see the header), so type the read explicitly.
	var end_screen: Node = _level.get_node_or_null("EndScreen")
	if end_screen != null and end_screen.has_method("show_end"):
		end_screen.show_end(_state == GameStateSystemScript.STATE_WON)


## The World freeze (gADR-0010): disable processing on every non-CanvasLayer
## child of the level — actors, bolts, fields, pickups halt where they are (the
## finale's time-stopped tableau) while the HUD keeps its final readout and the
## End screen runs its fade. NEVER get_tree().paused: the gda harness autoload
## serves the live IPC channel from _process under the default pause mode, so a
## tree pause would sever gda's live channel exactly when an e2e wants to observe
## the End state and press retry. The level itself stays processing — only
## children are disabled — so the retry poll survives.
func _freeze_world() -> void:
	for child in _level.get_children():
		if child is CanvasLayer:
			continue
		child.process_mode = Node.PROCESS_MODE_DISABLED


## Retry (gADR-0010): log the restart (before the scene dies), then reload the
## level scene — the whole run re-derives from config, with zero reset code to
## drift. The gda session survives the reload (same process), so the fresh boot
## records land in the same session log.
func _retry() -> void:
	GameLogScript.emit("info", "game_retried", {"from_state": _state})
	_level.get_tree().reload_current_scene()
