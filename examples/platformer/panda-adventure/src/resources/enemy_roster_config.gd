class_name EnemyRosterConfig
extends Resource

## The Spawn Roster (gADR-0003): the data-driven which-kind-spawns-where list
## the level consumes at boot. Each entry is a Dictionary
## {"kind": String, "name": String, "position": Vector2} referencing an Enemy
## Kind by its enemies_config.json key (spawn->kind referential integrity is
## guarded by the data-seam tests).
##
## This Resource is a DERIVED artifact: regenerated from the authoritative
## data/json/enemies_config.json `spawns` array by scripts/build_config.py into
## data/generated/enemy_roster.tres. Never hand-edit it (gADR-0000). The Wave
## slice will compose these entries per Wave; S4 ships a single default entry
## so the S2 combat flow keeps working unchanged.

@export var spawns: Array
