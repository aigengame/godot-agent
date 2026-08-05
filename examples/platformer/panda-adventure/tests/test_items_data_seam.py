"""Data seam (a) for S7 Items & Equipment (Consumables + Spacesuit).

Proves the JSON -> Resource pipeline (gADR-0000) for the S7 items config: the
authoritative ``items_config.json`` validates against its schema, bad config
is rejected, and the derived ``ItemsConfig`` ``.tres`` round-trips back
through gda with its declared Godot types. This source is the ONE items
authority (gADR-0008): ``wine_mp_restore`` lives here — migrated out of
``gravity_config.json``, whose seam now rejects the stray key. The
byte-stable freshness gate is NOT duplicated here:
``test_combat_data_seam.py`` parametrizes it over ``build_config.SPECS``, so
the items spec is covered there automatically — this file only pins that the
spec IS registered. Fast tier — never ``e2e``; the round-trip drives one-shot
``gda`` headless ops under the ``engine`` gate.
"""

from __future__ import annotations

import copy
import json

import jsonschema
import pytest

import build_config

ITEMS_JSON_PATH = build_config.GAME_DIR / "content/data/json/items_config.json"
ITEMS_SCHEMA_PATH = build_config.GAME_DIR / "content/data/schema/items_config.schema.json"
ITEMS_TRES_REL = "content/data/generated/items_config.tres"


def _valid_config() -> dict:
    """A fresh copy of a schema-valid items config to mutate into invalid variants."""
    return {
        "bun_hp_restore": 25.0,
        "wine_mp_restore": 15.0,
        "spacesuit_defense": 2.0,
        "bun_flash_color": [0.4, 0.95, 0.45, 1.0],
        "wine_flash_color": [0.45, 0.6, 1.0, 1.0],
        "consume_flash_duration": 0.25,
    }


def _items_schema() -> dict:
    return build_config.load_schema(ITEMS_SCHEMA_PATH)


def test_sample_json_passes_schema() -> None:
    """The authoritative items config validates against its schema."""
    config = build_config.load_json(ITEMS_JSON_PATH)
    assert build_config.validate_config(config, _items_schema()) is config


def test_items_spec_registered_for_freshness_gate() -> None:
    """The items spec is in SPECS, so the parametrized freshness gate covers it."""
    assert ITEMS_TRES_REL in [spec.out_rel for spec in build_config.SPECS]


def test_wine_restore_has_one_authority() -> None:
    """The Wine restore lives ONLY in the items source (the gADR-0008 migration):
    present here, absent from the gravity source it migrated out of."""
    items = build_config.load_json(ITEMS_JSON_PATH)
    gravity = build_config.load_json(
        build_config.GAME_DIR / "content/data/json/gravity_config.json"
    )
    assert "wine_mp_restore" in items
    assert "wine_mp_restore" not in gravity


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
        _without("bun_hp_restore"),  # missing Consumable effect
        _without("wine_mp_restore"),  # missing Consumable effect
        _without("spacesuit_defense"),  # missing Equipment value
        _without("consume_flash_duration"),  # missing juice number
        _with(0, "bun_hp_restore"),  # a no-op Consumable is a config bug
        _with(-5.0, "wine_mp_restore"),  # restore strictly positive
        _with(-1.0, "spacesuit_defense"),  # defense non-negative (0 is legal)
        _with(0, "consume_flash_duration"),  # tween strictly positive
        _with([0.4, 0.95, 0.45], "bun_flash_color"),  # color: too few components
        _with([0.45, 0.6, 1.5, 1.0], "wine_flash_color"),  # color: out of 0..1
        _with("armored", "spacesuit_defense"),  # wrong type
        {**_valid_config(), "extra": 1},  # unexpected extra top-level key
    ],
)
def test_invalid_json_rejected(bad: dict) -> None:
    """An items config that violates the schema raises jsonschema.ValidationError."""
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_config(bad, _items_schema())


def test_zero_defense_suit_is_legal() -> None:
    """A purely cosmetic (0-defense) Spacesuit is legal config — the bound is
    non-negative, not strictly positive (unlike the restores)."""
    config = _with(0.0, "spacesuit_defense")
    assert build_config.validate_config(config, _items_schema()) is config


# ---------------------------------------------------------------------------
# Round-trip: the derived items .tres loads back through gda with its
# declared Godot types, compared to the AUTHORITATIVE JSON (never hardcoded).
# ---------------------------------------------------------------------------


def _properties_by_name(get_result: dict) -> dict:
    """Index a ``gda resource get`` result's ``properties`` list by name."""
    return {p["name"]: p["value"] for p in get_result["properties"]}


@pytest.mark.engine
def test_items_config_round_trips(gda) -> None:
    """The ItemsConfig .tres round-trips every field through gda."""
    config = build_config.load_json(ITEMS_JSON_PATH)
    result = gda("resource", "get", f"res://{ITEMS_TRES_REL}", "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    props = _properties_by_name(json.loads(result.stdout))

    # Colors are float32 in Godot — compare with a tolerance.
    for color_field in ("bun_flash_color", "wine_flash_color"):
        assert props[color_field] == pytest.approx(config[color_field], abs=1e-5)
    # Scalar float fields.
    for float_field in (
        "bun_hp_restore",
        "wine_mp_restore",
        "spacesuit_defense",
        "consume_flash_duration",
    ):
        assert props[float_field] == pytest.approx(config[float_field])
