class_name GameStateSystem
extends RefCounted

## The pure End-state decision for S9 (gADR-0010): one game-flow event folded
## into the run's current state. Static, deterministic, and node/clock-free —
## state and event in, decision out (the WaveSystem/CombatSystem decision
## shape, gADR-0001/gADR-0005) — so the logic seam pins the whole state
## machine headless. The LevelController orchestrates: it feeds the two
## upstream edges (the schedule's all-cleared decision, the Player's death),
## applies the World freeze, shows the End screen, and serves Retry.

# The three run states. Structural identifiers (they name code paths and log
# values, not tunable numbers — gADR-0000 governs numbers).
const STATE_PLAYING := "playing"
const STATE_WON := "won"
const STATE_LOST := "lost"

# The two game-flow events, named after the log records that carry the edges.
const EVENT_ALL_WAVES_CLEARED := "all_waves_cleared"
const EVENT_PLAYER_DIED := "player_died"


## Resolve one game-flow event against the current state. Only `playing`
## transitions — the FIRST End state latches (a post-win death or a post-loss
## clear changes nothing; same-frame races resolve by arrival order,
## gADR-0010). An unknown event never transitions. Returns the full decision
## as a Dictionary:
## - "state": the state after the event;
## - "changed": this event entered an End state — the caller freezes the
##   world, shows the End screen, and logs the verdict exactly once.
static func resolve_event(state: String, event: String) -> Dictionary:
	var next := state
	if state == STATE_PLAYING:
		if event == EVENT_ALL_WAVES_CLEARED:
			next = STATE_WON
		elif event == EVENT_PLAYER_DIED:
			next = STATE_LOST
	return {
		"state": next,
		"changed": next != state,
	}


## Whether Retry is live: only an End state accepts the retry action —
## mid-run, Enter does nothing (gADR-0010).
static func can_retry(state: String) -> bool:
	return state == STATE_WON or state == STATE_LOST
