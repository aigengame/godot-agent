"""Data seam (a) for S3 Gravity Gun / Gravity Field / MP economy.

Proves the JSON -> Resource pipeline (gADR-0000) for the S3 gravity config: the
authoritative ``gravity_config.json`` validates against its schema, bad config
is rejected, and the derived ``GravityConfig`` ``.tres`` round-trips back
through gda with its declared Godot types. The byte-stable freshness gate is
NOT duplicated here: ``test_combat_data_seam.py`` parametrizes it over
``build_config.SPECS``, so the gravity spec is covered there automatically —
this file only pins that the spec IS registered. Fast tier — never ``e2e``;
the round-trip drives one-shot ``gda`` headless ops under the ``engine`` gate.
"""

from __future__ import annotations

import copy
import json

import jsonschema
import pytest

import build_config

GRAVITY_JSON_PATH = build_config.GAME_DIR / "data/json/gravity_config.json"
GRAVITY_SCHEMA_PATH = build_config.GAME_DIR / "data/schema/gravity_config.schema.json"
GRAVITY_TRES_REL = "data/generated/gravity_config.tres"


def _valid_config() -> dict:
    """A fresh copy of a schema-valid gravity config to mutate into invalid variants."""
    return {
        "mp_cost": 10.0,
        "wine_mp_restore": 15.0,
        "field_direction": [0.0, -1.0],
        "field_strength": 260.0,
        "field_radius": 96.0,
        "field_duration": 2.0,
        "field_color": [0.35, 0.65, 1.0, 0.35],
        "field_fade_duration": 0.25,
        "field_spawn_offset": [120.0, 0.0],
        "enemy_max_gravity_offset": 120.0,
        "obstacle_color": [0.62, 0.45, 0.25, 1.0],
        "obstacle_size": [40.0, 40.0],
        "obstacle_position": [320.0, 360.0],
        "obstacle_max_gravity_offset": 160.0,
    }


def _gravity_schema() -> dict:
    return build_config.load_schema(GRAVITY_SCHEMA_PATH)


def test_sample_json_passes_schema() -> None:
    """The authoritative gravity config validates against its schema."""
    config = build_config.load_json(GRAVITY_JSON_PATH)
    assert build_config.validate_config(config, _gravity_schema()) is config


def test_gravity_spec_registered_for_freshness_gate() -> None:
    """The gravity spec is in SPECS, so the parametrized freshness gate covers it."""
    assert GRAVITY_TRES_REL in [spec.out_rel for spec in build_config.SPECS]


def _without(key: str) -> dict:
    bad = _valid_config()
    del bad[key]
    return bad


def _with(value: object, key: str) -> dict:
    bad = copy.deepcopy(_valid_config())
    bad[key] = value
    return bad


@pytest.mark.parametrize(
    "bad",
    [
        _without("mp_cost"),  # missing economy scalar
        _without("field_direction"),  # missing field param
        _without("obstacle_position"),  # missing obstacle placement
        _with(0, "mp_cost"),  # a free fire would unbudget the pillar
        _with(-5.0, "wine_mp_restore"),  # restore must be strictly positive
        _with(0, "field_strength"),  # strength strictly positive
        _with(0, "field_radius"),  # radius strictly positive
        _with(0, "field_duration"),  # effect window strictly positive
        _with(0, "field_fade_duration"),  # fade tween strictly positive
        _with(0, "enemy_max_gravity_offset"),  # clamp strictly positive
        _with(0, "obstacle_max_gravity_offset"),  # clamp strictly positive
        _with([0.0], "field_direction"),  # direction: too few components
        _with([0.0, -1.0, 0.0], "field_direction"),  # direction: too many
        _with([0.35, 0.65, 1.0], "field_color"),  # color: too few components
        _with([0.35, 0.65, 1.5, 0.35], "field_color"),  # color: out of 0..1
        _with([40.0], "obstacle_size"),  # size: too few components
        _with([0.0, 40.0], "obstacle_size"),  # size: component must be > 0
        _with([120.0, 0.0, 1.0], "field_spawn_offset"),  # offset: too many
        _with("strong", "field_strength"),  # wrong type
        {**_valid_config(), "extra": 1},  # unexpected extra top-level key
    ],
)
def test_invalid_json_rejected(bad: dict) -> None:
    """A gravity config that violates the schema raises jsonschema.ValidationError."""
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_config(bad, _gravity_schema())


# ---------------------------------------------------------------------------
# Round-trip: the derived gravity .tres loads back through gda with its
# declared Godot types, compared to the AUTHORITATIVE JSON (never hardcoded).
# ---------------------------------------------------------------------------


def _properties_by_name(get_result: dict) -> dict:
    """Index a ``gda resource get`` result's ``properties`` list by name."""
    return {p["name"]: p["value"] for p in get_result["properties"]}


@pytest.mark.engine
def test_gravity_config_round_trips(gda) -> None:
    """The GravityConfig .tres round-trips every field through gda."""
    config = build_config.load_json(GRAVITY_JSON_PATH)
    result = gda("resource", "get", f"res://{GRAVITY_TRES_REL}", "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    props = _properties_by_name(json.loads(result.stdout))

    # Colors are float32 in Godot — compare with a tolerance.
    for color_field in ("field_color", "obstacle_color"):
        assert props[color_field] == pytest.approx(config[color_field], abs=1e-5)
    # Vector2 fields.
    for vec_field in (
        "field_direction",
        "field_spawn_offset",
        "obstacle_size",
        "obstacle_position",
    ):
        assert props[vec_field] == pytest.approx(config[vec_field])
    # Scalar float fields.
    for float_field in (
        "mp_cost",
        "wine_mp_restore",
        "field_strength",
        "field_radius",
        "field_duration",
        "field_fade_duration",
        "enemy_max_gravity_offset",
        "obstacle_max_gravity_offset",
    ):
        assert props[float_field] == pytest.approx(config[float_field])
