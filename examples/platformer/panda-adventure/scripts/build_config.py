#!/usr/bin/env python3
"""JSON -> Resource build pipeline for Panda Adventure (gADR-0000).

The authoritative config lives in ``data/json/*.json``. This step validates each
source against its JSON Schema (raising on invalid input) and emits the *derived*
Godot Resources under ``data/generated/`` that the runtime ``load()``s. Every
``.tres`` is a committed derived artifact (a freshness gate keeps each one
byte-identical to a fresh build), never hand-edited: changing config means
changing the JSON.

Seven sources feed the outputs (``specs_for``/``SPECS``):

- ``player_config.json`` -> ``player_config.tres`` (``PlayerConfig``, S1)
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema

# Resolve paths relative to this file so the script works from any CWD.
GAME_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class TresSpec:
    """One derived ``.tres`` output: its source JSON, schema, and field layout.

    ``json_root`` addresses the sub-object of the source document the fields are
    read from (``()`` = the document root). ``fields`` is the render authority —
    ``(json key, Godot type)`` pairs rendered in declaration order, so a rebuild
    is byte-stable (the freshness gate depends on it) and adding a config field
    is a one-line change. Types: "color" (4-array -> Color), "vec2" (2-array ->
    Vector2), "float" (scalar -> bare number), "string" (str -> quoted String),
    "wave_list" (waves -> Array of {"spawns": Array of Dictionary}, S5's Wave
    schedule), "number_list" (number array -> Array, S6b's leveling curve),
    "drop_list" (drop entries -> Array of Dictionary, S6b's per-kind Drop
    table), "item_style_map" (item name -> {"color": Color, "size": Vector2},
    S6b's pickup blockout). The schema is the validation authority; keep the
    two in step.
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
    ("player_start", "vec2"),
    ("move_speed", "float"),
    ("jump_velocity", "float"),
    ("gravity", "float"),
    ("max_fall_speed", "float"),
    ("platform_color", "color"),
    ("platform_size", "vec2"),
    ("platform_position", "vec2"),
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
    ("projectile_speed", "float"),
    ("projectile_lifetime", "float"),
    ("projectile_spawn_offset", "vec2"),
    ("enemy_color", "color"),
    ("enemy_size", "vec2"),
    ("enemy_position", "vec2"),
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
    ("field_fade_duration", "float"),
    ("field_spawn_offset", "vec2"),
    ("enemy_max_gravity_offset", "float"),
    ("obstacle_color", "color"),
    ("obstacle_size", "vec2"),
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
# value-change pulse tween. Layout/styling beyond these stays a later asset
# concern (GDD "HUD & UI").
_HUD_FIELDS: list[tuple[str, str]] = [
    ("margin", "vec2"),
    ("value_punch_scale", "vec2"),
    ("value_tween_duration", "float"),
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


# The S4 enemies source (gADR-0003) — one json_rel shared by the derived
# per-kind specs and the Wave-schedule spec.
_ENEMIES_JSON_REL = "data/json/enemies_config.json"
_ENEMIES_SCHEMA_REL = "data/schema/enemies_config.schema.json"

# The S6b progression source (gADR-0006) — carries its own cross-field rule
# (the strictly increasing leveling curve, validate_progression_semantics).
_PROGRESSION_JSON_REL = "data/json/progression_config.json"


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
        out_rel=f"data/generated/enemy_{kind}.tres",
        script_res_path="res://src/resources/enemy_config.gd",
        script_class="EnemyConfig",
        ext_id="1_enemyconfig",
        json_root=("kinds", kind),
        fields=fields,
    )


_PLAYER_SPEC = TresSpec(
    json_rel="data/json/player_config.json",
    schema_rel="data/schema/player_config.schema.json",
    out_rel="data/generated/player_config.tres",
    script_res_path="res://src/resources/player_config.gd",
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
        json_rel="data/json/combat_config.json",
        schema_rel="data/schema/combat_config.schema.json",
        out_rel="data/generated/stats_player.tres",
        script_res_path="res://src/resources/stats_config.gd",
        script_class="StatsConfig",
        ext_id="1_statsconfig",
        json_root=("player_stats",),
        fields=_STAT_BLOCK_FIELDS,
    ),
    TresSpec(
        json_rel="data/json/combat_config.json",
        schema_rel="data/schema/combat_config.schema.json",
        out_rel="data/generated/stats_enemy.tres",
        script_res_path="res://src/resources/stats_config.gd",
        script_class="StatsConfig",
        ext_id="1_statsconfig",
        json_root=("enemy_stats",),
        fields=_STAT_BLOCK_FIELDS,
    ),
    TresSpec(
        json_rel="data/json/combat_config.json",
        schema_rel="data/schema/combat_config.schema.json",
        out_rel="data/generated/combat_config.tres",
        script_res_path="res://src/resources/combat_config.gd",
        script_class="CombatConfig",
        ext_id="1_combatconfig",
        fields=_COMBAT_FIELDS,
    ),
    TresSpec(
        json_rel="data/json/gravity_config.json",
        schema_rel="data/schema/gravity_config.schema.json",
        out_rel="data/generated/gravity_config.tres",
        script_res_path="res://src/resources/gravity_config.gd",
        script_class="GravityConfig",
        ext_id="1_gravityconfig",
        fields=_GRAVITY_FIELDS,
    ),
    TresSpec(
        json_rel="data/json/hud_config.json",
        schema_rel="data/schema/hud_config.schema.json",
        out_rel="data/generated/hud_config.tres",
        script_res_path="res://src/resources/hud_config.gd",
        script_class="HudConfig",
        ext_id="1_hudconfig",
        fields=_HUD_FIELDS,
    ),
    TresSpec(
        json_rel=_PROGRESSION_JSON_REL,
        schema_rel="data/schema/progression_config.schema.json",
        out_rel="data/generated/progression_config.tres",
        script_res_path="res://src/resources/progression_config.gd",
        script_class="ProgressionConfig",
        ext_id="1_progressionconfig",
        fields=_PROGRESSION_FIELDS,
    ),
    TresSpec(
        json_rel="data/json/items_config.json",
        schema_rel="data/schema/items_config.schema.json",
        out_rel="data/generated/items_config.tres",
        script_res_path="res://src/resources/items_config.gd",
        script_class="ItemsConfig",
        ext_id="1_itemsconfig",
        fields=_ITEMS_FIELDS,
    ),
]

_WAVE_SCHEDULE_SPEC = TresSpec(
    json_rel=_ENEMIES_JSON_REL,
    schema_rel=_ENEMIES_SCHEMA_REL,
    out_rel="data/generated/wave_schedule.tres",
    script_res_path="res://src/resources/wave_schedule_config.gd",
    script_class="WaveScheduleConfig",
    ext_id="1_waveschedule",
    fields=_WAVE_SCHEDULE_FIELDS,
)

# S1 back-compat conveniences (existing tests and callers import these; they are
# the player spec's paths) plus the S2 combat-source counterparts.
JSON_PATH = GAME_DIR / _PLAYER_SPEC.json_rel
SCHEMA_PATH = GAME_DIR / _PLAYER_SPEC.schema_rel
GENERATED_TRES = GAME_DIR / _PLAYER_SPEC.out_rel
COMBAT_JSON_PATH = GAME_DIR / "data/json/combat_config.json"
COMBAT_SCHEMA_PATH = GAME_DIR / "data/schema/combat_config.schema.json"
ENEMIES_JSON_PATH = GAME_DIR / "data/json/enemies_config.json"
ENEMIES_SCHEMA_PATH = GAME_DIR / "data/schema/enemies_config.schema.json"


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
    - **Melee damage is contact damage**: a melee kind's ``attack_range`` must
      not exceed ``keep_range_max`` — the attack gate cannot reach beyond the
      point-blank band the steering holds.
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
            kind["archetype"] == "melee"
            and kind["attack_range"] > kind["keep_range_max"]
        ):
            raise jsonschema.ValidationError(
                f"kind {name!r}: melee attack_range ({kind['attack_range']}) must "
                f"not exceed keep_range_max ({kind['keep_range_max']}) — melee "
                "damage is contact damage, gated to the point-blank band"
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
    return [
        _enemy_kind_spec(name, kind) for name, kind in document["kinds"].items()
    ]


def specs_for(root: Path = GAME_DIR) -> list[TresSpec]:
    """Every declared output under ``root``: the static table plus the
    JSON-derived per-kind enemy specs and the Wave schedule."""
    return [*_STATIC_SPECS, *enemy_kind_specs(root), _WAVE_SCHEDULE_SPEC]


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
    if kind == "string":
        # Schema-constrained enum/pattern values (no quotes/escapes possible).
        return f'"{value}"'
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
    if kind == "item_style_map":
        # The pickup blockout per droppable item (gADR-0006): item name ->
        # {"color": Color, "size": Vector2}, in source key order (JSON parsing
        # preserves it — the enemy_kind_specs determinism note).
        styles = ", ".join(
            '"{item}": {{"color": {color}, "size": {size}}}'.format(
                item=item,
                color=_render_field("color", "color", style["color"]),
                size=_render_field("size", "vec2", style["size"]),
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
        f"{key} = {_render_field(key, kind, config[key])}\n"
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
    target = out_path if out_path is not None else root / spec.out_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_spec(spec, document), encoding="utf-8")
    return target


def build_all(root: Path = GAME_DIR) -> list[Path]:
    """Build every declared output under ``root``; returns the paths written.

    The spec list is re-derived from ``root``'s own enemies JSON, so a copy
    that adds (or renames) an Enemy Kind builds that kind's ``.tres`` with no
    code change.
    """
    return [build_spec(spec, root=root) for spec in specs_for(root)]


def build(
    json_path: Path = JSON_PATH,
    schema_path: Path = SCHEMA_PATH,
    out_path: Path = GENERATED_TRES,
) -> Path:
    """Validate the authoritative player JSON and write its ``.tres`` (S1 API)."""
    config = load_json(json_path)
    validate_config(config, load_schema(schema_path))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_tres(config), encoding="utf-8")
    return out_path


def main() -> None:
    for spec in SPECS:
        written = build_spec(spec)
        print(
            f"build_config: wrote {written.relative_to(GAME_DIR)} "
            f"from {Path(spec.json_rel).name}"
        )


if __name__ == "__main__":
    main()
