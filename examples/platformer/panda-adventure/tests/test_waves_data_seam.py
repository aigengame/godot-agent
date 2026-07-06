"""Data seam (a) for the S5 Wave spawn system (gADR-0005).

Proves the Wave schedule's JSON -> Resource pipeline (gADR-0000): the
authoritative ``waves`` array validates (and bad wave shapes are rejected),
the demo default is exactly the GDD four-Wave arc (melee Minions -> ranged
Elite -> mixed Xenomorph swarm -> Boss slot), **reconfiguring the wave count
(3 and 5) is a JSON-only change** (the issue-#334 no-hardcoded-count proof at
this seam), the cross-wave rules JSON Schema cannot express are enforced by
``build_config.validate_enemies_semantics`` (spawn -> kind referential
integrity in every wave, spawn-name uniqueness across the whole schedule),
the derived ``WaveScheduleConfig`` .tres round-trips through gda with its
declared Godot types, and the default Wave-2 composition stays DORMANT at the
positions where the legacy kill flows leave the Player — the by-data
compatibility contract that keeps the pre-S5 e2e green (gADR-0005). Freshness
of ``wave_schedule.tres`` is covered by ``test_combat_data_seam.py``'s
SPECS-parametrized gate. Fast tier — never ``e2e``; the round-trip drives a
one-shot ``gda`` headless op under the ``engine`` gate.
"""

from __future__ import annotations

import copy
import json
import math

import jsonschema
import pytest

import build_config


def _config() -> dict:
    """A fresh copy of the authoritative enemies config."""
    return copy.deepcopy(build_config.load_json(build_config.ENEMIES_JSON_PATH))


def _enemies_schema() -> dict:
    return build_config.load_schema(build_config.ENEMIES_SCHEMA_PATH)


def _player_config() -> dict:
    return build_config.load_json(build_config.JSON_PATH)


def _rampart() -> dict:
    """The main fight platform from the authoritative level config."""
    level_cfg = build_config.load_json(build_config.LEVEL_JSON_PATH)
    return next(p for p in level_cfg["platforms"] if p["name"] == "Rampart")


# ---------------------------------------------------------------------------
# The demo default: the GDD four-Wave arc, asserted structurally from the
# authoritative JSON (compositions, not balance numbers).
# ---------------------------------------------------------------------------


def test_default_schedule_is_the_four_wave_demo_arc() -> None:
    """Four waves: melee Minions -> ranged Elite -> mixed swarm -> Boss slot."""
    config = _config()
    waves = config["waves"]
    kinds = config["kinds"]
    assert len(waves) == 4

    def axes(spawn: dict) -> tuple[str, str, str]:
        kind = kinds[spawn["kind"]]
        return kind["faction"], kind["tier"], kind["archetype"]

    # Wave 1 — onboarding melee Minions (and the S2/S4 legacy default spawn).
    for spawn in waves[0]["spawns"]:
        _, tier, archetype = axes(spawn)
        assert (tier, archetype) == ("minion", "melee"), spawn
    # Wave 2 — the first Elite, ranged pressure.
    for spawn in waves[1]["spawns"]:
        _, tier, archetype = axes(spawn)
        assert (tier, archetype) == ("elite", "ranged"), spawn
    # Wave 3 — the mixed Minion swarm: several spawns, one Faction, BOTH
    # delivery archetypes present (the combined-arms beat).
    swarm = waves[2]["spawns"]
    assert len(swarm) >= 2
    swarm_axes = [axes(s) for s in swarm]
    assert {tier for _, tier, _ in swarm_axes} == {"minion"}
    assert len({faction for faction, _, _ in swarm_axes}) == 1
    assert {archetype for _, _, archetype in swarm_axes} == {"melee", "ranged"}
    # Wave 4 — the Boss slot: the FINAL wave composes the boss Tier
    # (behavior is S8; the slot is data, gADR-0005).
    final_axes = [axes(s) for s in waves[3]["spawns"]]
    assert {tier for _, tier, _ in final_axes} == {"boss"}


def test_default_wave_two_stays_dormant_at_the_legacy_kill_positions() -> None:
    """Clearing Wave 1 during a legacy kill flow must not aggro Wave 2.

    Killing the Wave-1 minion now spawns Wave 2 mid-test (gADR-0005), so for
    the pre-S5 e2e to stay green BY DATA every Wave-2 spawn must be dormant —
    Aggro Range short of the gap — against the Player wherever those flows
    leave them: parked at ``player_start`` (the S2 combat flow) or walked to
    the Wave-1 minion's aggro edge (the S6a reward flow's walk target,
    ``enemy_x - aggro_range + 40``). ``can_attack`` is aggro-gated too, so
    dormancy needs no attack_range bound. Tune data if this trips; never
    loosen the margin.
    """
    config = _config()
    player_cfg = _player_config()
    rampart = _rampart()
    rest_y = (
        rampart["position"][1]
        - rampart["size"][1] / 2.0
        - player_cfg["player_size"][1] / 2.0
    )
    wave_one = config["waves"][0]["spawns"][0]
    wave_one_aggro = config["kinds"][wave_one["kind"]]["aggro_range"]
    player_positions = [
        (player_cfg["player_start"][0], rest_y),
        # The reward flow's walk target (test_reward_hud_e2e.py): just inside
        # the Wave-1 minion's Aggro Range.
        (wave_one["position"][0] - wave_one_aggro + 40.0, rest_y),
    ]
    for spawn in config["waves"][1]["spawns"]:
        aggro = config["kinds"][spawn["kind"]]["aggro_range"]
        for player_pos in player_positions:
            gap = math.dist(player_pos, spawn["position"])
            assert gap > aggro + 50.0, (
                f"wave-2 spawn {spawn['name']!r} would aggro (gap {gap:.1f}, "
                f"aggro {aggro}) against the Player at {player_pos}"
            )


# ---------------------------------------------------------------------------
# The no-hardcoded-count proof at this seam: 3- and 5-wave schedules build
# with no code change.
# ---------------------------------------------------------------------------


def _stage_inputs(root) -> None:
    """Copy every spec's authoritative JSON + schema into an isolated root."""
    for rel in {s.json_rel for s in build_config.SPECS} | {
        s.schema_rel for s in build_config.SPECS
    }:
        src = build_config.GAME_DIR / rel
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def _reconfigured_waves(count: int) -> list[dict]:
    """A valid ``count``-wave schedule of single melee-minion spawns."""
    return [
        {
            "spawns": [
                {
                    "kind": "monster_minion_melee",
                    "name": f"Wave{n}Minion",
                    "position": [640.0, 452.0],
                }
            ]
        }
        for n in range(1, count + 1)
    ]


@pytest.mark.parametrize("count", [3, 5])
def test_reconfiguring_the_wave_count_is_json_only(tmp_path, count: int) -> None:
    """A 3- or 5-wave schedule builds from a JSON-only edit (#334).

    Stage the inputs in an isolated root, rewrite ``waves`` alone — no
    Python/spec/code edit — and the build derives a ``wave_schedule.tres``
    carrying exactly that many waves.
    """
    _stage_inputs(tmp_path)
    enemies_path = tmp_path / "data/json/enemies_config.json"
    config = json.loads(enemies_path.read_text(encoding="utf-8"))
    config["waves"] = _reconfigured_waves(count)
    enemies_path.write_text(json.dumps(config), encoding="utf-8")

    build_config.build_all(root=tmp_path)

    tres = (tmp_path / "data/generated/wave_schedule.tres").read_text(encoding="utf-8")
    assert tres.count('{"spawns": [') == count
    for n in range(1, count + 1):
        assert f'"name": "Wave{n}Minion"' in tres


# ---------------------------------------------------------------------------
# Schema rejections for the wave shapes (the entry-level shapes stay covered
# by test_enemies_data_seam.py through the same `waves` paths).
# ---------------------------------------------------------------------------


def _with(value: object, *path) -> dict:
    bad = _config()
    node = bad
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return bad


def _without(*path: str) -> dict:
    bad = _config()
    node = bad
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    return bad


_SPAWN = {"kind": "monster_minion_melee", "name": "Enemy", "position": [640.0, 452.0]}


@pytest.mark.parametrize(
    "bad",
    [
        _without("waves"),  # the Wave schedule is required
        _with([], "waves"),  # at least one wave
        _with([{}], "waves"),  # a wave requires its spawns
        _with([{"spawns": []}], "waves"),  # a wave spawns at least one enemy
        _with([{"spawns": [_SPAWN], "extra": 1}], "waves"),  # extra key in a wave
        _with([_SPAWN], "waves"),  # a bare spawn is not a wave
        _without("spawn_squash"),  # the spawn telegraph numbers are required
        _without("spawn_tween_duration"),
        _with([0.3], "spawn_squash"),  # squash: too few components
        _with([0.0, 0.3], "spawn_squash"),  # squash components strictly positive
        _with(0, "spawn_tween_duration"),  # duration strictly positive
    ],
)
def test_invalid_wave_shapes_rejected(bad: dict) -> None:
    """A waves array violating the schema raises jsonschema.ValidationError."""
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_config(bad, _enemies_schema())


# ---------------------------------------------------------------------------
# Cross-wave semantic rules (gADR-0005): schema-valid configs the validator
# must reject.
# ---------------------------------------------------------------------------


def _unknown_kind_in_wave_two() -> dict:
    bad = _config()
    bad["waves"][1]["spawns"][0]["kind"] = "no_such_kind"
    return bad


def _duplicate_name_across_waves() -> dict:
    # Wave 3 reuses Wave 1's node name: unique-per-wave, duplicate schedule-wide.
    bad = _config()
    bad["waves"][2]["spawns"][0]["name"] = bad["waves"][0]["spawns"][0]["name"]
    return bad


@pytest.mark.parametrize(
    "bad",
    [_unknown_kind_in_wave_two(), _duplicate_name_across_waves()],
    ids=["unknown-kind-in-a-later-wave", "duplicate-name-across-waves"],
)
def test_semantically_invalid_schedule_rejected(bad: dict) -> None:
    """Schema-valid schedules violating a cross-wave rule are rejected."""
    build_config.validate_config(bad, _enemies_schema())
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_enemies_semantics(bad)


# ---------------------------------------------------------------------------
# Round-trip: the derived WaveScheduleConfig .tres loads back through gda with
# its declared Godot types, compared to the AUTHORITATIVE JSON.
# ---------------------------------------------------------------------------


@pytest.mark.engine
def test_wave_schedule_round_trips(gda) -> None:
    """The WaveScheduleConfig .tres round-trips the schedule structurally.

    gda projects the nested waves as structured JSON (ADR-0035): each wave's
    spawns come back with kind/name as strings and position as the [x, y]
    Vector2 projection, and the spawn-telegraph tween numbers ride along —
    all matching the authoritative JSON.
    """
    config = _config()
    result = gda("resource", "get", "res://data/generated/wave_schedule.tres", "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    props = {p["name"]: p["value"] for p in json.loads(result.stdout)["properties"]}
    assert props["spawn_squash"] == pytest.approx(config["spawn_squash"])
    assert props["spawn_tween_duration"] == pytest.approx(
        config["spawn_tween_duration"]
    )
    assert len(props["waves"]) == len(config["waves"])
    for got_wave, expected_wave in zip(props["waves"], config["waves"]):
        assert len(got_wave["spawns"]) == len(expected_wave["spawns"])
        for got, expected in zip(got_wave["spawns"], expected_wave["spawns"]):
            assert got["kind"] == expected["kind"]
            assert got["name"] == expected["name"]
            assert got["position"] == pytest.approx(expected["position"])
