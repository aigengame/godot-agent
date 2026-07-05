class_name StatsSystem
extends Resource

## The runtime holder of one actor's live stats: HP/MP/EXP/Gold (issue #331).
##
## Instantiated fresh per actor (`StatsSystemScript.new()` + `init_from(block)`)
## from that actor's derived StatsConfig stat block — NEVER load()ed from disk
## and never saved back (gADR-0001): the .tres stays a derived, immutable config
## artifact; live mutation exists only in memory, per run.
##
## All four stats are live: HP takes damage (S2/S4), MP is spent by the Gravity
## Gun and restored by Wine (S3), EXP/Gold accumulate from Kill rewards
## (gain_reward, S6a — gADR-0004). EXP is named `exp_points` in code because
## `exp` would shadow the built-in exp().

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


## Spend MP on a Gravity Gun fire — the game's only MP sink (S3, issue #332).
## All-or-nothing gate: when the full cost is affordable it is deducted and
## true is returned; otherwise NOTHING is spent and false is returned (so at
## 0 MP the Gravity Gun cannot fire, and MP never goes negative).
func spend_mp(cost: float) -> bool:
	if mp < cost:
		return false
	mp -= cost
	return true


## Restore MP (the S3 Wine hook), capped at the actor's max_mp. The cap is a
## PARAMETER, passed by the caller from its immutable stat block — config data
## stays outside this runtime holder (gADR-0001).
func restore_mp(amount: float, max_mp: float) -> void:
	mp = minf(mp + amount, max_mp)


## Accumulate one Kill reward (S6a, gADR-0004): EXP and Gold only ever grow
## from their accumulation identity (0) — uncapped, unspent in Phase 1. The
## amounts are PARAMETERS, passed by the caller from the defeated kind's
## derived config — reward numbers stay outside this runtime holder
## (gADR-0001).
func gain_reward(exp_amount: float, gold_amount: float) -> void:
	exp_points += exp_amount
	gold += gold_amount


## Accumulate collected drop Gold (S6b, gADR-0006): the Pickup path's pure
## addition — Gold's second source next to the Kill reward's gain_reward,
## same uncapped accumulation, no EXP side. The amount is a PARAMETER, read
## by the caller from the collected Pickup (whose value came from the
## defeated kind's derived drop_table) — drop numbers stay outside this
## runtime holder (gADR-0001).
func gain_gold(amount: float) -> void:
	gold += amount
