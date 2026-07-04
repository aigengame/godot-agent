"""Data seam (a) for S6a Kill reward (EXP/Gold per Tier) + HUD.

Proves the JSON -> Resource pipeline (gADR-0000) for the S6a config surfaces
(gADR-0004): the authoritative per-Tier ``tiers`` reward table in
``enemies_config.json`` validates against its schema and bad reward config is
rejected; the Tier->reward coverage rule the schema cannot express (every Tier
a kind uses must have a reward entry) is enforced by
``build_config.validate_enemies_semantics`` and gates the build; the builder
RESOLVES the per-Tier table into per-kind derived ``exp_reward``/``gold_reward``
fields (the runtime reads dumb fields, the authority stays per-Tier); the
shipped reward budgets actually scale by Tier (the GDD's "Tier sets an enemy's
reward budget"); and the new ``hud_config.json`` validates, rejects bad config,
and round-trips through gda with its declared Godot types. Freshness of the
committed ``hud_config.tres`` and of the reward fields inside every
``enemy_<kind>.tres`` is covered by ``test_combat_data_seam.py``'s
SPECS-parametrized gate. Fast tier — never ``e2e``; the round-trips drive
one-shot ``gda`` headless ops under the ``engine`` gate.
"""

from __future__ import annotations

import copy
import json

import jsonschema
import pytest

import build_config

HUD_JSON_PATH = build_config.GAME_DIR / "data/json/hud_config.json"
HUD_SCHEMA_PATH = build_config.GAME_DIR / "data/schema/hud_config.schema.json"

# The kind names, derived from the authoritative JSON (never a static list).
_KIND_NAMES: list[str] = list(
    build_config.load_json(build_config.ENEMIES_JSON_PATH)["kinds"]
)


def _enemies_config() -> dict:
    """A fresh copy of the authoritative enemies config to mutate."""
    return copy.deepcopy(build_config.load_json(build_config.ENEMIES_JSON_PATH))


def _enemies_schema() -> dict:
    return build_config.load_schema(build_config.ENEMIES_SCHEMA_PATH)


def _hud_config() -> dict:
    return copy.deepcopy(build_config.load_json(HUD_JSON_PATH))


def _hud_schema() -> dict:
    return build_config.load_schema(HUD_SCHEMA_PATH)


# ---------------------------------------------------------------------------
# The per-Tier reward table: schema shape + the coverage rule + Tier scaling.
# ---------------------------------------------------------------------------


def test_authoritative_config_carries_a_reward_for_every_used_tier() -> None:
    """The shipped config passes schema + semantics with its ``tiers`` table."""
    config = build_config.load_json(build_config.ENEMIES_JSON_PATH)
    assert build_config.validate_config(config, _enemies_schema()) is config
    assert build_config.validate_enemies_semantics(config) is config
    used = {kind["tier"] for kind in config["kinds"].values()}
    assert used <= set(config["tiers"]), "a used Tier is missing its reward entry"


def test_shipped_rewards_scale_by_tier() -> None:
    """Tier sets the reward budget (GDD): tougher Tiers award strictly more.

    An intent guard on the SHIPPED numbers, not a validator rule — balancing
    may retune values freely, but a config where a Boss kill pays less than a
    Minion kill would silently invert the risk->reward story of gADR-0004.
    """
    tiers = build_config.load_json(build_config.ENEMIES_JSON_PATH)["tiers"]
    for field in ("exp_reward", "gold_reward"):
        assert tiers["minion"][field] < tiers["elite"][field] < tiers["boss"][field], (
            field
        )


def _without_tiers(*path: str) -> dict:
    bad = _enemies_config()
    node = bad
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    return bad


def _with_tiers(value: object, *path: str) -> dict:
    bad = _enemies_config()
    node = bad
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return bad


@pytest.mark.parametrize(
    "bad",
    [
        _without_tiers("tiers"),  # the reward table is required
        _with_tiers({}, "tiers"),  # at least one Tier entry required
        _without_tiers("tiers", "minion", "exp_reward"),  # entry missing a field
        _without_tiers("tiers", "minion", "gold_reward"),  # entry missing a field
        _with_tiers(-1.0, "tiers", "minion", "exp_reward"),  # reward non-negative
        _with_tiers(-0.5, "tiers", "boss", "gold_reward"),  # reward non-negative
        _with_tiers("lots", "tiers", "elite", "exp_reward"),  # wrong type
        _with_tiers(
            {"exp_reward": 1.0, "gold_reward": 1.0, "extra": 1}, "tiers", "minion"
        ),  # extra key in a reward entry
        _with_tiers(
            {"mini_boss": {"exp_reward": 1.0, "gold_reward": 1.0}}, "tiers"
        ),  # off-taxonomy Tier name
    ],
)
def test_invalid_reward_table_rejected(bad: dict) -> None:
    """A ``tiers`` table that violates the schema raises ValidationError."""
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_config(bad, _enemies_schema())


def test_used_tier_without_reward_entry_rejected() -> None:
    """The coverage rule: a kind's Tier absent from ``tiers`` fails semantics.

    Dropping ``boss`` while ``alien_boss_tank`` uses it is schema-valid (the
    table may be a subset) but must be rejected by
    ``validate_enemies_semantics`` — proven schema-first so this suite would
    catch the rule silently migrating into the schema.
    """
    bad = _enemies_config()
    del bad["tiers"]["boss"]
    build_config.validate_config(bad, _enemies_schema())
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_enemies_semantics(bad)


def _stage_inputs(root) -> None:
    """Copy every spec's authoritative JSON + schema into an isolated root."""
    for rel in {s.json_rel for s in build_config.SPECS} | {
        s.schema_rel for s in build_config.SPECS
    }:
        src = build_config.GAME_DIR / rel
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def test_missing_tier_reward_gates_the_build(tmp_path) -> None:
    """The coverage rule gates the BUILD, not just direct validator calls."""
    _stage_inputs(tmp_path)
    enemies_path = tmp_path / "data/json/enemies_config.json"
    config = json.loads(enemies_path.read_text(encoding="utf-8"))
    del config["tiers"]["boss"]  # alien_boss_tank still uses it
    enemies_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(jsonschema.ValidationError):
        build_config.build_all(root=tmp_path)


# ---------------------------------------------------------------------------
# Resolution: the builder derives per-kind reward fields FROM the per-Tier
# table — one edit retunes every kind of that Tier.
# ---------------------------------------------------------------------------


def test_resolve_enemy_rewards_reads_the_kind_tier() -> None:
    """Every kind gains exp_reward/gold_reward equal to its Tier's entry."""
    config = build_config.load_json(build_config.ENEMIES_JSON_PATH)
    resolved = build_config.resolve_enemy_rewards(config)
    for name, kind in resolved["kinds"].items():
        reward = config["tiers"][kind["tier"]]
        assert kind["exp_reward"] == reward["exp_reward"], name
        assert kind["gold_reward"] == reward["gold_reward"], name
    # The source document is untouched (the resolver returns a copy).
    assert "exp_reward" not in config["kinds"][_KIND_NAMES[0]]


def test_retuning_a_tier_is_one_json_edit(tmp_path) -> None:
    """Changing one Tier's budget re-derives every kind of that Tier.

    The reward AUTHORITY is per-Tier (gADR-0004): edit ``tiers.minion`` alone
    and the rebuilt minion ``.tres`` carries the new numbers — no per-kind
    edit, no Python edit.
    """
    _stage_inputs(tmp_path)
    enemies_path = tmp_path / "data/json/enemies_config.json"
    config = json.loads(enemies_path.read_text(encoding="utf-8"))
    config["tiers"]["minion"] = {"exp_reward": 77.0, "gold_reward": 33.0}
    enemies_path.write_text(json.dumps(config), encoding="utf-8")

    build_config.build_all(root=tmp_path)

    minion_tres = (
        tmp_path / "data/generated/enemy_monster_minion_melee.tres"
    ).read_text(encoding="utf-8")
    assert "exp_reward = 77" in minion_tres
    assert "gold_reward = 33" in minion_tres


# ---------------------------------------------------------------------------
# Round-trip: the derived reward fields and the HudConfig .tres load back
# through gda with their declared Godot types, compared to the AUTHORITATIVE
# JSON (never hardcoded values).
# ---------------------------------------------------------------------------


def _properties_by_name(get_result: dict) -> dict:
    """Index a ``gda resource get`` result's ``properties`` list by name."""
    return {p["name"]: p["value"] for p in get_result["properties"]}


def _get_props(gda, res_path: str) -> dict:
    result = gda("resource", "get", res_path, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    return _properties_by_name(json.loads(result.stdout))


@pytest.mark.engine
@pytest.mark.parametrize("kind", _KIND_NAMES)
def test_kind_reward_fields_round_trip(gda, kind: str) -> None:
    """Each EnemyConfig .tres round-trips its Tier-resolved reward fields."""
    config = build_config.load_json(build_config.ENEMIES_JSON_PATH)
    reward = config["tiers"][config["kinds"][kind]["tier"]]
    props = _get_props(gda, f"res://data/generated/enemy_{kind}.tres")
    assert props["exp_reward"] == pytest.approx(reward["exp_reward"]), kind
    assert props["gold_reward"] == pytest.approx(reward["gold_reward"]), kind


def test_hud_sample_json_passes_schema() -> None:
    """The authoritative HUD config validates against its schema."""
    config = build_config.load_json(HUD_JSON_PATH)
    assert build_config.validate_config(config, _hud_schema()) is config


def _hud_without(key: str) -> dict:
    bad = _hud_config()
    del bad[key]
    return bad


def _hud_with(value: object, key: str) -> dict:
    bad = _hud_config()
    bad[key] = value
    return bad


@pytest.mark.parametrize(
    "bad",
    [
        _hud_without("margin"),  # missing placement
        _hud_without("value_tween_duration"),  # missing tween duration
        _hud_with([-1.0, 24.0], "margin"),  # margin components non-negative
        _hud_with([24.0], "margin"),  # margin: too few components
        _hud_with([0.0, 1.25], "value_punch_scale"),  # punch strictly positive
        _hud_with(0, "value_tween_duration"),  # duration strictly positive
        _hud_with("fast", "value_tween_duration"),  # wrong type
        {**_hud_config(), "extra": 1},  # unexpected extra top-level key
    ],
)
def test_invalid_hud_json_rejected(bad: dict) -> None:
    """A HUD config that violates the schema raises jsonschema.ValidationError."""
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_config(bad, _hud_schema())


@pytest.mark.engine
def test_hud_config_round_trips(gda) -> None:
    """The HudConfig .tres round-trips every field through gda."""
    config = build_config.load_json(HUD_JSON_PATH)
    props = _get_props(gda, "res://data/generated/hud_config.tres")
    for vec_field in ("margin", "value_punch_scale"):
        assert props[vec_field] == pytest.approx(config[vec_field])
    assert props["value_tween_duration"] == pytest.approx(
        config["value_tween_duration"]
    )
