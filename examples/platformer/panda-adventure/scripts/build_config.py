#!/usr/bin/env python3
"""JSON -> Resource build pipeline for Panda Adventure (gADR-0000).

The authoritative config lives in ``content/data/json/*.json``. This step validates each
source against its JSON Schema (raising on invalid input) and emits the *derived*
Godot Resources under ``content/data/generated/`` that the runtime ``load()``s. Every
``.tres`` is a committed derived artifact (a freshness gate keeps each one
byte-identical to a fresh build), never hand-edited: changing config means
changing the JSON.

Nine sources feed the outputs (``specs_for``/``SPECS``):

- ``player_config.json`` -> ``player_config.tres`` (``PlayerConfig``, S1;
  the platform blockout migrated OUT to ``level_config.json`` in S9,
  gADR-0010 — one level authority)
- ``combat_config.json`` -> ``stats_player.tres`` + ``stats_enemy.tres``
  (``StatsConfig`` stat blocks, gADR-0001) and ``combat_config.tres``
  (``CombatConfig``) — S2
- ``gravity_config.json`` -> ``gravity_config.tres`` (``GravityConfig``,
  gADR-0002) — S3
- ``enemies_config.json`` -> one ``enemy_<kind>.tres`` (``EnemyConfig``) per
  Enemy Kind plus ``wave_schedule.tres`` (``WaveScheduleConfig``, the Wave
  schedule — S5, gADR-0005: each wave one Spawn Roster; the wave COUNT is the
  ``waves`` array's length, config never code). The per-kind specs are DERIVED
  by iterating the JSON's ``kinds`` (gADR-0001: a new actor kind is config,
  not code — adding a kind is a JSON-only change), while the non-enemy specs
  stay a static table. Since S6a (gADR-0004) the same source also carries the
  per-Tier Kill-reward table (``tiers``), resolved into per-kind derived
  ``exp_reward``/``gold_reward`` fields by ``resolve_enemy_rewards`` before
  rendering: the runtime stays a dumb ``kind.<field>`` read while the reward
  AUTHORITY stays per-Tier data. Since S6b (gADR-0006) each Tier entry also
  carries its Drop table (``drops``), resolved into a per-kind derived
  ``drop_table`` field by the same resolver.
- ``hud_config.json`` -> ``hud_config.tres`` (``HudConfig``, the HUD blockout
  numbers — gADR-0004) — S6a.
- ``progression_config.json`` -> ``progression_config.tres``
  (``ProgressionConfig``: the leveling curve — max level is the curve's
  length + 1, config never code — plus the Drop/Pickup blockout and juice,
  gADR-0006) — S6b. The curve's strict monotonicity is a cross-field rule
  enforced by ``validate_progression_semantics``.
- ``items_config.json`` -> ``items_config.tres`` (``ItemsConfig``: the
  Consumable restore amounts — ``wine_mp_restore`` migrated here from
  ``gravity_config.json`` — the consume-flash juice, and the Spacesuit's
  defense bonus, gADR-0008) — S7.
- ``level_config.json`` -> ``level_config.tres`` (``LevelConfig``: the level
  authority, gADR-0010 — the Great-Wall blockout segments, the backdrop, the
  Arena interval that clamps the Warp Blink's landing, and the End screen's
  blockout numbers). Its cross-field rules (unique segment names, a real
  Arena interval) are enforced by ``validate_level_semantics``.
- ``scale_spec.json`` -> ``scale_spec.tres`` (``ScaleSpecConfig``, the Scale
  spec — gADR-0013): the SINGLE authority for element dimensions. Its own
  ``.tres`` carries only the pixel-art/presentation anchors (PPU, tile size,
  the Design base, the stretch policy, the platform thickness); every
  per-ELEMENT dimension (the Player box, per-kind enemy/bolt boxes, the
  field radii, the pickup boxes, the HUD margin and font sizes) is COMPOSED
  by ``compose_scale_spec`` into the source document each consumer's derived
  Resource renders from — one authored home, N derived projections (the
  gADR-0004 per-Tier-table pattern, widened). Its cross-FILE rules — two-way
  kind integrity with the enemies config, strict Tier size ordering, two-way
  pickup-item integrity with the progression config, and level-segment
  tile-grid alignment — are enforced by ``validate_scale_semantics``.

Dogfooding note: since gda's ADR-0032 static class_name scan (issue #360), ``gda
resource create --type PlayerConfig`` CAN instantiate a project-local class in
this never-imported project. This converter still emits the ``.tres`` text
directly: it is the head of the offline balancing pipeline (pure Python, no
Godot spawn, byte-stable output for the freshness gate), not a workaround. The
emitted files load through gda/Godot, which the data-seam round-trip tests prove.

Run standalone: ``python scripts/build_config.py`` (writes every .tres, prints a
one-line summary per file).
"""

from __future__ import annotations

import copy
import json
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

# Resolve paths relative to this file so the script works from any CWD.
GAME_DIR = Path(__file__).resolve().parent.parent

# The asset-pipeline package (``assets.*``) lives under ``tools/``; put it on
# sys.path so the size-gate delegation (``validate_asset_sizes``) imports when this
# runs standalone (``python scripts/build_config.py``). Tests already get it from
# conftest; a duplicate path entry is harmless.
sys.path.insert(0, str(GAME_DIR / "tools"))


@dataclass(frozen=True)
class TresSpec:
    """One derived ``.tres`` output: its source JSON, schema, and field layout.

    ``json_root`` addresses the sub-object of the source document the fields are
    read from (``()`` = the document root). ``fields`` is the render authority —
    ``(json key, Godot type)`` pairs rendered in declaration order, so a rebuild
    is byte-stable (the freshness gate depends on it) and adding a config field
    is a one-line change. Types: "color" (4-array -> Color), "vec2" (2-array ->
    Vector2), "float" (scalar -> bare number), "string" (str -> quoted String),
    "asset" (OPTIONAL str -> quoted String, defaulting to "" when the authored
    key is absent — the P2-S2 view asset reference, #436: the ViewBuilder-
    resolved sprite reference, authored empty until an asset slice fills it),
    "bool" (bool -> true/false, the Scale spec's snap flag),
    "wave_list" (waves -> Array of {"spawns": Array of Dictionary}, S5's Wave
    schedule), "number_list" (number array -> Array, S6b's leveling curve),
    "drop_list" (drop entries -> Array of Dictionary, S6b's per-kind Drop
    table), "item_style_map" (item name -> {"color": Color, "size": Vector2,
    "asset": String}, S6b's pickup blockout plus its P2-S2 asset reference).
    The schema is the validation authority; keep the two in step.
    """

    json_rel: str
    schema_rel: str
    out_rel: str
    script_res_path: str
    script_class: str
    ext_id: str
    json_root: tuple[str, ...] = ()
    fields: list[tuple[str, str]] = field(default_factory=list)


_PLAYER_FIELDS: list[tuple[str, str]] = [
    ("player_color", "color"),
    ("player_size", "vec2"),
    ("player_asset", "asset"),
    ("player_start", "vec2"),
    ("move_speed", "float"),
    ("jump_velocity", "float"),
    ("gravity", "float"),
    ("max_fall_speed", "float"),
    ("camera_smoothing_speed", "float"),
    ("landing_squash", "vec2"),
    ("landing_tween_duration", "float"),
]

_STAT_BLOCK_FIELDS: list[tuple[str, str]] = [
    ("max_hp", "float"),
    ("max_mp", "float"),
    ("attack", "float"),
    ("defense", "float"),
]

_COMBAT_FIELDS: list[tuple[str, str]] = [
    ("attack_scale", "float"),
    ("defense_scale", "float"),
    ("min_damage", "float"),
    ("iframe_duration", "float"),
    ("projectile_color", "color"),
    ("projectile_size", "vec2"),
    ("projectile_asset", "asset"),
    ("projectile_speed", "float"),
    ("projectile_lifetime", "float"),
    ("projectile_spawn_offset", "vec2"),
    ("hit_flash_color", "color"),
    ("hit_flash_duration", "float"),
]

_GRAVITY_FIELDS: list[tuple[str, str]] = [
    ("mp_cost", "float"),
    ("field_direction", "vec2"),
    ("field_strength", "float"),
    ("field_radius", "float"),
    ("field_duration", "float"),
    ("field_color", "color"),
    ("field_asset", "asset"),
    ("field_fade_duration", "float"),
    ("field_spawn_offset", "vec2"),
    ("enemy_max_gravity_offset", "float"),
    ("obstacle_color", "color"),
    ("obstacle_size", "vec2"),
    ("obstacle_asset", "asset"),
    ("obstacle_position", "vec2"),
    ("obstacle_max_gravity_offset", "float"),
]

# One Enemy Kind's field layout (gADR-0003): the three taxonomy axes, the stat
# block (same four fields as _STAT_BLOCK_FIELDS — the symmetric damage-formula
# shape, gADR-0001), the blockout, the Archetype-AI params, the S6a Kill
# reward (gADR-0004), and the S6b Drop table (gADR-0006) — the last three are
# DERIVED per kind from the top-level per-Tier ``tiers`` table by
# ``resolve_enemy_rewards``, not authored per kind.
_ENEMY_KIND_FIELDS: list[tuple[str, str]] = [
    ("faction", "string"),
    ("tier", "string"),
    ("archetype", "string"),
    ("max_hp", "float"),
    ("max_mp", "float"),
    ("attack", "float"),
    ("defense", "float"),
    ("color", "color"),
    ("size", "vec2"),
    ("asset", "asset"),
    ("move_speed", "float"),
    ("gravity", "float"),
    ("max_fall_speed", "float"),
    ("aggro_range", "float"),
    ("attack_range", "float"),
    ("attack_cooldown", "float"),
    ("keep_range_min", "float"),
    ("keep_range_max", "float"),
    ("attack_squash", "vec2"),
    ("attack_tween_duration", "float"),
    ("exp_reward", "float"),
    ("gold_reward", "float"),
    ("drop_table", "drop_list"),
]

# Ranged kinds additionally carry their bolt's blockout+motion (schema-enforced
# via if/then on archetype == "ranged").
_ENEMY_KIND_PROJECTILE_FIELDS: list[tuple[str, str]] = [
    ("projectile_color", "color"),
    ("projectile_size", "vec2"),
    ("projectile_asset", "asset"),
    ("projectile_speed", "float"),
    ("projectile_lifetime", "float"),
    ("projectile_spawn_offset", "vec2"),
]

# The S8 Warp kit (gADR-0009): presence-gated per-kind ability params — a kind
# carries the whole block or none of it (schema dependentRequired), keyed to
# neither Tier nor Archetype. Presence of the FIRST key selects the block.
_ENEMY_KIND_WARP_FIELDS: list[tuple[str, str]] = [
    ("warp_cooldown", "float"),
    ("warp_trigger_range", "float"),
    ("warp_offset", "vec2"),
    ("warp_tell_duration", "float"),
    ("warp_recovery_duration", "float"),
    ("time_field_radius", "float"),
    ("time_field_factor", "float"),
    ("time_field_duration", "float"),
    ("time_field_color", "color"),
    ("time_field_asset", "asset"),
    ("time_field_fade_duration", "float"),
]

# The Wave schedule's own fields (gADR-0005): the spawn-telegraph tween
# numbers (they belong to the wave system, not to any one kind) plus the
# ordered waves themselves.
_WAVE_SCHEDULE_FIELDS: list[tuple[str, str]] = [
    ("spawn_squash", "vec2"),
    ("spawn_tween_duration", "float"),
    ("waves", "wave_list"),
]

# The S6a HUD blockout numbers (gADR-0004): overlay placement and the
# value-change pulse tween. ``margin`` and ``font_size`` are COMPOSED from the
# Scale spec (gADR-0013) — authored in scale_spec.json, not hud_config.json.
# ``hud_font`` is the P2-S9 (#445) view asset reference — the HUD's bitmap font,
# resolved by the builder from its Asset manifest id to the single-homed res://
# path (gADR-0014); authored empty until the font slice fills it.
_HUD_FIELDS: list[tuple[str, str]] = [
    ("margin", "vec2"),
    ("font_size", "float"),
    ("value_punch_scale", "vec2"),
    ("value_tween_duration", "float"),
    ("hud_font", "asset"),
]

# The S7 Items & Equipment numbers (gADR-0008): the Consumable restore
# amounts (wine_mp_restore migrated from _GRAVITY_FIELDS — one items
# authority), the consume-flash juice, and the Spacesuit's defense bonus.
_ITEMS_FIELDS: list[tuple[str, str]] = [
    ("bun_hp_restore", "float"),
    ("wine_mp_restore", "float"),
    ("spacesuit_defense", "float"),
    ("bun_flash_color", "color"),
    ("wine_flash_color", "color"),
    ("consume_flash_duration", "float"),
]

# The S9 level authority (gADR-0010): the backdrop, the Great-Wall blockout
# (one shared segment color + the ordered named segments), the Arena interval
# the Warp-landing clamp reads, and the End screen's blockout numbers. The
# platform fields migrated here from _PLAYER_FIELDS (the gADR-0008
# one-authority pattern).
_LEVEL_FIELDS: list[tuple[str, str]] = [
    ("background_color", "color"),
    ("background_asset", "asset"),
    ("platform_color", "color"),
    ("platforms", "platform_list"),
    ("arena_min_x", "float"),
    ("arena_max_x", "float"),
    ("end_overlay_color", "color"),
    ("end_win_color", "color"),
    ("end_lose_color", "color"),
    ("end_title_font_size", "float"),
    ("end_hint_font_size", "float"),
    ("end_fade_duration", "float"),
]

# The S6b progression loop (gADR-0006): the leveling curve (cumulative EXP
# thresholds — the max level is the array's length + 1, config never code)
# plus the level-up flash and the Drop/Pickup blockout and juice.
_PROGRESSION_FIELDS: list[tuple[str, str]] = [
    ("level_curve", "number_list"),
    ("level_up_flash_color", "color"),
    ("level_up_flash_duration", "float"),
    ("drop_items", "item_style_map"),
    ("pickup_spacing", "float"),
    ("pickup_spawn_squash", "vec2"),
    ("pickup_spawn_tween_duration", "float"),
    ("pickup_collect_tween_duration", "float"),
]


# The Scale spec's own fields (gADR-0013): ONLY the pixel-art and presentation
# anchors — per-element dimensions are composed into their consumers' documents
# by ``compose_scale_spec`` instead of rendering here.
_SCALE_FIELDS: list[tuple[str, str]] = [
    ("ppu", "float"),
    ("tile_size", "float"),
    ("design_base", "vec2"),
    ("stretch_mode", "string"),
    ("stretch_aspect", "string"),
    ("texture_filter", "string"),
    ("snap_2d_transforms_to_pixel", "bool"),
    ("platform_thickness", "float"),
]


# The S4 enemies source (gADR-0003) — one json_rel shared by the derived
# per-kind specs and the Wave-schedule spec.
_ENEMIES_JSON_REL = "content/data/json/enemies_config.json"
_ENEMIES_SCHEMA_REL = "content/data/schema/enemies_config.schema.json"

# The P2-S0 Scale spec source (gADR-0013) — the single authority for element
# dimensions, composed into every other source by ``compose_scale_spec``.
_SCALE_JSON_REL = "content/data/json/scale_spec.json"
_SCALE_SCHEMA_REL = "content/data/schema/scale_spec.schema.json"

# The remaining sources ``compose_scale_spec`` keys its injection map on.
_PLAYER_JSON_REL = "content/data/json/player_config.json"
_COMBAT_JSON_REL = "content/data/json/combat_config.json"
_GRAVITY_JSON_REL = "content/data/json/gravity_config.json"
_HUD_JSON_REL = "content/data/json/hud_config.json"

# The S6b progression source (gADR-0006) — carries its own cross-field rule
# (the strictly increasing leveling curve, validate_progression_semantics).
_PROGRESSION_JSON_REL = "content/data/json/progression_config.json"

# The S9 level source (gADR-0010) — carries its own cross-field rules
# (unique segment names, a real Arena interval, validate_level_semantics).
_LEVEL_JSON_REL = "content/data/json/level_config.json"


def _enemy_kind_spec(kind: str, definition: dict[str, Any]) -> TresSpec:
    """The TresSpec for one Enemy Kind: kinds.<kind> -> enemy_<kind>.tres.

    The field layout follows the kind's own data: ranged kinds carry their
    bolt's projectile block on top of the base layout (the schema's if/then
    requires it), and a Warp kind carries the warp block (presence-gated —
    the schema's dependentRequired makes it all-or-none, gADR-0009). The two
    compose: a ranged Warp kind would render both.
    """
    fields = list(_ENEMY_KIND_FIELDS)
    if definition["archetype"] == "ranged":
        fields += _ENEMY_KIND_PROJECTILE_FIELDS
    if "warp_cooldown" in definition:
        fields += _ENEMY_KIND_WARP_FIELDS
    return TresSpec(
        json_rel=_ENEMIES_JSON_REL,
        schema_rel=_ENEMIES_SCHEMA_REL,
        out_rel=f"content/data/generated/enemy_{kind}.tres",
        script_res_path="res://content/config/enemy_config.gd",
        script_class="EnemyConfig",
        ext_id="1_enemyconfig",
        json_root=("kinds", kind),
        fields=fields,
    )


_PLAYER_SPEC = TresSpec(
    json_rel="content/data/json/player_config.json",
    schema_rel="content/data/schema/player_config.schema.json",
    out_rel="content/data/generated/player_config.tres",
    script_res_path="res://content/config/player_config.gd",
    script_class="PlayerConfig",
    ext_id="1_playerconfig",
    fields=_PLAYER_FIELDS,
)

# The non-enemy outputs: a static table (their shapes are code-owned Resource
# layouts, one spec each). Enemy Kind specs are NOT listed here — they are
# derived from the authoritative JSON by ``enemy_kind_specs`` (gADR-0003).
_STATIC_SPECS: list[TresSpec] = [
    _PLAYER_SPEC,
    TresSpec(
        json_rel="content/data/json/combat_config.json",
        schema_rel="content/data/schema/combat_config.schema.json",
        out_rel="content/data/generated/stats_player.tres",
        script_res_path="res://systems/stats_config.gd",
        script_class="StatsConfig",
        ext_id="1_statsconfig",
        json_root=("player_stats",),
        fields=_STAT_BLOCK_FIELDS,
    ),
    TresSpec(
        json_rel="content/data/json/combat_config.json",
        schema_rel="content/data/schema/combat_config.schema.json",
        out_rel="content/data/generated/stats_enemy.tres",
        script_res_path="res://systems/stats_config.gd",
        script_class="StatsConfig",
        ext_id="1_statsconfig",
        json_root=("enemy_stats",),
        fields=_STAT_BLOCK_FIELDS,
    ),
    TresSpec(
        json_rel="content/data/json/combat_config.json",
        schema_rel="content/data/schema/combat_config.schema.json",
        out_rel="content/data/generated/combat_config.tres",
        script_res_path="res://content/config/combat_config.gd",
        script_class="CombatConfig",
        ext_id="1_combatconfig",
        fields=_COMBAT_FIELDS,
    ),
    TresSpec(
        json_rel="content/data/json/gravity_config.json",
        schema_rel="content/data/schema/gravity_config.schema.json",
        out_rel="content/data/generated/gravity_config.tres",
        script_res_path="res://content/config/gravity_config.gd",
        script_class="GravityConfig",
        ext_id="1_gravityconfig",
        fields=_GRAVITY_FIELDS,
    ),
    TresSpec(
        json_rel="content/data/json/hud_config.json",
        schema_rel="content/data/schema/hud_config.schema.json",
        out_rel="content/data/generated/hud_config.tres",
        script_res_path="res://content/config/hud_config.gd",
        script_class="HudConfig",
        ext_id="1_hudconfig",
        fields=_HUD_FIELDS,
    ),
    TresSpec(
        json_rel=_PROGRESSION_JSON_REL,
        schema_rel="content/data/schema/progression_config.schema.json",
        out_rel="content/data/generated/progression_config.tres",
        script_res_path="res://content/config/progression_config.gd",
        script_class="ProgressionConfig",
        ext_id="1_progressionconfig",
        fields=_PROGRESSION_FIELDS,
    ),
    TresSpec(
        json_rel="content/data/json/items_config.json",
        schema_rel="content/data/schema/items_config.schema.json",
        out_rel="content/data/generated/items_config.tres",
        script_res_path="res://content/config/items_config.gd",
        script_class="ItemsConfig",
        ext_id="1_itemsconfig",
        fields=_ITEMS_FIELDS,
    ),
    TresSpec(
        json_rel=_LEVEL_JSON_REL,
        schema_rel="content/data/schema/level_config.schema.json",
        out_rel="content/data/generated/level_config.tres",
        script_res_path="res://content/config/level_config.gd",
        script_class="LevelConfig",
        ext_id="1_levelconfig",
        fields=_LEVEL_FIELDS,
    ),
    TresSpec(
        json_rel=_SCALE_JSON_REL,
        schema_rel=_SCALE_SCHEMA_REL,
        out_rel="content/data/generated/scale_spec.tres",
        script_res_path="res://content/config/scale_spec_config.gd",
        script_class="ScaleSpecConfig",
        ext_id="1_scalespecconfig",
        fields=_SCALE_FIELDS,
    ),
]

_WAVE_SCHEDULE_SPEC = TresSpec(
    json_rel=_ENEMIES_JSON_REL,
    schema_rel=_ENEMIES_SCHEMA_REL,
    out_rel="content/data/generated/wave_schedule.tres",
    script_res_path="res://content/config/wave_schedule_config.gd",
    script_class="WaveScheduleConfig",
    ext_id="1_waveschedule",
    fields=_WAVE_SCHEDULE_FIELDS,
)

# S1 back-compat conveniences (existing tests and callers import these; they are
# the player spec's paths) plus the S2 combat-source counterparts.
JSON_PATH = GAME_DIR / _PLAYER_SPEC.json_rel
SCHEMA_PATH = GAME_DIR / _PLAYER_SPEC.schema_rel
GENERATED_TRES = GAME_DIR / _PLAYER_SPEC.out_rel
COMBAT_JSON_PATH = GAME_DIR / "content/data/json/combat_config.json"
COMBAT_SCHEMA_PATH = GAME_DIR / "content/data/schema/combat_config.schema.json"
ENEMIES_JSON_PATH = GAME_DIR / "content/data/json/enemies_config.json"
ENEMIES_SCHEMA_PATH = GAME_DIR / "content/data/schema/enemies_config.schema.json"
LEVEL_JSON_PATH = GAME_DIR / _LEVEL_JSON_REL
LEVEL_SCHEMA_PATH = GAME_DIR / "content/data/schema/level_config.schema.json"


def load_json(path: Path) -> Any:
    """Parse a JSON file into Python data."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    """Load a JSON Schema (defaults to the S1 player-config schema)."""
    return load_json(path)


def validate_config(config: Any, schema: dict[str, Any] | None = None) -> Any:
    """Validate ``config`` against the schema; raise on invalid, else return it.

    Defaults to the player-config schema (S1 back-compat). Raises
    :class:`jsonschema.ValidationError` for any schema violation (missing key,
    wrong type, out-of-range component, wrong array length, wrong sign).
    """
    jsonschema.validate(
        instance=config, schema=schema if schema is not None else load_schema()
    )
    return config


def validate_enemies_semantics(document: Any) -> Any:
    """Enforce the enemies-config cross-field rules vanilla JSON Schema cannot.

    Runs after (and assumes) schema validation, wherever an enemies-sourced
    spec is built. Raises :class:`jsonschema.ValidationError` — the same
    failure type as the schema gate — so a bad config fails the build loudly
    either way. The rules (gADR-0003):

    - **Steering Band is a real interval**: ``keep_range_min <= keep_range_max``
      for every kind.
    - **Contact damage stays in the point-blank band**: a contact-delivery
      kind's ``attack_range`` must not exceed ``keep_range_max`` — the attack
      gate cannot reach beyond the band the steering holds. Delivery follows
      the controller's branch: ranged fires a bolt, every other archetype
      (melee, and tank since S8/gADR-0009) hits by contact.
    - **Spawn -> kind referential integrity**: every spawn entry of every
      Wave references a defined Enemy Kind.
    - **Spawn names are unique across the whole Wave schedule** (gADR-0005):
      ``queue_free`` on a cleared wave's last corpse is deferred, so the next
      wave can spawn while the dying node is still in the tree — a same-name
      spawn would be silently renamed by Godot and break addressability.
    - **Tier -> reward coverage** (gADR-0004): every Tier a kind uses must
      have a reward entry in the top-level ``tiers`` table — a kind whose
      kill could award nothing is a config bug, caught before any resource
      derives.
    - **The Warp Blink is an engage tool** (gADR-0009): a Warp kind's
      ``warp_trigger_range`` must not undercut its ``attack_range`` — the
      Boss never warps inside a brawl.
    - **At most one Time Dilation Field** (gADR-0009): a Warp kind's
      ``time_field_duration`` must stay strictly below ``warp_cooldown`` —
      the blink drops a field unconditionally, so an outliving field would
      overlap the next.
    """
    kinds = document["kinds"]
    tiers = document["tiers"]
    for name, kind in kinds.items():
        if kind["tier"] not in tiers:
            raise jsonschema.ValidationError(
                f"kind {name!r} uses tier {kind['tier']!r} but 'tiers' has no "
                "reward entry for it — every used Tier needs its Kill reward "
                "(gADR-0004)"
            )
        if kind["keep_range_min"] > kind["keep_range_max"]:
            raise jsonschema.ValidationError(
                f"kind {name!r}: keep_range_min ({kind['keep_range_min']}) must "
                f"not exceed keep_range_max ({kind['keep_range_max']}) — the "
                "Steering Band is an interval"
            )
        if (
            kind["archetype"] != "ranged"
            and kind["attack_range"] > kind["keep_range_max"]
        ):
            raise jsonschema.ValidationError(
                f"kind {name!r}: contact attack_range ({kind['attack_range']}) "
                f"must not exceed keep_range_max ({kind['keep_range_max']}) — "
                "every non-ranged archetype (melee; tank since gADR-0009) "
                "delivers contact damage, gated to the point-blank band"
            )
        if (
            "warp_cooldown" in kind
            and kind["warp_trigger_range"] < kind["attack_range"]
        ):
            raise jsonschema.ValidationError(
                f"kind {name!r}: warp_trigger_range "
                f"({kind['warp_trigger_range']}) must not undercut attack_range "
                f"({kind['attack_range']}) — the Warp Blink is an engage tool; "
                "the Boss never warps inside a brawl (gADR-0009)"
            )
        if (
            "warp_cooldown" in kind
            and kind["time_field_duration"] >= kind["warp_cooldown"]
        ):
            raise jsonschema.ValidationError(
                f"kind {name!r}: time_field_duration "
                f"({kind['time_field_duration']}) must stay strictly below "
                f"warp_cooldown ({kind['warp_cooldown']}) — at most one Time "
                "Dilation Field exists at a time (gADR-0009); the blink drops "
                "a field unconditionally, so an outliving field would overlap "
                "the next"
            )
    seen_names: set[str] = set()
    for wave_number, wave in enumerate(document["waves"], start=1):
        for spawn in wave["spawns"]:
            if spawn["kind"] not in kinds:
                raise jsonschema.ValidationError(
                    f"wave {wave_number} spawn {spawn['name']!r} references "
                    f"unknown kind {spawn['kind']!r}"
                )
            if spawn["name"] in seen_names:
                raise jsonschema.ValidationError(
                    f"duplicate spawn name {spawn['name']!r} (wave {wave_number}) "
                    "— spawn names must be unique across the Wave schedule for "
                    "addressability (gADR-0005)"
                )
            seen_names.add(spawn["name"])
    return document


def resolve_enemy_rewards(document: Any) -> Any:
    """Resolve the per-Tier Kill-reward table into per-kind derived fields.

    Returns a COPY of the enemies document where every kind carries
    ``exp_reward``/``gold_reward`` (gADR-0004) and ``drop_table`` (the Tier's
    ``drops``, gADR-0006) read from ``tiers[kind["tier"]]``. Runs after
    schema + semantic validation (which guarantee the tier entry exists),
    wherever an enemies-sourced spec is rendered, so the derived
    ``enemy_<kind>.tres`` stays a dumb per-kind read while the JSON keeps a
    single per-Tier authority — retuning a Tier's reward or drops is one
    edit, never three.
    """
    resolved = copy.deepcopy(document)
    for kind in resolved["kinds"].values():
        reward = resolved["tiers"][kind["tier"]]
        kind["exp_reward"] = reward["exp_reward"]
        kind["gold_reward"] = reward["gold_reward"]
        kind["drop_table"] = reward["drops"]
    return resolved


def validate_progression_semantics(document: Any) -> Any:
    """Enforce the progression cross-field rule vanilla JSON Schema cannot.

    The leveling curve must be STRICTLY increasing (gADR-0006): each entry is
    a cumulative EXP threshold, so a flat or decreasing step would make a
    level unreachable-then-instant — a config bug, caught before the resource
    derives. Raises :class:`jsonschema.ValidationError` (the same failure
    type as the schema gate) so a bad config fails the build loudly either
    way.
    """
    curve = document["level_curve"]
    for i in range(1, len(curve)):
        if curve[i] <= curve[i - 1]:
            raise jsonschema.ValidationError(
                f"level_curve must be strictly increasing, but entry {i} "
                f"({curve[i]}) does not exceed entry {i - 1} ({curve[i - 1]}) "
                "— each entry is a cumulative EXP threshold (gADR-0006)"
            )
    return document


def validate_level_semantics(document: Any) -> Any:
    """Enforce the level-config cross-field rules vanilla JSON Schema cannot.

    Runs after (and assumes) schema validation. Raises
    :class:`jsonschema.ValidationError` — the same failure type as the schema
    gate — so a bad config fails the build loudly either way. The rules
    (gADR-0010):

    - **Segment names are unique**: each Great-Wall segment is instanced as a
      named sibling under Main (next to the Wave spawns), so a duplicate
      would be silently renamed by Godot and break addressability — the
      gADR-0005 argument.
    - **The Arena is a real interval**: ``arena_min_x < arena_max_x`` — the
      Warp Blink's landing clamp needs a non-degenerate span.
    """
    seen_names: set[str] = set()
    for platform in document["platforms"]:
        if platform["name"] in seen_names:
            raise jsonschema.ValidationError(
                f"duplicate platform name {platform['name']!r} — Great-Wall "
                "segment names must be unique for addressability (gADR-0010)"
            )
        seen_names.add(platform["name"])
    if document["arena_min_x"] >= document["arena_max_x"]:
        raise jsonschema.ValidationError(
            f"arena_min_x ({document['arena_min_x']}) must stay strictly below "
            f"arena_max_x ({document['arena_max_x']}) — the Arena is a real "
            "interval; it clamps the Warp Blink's landing (gADR-0010)"
        )
    return document


def load_scale_spec(root: Path = GAME_DIR) -> dict[str, Any]:
    """Load and schema-validate ``root``'s Scale spec (gADR-0013)."""
    document = load_json(root / _SCALE_JSON_REL)
    validate_config(document, load_schema(root / _SCALE_SCHEMA_REL))
    return document


def compose_scale_spec(document: Any, json_rel: str, scale: dict[str, Any]) -> Any:
    """Compose the Scale spec's element dimensions into one source document.

    The write side of gADR-0013's single size authority: every migrated
    dimension is injected back into the source document its derived Resource
    renders from, so the runtime keeps its existing per-module config shape
    while the numbers have ONE authored home (the gADR-0004 per-Tier-table
    pattern, widened). Mutates and returns ``document``; a source that carries
    no dimensions (e.g. items_config) passes through unchanged. Raises
    :class:`jsonschema.ValidationError` when the spec lacks an entry the
    source needs — the same failure type as the schema gate, so a bad config
    fails the build loudly (the full two-way rules live in
    ``validate_scale_semantics``; these are the composition-side guards).
    """
    if json_rel == _PLAYER_JSON_REL:
        document["player_size"] = scale["player_size"]
    elif json_rel == _COMBAT_JSON_REL:
        document["projectile_size"] = scale["player_projectile_size"]
    elif json_rel == _GRAVITY_JSON_REL:
        document["field_radius"] = scale["gravity_field_radius"]
        document["obstacle_size"] = scale["obstacle_size"]
    elif json_rel == _ENEMIES_JSON_REL:
        for name, kind in document["kinds"].items():
            box = scale["enemy_boxes"].get(name)
            if box is None:
                raise jsonschema.ValidationError(
                    f"kind {name!r} has no enemy_boxes entry in scale_spec.json "
                    "— every Enemy Kind's box lives in the Scale spec "
                    "(gADR-0013)"
                )
            kind["size"] = box["size"]
            if kind["archetype"] == "ranged":
                if "projectile_size" not in box:
                    raise jsonschema.ValidationError(
                        f"ranged kind {name!r} has no projectile_size in its "
                        "scale_spec.json enemy_boxes entry (gADR-0013)"
                    )
                kind["projectile_size"] = box["projectile_size"]
            if "warp_cooldown" in kind:
                if "time_field_radius" not in box:
                    raise jsonschema.ValidationError(
                        f"Warp kind {name!r} has no time_field_radius in its "
                        "scale_spec.json enemy_boxes entry (gADR-0013)"
                    )
                kind["time_field_radius"] = box["time_field_radius"]
    elif json_rel == _HUD_JSON_REL:
        document["margin"] = scale["hud_margin"]
        document["font_size"] = scale["hud_font_size"]
    elif json_rel == _PROGRESSION_JSON_REL:
        for item, style in document["drop_items"].items():
            size = scale["pickup_sizes"].get(item)
            if size is None:
                raise jsonschema.ValidationError(
                    f"drop item {item!r} has no pickup_sizes entry in "
                    "scale_spec.json (gADR-0013)"
                )
            style["size"] = size
        document["pickup_spacing"] = scale["pickup_spacing"]
    elif json_rel == _LEVEL_JSON_REL:
        document["end_title_font_size"] = scale["end_title_font_size"]
        document["end_hint_font_size"] = scale["end_hint_font_size"]
    return document


def load_composed(json_rel: str, root: Path = GAME_DIR) -> Any:
    """Load one authored source with the Scale spec's dimensions composed in.

    The read-side twin of ``build_spec``'s composition (gADR-0013): the exact
    document a derived Resource renders from, for tests and tools that need
    expectation values without rebuilding. The Scale spec itself loads
    validated and unchanged. The Asset manifest's id -> path is composed in too
    (gADR-0014), so a resolved asset reference is visible to the reader.
    """
    document = load_json(root / json_rel)
    if json_rel == _SCALE_JSON_REL:
        return validate_config(document, load_schema(root / _SCALE_SCHEMA_REL))
    document = compose_scale_spec(document, json_rel, load_scale_spec(root))
    return compose_asset_refs(document, json_rel, load_asset_manifest(root))


# The Asset pipeline (gADR-0014): the Asset manifest single-homes each produced
# asset's path; the JSON authority references it by a manifest ``id`` (a foreign
# key), never a raw path, and the builder composes id -> path into the derived
# ``.tres`` so the game/view read a resolved path and never the manifest. The
# manifest is a RECORD source (its provenance/license are not derivable), split
# per category so parallel asset slices don't contend — read as-is, never rebuilt
# (it is integrity-checked by ``validate_asset_refs``, not freshness-gated).
_MANIFEST_DIRNAME = "manifest"


@lru_cache(maxsize=1)
def _configured_assets_root() -> str:
    """Read the Asset pipeline's single assets-root authority."""
    from assets import config as assets_config
    from panda_assets import STYLE_PATH

    return assets_config.load_style_config(STYLE_PATH).assets_root


# The authored TOP-LEVEL asset-reference fields the builder resolves, per source.
# The tracer (#439) wires the Obstacle; sibling asset slices (#442/#443/#444/#445)
# extend this with their own sources' reference fields. P2-S3 (#442) adds the
# player Laser bolt (``combat_config`` ``projectile_asset``).
_ASSET_REF_FIELDS: dict[str, tuple[str, ...]] = {
    _GRAVITY_JSON_REL: ("obstacle_asset",),
    # P2-S5 (#443): the Player's animated look — ``player_asset`` resolves to the
    # committed ``SpriteFrames`` the ViewBuilder loads onto an AnimatedSprite2D
    # (gADR-0015/gADR-0016). The manifest ``player`` id single-homes its path.
    _PLAYER_JSON_REL: ("player_asset",),
    _COMBAT_JSON_REL: ("projectile_asset",),
    _HUD_JSON_REL: ("hud_font",),
}

# The nested view structures whose per-entry ``asset`` also resolves id -> path,
# per source: the item-style maps keyed by item name (the gADR-0006 ``item_style_map``
# render kind). ``_authored_asset_refs`` already SCANS these for the FK gate; this is
# the COMPOSE-side twin so the derived ``.tres`` carries the resolved path, not the id.
# P2-S3 (#442) wires the progression drop_items (the Pickups); a sibling slice adds the
# level ``platforms`` (#446) as it wires the terrain skin.
_ASSET_REF_ITEM_MAPS: dict[str, str] = {
    _PROGRESSION_JSON_REL: "drop_items",
}


def load_asset_manifest(root: Path = GAME_DIR) -> dict[str, dict[str, Any]]:
    """Merge the Asset manifest fragments into ``id -> record`` (gADR-0014).

    Reads every ``<assets_root>/manifest/<category>.json`` fragment, where
    ``assets_root`` comes from the Asset pipeline's style config. Returns ``{}``
    when the manifest directory is absent (a root with no acquired assets yet —
    an isolated build stages none). Raises on a duplicate id across fragments
    (the id is the manifest's primary key).
    """
    directory = root / _configured_assets_root() / _MANIFEST_DIRNAME
    if not directory.exists():
        return {}
    merged: dict[str, dict[str, Any]] = {}
    for fragment in sorted(directory.glob("*.json")):
        for asset_id, record in load_json(fragment).items():
            if asset_id in merged:
                raise jsonschema.ValidationError(
                    f"duplicate manifest id {asset_id!r} across fragments — the id "
                    "is the Asset manifest's primary key (gADR-0014)"
                )
            merged[asset_id] = record
    return merged


def _resolve_asset_ref(ref: str, manifest: dict[str, dict[str, Any]]) -> str:
    """Resolve one asset reference: a manifest id -> its single-homed path.

    An empty reference (no asset yet) and an id ABSENT from the manifest pass
    through unchanged. Absence is not raised here — the config gate
    (``validate_asset_refs``) enforces FK integrity against the committed
    manifest, so an isolated build with no manifest still renders (the id
    round-trips) while the committed build resolves the path and the gate keeps
    the two honest.
    """
    if not ref:
        return ""
    entry = manifest.get(ref)
    return entry["path"] if entry is not None else ref


def compose_asset_refs(
    document: Any, json_rel: str, manifest: dict[str, dict[str, Any]]
) -> Any:
    """Compose the Asset manifest's id -> path into a source's asset references.

    The write side of gADR-0014's id-referenced manifest: the authority names an
    asset by its manifest id, and the builder resolves it to the single-homed path
    so the derived Resource carries a resolved path (the gADR-0013 "one authored
    home, N derived projections" pattern applied to assets). Resolves both the
    top-level reference fields (``_ASSET_REF_FIELDS``) and the per-entry ``asset``
    of a nested item-style map (``_ASSET_REF_ITEM_MAPS`` — the Pickups' drop_items,
    #442). Mutates and returns ``document``; a source with no asset reference passes
    through unchanged.
    """
    for field_name in _ASSET_REF_FIELDS.get(json_rel, ()):
        document[field_name] = _resolve_asset_ref(
            document.get(field_name, ""), manifest
        )
    map_field = _ASSET_REF_ITEM_MAPS.get(json_rel)
    if map_field is not None:
        for style in document[map_field].values():
            if "asset" in style:
                style["asset"] = _resolve_asset_ref(style.get("asset", ""), manifest)
    return document


# The Tier axis in ascending power order — the GDD's at-a-glance size
# staircase (Minion near the Player, Elite above, Boss the largest).
_TIER_ORDER = ["minion", "elite", "boss"]


def validate_scale_semantics(scale: dict[str, Any], root: Path = GAME_DIR) -> Any:
    """Enforce the Scale spec's cross-FILE rules (gADR-0013).

    Runs after (and assumes) schema validation, when the Scale spec's own
    resource builds; raises :class:`jsonschema.ValidationError` — the same
    failure type as the schema gate — so a bad config fails the build loudly
    either way. The rules:

    - **Two-way kind integrity**: every Enemy Kind in the enemies config has
      an ``enemy_boxes`` entry, and every entry names a defined kind — adding
      a kind touches both authored files, and the gate catches a miss.
    - **Optional keys follow the kind's shape**: an entry carries
      ``projectile_size`` iff its kind is ranged, and ``time_field_radius``
      iff its kind carries the Warp block.
    - **Strict Tier size ordering** (the GDD rule, machine-enforced): every
      lower-Tier box stays strictly below every higher-Tier box on BOTH
      dimensions — Tier must read at a glance.
    - **Two-way pickup-item integrity**: ``pickup_sizes`` and the progression
      config's ``drop_items`` name the same item vocabulary.
    - **The tile grid**: every level segment dimension and the standard
      ``platform_thickness`` are multiples of ``tile_size``, so the View
      skin's tile vocabulary composes seamlessly (level GEOMETRY stays
      authored content in the Level authority; the spec only constrains it
      to the grid).
    """
    enemies = load_json(root / _ENEMIES_JSON_REL)
    progression = load_json(root / _PROGRESSION_JSON_REL)
    level = load_json(root / _LEVEL_JSON_REL)

    kinds = enemies["kinds"]
    boxes = scale["enemy_boxes"]
    for name in kinds:
        if name not in boxes:
            raise jsonschema.ValidationError(
                f"kind {name!r} has no enemy_boxes entry in scale_spec.json — "
                "every Enemy Kind's box lives in the Scale spec (gADR-0013)"
            )
    for name in boxes:
        if name not in kinds:
            raise jsonschema.ValidationError(
                f"enemy_boxes entry {name!r} names no kind in "
                "enemies_config.json — a stale box is a config bug (gADR-0013)"
            )
    for name, kind in kinds.items():
        box = boxes[name]
        if (kind["archetype"] == "ranged") != ("projectile_size" in box):
            raise jsonschema.ValidationError(
                f"kind {name!r}: enemy_boxes carries projectile_size iff the "
                "kind is ranged (gADR-0013)"
            )
        if ("warp_cooldown" in kind) != ("time_field_radius" in box):
            raise jsonschema.ValidationError(
                f"kind {name!r}: enemy_boxes carries time_field_radius iff "
                "the kind carries the Warp block (gADR-0013)"
            )

    by_tier: dict[str, list[tuple[str, list[float]]]] = {
        tier: [] for tier in _TIER_ORDER
    }
    for name, kind in kinds.items():
        by_tier[kind["tier"]].append((name, boxes[name]["size"]))
    present = [tier for tier in _TIER_ORDER if by_tier[tier]]
    for lower, higher in zip(present, present[1:]):
        for axis, label in ((0, "width"), (1, "height")):
            low_name, low_size = max(by_tier[lower], key=lambda e: e[1][axis])
            high_name, high_size = min(by_tier[higher], key=lambda e: e[1][axis])
            if low_size[axis] >= high_size[axis]:
                raise jsonschema.ValidationError(
                    f"Tier size ordering broken: {lower} {low_name!r} {label} "
                    f"({low_size[axis]}) must stay strictly below {higher} "
                    f"{high_name!r} {label} ({high_size[axis]}) — Tier reads "
                    "at a glance (gADR-0013)"
                )

    drop_items = progression["drop_items"]
    pickup_sizes = scale["pickup_sizes"]
    for item in drop_items:
        if item not in pickup_sizes:
            raise jsonschema.ValidationError(
                f"drop item {item!r} has no pickup_sizes entry in "
                "scale_spec.json (gADR-0013)"
            )
    for item in pickup_sizes:
        if item not in drop_items:
            raise jsonschema.ValidationError(
                f"pickup_sizes entry {item!r} names no drop item in "
                "progression_config.json (gADR-0013)"
            )

    tile = scale["tile_size"]
    for platform in level["platforms"]:
        for axis, label in ((0, "width"), (1, "height")):
            if platform["size"][axis] % tile != 0:
                raise jsonschema.ValidationError(
                    f"segment {platform['name']!r} {label} "
                    f"({platform['size'][axis]}) is not a multiple of the "
                    f"tile_size ({tile}) — segment geometry must land on the "
                    "tile grid so the View skin composes seamlessly "
                    "(gADR-0013)"
                )
    if scale["platform_thickness"] % tile != 0:
        raise jsonschema.ValidationError(
            f"platform_thickness ({scale['platform_thickness']}) is not a "
            f"multiple of the tile_size ({tile}) — the standard slab is a "
            "grid multiple (gADR-0013)"
        )
    return scale


def enemy_kind_specs(root: Path = GAME_DIR) -> list[TresSpec]:
    """One TresSpec per Enemy Kind, DERIVED from ``root``'s enemies JSON.

    Iterating the JSON's own ``kinds`` (whose key order JSON parsing preserves)
    keeps the derivation deterministic, so the committed ``.tres`` set and
    bytes are stable for a given source. This is what makes adding a kind a
    JSON-only change (gADR-0001/gADR-0003): no Python edit, and every consumer
    of ``specs_for``/``SPECS`` — the builder, the freshness gate — picks the
    new kind up automatically.
    """
    document = load_json(root / _ENEMIES_JSON_REL)
    return [_enemy_kind_spec(name, kind) for name, kind in document["kinds"].items()]


def specs_for(root: Path = GAME_DIR) -> list[TresSpec]:
    """Every declared output under ``root``: the static table plus the
    JSON-derived per-kind enemy specs and the Wave schedule."""
    return [*_STATIC_SPECS, *enemy_kind_specs(root), _WAVE_SCHEDULE_SPEC]


def _resource_to_fs(root: Path, resource_path: str) -> Path:
    """Map a ``res://...`` asset path to its on-disk location under ``root``."""
    return root / resource_path.removeprefix("res://")


def _authored_asset_refs(root: Path = GAME_DIR) -> list[tuple[str, str]]:
    """Every non-empty asset reference authored across the authority (gADR-0014).

    Reads each spec's ``asset``-kind fields plus the nested view structures (the
    level ``platforms`` and the progression ``drop_items`` styles), so the FK gate
    sees EVERY referenced id — the tracer's Obstacle today, and every sibling
    slice's references as they are authored. Returns ``(asset_id, where)`` pairs
    (``where`` naming the derived output + field for a legible failure).
    """
    docs: dict[str, Any] = {}

    def _doc(json_rel: str) -> Any:
        if json_rel not in docs:
            docs[json_rel] = load_json(root / json_rel)
        return docs[json_rel]

    refs: list[tuple[str, str]] = []
    for spec in specs_for(root):
        config = _doc(spec.json_rel)
        for key in spec.json_root:
            config = config[key]
        for name, kind in spec.fields:
            if kind == "asset":
                if config.get(name):
                    refs.append((config[name], f"{spec.out_rel}:{name}"))
            elif kind == "platform_list":
                for entry in config[name]:
                    if entry.get("asset"):
                        refs.append(
                            (entry["asset"], f"{spec.out_rel}:{name}[{entry['name']}]")
                        )
            elif kind == "item_style_map":
                for item, style in config[name].items():
                    if style.get("asset"):
                        refs.append((style["asset"], f"{spec.out_rel}:{name}[{item}]"))
    return refs


# The record shape a referenced Asset manifest entry must carry (gADR-0014): the
# seven core fields, so no referenced-but-unprovenanced/unlicensed asset ships.
_REQUIRED_MANIFEST_FIELDS = (
    "path",
    "category",
    "acquire_mode",
    "source",
    "license",
    "license_url",
    "target_dims",
)


def validate_asset_refs(root: Path = GAME_DIR) -> dict[str, dict[str, Any]]:
    """Enforce the Asset manifest <-> authority integrity gate (gADR-0014).

    Mirrors ``validate_scale_semantics``'s two-way integrity, joining the config
    gate. Raises :class:`jsonschema.ValidationError` — the same failure type as
    the schema gate — so a broken reference fails the build loudly. The rules:

    - **FK integrity**: every asset id referenced in any authority exists in the
      manifest — no referenced-but-unprovenanced/unlicensed asset ships.
    - **Record shape**: every REFERENCED entry carries the full record
      (``path``/``category``/``acquire_mode``/``source``/``license``/
      ``license_url``/``target_dims``) — a referenced asset missing its provenance
      or license is a config bug, caught before it ships.
    - **No dangling**: every manifest entry's ``path`` exists on disk — a recorded
      asset whose file was removed is a config bug.

    Returns the merged manifest (the soft orphan report is ``asset_ref_orphans``).
    """
    manifest = load_asset_manifest(root)
    for asset_id, where in _authored_asset_refs(root):
        record = manifest.get(asset_id)
        if record is None:
            raise jsonschema.ValidationError(
                f"asset reference {asset_id!r} ({where}) has no Asset manifest "
                "entry — every referenced asset must be recorded with its "
                "provenance and license (gADR-0014)"
            )
        missing = [f for f in _REQUIRED_MANIFEST_FIELDS if f not in record]
        if missing:
            raise jsonschema.ValidationError(
                f"manifest entry {asset_id!r} ({where}) is missing required "
                f"field(s) {missing} — a referenced asset must record its full "
                "provenance and license (gADR-0014)"
            )
    for asset_id, record in manifest.items():
        path = record.get("path")
        if path is None:  # shape is enforced on referenced entries; skip orphans
            continue
        if not _resource_to_fs(root, path).exists():
            raise jsonschema.ValidationError(
                f"manifest entry {asset_id!r} path {path} does not exist on disk "
                "— a dangling Asset manifest record (gADR-0014)"
            )
    return manifest


def validate_asset_sizes(root: Path = GAME_DIR) -> list[Any]:
    """Enforce gADR-0015's size-based Git-LFS gate at the config gate (review S1).

    Delegates to the asset pipeline's lifecycle gate with the threshold ``T`` from
    the committed Style descriptor config, so ``python scripts/build_config.py``
    mechanically FAILS a committed Content asset binary ``>= T`` that is not
    LFS-tracked — not merely an optional test path. Joins ``main`` (the
    authoritative standalone build), NOT ``build_all``: build_all runs against
    isolated, non-git e2e roots where ``git check-attr`` has nothing to consult —
    the size gate is repo-scoped. Raises ``assets.lifecycle.AssetSizeError`` on a
    violation.
    """
    from assets import config as assets_config
    from assets import lifecycle
    from panda_assets import STYLE_PATH

    config = assets_config.load_style_config(STYLE_PATH)
    return lifecycle.validate_committed_asset_sizes(
        root,
        config.lfs_size_threshold_bytes,
        assets_root=config.assets_root,
    )


def validate_asset_licenses(root: Path = GAME_DIR) -> list[Any]:
    """Enforce the license/acquire-mode consistency gate (gADR-0015 §5d).

    Delegates to the asset pipeline's pure licensing core with the DOWNLOAD-license
    allowlist resolved PER CATEGORY (gADR-0014): the global rule is CC0/CC-BY, with
    fonts additionally allowing OFL (a permissive font license, P2-S9/#445) — so a
    downloaded OFL font is accepted for the fonts category only, every other category
    staying CC0/CC-BY. A ``search_download`` entry must record a download license
    allowed for its category; a ``generation`` entry its BACKEND's usage terms (a
    non-empty token that is NOT a download license — so a generated asset mislabeled
    ``CC0`` fails the build). Validates EVERY manifest entry (referenced or not), so
    it is general across asset slices. Raises ``assets.lifecycle.LicenseModeError``
    on a violation.
    """
    from assets import config as assets_config
    from assets import lifecycle
    from panda_assets import STYLE_PATH

    config = assets_config.load_style_config(STYLE_PATH)
    by_category: dict[str, list[tuple[str, str, str]]] = {}
    for asset_id, rec in load_asset_manifest(root).items():
        entry = (
            asset_id,
            str(rec.get("acquire_mode", "")),
            str(rec.get("license", "")),
        )
        by_category.setdefault(str(rec.get("category", "")), []).append(entry)
    violations: list[Any] = []
    for category, entries in sorted(by_category.items()):
        violations += lifecycle.validate_license_modes(
            entries, config.download_licenses_for(category)
        )
    return violations


def asset_ref_orphans(root: Path = GAME_DIR) -> list[str]:
    """Manifest ids no authority references — a SOFT report (gADR-0014).

    An orphan is a recorded-but-unwired asset: a warning, not a build failure
    (wave-close DoD requires zero). Returns the sorted orphan ids.
    """
    referenced = {asset_id for asset_id, _ in _authored_asset_refs(root)}
    return sorted(set(load_asset_manifest(root)) - referenced)


def asset_input_rels(root: Path = GAME_DIR) -> list[str]:
    """The Asset manifest fragments + the asset files ``build_all``'s gate needs.

    Since ``build_all`` enforces ``validate_asset_refs`` (FK + no-dangling + shape,
    gADR-0014), an isolated build root must carry the manifest and every asset it
    records. This returns those paths relative to ``root`` so tests/tools that
    stage a build root copy exactly what the gate needs — auto-extending as
    sibling asset slices record more assets (no per-test hardcoding).
    """
    directory = root / _configured_assets_root() / _MANIFEST_DIRNAME
    if not directory.exists():
        return []
    rels = [str(frag.relative_to(root)) for frag in sorted(directory.glob("*.json"))]
    rels += [
        record["path"].removeprefix("res://")
        for record in load_asset_manifest(root).values()
    ]
    return rels


# The committed game's spec list (tests parametrize over it; ``build_all``
# re-derives per root so e2e project copies see their own kinds).
SPECS: list[TresSpec] = specs_for()


def _num(value: float) -> str:
    """Format a JSON number the way a Godot ``.tres`` literal expects.

    Renders an integral float without a trailing ``.0`` (``1.0`` -> ``1``),
    matching Godot's own serializer; non-integral values keep full precision.
    Godot's parser accepts either form for ``Color``/``Vector2``/``float``.
    """
    if isinstance(value, bool):  # guard: bool is an int subclass
        raise TypeError("boolean is not a numeric config value")
    if float(value).is_integer():
        return str(int(value))
    return repr(float(value))


def _render_field(key: str, kind: str, value: Any) -> str:
    """Render one config value as its Godot ``.tres`` literal for the given kind."""
    if kind == "color":
        r, g, b, a = value
        return f"Color({_num(r)}, {_num(g)}, {_num(b)}, {_num(a)})"
    if kind == "vec2":
        x, y = value
        return f"Vector2({_num(x)}, {_num(y)})"
    if kind == "float":
        return _num(value)
    if kind == "string" or kind == "asset":
        # Schema-constrained enum/pattern values (no quotes/escapes possible).
        # "asset" differs from "string" only on the LOOKUP side (optional,
        # defaulting to "" — see _field_value); the literal renders the same.
        return f'"{value}"'
    if kind == "bool":
        return "true" if value else "false"
    if kind == "wave_list":
        # The Wave schedule: an Array of {"spawns": [...]} Dictionaries, each
        # spawn a {kind, name, position} Dictionary (the gADR-0003 entry
        # shape), rendered deterministically (byte-stable, like every other
        # kind, so the freshness gate holds).
        waves = ", ".join(
            '{{"spawns": [{spawns}]}}'.format(
                spawns=", ".join(_spawn_literal(entry) for entry in wave["spawns"])
            )
            for wave in value
        )
        return f"[{waves}]"
    if kind == "number_list":
        # A plain number Array (S6b's leveling curve), in source order.
        return "[{}]".format(", ".join(_num(entry) for entry in value))
    if kind == "drop_list":
        # A per-kind Drop table (gADR-0006): an Array of {item, amount,
        # chance} Dictionaries in source order.
        drops = ", ".join(
            '{{"item": "{item}", "amount": {amount}, "chance": {chance}}}'.format(
                item=entry["item"],
                amount=_num(entry["amount"]),
                chance=_num(entry["chance"]),
            )
            for entry in value
        )
        return f"[{drops}]"
    if kind == "platform_list":
        # The Great-Wall blockout (gADR-0010): an Array of {name, position,
        # size, asset} Dictionaries in source order — the ordered segments the
        # level runtime-instances. `asset` is the per-segment view asset
        # reference (P2-S2, #436), optional in the authored JSON (default "").
        platforms = ", ".join(
            '{{"name": "{name}", "position": Vector2({px}, {py}), '
            '"size": Vector2({sx}, {sy}), "asset": "{asset}"}}'.format(
                name=entry["name"],
                px=_num(entry["position"][0]),
                py=_num(entry["position"][1]),
                sx=_num(entry["size"][0]),
                sy=_num(entry["size"][1]),
                asset=entry.get("asset", ""),
            )
            for entry in value
        )
        return f"[{platforms}]"
    if kind == "item_style_map":
        # The pickup blockout per droppable item (gADR-0006): item name ->
        # {"color": Color, "size": Vector2, "asset": String}, in source key
        # order (JSON parsing preserves it — the enemy_kind_specs determinism
        # note). `asset` is the per-item view asset reference (P2-S2, #436),
        # optional in the authored JSON (default "").
        styles = ", ".join(
            '"{item}": {{"color": {color}, "size": {size}, "asset": "{asset}"}}'.format(
                item=item,
                color=_render_field("color", "color", style["color"]),
                size=_render_field("size", "vec2", style["size"]),
                asset=style.get("asset", ""),
            )
            for item, style in value.items()
        )
        return f"{{{styles}}}"
    raise ValueError(f"unknown field kind {kind!r} for {key!r}")


def _spawn_literal(entry: dict[str, Any]) -> str:
    """Render one Spawn Roster entry as its Godot Dictionary literal."""
    return (
        '{{"kind": "{kind}", "name": "{name}", "position": Vector2({x}, {y})}}'.format(
            kind=entry["kind"],
            name=entry["name"],
            x=_num(entry["position"][0]),
            y=_num(entry["position"][1]),
        )
    )


def _field_value(config: dict[str, Any], key: str, kind: str) -> Any:
    """Look one field's value up in the source document.

    Every kind reads its authored (or composed) key directly — a miss is a
    config bug the loud KeyError surfaces — except "asset": the view asset
    reference (P2-S2, #436) is OPTIONAL in the authored JSON and defaults to ""
    (no asset yet -> the ViewBuilder block fallback), so the derived ``.tres``
    always carries the field without every source having to author it.
    """
    if kind == "asset":
        return config.get(key, "")
    return config[key]


def render_spec(spec: TresSpec, document: dict[str, Any]) -> str:
    """Render one spec's ``.tres`` text from a validated source document.

    Pure function (no IO): the JSON->Resource conversion seam. Descends
    ``spec.json_root`` into the document, then walks ``spec.fields`` in
    declaration order, mapping each JSON value to its Godot type.
    """
    config = document
    for key in spec.json_root:
        config = config[key]
    body = "".join(
        f"{key} = {_render_field(key, kind, _field_value(config, key, kind))}\n"
        for key, kind in spec.fields
    )
    return (
        f'[gd_resource type="Resource" script_class="{spec.script_class}" '
        f"load_steps=2 format=3]\n\n"
        f'[ext_resource type="Script" path="{spec.script_res_path}" '
        f'id="{spec.ext_id}"]\n\n'
        f"[resource]\n"
        f'script = ExtResource("{spec.ext_id}")\n'
        f"{body}"
    )


def render_tres(config: dict[str, Any]) -> str:
    """Render a validated player config as ``PlayerConfig`` ``.tres`` text (S1)."""
    return render_spec(_PLAYER_SPEC, config)


def build_spec(
    spec: TresSpec, root: Path = GAME_DIR, out_path: Path | None = None
) -> Path:
    """Validate one spec's source JSON and write its derived ``.tres``.

    Paths resolve against ``root`` so the e2e project copies can rebuild in
    place. Returns the path written; raises
    :class:`jsonschema.ValidationError` if the JSON is invalid, so a bad config
    fails the build loudly.
    """
    document = load_json(root / spec.json_rel)
    validate_config(document, load_schema(root / spec.schema_rel))
    if spec.json_rel == _SCALE_JSON_REL:
        # The Scale spec's own cross-FILE rules (gADR-0013): kind and pickup
        # integrity, Tier size ordering, and the tile grid.
        validate_scale_semantics(document, root=root)
    else:
        # Compose the Scale spec's dimensions into the source document
        # (gADR-0013): one authored home, N derived projections. The FULL
        # cross-file semantics run here too — before ANY spec writes — so a
        # semantically invalid Scale spec fails the very first build_spec of
        # a build_all pass and no partial derived set is left behind (the
        # gADR-0000 no-drift rule; PR #457 review finding).
        scale = validate_scale_semantics(load_scale_spec(root), root=root)
        document = compose_scale_spec(document, spec.json_rel, scale)
        # Compose the Asset manifest's id -> path into any asset references
        # (gADR-0014): the authored id resolves to the single-homed path so the
        # derived Resource carries a resolved path. Reads the committed manifest,
        # so a manifest path change re-derives (the freshness gate takes the
        # manifest as an input); an isolated root with no manifest passes the id
        # through unchanged (the FK gate — validate_asset_refs — is separate).
        document = compose_asset_refs(
            document, spec.json_rel, load_asset_manifest(root)
        )
    if spec.json_rel == _ENEMIES_JSON_REL:
        # The enemies source carries cross-field rules the schema cannot
        # express (gADR-0003) — enforce them before deriving any resource,
        # then resolve the per-Tier rewards into the per-kind derived fields
        # the specs render (gADR-0004/gADR-0006).
        validate_enemies_semantics(document)
        document = resolve_enemy_rewards(document)
    if spec.json_rel == _PROGRESSION_JSON_REL:
        # The progression source's own cross-field rule: the leveling curve
        # is strictly increasing (gADR-0006).
        validate_progression_semantics(document)
    if spec.json_rel == _LEVEL_JSON_REL:
        # The level source's own cross-field rules: unique Great-Wall segment
        # names and a real Arena interval (gADR-0010).
        validate_level_semantics(document)
    target = out_path if out_path is not None else root / spec.out_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_spec(spec, document), encoding="utf-8")
    return target


def build_all(root: Path = GAME_DIR) -> list[Path]:
    """Build every declared output under ``root``; returns the paths written.

    The spec list is re-derived from ``root``'s own enemies JSON, so a copy
    that adds (or renames) an Enemy Kind builds that kind's ``.tres`` with no
    code change.

    The Asset manifest gate runs FIRST (gADR-0014): FK integrity, no-dangling, and
    record shape are enforced before ANY spec writes — so a bad manifest fails the
    build with no partial derived set left behind (the gADR-0000 no-drift rule),
    joining the schema/semantic/freshness config gate rather than living only in
    tests. The per-spec ``compose_asset_refs`` stays lenient (an isolated
    ``build_spec`` on a manifest-less root still resolves by passthrough); the
    whole-authority ``build_all`` path is the one that enforces.
    """
    validate_asset_refs(root)
    validate_asset_licenses(root)
    return [build_spec(spec, root=root) for spec in specs_for(root)]


def build(
    json_path: Path = JSON_PATH,
    schema_path: Path = SCHEMA_PATH,
    out_path: Path = GENERATED_TRES,
) -> Path:
    """Validate the authoritative player JSON and write its ``.tres`` (S1 API).

    Composes the committed Scale spec's dimensions in (gADR-0013) — this
    convenience API always reads the game's own scale_spec.json; a copied
    root goes through ``build_spec``/``build_all``.
    """
    config = load_json(json_path)
    validate_config(config, load_schema(schema_path))
    scale = validate_scale_semantics(load_scale_spec())
    config = compose_scale_spec(config, _PLAYER_JSON_REL, scale)
    # Resolve the Player's asset reference (manifest id -> path, gADR-0014), so this
    # convenience API produces the same bytes as build_spec/build_all (the freshness
    # gate compares against it) — the Player sprite reference is wired since #443.
    config = compose_asset_refs(config, _PLAYER_JSON_REL, load_asset_manifest())
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_tres(config), encoding="utf-8")
    return out_path


def main() -> None:
    # The Asset manifest gate first (gADR-0014), so a standalone build fails loudly
    # on a broken reference / dangling / malformed record before writing anything.
    validate_asset_refs()
    # The license/acquire-mode consistency gate (gADR-0015 §5d): a generated asset
    # mislabeled with a download license (or a downloaded one mislabeled) fails here.
    validate_asset_licenses()
    # Then the size-based Git-LFS gate (gADR-0015): a committed content/assets/** binary
    # >= T outside LFS fails the authoritative build before any .tres is written.
    validate_asset_sizes()
    for spec in SPECS:
        written = build_spec(spec)
        print(
            f"build_config: wrote {written.relative_to(GAME_DIR)} "
            f"from {Path(spec.json_rel).name}"
        )


if __name__ == "__main__":
    main()
