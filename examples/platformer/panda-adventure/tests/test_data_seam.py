"""Data seam (b) for the S0 walking skeleton.

Proves the JSON -> Resource pipeline (gADR-0000): the authoritative
``boot_config.json`` validates against its schema, bad config is rejected, and
``build_config.build()`` emits a ``.tres`` whose fields round-trip back through
gda with their declared Godot types. Fast tier — never marked ``e2e``; the
round-trip drives a one-shot ``gda`` headless op under the ``engine`` gate.
"""

from __future__ import annotations

import json

import jsonschema
import pytest

import build_config


def _valid_config() -> dict:
    """A fresh copy of a schema-valid config to mutate into invalid variants."""
    return {
        "block_color": [0.2, 0.6, 1.0, 1.0],
        "block_size": [64.0, 64.0],
        "start_position": [100.0, 300.0],
        "target_position": [500.0, 300.0],
        "tween_duration": 1.5,
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
_TRES_RES_PATH = "res://data/generated/boot_config.tres"


def _properties_by_name(get_result: dict) -> dict:
    """Index a ``gda resource get`` result's ``properties`` list by name."""
    return {p["name"]: p["value"] for p in get_result["properties"]}


@pytest.mark.engine
def test_build_produces_round_trippable_resource(gda) -> None:
    """build() emits a .tres whose fields round-trip back through gda.

    The generated ``.tres`` is a derived artifact (committed, but rebuilt here to
    prove build() writes it). It lives under the project's ``data/generated/`` dir
    so ``res://`` resolves it. Reading each field back via ``gda resource get`` and
    comparing to the *authoritative JSON* (not hardcoded values) proves the
    JSON->Resource conversion preserves both value and Godot type
    (Color/Vector2/float).
    """
    config = build_config.load_json(build_config.JSON_PATH)

    build_config.GENERATED_TRES.unlink(missing_ok=True)
    out = build_config.build(out_path=build_config.GENERATED_TRES)
    assert out.exists(), "build() did not write the .tres"

    result = gda("resource", "get", _TRES_RES_PATH, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    props = _properties_by_name(json.loads(result.stdout))

    # Color is stored as float32 in Godot, so compare with a tolerance.
    assert props["block_color"] == pytest.approx(config["block_color"], abs=1e-5)
    assert props["block_size"] == pytest.approx(config["block_size"])
    assert props["start_position"] == pytest.approx(config["start_position"])
    assert props["target_position"] == pytest.approx(config["target_position"])
    assert props["tween_duration"] == pytest.approx(config["tween_duration"])


def test_generated_resource_is_fresh(tmp_path) -> None:
    """The COMMITTED .tres matches a fresh build — JSON stays authoritative.

    ``data/generated/boot_config.tres`` is a derived artifact that is committed
    (tracked) so a clean checkout / exported ``.app`` boots with no build step.
    This gate runs in the pure-Python tier (every PR): it rebuilds from the
    authoritative JSON to a temp path and asserts byte-equality with the committed
    file, so drift between the JSON and the committed Resource is caught.
    """
    committed = build_config.GENERATED_TRES
    assert committed.exists(), (
        "committed data/generated/boot_config.tres is missing — "
        "run scripts/build_config.py"
    )
    fresh = build_config.build(out_path=tmp_path / "boot_config.tres")
    assert fresh.read_text(encoding="utf-8") == committed.read_text(encoding="utf-8"), (
        "committed .tres is stale — run scripts/build_config.py"
    )


@pytest.mark.parametrize(
    "bad",
    [
        _without("tween_duration"),  # missing required key
        _without("block_size"),  # missing required block_size
        _with("block_color", [0.2, 0.6, 1.0]),  # color: too few components
        _with("block_color", [0.2, 0.6, 1.0, 1.0, 0.5]),  # color: too many
        _with("block_color", [0.2, 0.6, 1.5, 1.0]),  # color: component out of 0..1
        _with("block_size", [64.0]),  # size: too few components
        _with("block_size", [0.0, 64.0]),  # size: component must be > 0
        _with("start_position", [100.0]),  # position: too few components
        _with("target_position", [1.0, 2.0, 3.0]),  # position: too many
        _with("tween_duration", 0),  # duration must be strictly positive
        _with("tween_duration", -1.0),  # duration negative
        _with("tween_duration", "fast"),  # duration wrong type
        {**_valid_config(), "extra": 1},  # unexpected extra key
    ],
)
def test_invalid_json_rejected(bad: dict) -> None:
    """A config that violates the schema raises jsonschema.ValidationError."""
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_config(bad)
