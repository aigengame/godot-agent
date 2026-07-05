class_name EconomySystem
extends RefCounted

## The pure Drop-table decisions for S6b (gADR-0006): which of a defeated
## kind's Drop-table entries actually drop, and where each Pickup lands.
## Static, deterministic, and node/clock/RNG-free (the CombatSystem/WaveSystem
## decision shape, gADR-0001): the rolls are PARAMETERS — the LevelController
## supplies randf() per entry at runtime, the logic seam and the offline
## balancing sim supply chosen values — so chance behavior pins headless.
## The LevelController orchestrates: it rolls and instances pickup.tscn per
## resolved drop; each Pickup logs its own pickup_spawned record.


## Resolve one death's drops: entry i of `drop_table` (the derived per-kind
## Array of {"item": String, "amount": int, "chance": float}, gADR-0006)
## drops iff rolls[i] <= its chance — inclusive, so a chance of 1.0 is a
## GUARANTEED drop even at the roll domain's top (Godot's randf() is
## inclusive of 1.0). Returns the resolved drops in table order, each
## {"item": String, "amount": int} (the chance is consumed by the roll).
static func resolve_drops(drop_table: Array, rolls: Array) -> Array:
	var drops: Array = []
	for i in drop_table.size():
		var entry: Dictionary = drop_table[i]
		if float(rolls[i]) <= float(entry["chance"]):
			drops.append({"item": entry["item"], "amount": entry["amount"]})
	return drops


## The deterministic drop scatter: Pickup `index` of `count` resolved drops
## sits on a horizontal row centered on the death position, `spacing` px
## apart — deterministic (no scatter RNG) so a drop's landing spot is
## data-predictable for tests and for the player's read.
static func drop_offset(index: int, count: int, spacing: float) -> Vector2:
	return Vector2((float(index) - float(count - 1) / 2.0) * spacing, 0.0)
