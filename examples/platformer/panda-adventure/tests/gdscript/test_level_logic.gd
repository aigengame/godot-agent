extends SceneTree

## Logic seam (b) for S9: exercise the PURE End-state decision headless —
## GameStateSystem.resolve_event / can_retry (gADR-0010) — by folding every
## (state, event) pair through the machine and pinning the latch.
##
## Run via gda (ADR-0031):
##   gda script run res://tests/gdscript/test_level_logic.gd
##
## preload() the script (a headless runtime has no editor-generated
## global_script_class_cache) and assert every transition and boundary.
## Prints "LOGIC_SEAM: PASS" + quit(0) on success, else push_error + quit(1).

const GameStateSystemScript := preload("res://systems/game_state_system.gd")


func _fail(msg: String) -> void:
	push_error("LOGIC_SEAM: " + msg)
	quit(1)


## Assert one resolve_event decision: the state it lands in and whether it
## reported a change. Returns false after _fail.
func _expect(state: String, event: String, want_state: String, want_changed: bool) -> bool:
	var decision: Dictionary = GameStateSystemScript.resolve_event(state, event)
	if decision["state"] != want_state or decision["changed"] != want_changed:
		_fail(
			"resolve_event(%s, %s) should be {state: %s, changed: %s}, got %s"
			% [state, event, want_state, want_changed, decision]
		)
		return false
	return true


func _init() -> void:
	var playing: String = GameStateSystemScript.STATE_PLAYING
	var won: String = GameStateSystemScript.STATE_WON
	var lost: String = GameStateSystemScript.STATE_LOST
	var cleared: String = GameStateSystemScript.EVENT_ALL_WAVES_CLEARED
	var died: String = GameStateSystemScript.EVENT_PLAYER_DIED

	# The two live transitions: playing ends won on the schedule's clear,
	# lost on the Player's death.
	if not _expect(playing, cleared, won, true):
		return
	if not _expect(playing, died, lost, true):
		return

	# The latch (gADR-0010): the FIRST End state holds — a post-win death and
	# a post-loss clear change nothing, in either order.
	if not _expect(won, died, won, false):
		return
	if not _expect(won, cleared, won, false):
		return
	if not _expect(lost, cleared, lost, false):
		return
	if not _expect(lost, died, lost, false):
		return

	# An unknown event never transitions, from any state.
	for state in [playing, won, lost]:
		if not _expect(state, "wave_started", state, false):
			return

	# Retry is live ONLY in an End state.
	if GameStateSystemScript.can_retry(playing):
		_fail("can_retry(playing) must be false — Enter does nothing mid-run")
		return
	if not GameStateSystemScript.can_retry(won):
		_fail("can_retry(won) must be true")
		return
	if not GameStateSystemScript.can_retry(lost):
		_fail("can_retry(lost) must be true")
		return

	print("LOGIC_SEAM: PASS")
	quit(0)
