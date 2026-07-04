#!/usr/bin/env python3
"""JSON -> Resource build pipeline for Panda Adventure (gADR-0000).

The authoritative config lives in ``data/json/*.json``. This step validates each
source against its JSON Schema (raising on invalid input) and emits the *derived*
Godot Resources under ``data/generated/`` that the runtime ``load()``s. Every
``.tres`` is a committed derived artifact (a freshness gate keeps each one
byte-identical to a fresh build), never hand-edited: changing config means
changing the JSON.

Four sources feed the outputs (``specs_for``/``SPECS``):

- ``player_config.json`` -> ``player_config.tres`` (``PlayerConfig``, S1)
- ``combat_config.json`` -> ``stats_player.tres`` + ``stats_enemy.tres``
  (``StatsConfig`` stat blocks, gADR-0001) and ``combat_config.tres``
  (``CombatConfig``) — S2
- ``gravity_config.json`` -> ``gravity_config.tres`` (``GravityConfig``,
  gADR-0002) — S3
- ``enemies_config.json`` -> one ``enemy_<kind>.tres`` (``EnemyConfig``) per
  Enemy Kind plus ``enemy_roster.tres`` (``EnemyRosterConfig``, the Spawn
  Roster) — S4 (gADR-0003). The per-kind specs are DERIVED by iterating the
  JSON's ``kinds`` (gADR-0001: a new actor kind is config, not code — adding a
  kind is a JSON-only change), while the non-enemy specs stay a static table.

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
    "spawn_list" (spawn entries -> Array of Dictionary, S4's Spawn Roster). The
    schema is the validation authority; keep the two in step.
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
    ("wine_mp_restore", "float"),
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
# shape, gADR-0001), the blockout, and the Archetype-AI params.
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
]

# Ranged kinds additionally carry their bolt's blockout+motion (schema-enforced
# via if/then on archetype == "ranged").
_ENEMY_KIND_RANGED_FIELDS: list[tuple[str, str]] = _ENEMY_KIND_FIELDS + [
    ("projectile_color", "color"),
    ("projectile_size", "vec2"),
    ("projectile_speed", "float"),
    ("projectile_lifetime", "float"),
    ("projectile_spawn_offset", "vec2"),
]

_ROSTER_FIELDS: list[tuple[str, str]] = [
    ("spawns", "spawn_list"),
]


# The S4 enemies source (gADR-0003) — one json_rel shared by the derived
# per-kind specs and the roster spec.
_ENEMIES_JSON_REL = "data/json/enemies_config.json"
_ENEMIES_SCHEMA_REL = "data/schema/enemies_config.schema.json"


def _enemy_kind_spec(kind: str, archetype: str) -> TresSpec:
    """The TresSpec for one Enemy Kind: kinds.<kind> -> enemy_<kind>.tres.

    The field layout follows the kind's archetype: ranged kinds carry their
    bolt's projectile block on top of the base layout (the schema's if/then
    requires it), every other archetype renders the base layout.
    """
    fields = _ENEMY_KIND_RANGED_FIELDS if archetype == "ranged" else _ENEMY_KIND_FIELDS
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
]

_ROSTER_SPEC = TresSpec(
    json_rel=_ENEMIES_JSON_REL,
    schema_rel=_ENEMIES_SCHEMA_REL,
    out_rel="data/generated/enemy_roster.tres",
    script_res_path="res://src/resources/enemy_roster_config.gd",
    script_class="EnemyRosterConfig",
    ext_id="1_rosterconfig",
    fields=_ROSTER_FIELDS,
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
    - **Spawn -> kind referential integrity**: every Spawn Roster entry
      references a defined Enemy Kind.
    - **Roster names are unique**: each spawn's node ``name`` addresses one
      enemy (duplicate names would silently shadow in the scene tree).
    """
    kinds = document["kinds"]
    for name, kind in kinds.items():
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
    seen_names: set[str] = set()
    for spawn in document["spawns"]:
        if spawn["kind"] not in kinds:
            raise jsonschema.ValidationError(
                f"spawn {spawn['name']!r} references unknown kind {spawn['kind']!r}"
            )
        if spawn["name"] in seen_names:
            raise jsonschema.ValidationError(
                f"duplicate spawn name {spawn['name']!r} — roster names must be "
                "unique for addressability"
            )
        seen_names.add(spawn["name"])
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
        _enemy_kind_spec(name, kind["archetype"])
        for name, kind in document["kinds"].items()
    ]


def specs_for(root: Path = GAME_DIR) -> list[TresSpec]:
    """Every declared output under ``root``: the static table plus the
    JSON-derived per-kind enemy specs and the roster."""
    return [*_STATIC_SPECS, *enemy_kind_specs(root), _ROSTER_SPEC]


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
    if kind == "spawn_list":
        # The Spawn Roster: an Array of {kind, name, position} Dictionaries,
        # rendered one-line-per-build deterministically (byte-stable, like every
        # other kind, so the freshness gate holds).
        entries = ", ".join(
            '{{"kind": "{kind}", "name": "{name}", "position": Vector2({x}, {y})}}'.format(
                kind=entry["kind"],
                name=entry["name"],
                x=_num(entry["position"][0]),
                y=_num(entry["position"][1]),
            )
            for entry in value
        )
        return f"[{entries}]"
    raise ValueError(f"unknown field kind {kind!r} for {key!r}")


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
        # express (gADR-0003) — enforce them before deriving any resource.
        validate_enemies_semantics(document)
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
