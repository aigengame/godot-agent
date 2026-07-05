"""Data seam (a) for S8's Boss Warp kit (gADR-0009).

Proves the JSON -> Resource pipeline for the Warp ability params: the
authoritative ``alien_boss_tank`` kind carries the full ``warp_*`` /
``time_field_*`` block, the block is PRESENCE-GATED per kind (all-or-none —
a partial block is rejected; a full block is valid on ANY kind, keyed to
neither Tier nor Archetype: the ``projectile_*`` precedent, gADR-0009),
out-of-range values are rejected (the time factor must actually slow:
strictly inside (0, 1)), the engage-tool invariant is a cross-field rule
(``warp_trigger_range`` must not undercut ``attack_range`` — the Boss never
warps inside a brawl), and the derived ``EnemyConfig`` .tres round-trips the
warp fields back through gda. Fast tier — never ``e2e``; the round-trip
drives one-shot ``gda`` headless ops under the ``engine`` gate.
"""

from __future__ import annotations

import copy
import json

import jsonschema
import pytest

import build_config

_BOSS = ("kinds", "alien_boss_tank")

# The presence-gated Warp block (gADR-0009): every key, in the field order the
# builder renders. Derived tests parametrize over this list so a new warp
# param automatically joins every all-or-none and round-trip case.
_WARP_KEYS: list[str] = [
    "warp_cooldown",
    "warp_trigger_range",
    "warp_offset",
    "warp_tell_duration",
    "warp_recovery_duration",
    "time_field_radius",
    "time_field_factor",
    "time_field_duration",
]

_WARP_SCALAR_KEYS = [k for k in _WARP_KEYS if k != "warp_offset"]


def _valid_config() -> dict:
    return copy.deepcopy(build_config.load_json(build_config.ENEMIES_JSON_PATH))


def _enemies_schema() -> dict:
    return build_config.load_schema(build_config.ENEMIES_SCHEMA_PATH)


def _with(value: object, *path) -> dict:
    bad = _valid_config()
    node = bad
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return bad


def _without(*path: str) -> dict:
    bad = _valid_config()
    node = bad
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    return bad


def test_boss_kind_carries_the_full_warp_block() -> None:
    """The authoritative Boss kind is a Warp kind: every warp param present."""
    boss = build_config.load_json(build_config.ENEMIES_JSON_PATH)["kinds"][
        "alien_boss_tank"
    ]
    for key in _WARP_KEYS:
        assert key in boss, key


def test_warp_block_is_valid_on_any_kind() -> None:
    """The Warp block is presence-gated, keyed to NEITHER Tier nor Archetype.

    Copying the Boss's full block onto a melee minion stays schema- AND
    semantics-valid (gADR-0009: no fourth axis, no "Boss implies Warp" rule).
    """
    config = _valid_config()
    boss = config["kinds"]["alien_boss_tank"]
    minion = config["kinds"]["monster_minion_melee"]
    for key in _WARP_KEYS:
        minion[key] = copy.deepcopy(boss[key])
    build_config.validate_config(config, _enemies_schema())
    build_config.validate_enemies_semantics(config)


@pytest.mark.parametrize("missing", _WARP_KEYS)
def test_partial_warp_block_rejected(missing: str) -> None:
    """All-or-none: a Warp kind missing ANY single warp param is rejected."""
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_config(_without(*_BOSS, missing), _enemies_schema())


@pytest.mark.parametrize(
    "bad",
    [
        _with(0, *_BOSS, "warp_cooldown"),  # cooldown strictly positive
        _with(0, *_BOSS, "warp_trigger_range"),  # trigger range strictly positive
        _with(0, *_BOSS, "warp_tell_duration"),  # a warp always telegraphs
        _with(-0.1, *_BOSS, "warp_recovery_duration"),  # recovery non-negative
        _with([60.0], *_BOSS, "warp_offset"),  # offset: too few components
        _with(0, *_BOSS, "time_field_radius"),  # radius strictly positive
        _with(0, *_BOSS, "time_field_factor"),  # factor 0 would freeze, not slow
        _with(1.0, *_BOSS, "time_field_factor"),  # factor 1 is dead config
        _with(1.5, *_BOSS, "time_field_factor"),  # the field never accelerates
        _with(0, *_BOSS, "time_field_duration"),  # duration strictly positive
    ],
)
def test_out_of_range_warp_values_rejected(bad: dict) -> None:
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_config(bad, _enemies_schema())


def test_trigger_range_must_not_undercut_attack_range() -> None:
    """The engage-tool invariant (gADR-0009): never warp inside a brawl.

    ``warp_trigger_range < attack_range`` would let the Boss warp away from
    point-blank trades — schema-valid, rejected by the cross-field rule.
    """
    boss = _valid_config()["kinds"]["alien_boss_tank"]
    bad = _with(boss["attack_range"] - 1.0, *_BOSS, "warp_trigger_range")
    build_config.validate_config(bad, _enemies_schema())
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_enemies_semantics(bad)


@pytest.mark.engine
def test_boss_warp_fields_round_trip(gda) -> None:
    """The derived Boss EnemyConfig .tres round-trips its Warp block via gda."""
    config = build_config.load_json(build_config.ENEMIES_JSON_PATH)["kinds"][
        "alien_boss_tank"
    ]
    result = gda(
        "resource", "get", "res://data/generated/enemy_alien_boss_tank.tres", "--json"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    props = {p["name"]: p["value"] for p in json.loads(result.stdout)["properties"]}
    for key in _WARP_SCALAR_KEYS:
        assert props[key] == pytest.approx(config[key]), key
    assert props["warp_offset"] == pytest.approx(config["warp_offset"])
