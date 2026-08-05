"""Data seam (b) for S1 player traversal.

Proves the JSON -> Resource pipeline (gADR-0000) for the S1 ``PlayerConfig``: the
authoritative ``player_config.json`` validates against its schema, bad config is
rejected, and ``build_config.build()`` emits a ``.tres`` whose fields round-trip
back through gda with their declared Godot types (Color/Vector2/float). Fast tier
— never marked ``e2e``; the round-trip drives a one-shot ``gda`` headless op under
the ``engine`` gate.
"""

from __future__ import annotations

import json

import jsonschema
import pytest

import build_config


def _valid_config() -> dict:
    """A fresh copy of a schema-valid config to mutate into invalid variants."""
    return {
        "player_color": [0.92, 0.92, 0.96, 1.0],
        "player_start": [200.0, 200.0],
        "move_speed": 300.0,
        "jump_velocity": -650.0,
        "gravity": 1400.0,
        "max_fall_speed": 1200.0,
        "camera_smoothing_speed": 5.0,
        "landing_squash": [1.2, 0.8],
        "landing_tween_duration": 0.15,
    }


def test_sample_json_passes_schema() -> None:
    """The authoritative sample config validates against its schema."""
    config = build_config.load_json(build_config.JSON_PATH)
    schema = build_config.load_schema()
    # validate_config returns the config unchanged and raises on any violation.
    assert build_config.validate_config(config, schema) is config


def _without(key: str) -> dict:
    bad = _valid_config()
    del bad[key]
    return bad


def _with(key: str, value: object) -> dict:
    bad = _valid_config()
    bad[key] = value
    return bad


# res:// path of the derived resource, resolved against the project (--project).
_TRES_RES_PATH = "res://content/data/generated/player_config.tres"


def _properties_by_name(get_result: dict) -> dict:
    """Index a ``gda resource get`` result's ``properties`` list by name."""
    return {p["name"]: p["value"] for p in get_result["properties"]}


@pytest.mark.engine
def test_build_produces_round_trippable_resource(gda) -> None:
    """build() emits a .tres whose fields round-trip back through gda.

    Reading each field back via ``gda resource get`` and comparing to the
    *composed authority* (the player source with the Scale spec's player_size
    composed in, gADR-0013 — never hardcoded values) proves the JSON->Resource
    conversion preserves both value and Godot type (Color/Vector2/float) across
    every declared field.
    """
    config = build_config.load_composed("content/data/json/player_config.json")

    build_config.GENERATED_TRES.unlink(missing_ok=True)
    out = build_config.build(out_path=build_config.GENERATED_TRES)
    assert out.exists(), "build() did not write the .tres"

    result = gda("resource", "get", _TRES_RES_PATH, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    props = _properties_by_name(json.loads(result.stdout))

    # Color is stored as float32 in Godot, so compare with a tolerance.
    assert props["player_color"] == pytest.approx(config["player_color"], abs=1e-5)
    # Vector2 fields.
    assert props["player_size"] == pytest.approx(config["player_size"])
    assert props["player_start"] == pytest.approx(config["player_start"])
    assert props["landing_squash"] == pytest.approx(config["landing_squash"])
    # Scalar float fields.
    assert props["move_speed"] == pytest.approx(config["move_speed"])
    assert props["jump_velocity"] == pytest.approx(config["jump_velocity"])
    assert props["gravity"] == pytest.approx(config["gravity"])
    assert props["max_fall_speed"] == pytest.approx(config["max_fall_speed"])
    assert props["camera_smoothing_speed"] == pytest.approx(
        config["camera_smoothing_speed"]
    )
    assert props["landing_tween_duration"] == pytest.approx(
        config["landing_tween_duration"]
    )


def test_generated_resource_is_fresh(tmp_path) -> None:
    """The COMMITTED .tres matches a fresh build — JSON stays authoritative.

    ``content/data/generated/player_config.tres`` is a derived artifact that is committed
    (tracked) so a clean checkout / exported ``.app`` boots with no build step.
    This gate runs in the pure-Python tier (every PR): it rebuilds from the
    authoritative JSON to a temp path and asserts byte-equality with the committed
    file, so drift between the JSON and the committed Resource is caught.
    """
    committed = build_config.GENERATED_TRES
    assert committed.exists(), (
        "committed content/data/generated/player_config.tres is missing — "
        "run scripts/build_config.py"
    )
    fresh = build_config.build(out_path=tmp_path / "player_config.tres")
    assert fresh.read_text(encoding="utf-8") == committed.read_text(encoding="utf-8"), (
        "committed .tres is stale — run scripts/build_config.py"
    )


@pytest.mark.parametrize(
    "bad",
    [
        _without("move_speed"),  # missing required scalar
        _with("player_color", [0.2, 0.6, 1.0]),  # color: too few components
        _with("player_color", [0.2, 0.6, 1.0, 1.0, 0.5]),  # color: too many
        _with("player_color", [0.2, 0.6, 1.5, 1.0]),  # color: component out of 0..1
        _with("player_size", [48.0, 64.0]),  # size lives in scale_spec (gADR-0013)
        _with("player_start", [100.0]),  # position: too few components
        _with("player_start", [1.0, 2.0, 3.0]),  # position: too many
        _with("move_speed", 0),  # speed must be strictly positive
        _with("gravity", -1.0),  # gravity must be positive
        _with("jump_velocity", 0),  # jump must be strictly negative (upward)
        _with("jump_velocity", 650.0),  # jump downward is invalid
        _with("landing_squash", [1.2]),  # squash: too few components
        _with("landing_squash", [1.2, 0.0]),  # squash: component must be > 0
        _with("landing_tween_duration", 0),  # duration must be strictly positive
        _with("move_speed", "fast"),  # wrong type
        {**_valid_config(), "extra": 1},  # unexpected extra key
    ],
)
def test_invalid_json_rejected(bad: dict) -> None:
    """A config that violates the schema raises jsonschema.ValidationError."""
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_config(bad)
