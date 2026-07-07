"""Data seam for the P2-S0 Scale spec (gADR-0013).

Proves the single-size-authority machinery: the authoritative
``scale_spec.json`` validates against its schema, bad specs are rejected, the
cross-FILE rules (two-way kind integrity with the enemies config, strict Tier
size ordering, two-way pickup-item integrity, level-segment tile-grid
alignment) are enforced by ``build_config.validate_scale_semantics`` and GATE
the build, ``compose_scale_spec`` injects every migrated dimension back into
its consumer's source document, the derived ``ScaleSpecConfig`` .tres
round-trips through gda, and ``project.godot``'s display block MIRRORS the
spec's presentation policy (the engine reads project.godot directly, so the
mirror is gate-checked rather than derived). Freshness of ``scale_spec.tres``
is covered by ``test_combat_data_seam.py``'s SPECS-parametrized gate. Fast
tier — never ``e2e``; the round-trip drives one-shot ``gda`` headless ops
under the ``engine`` gate.
"""

from __future__ import annotations

import copy
import json
import re

import jsonschema
import pytest

import build_config

SCALE_JSON_PATH = build_config.GAME_DIR / "data/json/scale_spec.json"
SCALE_SCHEMA_PATH = build_config.GAME_DIR / "data/schema/scale_spec.schema.json"
SCALE_TRES_REL = "data/generated/scale_spec.tres"


def _valid_spec() -> dict:
    """A fresh copy of the authoritative Scale spec to mutate."""
    return copy.deepcopy(build_config.load_json(SCALE_JSON_PATH))


def _scale_schema() -> dict:
    return build_config.load_schema(SCALE_SCHEMA_PATH)


def _with(value: object, *path) -> dict:
    bad = _valid_spec()
    node = bad
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return bad


def _without(*path: str) -> dict:
    bad = _valid_spec()
    node = bad
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    return bad


def test_authoritative_scale_spec_validates() -> None:
    """The shipped Scale spec passes its schema AND its cross-file rules."""
    spec = build_config.load_json(SCALE_JSON_PATH)
    assert build_config.validate_config(spec, _scale_schema()) is spec
    assert build_config.validate_scale_semantics(spec) is spec


def test_scale_spec_registered_for_freshness_gate() -> None:
    """The scale spec is in SPECS, so the parametrized freshness gate covers it."""
    assert SCALE_TRES_REL in [spec.out_rel for spec in build_config.SPECS]


@pytest.mark.parametrize(
    "bad",
    [
        _without("ppu"),  # every anchor is required
        _without("tile_size"),
        _without("player_size"),
        _without("enemy_boxes"),
        _without("pickup_sizes", "wine"),  # the closed item vocabulary
        _with(0, "ppu"),  # strictly positive
        _with(0, "tile_size"),  # strictly positive
        _with(16.5, "tile_size"),  # a whole number of pixels
        _with([1280.0], "design_base"),  # too few components
        _with("stretched", "stretch_mode"),  # off-enum
        _with("bilinear", "texture_filter"),  # off-enum
        _with("yes", "snap_2d_transforms_to_pixel"),  # wrong type
        _with([48.0], "player_size"),  # size: too few components
        _with([0.0, 64.0], "player_size"),  # size: component must be > 0
        _with(0, "gravity_field_radius"),  # strictly positive
        _with(16.5, "hud_font_size"),  # a whole number
        _with({}, "enemy_boxes"),  # at least one kind
        _with({"size": [40.0, 40.0], "x": 1}, "enemy_boxes", "monster_minion_melee"),
        _with({"projectile_size": [12.0, 5.0]}, "enemy_boxes", "monster_minion_melee"),
        {**_valid_spec(), "extra": 1},  # unexpected extra top-level key
    ],
)
def test_invalid_scale_spec_rejected(bad: dict) -> None:
    """A Scale spec violating the schema raises jsonschema.ValidationError."""
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_config(bad, _scale_schema())


# ---------------------------------------------------------------------------
# Cross-file semantics: schema-valid specs the semantic gate must reject
# (validated against the SHIPPED sibling configs).
# ---------------------------------------------------------------------------


def _boxes_without(kind: str) -> dict:
    bad = _valid_spec()
    del bad["enemy_boxes"][kind]
    return bad


@pytest.mark.parametrize(
    "bad, why",
    [
        (_boxes_without("monster_minion_melee"), "a kind without a box"),
        (
            _with({"size": [30.0, 30.0]}, "enemy_boxes", "stale_kind"),
            "a box naming no kind",
        ),
        (
            _with(
                {"size": [48.0, 48.0], "projectile_size": [12.0, 5.0]},
                "enemy_boxes",
                "monster_minion_melee",
            ),
            "a bolt box on a melee kind",
        ),
        (
            _with({"size": [96.0, 128.0]}, "enemy_boxes", "alien_boss_tank"),
            "a Warp kind without its zone radius",
        ),
        (
            _with({"size": [200.0, 200.0]}, "enemy_boxes", "monster_minion_melee"),
            "a Minion outsizing the Elite breaks Tier ordering",
        ),
        (
            _with(40.0, "platform_thickness"),
            "the standard slab off the tile grid",
        ),
    ],
)
def test_semantically_invalid_scale_spec_rejected(bad: dict, why: str) -> None:
    build_config.validate_config(bad, _scale_schema())  # passes the schema
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_scale_semantics(bad)


def _stage_inputs(root) -> None:
    """Copy every spec's authoritative JSON + schema into an isolated root."""
    for rel in {s.json_rel for s in build_config.SPECS} | {
        s.schema_rel for s in build_config.SPECS
    }:
        src = build_config.GAME_DIR / rel
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def test_off_grid_segment_gates_the_build_with_no_partial_writes(tmp_path) -> None:
    """The tile-grid rule gates the BUILD before ANY resource derives.

    A segment dimension off the grid (the pre-reconcile parapet width, 140)
    must fail ``build_all`` — and because the cross-file semantics run in
    every ``build_spec`` before its write, the failure is all-or-nothing: no
    partial derived set may be left behind (the gADR-0000 no-drift rule;
    PR #457 review finding).
    """
    _stage_inputs(tmp_path)
    level_path = tmp_path / "data/json/level_config.json"
    config = json.loads(level_path.read_text(encoding="utf-8"))
    config["platforms"][-1]["size"] = [140.0, 48.0]
    level_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(jsonschema.ValidationError):
        build_config.build_all(root=tmp_path)

    generated = tmp_path / "data" / "generated"
    written = (
        sorted(p.name for p in generated.glob("*.tres")) if generated.exists() else []
    )
    assert written == [], f"a failed build must write NOTHING, but wrote {written}"


def test_broken_tier_ordering_gates_the_build_with_no_partial_writes(tmp_path) -> None:
    """A Scale spec violating Tier size ordering fails ``build_all`` with
    zero derived outputs — the semantic gate fires on the FIRST spec, not
    when the scale spec's own output is finally reached."""
    _stage_inputs(tmp_path)
    scale_path = tmp_path / "data/json/scale_spec.json"
    spec = json.loads(scale_path.read_text(encoding="utf-8"))
    spec["enemy_boxes"]["monster_minion_melee"]["size"] = [200.0, 200.0]
    scale_path.write_text(json.dumps(spec), encoding="utf-8")

    with pytest.raises(jsonschema.ValidationError):
        build_config.build_all(root=tmp_path)

    generated = tmp_path / "data" / "generated"
    written = (
        sorted(p.name for p in generated.glob("*.tres")) if generated.exists() else []
    )
    assert written == [], f"a failed build must write NOTHING, but wrote {written}"


# ---------------------------------------------------------------------------
# Composition: the write side of the single size authority.
# ---------------------------------------------------------------------------


def test_composition_injects_every_migrated_dimension() -> None:
    """``load_composed`` returns each source with its dimensions injected."""
    scale = build_config.load_json(SCALE_JSON_PATH)

    player = build_config.load_composed("data/json/player_config.json")
    assert player["player_size"] == scale["player_size"]

    combat = build_config.load_composed("data/json/combat_config.json")
    assert combat["projectile_size"] == scale["player_projectile_size"]
    assert "enemy_size" not in combat  # the legacy block stays deleted

    gravity = build_config.load_composed("data/json/gravity_config.json")
    assert gravity["field_radius"] == scale["gravity_field_radius"]
    assert gravity["obstacle_size"] == scale["obstacle_size"]

    enemies = build_config.load_composed("data/json/enemies_config.json")
    for name, kind in enemies["kinds"].items():
        box = scale["enemy_boxes"][name]
        assert kind["size"] == box["size"], name
        assert (kind["archetype"] == "ranged") == ("projectile_size" in kind), name
        if kind["archetype"] == "ranged":
            assert kind["projectile_size"] == box["projectile_size"], name
        if "warp_cooldown" in kind:
            assert kind["time_field_radius"] == box["time_field_radius"], name

    hud = build_config.load_composed("data/json/hud_config.json")
    assert hud["margin"] == scale["hud_margin"]
    assert hud["font_size"] == scale["hud_font_size"]

    progression = build_config.load_composed("data/json/progression_config.json")
    assert progression["pickup_spacing"] == scale["pickup_spacing"]
    for item, style in progression["drop_items"].items():
        assert style["size"] == scale["pickup_sizes"][item], item

    level = build_config.load_composed("data/json/level_config.json")
    assert level["end_title_font_size"] == scale["end_title_font_size"]
    assert level["end_hint_font_size"] == scale["end_hint_font_size"]


def test_composition_rejects_a_kind_without_a_box() -> None:
    """The composition-side guard: an enemies document naming a kind the spec
    has no box for fails loudly (the two-way rule's build-path half)."""
    scale = build_config.load_json(SCALE_JSON_PATH)
    enemies = copy.deepcopy(build_config.load_json(build_config.ENEMIES_JSON_PATH))
    enemies["kinds"]["new_kind"] = dict(enemies["kinds"]["monster_minion_melee"])
    with pytest.raises(jsonschema.ValidationError):
        build_config.compose_scale_spec(enemies, "data/json/enemies_config.json", scale)


# ---------------------------------------------------------------------------
# The project.godot mirror: the one presentation surface that cannot be a
# derived artifact (the engine reads it directly; the gda harness co-writes
# the file), so the gate cross-checks it against the spec (gADR-0013).
# ---------------------------------------------------------------------------

# texture_filter name -> project.godot's default_texture_filter enum value.
_FILTER_ENUM = {"nearest": 0, "linear": 1}


def _project_setting(text: str, key: str) -> str | None:
    match = re.search(rf"^{re.escape(key)}=(.+)$", text, flags=re.MULTILINE)
    return match.group(1) if match else None


def test_project_godot_mirrors_the_presentation_policy() -> None:
    """project.godot's display/rendering block matches the Scale spec."""
    scale = build_config.load_json(SCALE_JSON_PATH)
    text = (build_config.GAME_DIR / "project.godot").read_text(encoding="utf-8")

    width, height = scale["design_base"]
    assert _project_setting(text, "window/size/viewport_width") == str(int(width)), (
        "project.godot viewport width must mirror scale_spec.json's design_base"
    )
    assert _project_setting(text, "window/size/viewport_height") == str(int(height))
    assert _project_setting(text, "window/stretch/mode") == f'"{scale["stretch_mode"]}"'
    assert (
        _project_setting(text, "window/stretch/aspect")
        == f'"{scale["stretch_aspect"]}"'
    )
    assert _project_setting(
        text, "textures/canvas_textures/default_texture_filter"
    ) == str(_FILTER_ENUM[scale["texture_filter"]])
    assert (
        _project_setting(text, "2d/snap/snap_2d_transforms_to_pixel")
        == str(scale["snap_2d_transforms_to_pixel"]).lower()
    )


# ---------------------------------------------------------------------------
# Round-trip: the derived ScaleSpecConfig .tres loads back through gda with
# its declared Godot types, compared to the AUTHORITATIVE JSON.
# ---------------------------------------------------------------------------


@pytest.mark.engine
def test_scale_spec_round_trips(gda) -> None:
    """The ScaleSpecConfig .tres round-trips every anchor through gda."""
    spec = build_config.load_json(SCALE_JSON_PATH)
    result = gda("resource", "get", f"res://{SCALE_TRES_REL}", "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    props = {p["name"]: p["value"] for p in json.loads(result.stdout)["properties"]}

    for float_field in ("ppu", "tile_size", "platform_thickness"):
        assert props[float_field] == pytest.approx(spec[float_field])
    assert props["design_base"] == pytest.approx(spec["design_base"])
    for string_field in ("stretch_mode", "stretch_aspect", "texture_filter"):
        assert props[string_field] == spec[string_field]
    assert props["snap_2d_transforms_to_pixel"] is spec["snap_2d_transforms_to_pixel"]
