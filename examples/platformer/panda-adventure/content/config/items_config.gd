class_name ItemsConfig
extends Resource

## Typed items configuration for S7 (Consumable use + Spacesuit Equipment,
## gADR-0008): every item number in one authoritative source.
##
## This Resource is a DERIVED artifact: it is regenerated from the authoritative
## content/data/json/items_config.json by scripts/build_config.py (validated against
## content/data/schema/items_config.schema.json) and emitted to
## content/data/generated/items_config.tres. Never hand-edit the generated .tres or
## hardcode these values — change the JSON (gADR-0000).
##
## The @export fields carry NO default literals on purpose: a default would read
## as a second config source competing with the authoritative JSON (gADR-0000).

# Consumable restore amounts — applied capped at the stat block's max at use
# time (StatsSystem.restore_hp / restore_mp). wine_mp_restore migrated here
# from gravity_config (the S3 Wine hook's home): gravity keeps only the MP
# sink, items keep every item effect (gADR-0008).
@export var bun_hp_restore: float
@export var wine_mp_restore: float

# The Spacesuit's protective value: the defense bonus composed onto the
# Player's base stat block (ItemSystem.effective_defender) to feed the damage
# formula's mitigation term — the formula itself is untouched (gADR-0008).
@export var spacesuit_defense: float

# Consume juice: per-item flash color + a shared tween-back duration.
# SUPERSEDED by the Player sprite animations (P2-S5, #443, gADR-0016): consuming a
# Bun/Wine now plays the AnimatedSprite2D "consume" one-shot, so no runtime reads
# these. Retained (not deleted) — the editor schema forms (#441/#481) map them, and
# physical removal is a separate gated cleanup.
@export var bun_flash_color: Color
@export var wine_flash_color: Color
@export var consume_flash_duration: float
