"""Data seam (a) for S9 level integration (gADR-0010).

Proves the JSON -> Resource pipeline for the ``LevelConfig`` level authority:
the authoritative ``level_config.json`` validates against its schema, bad
config is rejected (schema violations AND the cross-field rules —
``validate_level_semantics``: unique Great-Wall segment names, a real Arena
interval), the committed ``.tres`` is fresh, and the derived fields round-trip
back through gda with their declared Godot types. Fast tier — never marked
``e2e``; the round-trip drives a one-shot ``gda`` headless op under the
``engine`` gate.
"""

from __future__ import annotations

import copy
import json

import jsonschema
import pytest

import build_config

_LEVEL_SPEC = next(
    spec
    for spec in build_config.SPECS
    if spec.json_rel == "data/json/level_config.json"
)

# res:// path of the derived resource, resolved against the project (--project).
_TRES_RES_PATH = "res://data/generated/level_config.tres"


def _valid_config() -> dict:
    """A fresh copy of the AUTHORITATIVE config to mutate into invalid variants."""
    return copy.deepcopy(build_config.load_json(build_config.LEVEL_JSON_PATH))


def _schema() -> dict:
    return build_config.load_schema(build_config.LEVEL_SCHEMA_PATH)


def _with(key: str, value: object) -> dict:
    bad = _valid_config()
    bad[key] = value
    return bad


def _without(key: str) -> dict:
    bad = _valid_config()
    del bad[key]
    return bad


def test_sample_json_passes_schema_and_semantics() -> None:
    """The authoritative config validates against schema AND cross-field rules."""
    config = build_config.load_json(build_config.LEVEL_JSON_PATH)
    assert build_config.validate_config(config, _schema()) is config
    assert build_config.validate_level_semantics(config) is config


@pytest.mark.parametrize(
    "missing",
    [
        "background_color",
        "platform_color",
        "platforms",
        "arena_min_x",
        "arena_max_x",
        "end_overlay_color",
        "end_win_color",
        "end_lose_color",
        "end_title_font_size",
        "end_hint_font_size",
        "end_fade_duration",
    ],
)
def test_missing_required_key_rejected(missing: str) -> None:
    """Every top-level key is required — dropping any one fails the schema."""
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_config(_without(missing), _schema())


@pytest.mark.parametrize(
    "bad",
    [
        _with("platforms", []),  # a level with no ground is a config bug
        _with("background_color", [0.1, 0.1, 1.5, 1.0]),  # component out of 0..1
        _with("platform_color", [0.1, 0.1]),  # too few components
        _with("end_title_font_size", 0),  # strictly positive
        _with("end_fade_duration", -0.4),  # strictly positive
        _with("arena_min_x", "west"),  # wrong type
        {**_valid_config(), "extra": 1},  # unexpected extra key
    ],
)
def test_invalid_json_rejected(bad: dict) -> None:
    """A config that violates the schema raises jsonschema.ValidationError."""
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_config(bad, _schema())


@pytest.mark.parametrize(
    "bad_segment",
    [
        {"position": [0.0, 0.0], "size": [10.0, 10.0]},  # missing name
        {"name": "A", "position": [0.0], "size": [10.0, 10.0]},  # short position
        {"name": "A", "position": [0.0, 0.0], "size": [0.0, 10.0]},  # zero width
        {"name": "A B", "position": [0.0, 0.0], "size": [10.0, 10.0]},  # bad name
        {"name": "A", "position": [0.0, 0.0], "size": [10.0, 10.0], "x": 1},  # extra
    ],
)
def test_invalid_platform_segment_rejected(bad_segment: dict) -> None:
    """A malformed Great-Wall segment fails the schema's item shape."""
    bad = _valid_config()
    bad["platforms"].append(bad_segment)
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_config(bad, _schema())


def test_duplicate_platform_name_rejected() -> None:
    """Segment names must be unique (gADR-0010): they become sibling node
    names under Main, where a duplicate would be silently renamed by Godot
    and break addressability (the gADR-0005 argument). Schema-valid, so only
    the semantic gate catches it."""
    bad = _valid_config()
    bad["platforms"].append(dict(bad["platforms"][0]))
    build_config.validate_config(bad, _schema())  # passes the schema
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_level_semantics(bad)


@pytest.mark.parametrize("arena_min_x", [1280.0, 2000.0])
def test_degenerate_arena_rejected(arena_min_x: float) -> None:
    """The Arena is a real interval (gADR-0010): arena_min_x must stay
    strictly below arena_max_x — it clamps the Warp Blink's landing.
    Schema-valid, so only the semantic gate catches it."""
    bad = _with("arena_min_x", arena_min_x)
    build_config.validate_config(bad, _schema())  # passes the schema
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_level_semantics(bad)


def test_generated_resource_is_fresh(tmp_path) -> None:
    """The COMMITTED .tres matches a fresh build — JSON stays authoritative."""
    committed = build_config.GAME_DIR / _LEVEL_SPEC.out_rel
    assert committed.exists(), (
        "committed data/generated/level_config.tres is missing — "
        "run scripts/build_config.py"
    )
    fresh = build_config.build_spec(
        _LEVEL_SPEC, out_path=tmp_path / "level_config.tres"
    )
    assert fresh.read_text(encoding="utf-8") == committed.read_text(encoding="utf-8"), (
        "committed .tres is stale — run scripts/build_config.py"
    )


@pytest.mark.engine
def test_build_produces_round_trippable_resource(gda) -> None:
    """The derived .tres round-trips back through gda against the JSON.

    Reading each field back via ``gda resource get`` and comparing to the
    *authoritative JSON* (not hardcoded values) proves the JSON->Resource
    conversion preserves value and Godot type — including the platform_list
    rendering of the Great-Wall segments (name/position/size per entry).
    """
    config = build_config.load_json(build_config.LEVEL_JSON_PATH)

    result = gda("resource", "get", _TRES_RES_PATH, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    props = {p["name"]: p["value"] for p in json.loads(result.stdout)["properties"]}

    # Colors are stored as float32 in Godot: compare with a tolerance.
    for key in (
        "background_color",
        "platform_color",
        "end_overlay_color",
        "end_win_color",
        "end_lose_color",
    ):
        assert props[key] == pytest.approx(config[key], abs=1e-5), key
    # Scalars.
    for key in (
        "arena_min_x",
        "arena_max_x",
        "end_title_font_size",
        "end_hint_font_size",
        "end_fade_duration",
    ):
        assert props[key] == pytest.approx(config[key]), key
    # The Great-Wall segments: same count, same order, same shape per entry.
    segments = props["platforms"]
    assert len(segments) == len(config["platforms"])
    for got, want in zip(segments, config["platforms"]):
        assert got["name"] == want["name"]
        assert got["position"] == pytest.approx(want["position"])
        assert got["size"] == pytest.approx(want["size"])
