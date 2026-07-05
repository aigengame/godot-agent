"""Data seam (a) for S6b Leveling curve + drop tables (gADR-0006).

Proves the JSON -> Resource pipeline (gADR-0000) for the S6b config surfaces:
the authoritative ``progression_config.json`` (the leveling curve, the pickup
blockout styles, and the drop/level-up juice) validates against its schema and
bad config is rejected; the strictly-increasing-curve rule the schema cannot
express is enforced by ``build_config.validate_progression_semantics`` and
gates the build; the per-Tier ``drops`` tables in ``enemies_config.json``
validate (and bad drop entries are rejected); the builder RESOLVES each
Tier's ``drops`` into a per-kind derived ``drop_table`` field (the runtime
reads dumb fields, the authority stays per-Tier — the gADR-0004 reward
resolution extended); retuning a Tier's drops is one JSON edit; and the
derived ``ProgressionConfig``/per-kind ``.tres`` round-trip through gda with
their declared Godot types. Freshness of ``progression_config.tres`` and of
the ``drop_table`` inside every ``enemy_<kind>.tres`` is covered by
``test_combat_data_seam.py``'s SPECS-parametrized gate. Fast tier — never
``e2e``; the round-trips drive one-shot ``gda`` headless ops under the
``engine`` gate.
"""

from __future__ import annotations

import copy
import json

import jsonschema
import pytest

import build_config

PROGRESSION_JSON_PATH = build_config.GAME_DIR / "data/json/progression_config.json"
PROGRESSION_SCHEMA_PATH = (
    build_config.GAME_DIR / "data/schema/progression_config.schema.json"
)

# The kind names, derived from the authoritative JSON (never a static list).
_KIND_NAMES: list[str] = list(
    build_config.load_json(build_config.ENEMIES_JSON_PATH)["kinds"]
)


def _progression_config() -> dict:
    """A fresh copy of the authoritative progression config to mutate."""
    return copy.deepcopy(build_config.load_json(PROGRESSION_JSON_PATH))


def _progression_schema() -> dict:
    return build_config.load_schema(PROGRESSION_SCHEMA_PATH)


def _enemies_config() -> dict:
    return copy.deepcopy(build_config.load_json(build_config.ENEMIES_JSON_PATH))


def _enemies_schema() -> dict:
    return build_config.load_schema(build_config.ENEMIES_SCHEMA_PATH)


# ---------------------------------------------------------------------------
# The progression source: schema shape + the strictly-increasing-curve rule.
# ---------------------------------------------------------------------------


def test_authoritative_progression_config_validates() -> None:
    """The shipped progression config passes its schema AND its semantics."""
    config = build_config.load_json(PROGRESSION_JSON_PATH)
    assert build_config.validate_config(config, _progression_schema()) is config
    assert build_config.validate_progression_semantics(config) is config


def test_every_shipped_drop_item_has_a_pickup_style() -> None:
    """Coverage by construction (gADR-0006): the schema requires a style for
    the whole item vocabulary, so every item any Tier's drops reference is
    styled — asserted on the SHIPPED data so the two sources cannot drift."""
    progression = build_config.load_json(PROGRESSION_JSON_PATH)
    enemies = build_config.load_json(build_config.ENEMIES_JSON_PATH)
    dropped = {
        entry["item"] for tier in enemies["tiers"].values() for entry in tier["drops"]
    }
    assert dropped <= set(progression["drop_items"])


def _prog_without(*path: str) -> dict:
    bad = _progression_config()
    node = bad
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    return bad


def _prog_with(value: object, *path: str) -> dict:
    bad = _progression_config()
    node = bad
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return bad


@pytest.mark.parametrize(
    "bad",
    [
        _prog_without("level_curve"),  # the curve is required
        _prog_with([], "level_curve"),  # at least one threshold
        _prog_with([0.0], "level_curve"),  # thresholds strictly positive
        _prog_with([10.0, "lots"], "level_curve"),  # wrong entry type
        _prog_without("drop_items"),  # the pickup styles are required
        _prog_without("drop_items", "wine"),  # the whole item vocabulary is styled
        _prog_without("drop_items", "gold", "size"),  # a style needs its size
        _prog_with([1.0, 0.9], "level_up_flash_color"),  # color: 4 components
        _prog_with(0, "pickup_spacing"),  # spacing strictly positive
        _prog_with(0, "pickup_spawn_tween_duration"),  # duration strictly positive
        _prog_with([0.0, 0.3], "pickup_spawn_squash"),  # squash strictly positive
        _prog_with(
            {"color": [1, 1, 1, 1], "size": [10.0, 10.0], "extra": 1},
            "drop_items",
            "bun",
        ),  # extra key in a style
        {**_progression_config(), "extra": 1},  # unexpected extra top-level key
    ],
)
def test_invalid_progression_json_rejected(bad: dict) -> None:
    """A progression config violating the schema raises ValidationError."""
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_config(bad, _progression_schema())


@pytest.mark.parametrize(
    "curve",
    [[10.0, 10.0], [10.0, 50.0, 40.0]],
    ids=["flat-step", "decreasing-step"],
)
def test_non_increasing_curve_rejected_by_semantics(curve: list[float]) -> None:
    """The cross-field rule: a flat/decreasing curve is schema-valid (each
    entry alone is fine) but must be rejected by
    ``validate_progression_semantics`` — proven schema-first so this suite
    would catch the rule silently migrating into the schema."""
    bad = _prog_with(curve, "level_curve")
    build_config.validate_config(bad, _progression_schema())
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_progression_semantics(bad)


def _stage_inputs(root) -> None:
    """Copy every spec's authoritative JSON + schema into an isolated root."""
    for rel in {s.json_rel for s in build_config.SPECS} | {
        s.schema_rel for s in build_config.SPECS
    }:
        src = build_config.GAME_DIR / rel
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def test_non_increasing_curve_gates_the_build(tmp_path) -> None:
    """The curve rule gates the BUILD, not just direct validator calls."""
    _stage_inputs(tmp_path)
    progression_path = tmp_path / "data/json/progression_config.json"
    config = json.loads(progression_path.read_text(encoding="utf-8"))
    config["level_curve"] = [50.0, 50.0]
    progression_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(jsonschema.ValidationError):
        build_config.build_all(root=tmp_path)


# ---------------------------------------------------------------------------
# The per-Tier drops tables: schema shape + resolution into per-kind derived
# drop_table fields (the gADR-0004 reward resolution extended, gADR-0006).
# ---------------------------------------------------------------------------


def _with_drop(value: object, tier: str, *path) -> dict:
    """The enemies config with ``tiers.<tier>.drops[0].<path>`` (or the whole
    ``drops`` when path is empty) replaced by ``value``."""
    bad = _enemies_config()
    node = bad["tiers"][tier]
    keys = ["drops", *path]
    for key in keys[:-1]:
        node = node[key]
    node[keys[-1]] = value
    return bad


def _without_drops(tier: str) -> dict:
    bad = _enemies_config()
    del bad["tiers"][tier]["drops"]
    return bad


@pytest.mark.parametrize(
    "bad",
    [
        _without_drops("minion"),  # every Tier entry carries its drops table
        _with_drop({"item": "gold"}, "minion"),  # drops must be an array
        _with_drop([{"item": "gold", "amount": 3}], "minion"),  # chance required
        _with_drop([{"item": "gold", "chance": 1.0}], "minion"),  # amount required
        _with_drop([{"amount": 3, "chance": 1.0}], "minion"),  # item required
        _with_drop(
            [{"item": "diamond", "amount": 1, "chance": 1.0}], "minion"
        ),  # off-vocabulary item
        _with_drop(
            [{"item": "gold", "amount": 0, "chance": 1.0}], "minion"
        ),  # amount at least 1
        _with_drop(
            [{"item": "gold", "amount": 1.5, "chance": 1.0}], "minion"
        ),  # amount a whole number
        _with_drop(
            [{"item": "gold", "amount": 3, "chance": 0.0}], "minion"
        ),  # a 0 chance is dead config
        _with_drop(
            [{"item": "gold", "amount": 3, "chance": 1.1}], "minion"
        ),  # chance at most 1
        _with_drop(
            [{"item": "gold", "amount": 3, "chance": 1.0, "extra": 1}], "minion"
        ),  # extra key in an entry
    ],
)
def test_invalid_drop_table_rejected(bad: dict) -> None:
    """A ``drops`` table violating the schema raises ValidationError."""
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_config(bad, _enemies_schema())


def test_empty_drops_table_is_legal() -> None:
    """A Tier that drops nothing is valid config (the entries roll
    independently; an empty table simply resolves to no drops)."""
    config = _with_drop([], "minion")
    assert build_config.validate_config(config, _enemies_schema()) is config
    assert build_config.validate_enemies_semantics(config) is config


def test_resolve_enemy_rewards_carries_the_tier_drops() -> None:
    """Every kind gains a drop_table equal to its Tier's drops entry."""
    config = build_config.load_json(build_config.ENEMIES_JSON_PATH)
    resolved = build_config.resolve_enemy_rewards(config)
    for name, kind in resolved["kinds"].items():
        assert kind["drop_table"] == config["tiers"][kind["tier"]]["drops"], name
    # The source document is untouched (the resolver returns a copy).
    assert "drop_table" not in config["kinds"][_KIND_NAMES[0]]


def test_retuning_a_tier_drops_is_one_json_edit(tmp_path) -> None:
    """Changing one Tier's drops re-derives every kind of that Tier.

    The drop AUTHORITY is per-Tier (gADR-0006, the gADR-0004 rule): edit
    ``tiers.minion.drops`` alone and the rebuilt minion ``.tres`` carries the
    new table — no per-kind edit, no Python edit.
    """
    _stage_inputs(tmp_path)
    enemies_path = tmp_path / "data/json/enemies_config.json"
    config = json.loads(enemies_path.read_text(encoding="utf-8"))
    config["tiers"]["minion"]["drops"] = [{"item": "wine", "amount": 7, "chance": 0.75}]
    enemies_path.write_text(json.dumps(config), encoding="utf-8")

    build_config.build_all(root=tmp_path)

    minion_tres = (
        tmp_path / "data/generated/enemy_monster_minion_melee.tres"
    ).read_text(encoding="utf-8")
    assert 'drop_table = [{"item": "wine", "amount": 7, "chance": 0.75}]' in minion_tres


# ---------------------------------------------------------------------------
# Round-trip: the derived ProgressionConfig .tres and the per-kind drop_table
# load back through gda with their declared Godot types, compared to the
# AUTHORITATIVE JSON (never hardcoded values).
# ---------------------------------------------------------------------------


def _get_props(gda, res_path: str) -> dict:
    result = gda("resource", "get", res_path, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    return {p["name"]: p["value"] for p in json.loads(result.stdout)["properties"]}


@pytest.mark.engine
def test_progression_config_round_trips(gda) -> None:
    """The ProgressionConfig .tres round-trips every field through gda.

    gda projects the nested values as structured JSON (ADR-0035): the curve
    as a number array, each pickup style with its color/size projections —
    all matching the authoritative JSON.
    """
    config = build_config.load_json(PROGRESSION_JSON_PATH)
    props = _get_props(gda, "res://data/generated/progression_config.tres")
    assert props["level_curve"] == pytest.approx(config["level_curve"])
    assert props["level_up_flash_color"] == pytest.approx(
        config["level_up_flash_color"]
    )
    assert props["level_up_flash_duration"] == pytest.approx(
        config["level_up_flash_duration"]
    )
    assert props["pickup_spacing"] == pytest.approx(config["pickup_spacing"])
    assert props["pickup_spawn_squash"] == pytest.approx(config["pickup_spawn_squash"])
    assert props["pickup_spawn_tween_duration"] == pytest.approx(
        config["pickup_spawn_tween_duration"]
    )
    assert props["pickup_collect_tween_duration"] == pytest.approx(
        config["pickup_collect_tween_duration"]
    )
    assert set(props["drop_items"]) == set(config["drop_items"])
    for item, style in config["drop_items"].items():
        got = props["drop_items"][item]
        assert got["color"] == pytest.approx(style["color"]), item
        assert got["size"] == pytest.approx(style["size"]), item


@pytest.mark.engine
@pytest.mark.parametrize("kind", _KIND_NAMES)
def test_kind_drop_table_round_trips(gda, kind: str) -> None:
    """Each EnemyConfig .tres round-trips its Tier-resolved drop_table."""
    config = build_config.load_json(build_config.ENEMIES_JSON_PATH)
    drops = config["tiers"][config["kinds"][kind]["tier"]]["drops"]
    props = _get_props(gda, f"res://data/generated/enemy_{kind}.tres")
    got = props["drop_table"]
    assert len(got) == len(drops), kind
    for got_entry, expected in zip(got, drops):
        assert got_entry["item"] == expected["item"]
        assert got_entry["amount"] == expected["amount"]
        assert got_entry["chance"] == pytest.approx(expected["chance"])
