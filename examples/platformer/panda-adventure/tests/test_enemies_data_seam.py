"""Data seam (a) for S4 enemy taxonomy + Archetype AI.

Proves the JSON -> Resource pipeline (gADR-0000) for the S4 enemies config: the
authoritative ``enemies_config.json`` validates against its schema, bad config
is rejected (axis enums, stat-block signs, the ranged-kind projectile
requirement, malformed Spawn Roster entries — expressed through the ``waves``
paths since S5/gADR-0005 replaced the top-level roster with the Wave
schedule), the cross-field rules JSON Schema cannot express are enforced by
``build_config.validate_enemies_semantics`` (the Steering Band interval, the
melee contact-damage bound, spawn->kind referential integrity, spawn-name
uniqueness — gADR-0003/gADR-0005) and wired into the build, adding an Enemy
Kind is a JSON-only change (the per-kind specs derive from the JSON), and the
derived per-kind ``EnemyConfig`` .tres round-trips back through gda with its
declared Godot types (the Wave schedule's own seam is
``test_waves_data_seam.py``). Freshness of every committed .tres (including
the enemy outputs, whose specs derive from the JSON's ``kinds``) is covered by
``test_combat_data_seam.py``'s SPECS-parametrized gate. Fast tier — never
``e2e``; the round-trip drives one-shot ``gda`` headless ops under the
``engine`` gate.
"""

from __future__ import annotations

import copy
import json

import jsonschema
import pytest

import build_config

# The kind names, derived from the authoritative JSON (never a static list):
# a new kind automatically joins every parametrized case below.
_KIND_NAMES: list[str] = list(
    build_config.load_json(build_config.ENEMIES_JSON_PATH)["kinds"]
)


def _valid_config() -> dict:
    """A fresh copy of a schema-valid enemies config to mutate into invalid variants."""
    return copy.deepcopy(build_config.load_json(build_config.ENEMIES_JSON_PATH))


def _enemies_schema() -> dict:
    return build_config.load_schema(build_config.ENEMIES_SCHEMA_PATH)


def test_sample_json_passes_schema() -> None:
    """The authoritative enemies config validates against its schema."""
    config = build_config.load_json(build_config.ENEMIES_JSON_PATH)
    assert build_config.validate_config(config, _enemies_schema()) is config


def test_sample_json_passes_semantic_validation() -> None:
    """The authoritative enemies config passes the cross-field rules too.

    ``validate_enemies_semantics`` enforces what the schema cannot express
    (gADR-0003): the Steering Band interval, the melee contact-damage bound,
    spawn->kind referential integrity, and roster-name uniqueness.
    """
    config = build_config.load_json(build_config.ENEMIES_JSON_PATH)
    assert build_config.validate_enemies_semantics(config) is config


def _stage_inputs(root) -> None:
    """Copy every spec's authoritative JSON + schema into an isolated root."""
    for rel in {s.json_rel for s in build_config.SPECS} | {
        s.schema_rel for s in build_config.SPECS
    }:
        src = build_config.GAME_DIR / rel
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def test_adding_a_kind_is_json_only(tmp_path) -> None:
    """A new Enemy Kind is a JSON-only change (gADR-0001/gADR-0003).

    Stage the inputs in an isolated root, add a fourth kind to the JSON alone
    — no Python/spec edit — and the build derives and writes that kind's
    ``.tres``: the per-kind specs (and with them the freshness gate, which
    parametrizes over the same derivation) follow the JSON.
    """
    _stage_inputs(tmp_path)
    enemies_path = tmp_path / "data/json/enemies_config.json"
    config = json.loads(enemies_path.read_text(encoding="utf-8"))
    new_kind = copy.deepcopy(config["kinds"]["monster_minion_melee"])
    new_kind["faction"] = "xenomorph"
    config["kinds"]["xenomorph_minion_melee"] = new_kind
    enemies_path.write_text(json.dumps(config), encoding="utf-8")

    written = build_config.build_all(root=tmp_path)

    new_tres = tmp_path / "data/generated/enemy_xenomorph_minion_melee.tres"
    assert new_tres in written
    assert new_tres.read_text(encoding="utf-8").startswith("[gd_resource")
    assert 'faction = "xenomorph"' in new_tres.read_text(encoding="utf-8")


def test_build_rejects_semantically_invalid_config(tmp_path) -> None:
    """The semantic rules gate the BUILD, not just direct validator calls.

    An inverted Steering Band passes the schema but must fail ``build_all``
    before any resource derives (the validator is wired into ``build_spec``
    for every enemies-sourced output).
    """
    _stage_inputs(tmp_path)
    enemies_path = tmp_path / "data/json/enemies_config.json"
    config = json.loads(enemies_path.read_text(encoding="utf-8"))
    config["kinds"]["monster_minion_melee"]["keep_range_min"] = 99.0
    enemies_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(jsonschema.ValidationError):
        build_config.build_all(root=tmp_path)


def test_default_spawn_matches_legacy_combat_expectations() -> None:
    """The shipped Wave-1 spawn still serves the S2 combat e2e unchanged.

    ``test_combat_e2e.py`` derives its expectations from combat_config.json's
    ``enemy_stats`` block (which STAYS, per the S2 data contract) and the
    Wave-1 spawn position, while the runtime enemy is Wave 1's default kind
    (the S4 boot roster became Wave 1 of the schedule, gADR-0005; the legacy
    duplicated ``enemy_position`` was deleted by the gADR-0013 consolidation
    — the wave schedule is the one position authority). This guard makes any
    drift between the stat sources fail here — fast tier — rather than deep
    inside the live e2e.
    """
    enemies = build_config.load_json(build_config.ENEMIES_JSON_PATH)
    combat = build_config.load_json(build_config.COMBAT_JSON_PATH)
    default = enemies["waves"][0]["spawns"][0]
    kind = enemies["kinds"][default["kind"]]
    assert default["name"] == "Enemy"
    for stat in ("max_hp", "max_mp", "attack", "defense"):
        assert kind[stat] == combat["enemy_stats"][stat], stat
    # Dormant by default: the S2 flows park the Player at player_start's x and
    # never approach, so the default kind must not aggro across that distance
    # (nor its bolt/attack reach it) — AI stays inert during the legacy e2e.
    player = build_config.load_json(build_config.JSON_PATH)
    distance = abs(default["position"][0] - player["player_start"][0])
    assert kind["aggro_range"] < distance
    assert kind["attack_range"] < distance


def _without(*path: str) -> dict:
    bad = _valid_config()
    node = bad
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    return bad


def _with(value: object, *path) -> dict:
    bad = _valid_config()
    node = bad
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return bad


_MELEE = ("kinds", "monster_minion_melee")
_RANGED = ("kinds", "robot_elite_ranged")


def _wave_of(*entries: dict) -> list[dict]:
    """A one-wave ``waves`` value wrapping the given spawn entries (gADR-0005)."""
    return [{"spawns": list(entries)}]


@pytest.mark.parametrize(
    "bad",
    [
        _without("kinds"),  # missing the kind table
        _without("waves"),  # missing the Wave schedule
        _with({}, "kinds"),  # at least one kind required
        _without(*_MELEE, "faction"),  # missing an axis
        _without(*_MELEE, "max_hp"),  # missing a stat-block field
        _without(*_MELEE, "aggro_range"),  # missing an AI param
        _with("goblin", *_MELEE, "faction"),  # off-taxonomy Faction
        _with("mini", *_MELEE, "tier"),  # off-taxonomy Tier
        _with("healer", *_MELEE, "archetype"),  # off-taxonomy Archetype
        _with(0, *_MELEE, "max_hp"),  # max_hp strictly positive
        _with(-1.0, *_MELEE, "defense"),  # defense non-negative
        _with(-5.0, *_MELEE, "move_speed"),  # move_speed non-negative
        _with(0, *_MELEE, "attack_cooldown"),  # cooldown strictly positive
        _with(-1.0, *_MELEE, "keep_range_min"),  # band min non-negative
        _with([48.0], *_MELEE, "size"),  # size: too few components
        _with([1.0, 0.2, 0.55], *_MELEE, "color"),  # color: too few components
        _with(
            {**_valid_config()["kinds"]["monster_minion_melee"], "extra": 1}, *_MELEE
        ),  # extra key in a kind
        # A ranged kind MUST carry its projectile block (schema if/then).
        _without(*_RANGED, "projectile_speed"),
        _without(*_RANGED, "projectile_color"),
        _with(0, *_RANGED, "projectile_speed"),  # bolt speed strictly positive
        # Spawn Roster entry shape (through a wave, gADR-0005).
        _with(_wave_of({"kind": "monster_minion_melee"}), "waves"),  # missing fields
        _with(
            _wave_of({"kind": "Bad Kind!", "name": "Enemy", "position": [0.0, 0.0]}),
            "waves",
        ),  # kind key off-pattern
        _with(
            _wave_of(
                {"kind": "monster_minion_melee", "name": "", "position": [0.0, 0.0]}
            ),
            "waves",
        ),  # empty node name
        _with(
            _wave_of(
                {"kind": "monster_minion_melee", "name": "Enemy", "position": [640.0]}
            ),
            "waves",
        ),  # position: too few components
        {**_valid_config(), "extra": 1},  # unexpected extra top-level key
    ],
)
def test_invalid_json_rejected(bad: dict) -> None:
    """An enemies config that violates the schema raises jsonschema.ValidationError."""
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_config(bad, _enemies_schema())


def _dup_spawns() -> dict:
    entry = {"kind": "monster_minion_melee", "name": "Enemy", "position": [0.0, 0.0]}
    return _with(_wave_of(entry, {**entry, "position": [100.0, 0.0]}), "waves")


@pytest.mark.parametrize(
    "bad",
    [
        # F3: the Steering Band must be a real interval (min <= max); the
        # reviewer's 99 > 48 case validates against the schema alone.
        _with(99.0, *_MELEE, "keep_range_min"),
        # F1: melee damage is contact damage — attack_range must not reach
        # beyond keep_range_max (this is exactly the pre-fix shipped shape).
        _with(64.0, *_MELEE, "attack_range"),
        # Spawn -> kind referential integrity.
        _with(
            _wave_of({"kind": "no_such_kind", "name": "Enemy", "position": [0.0, 0.0]}),
            "waves",
        ),
        # Spawn names must be unique for addressability — here WITHIN one
        # wave; the cross-wave flavor is test_waves_data_seam.py's.
        _dup_spawns(),
    ],
)
def test_semantically_invalid_config_rejected(bad: dict) -> None:
    """A schema-valid config violating a cross-field rule is rejected.

    Each case passes the JSON Schema (proven first, so this suite would catch
    a rule silently migrating into the schema) and must then be rejected by
    ``validate_enemies_semantics`` with the same failure type.
    """
    build_config.validate_config(bad, _enemies_schema())
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_enemies_semantics(bad)


# ---------------------------------------------------------------------------
# Round-trip: the derived per-kind EnemyConfig .tres loads back through gda
# with its declared Godot types, compared to the AUTHORITATIVE JSON (never
# hardcoded values). The WaveScheduleConfig round-trip lives in
# test_waves_data_seam.py.
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
def test_enemy_kind_round_trips(gda, kind: str) -> None:
    """Each EnemyConfig .tres round-trips its axes, stat block, and AI params.

    Compared to the COMPOSED authority: the body/bolt boxes are authored in
    scale_spec.json's enemy_boxes (gADR-0013) and composed into the kind.
    """
    config = build_config.load_composed("data/json/enemies_config.json")["kinds"][kind]
    props = _get_props(gda, f"res://data/generated/enemy_{kind}.tres")

    # Taxonomy axes come back as the exact strings.
    for axis in ("faction", "tier", "archetype"):
        assert props[axis] == config[axis], (kind, axis)
    # The inherited stat block (EnemyConfig extends StatsConfig, gADR-0003).
    for stat in ("max_hp", "max_mp", "attack", "defense"):
        assert props[stat] == pytest.approx(config[stat]), (kind, stat)
    # Colors are float32 in Godot — compare with a tolerance.
    assert props["color"] == pytest.approx(config["color"], abs=1e-5)
    # Vector2 fields.
    for vec_field in ("size", "attack_squash"):
        assert props[vec_field] == pytest.approx(config[vec_field]), (kind, vec_field)
    # Scalar AI/motion params.
    for float_field in (
        "move_speed",
        "gravity",
        "max_fall_speed",
        "aggro_range",
        "attack_range",
        "attack_cooldown",
        "keep_range_min",
        "keep_range_max",
        "attack_tween_duration",
    ):
        assert props[float_field] == pytest.approx(config[float_field]), (
            kind,
            float_field,
        )
    # Ranged kinds also round-trip their bolt block.
    if config["archetype"] == "ranged":
        assert props["projectile_color"] == pytest.approx(
            config["projectile_color"], abs=1e-5
        )
        assert props["projectile_size"] == pytest.approx(config["projectile_size"])
        for float_field in ("projectile_speed", "projectile_lifetime"):
            assert props[float_field] == pytest.approx(config[float_field])
        assert props["projectile_spawn_offset"] == pytest.approx(
            config["projectile_spawn_offset"]
        )
