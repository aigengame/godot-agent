"""Data seam (a) for S2 Laser Gun combat.

Proves the JSON -> Resource pipeline (gADR-0000) for the S2 combat config: the
authoritative ``combat_config.json`` validates against its schema, bad config is
rejected, and the builder emits three derived ``.tres`` (two ``StatsConfig`` stat
blocks + one ``CombatConfig``) whose fields round-trip back through gda with
their declared Godot types. The freshness gate is parametrized over EVERY builder
output — including the untouched S1 ``player_config.tres``, so it doubles as the
byte-identity guard on the multi-resource builder generalization. Fast tier —
never ``e2e``; the round-trip drives one-shot ``gda`` headless ops under the
``engine`` gate.
"""

from __future__ import annotations

import copy
import json

import jsonschema
import pytest

import build_config


def _valid_config() -> dict:
    """A fresh copy of a schema-valid combat config to mutate into invalid variants."""
    return {
        "player_stats": {
            "max_hp": 100.0,
            "max_mp": 50.0,
            "attack": 10.0,
            "defense": 0.0,
        },
        "enemy_stats": {"max_hp": 25.0, "max_mp": 0.0, "attack": 5.0, "defense": 0.0},
        "attack_scale": 1.0,
        "defense_scale": 1.0,
        "min_damage": 1.0,
        "iframe_duration": 0.6,
        "projectile_color": [1.0, 0.35, 0.25, 1.0],
        "projectile_speed": 900.0,
        "projectile_lifetime": 1.5,
        "projectile_spawn_offset": [36.0, 0.0],
        "hit_flash_color": [1.0, 1.0, 1.0, 1.0],
        "hit_flash_duration": 0.12,
    }


def _combat_schema() -> dict:
    return build_config.load_schema(build_config.COMBAT_SCHEMA_PATH)


def test_sample_json_passes_schema() -> None:
    """The authoritative combat config validates against its schema."""
    config = build_config.load_json(build_config.COMBAT_JSON_PATH)
    assert build_config.validate_config(config, _combat_schema()) is config


def _without(*path: str) -> dict:
    bad = copy.deepcopy(_valid_config())
    node = bad
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    return bad


def _with(value: object, *path: str) -> dict:
    bad = copy.deepcopy(_valid_config())
    node = bad
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return bad


@pytest.mark.parametrize(
    "bad",
    [
        _without("player_stats"),  # missing stat block
        _without("iframe_duration"),  # missing required scalar
        _without("player_stats", "max_hp"),  # stat block missing a field
        _with(0, "player_stats", "max_hp"),  # max_hp must be strictly positive
        _with(-1.0, "enemy_stats", "defense"),  # defense must be non-negative
        _with(-0.5, "player_stats", "attack"),  # attack must be non-negative
        _with(
            {**_valid_config()["player_stats"], "extra": 1}, "player_stats"
        ),  # extra key in block
        _with(0, "attack_scale"),  # attack_scale strictly positive
        _with(-1.0, "min_damage"),  # min_damage non-negative
        _with(0, "iframe_duration"),  # i-frame window strictly positive
        _with(0, "projectile_speed"),  # speed strictly positive
        _with(0, "hit_flash_duration"),  # flash duration strictly positive
        _with([1.0, 0.35, 0.25], "projectile_color"),  # color: too few components
        _with([18.0, 6.0], "projectile_size"),  # size lives in scale_spec (gADR-0013)
        _with([1.0, 2.0, 3.0], "projectile_spawn_offset"),  # offset: too many
        _with("fast", "projectile_speed"),  # wrong type
        {**_valid_config(), "extra": 1},  # unexpected extra top-level key
    ],
)
def test_invalid_json_rejected(bad: dict) -> None:
    """A combat config that violates the schema raises jsonschema.ValidationError."""
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_config(bad, _combat_schema())


# ---------------------------------------------------------------------------
# Freshness gate — parametrized over EVERY builder output (gADR-0000: the
# committed .tres are derived artifacts; drift from the authoritative JSON is
# caught here on every PR, pure-Python tier). Covering player_config.tres too
# makes this the byte-identity guard on the builder's multi-resource refactor.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec", build_config.SPECS, ids=lambda spec: spec.out_rel)
def test_generated_resource_is_fresh(spec, tmp_path) -> None:
    """Each COMMITTED .tres matches a fresh build — JSON stays authoritative."""
    committed = build_config.GAME_DIR / spec.out_rel
    assert committed.exists(), (
        f"committed {spec.out_rel} is missing — run scripts/build_config.py"
    )
    fresh = build_config.build_spec(spec, out_path=tmp_path / committed.name)
    assert fresh.read_text(encoding="utf-8") == committed.read_text(encoding="utf-8"), (
        f"committed {spec.out_rel} is stale — run scripts/build_config.py"
    )


def test_build_all_writes_every_spec(tmp_path) -> None:
    """build_all(root) emits every declared output under the given root."""
    # Stage the authoritative inputs in an isolated root (the e2e project-copy
    # shape: json+schema present, generated/ absent). The Asset manifest + its
    # recorded assets are staged too — build_all enforces the manifest gate
    # (validate_asset_refs, gADR-0014).
    for rel in {s.json_rel for s in build_config.SPECS} | {
        s.schema_rel for s in build_config.SPECS
    }:
        src = build_config.GAME_DIR / rel
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    for rel in build_config.asset_input_rels():
        src = build_config.GAME_DIR / rel
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())

    written = build_config.build_all(root=tmp_path)

    assert sorted(p.name for p in written) == sorted(
        (build_config.GAME_DIR / s.out_rel).name for s in build_config.SPECS
    )
    for path in written:
        assert path.exists() and path.read_text(encoding="utf-8").startswith(
            "[gd_resource"
        )


# ---------------------------------------------------------------------------
# Round-trip: each derived combat .tres loads back through gda with its declared
# Godot types, compared to the AUTHORITATIVE JSON (never hardcoded values).
# ---------------------------------------------------------------------------


def _properties_by_name(get_result: dict) -> dict:
    """Index a ``gda resource get`` result's ``properties`` list by name."""
    return {p["name"]: p["value"] for p in get_result["properties"]}


def _get_props(gda, res_path: str) -> dict:
    result = gda("resource", "get", res_path, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    return _properties_by_name(json.loads(result.stdout))


@pytest.mark.engine
@pytest.mark.parametrize("block", ["player_stats", "enemy_stats"])
def test_stat_block_round_trips(gda, block: str) -> None:
    """Each StatsConfig .tres round-trips its four stat fields through gda."""
    config = build_config.load_json(build_config.COMBAT_JSON_PATH)[block]
    res_path = f"res://content/data/generated/stats_{block.removesuffix('_stats')}.tres"
    props = _get_props(gda, res_path)
    for field in ("max_hp", "max_mp", "attack", "defense"):
        assert props[field] == pytest.approx(config[field]), (block, field)


@pytest.mark.engine
def test_combat_config_round_trips(gda) -> None:
    """The CombatConfig .tres round-trips every field through gda.

    Compared to the COMPOSED authority: projectile_size is authored in
    scale_spec.json (gADR-0013) and composed into the derived CombatConfig.
    """
    config = build_config.load_composed("content/data/json/combat_config.json")
    props = _get_props(gda, "res://content/data/generated/combat_config.tres")

    # Colors are float32 in Godot — compare with a tolerance.
    for color_field in ("projectile_color", "hit_flash_color"):
        assert props[color_field] == pytest.approx(config[color_field], abs=1e-5)
    # Vector2 fields.
    for vec_field in (
        "projectile_size",
        "projectile_spawn_offset",
    ):
        assert props[vec_field] == pytest.approx(config[vec_field])
    # Scalar float fields.
    for float_field in (
        "attack_scale",
        "defense_scale",
        "min_damage",
        "iframe_duration",
        "projectile_speed",
        "projectile_lifetime",
        "hit_flash_duration",
    ):
        assert props[float_field] == pytest.approx(config[float_field])
