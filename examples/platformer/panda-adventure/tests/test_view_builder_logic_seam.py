"""Logic seam for the P2-S2 view-construction seam (ViewBuilder, #436).

Exercises the ONE shared blockout builder headless, through ``gda script run``
(ADR-0031): the box blockout with and without the center pivot, the circle
field shape, and the asset-reference resolution branch (a non-empty asset
reference is the resolved sprite path, so the seam loads the texture and renders
a ``Sprite`` child of a transparent Visual frame — asset references are data,
gADR-0000; #439). The construction path every controller now routes through,
pinned so "renders exactly as before P2-S2" holds for the block fallback. Fast
tier (``engine`` marker), never ``e2e``.

Also pins the WRITE side of the seam's config feed (pure Python, no engine):
the optional ``asset`` field kind defaults to ``""`` when the authored JSON
omits it — so every derived ``.tres`` carries the reference the seam resolves —
and passes an authored value through verbatim (the freshness gates already pin
the committed-empty state byte-for-byte).
"""

from __future__ import annotations

import json
import subprocess

import pytest

import build_config

_LOGIC_SCRIPT = "res://tests/gdscript/test_view_builder_logic.gd"


def _run(gda) -> subprocess.CompletedProcess:
    return gda("script", "run", _LOGIC_SCRIPT, "--json")


@pytest.mark.engine
def test_logic_seam_view_builder(gda) -> None:
    """Every blockout the shared view seam produces holds exactly.

    The GDScript seam builds synthetic Visual/Collision node pairs and asserts
    the EXACT view ViewBuilder produces — box (centered ColorRect + same-size
    RectangleShape2D, with/without the center pivot), circle (2·radius square
    ColorRect + CircleShape2D), and the asset-reference resolution (a resolved
    reference loads the committed tracer texture and renders it as a ``Sprite``
    TextureRect child of a transparent Visual). We read gda's passed-through
    ``exit_status`` (0 == all assertions held) and require the PASS marker in
    stdout.
    """
    result = _run(gda)
    # gda itself succeeded (the script launched and ran to completion).
    assert result.returncode == 0, result.stdout + result.stderr
    doc = json.loads(result.stdout)
    # The script's own exit_status is passed through: 0 == every assertion held.
    assert doc["exit_status"] == 0, doc["stdout"] + doc["stderr"]
    assert "LOGIC_SEAM: PASS" in doc["stdout"], doc["stdout"] + doc["stderr"]


def test_asset_reference_renders_default_and_authored_value() -> None:
    """The optional asset reference flows JSON -> .tres, resolving the manifest id.

    The Player sprite reference is wired since P2-S5 (#443): ``player_asset``
    names the manifest id ``player``, which the builder resolves to the committed
    ``SpriteFrames`` path the view seam loads (gADR-0014/gADR-0015). A source
    WITHOUT the key still materializes the empty default (every derived Resource
    carries the field the seam resolves), and an authored value passes through
    verbatim. Pure render check (no IO beyond loading the committed authority).
    """
    composed = build_config.load_composed("content/data/json/player_config.json")
    spec = build_config._PLAYER_SPEC
    # The manifest id resolved to the derived SpriteFrames path.
    assert composed["player_asset"] == "res://content/assets/sprites/player.tres"
    assert (
        'player_asset = "res://content/assets/sprites/player.tres"'
        in build_config.render_spec(spec, composed)
    )

    # A source with the key ABSENT materializes the empty-string default.
    absent = {k: v for k, v in composed.items() if k != "player_asset"}
    assert 'player_asset = ""' in build_config.render_spec(spec, absent)

    # An authored value passes through verbatim.
    authored = dict(composed, player_asset="res://content/assets/player.png")
    rendered = build_config.render_spec(spec, authored)
    assert 'player_asset = "res://content/assets/player.png"' in rendered


def test_asset_reference_materializes_in_nested_view_structures() -> None:
    """Platform segments and pickup item styles carry the resolved asset per entry.

    The two nested view-bearing structures (level ``platforms`` entries and
    progression ``drop_items`` styles) each render an ``asset`` key so their
    runtime consumers (LevelController / PickupController) read the reference
    unconditionally. The level ``platforms`` stay authored-empty (the terrain skin
    is a later slice), so they render ``"asset": ""``; the P2-S3 Pickups (#442) are
    wired, so every ``drop_items`` style renders its resolved single-homed
    ``res://`` path (the builder composed the manifest id -> path).
    """
    level = build_config.load_composed("content/data/json/level_config.json")
    rendered = build_config._render_field(
        "platforms", "platform_list", level["platforms"]
    )
    assert rendered.count('"asset": ""') == len(level["platforms"])

    progression = build_config.load_composed(
        "content/data/json/progression_config.json"
    )
    rendered = build_config._render_field(
        "drop_items", "item_style_map", progression["drop_items"]
    )
    assert '"asset": ""' not in rendered  # every Pickup is wired now (#442)
    for item in progression["drop_items"]:
        assert f'"asset": "res://content/assets/textures/pickup_{item}.png"' in rendered
