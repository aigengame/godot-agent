class_name StatsSystem
extends Resource

## The runtime holder of one actor's live stats: HP/MP/EXP/Gold (issue #331).
##
## Instantiated fresh per actor (`StatsSystemScript.new()` + `init_from(block)`)
## from that actor's derived StatsConfig stat block — NEVER load()ed from disk
## and never saved back (gADR-0001): the .tres stays a derived, immutable config
## artifact; live mutation exists only in memory, per run.
##
## All four stats live now, but S2 exercises only HP: MP is spent by the Gravity
## Gun (S3), EXP/Gold accumulate from kill rewards (S6a). EXP is named
## `exp_points` in code because `exp` would shadow the built-in exp().

const StatsConfigScript := preload("res://src/resources/stats_config.gd")

var hp: float
var mp: float
var exp_points: float
var gold: float


## Initialize live stats from an actor's stat block: full HP/MP, and EXP/Gold at
## their accumulation identity (0 — structural, not a tunable).
func init_from(config: StatsConfigScript) -> void:
	hp = config.max_hp
	mp = config.max_mp
	exp_points = 0.0
	gold = 0.0


## Deduct damage from HP, clamping at 0 (HP never goes negative).
func apply_damage(amount: float) -> void:
	hp = maxf(hp - amount, 0.0)
