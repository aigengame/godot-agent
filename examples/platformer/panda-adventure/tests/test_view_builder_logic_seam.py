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
    """The optional asset reference flows JSON -> .tres with an empty default.

    An authored source WITHOUT the key renders ``player_asset = ""`` (the
    builder materializes the default, so the derived Resource always carries
    the field the view seam resolves); a source WITH the key renders it
    verbatim. Pure render check (no IO beyond loading the committed authority).
    """
    composed = build_config.load_composed("data/json/player_config.json")
    assert "player_asset" not in composed  # authored absent in wave 1 (#436)
    spec = build_config._PLAYER_SPEC
    assert 'player_asset = ""' in build_config.render_spec(spec, composed)

    authored = dict(composed, player_asset="res://assets/player.png")
    rendered = build_config.render_spec(spec, authored)
    assert 'player_asset = "res://assets/player.png"' in rendered


def test_asset_reference_materializes_in_nested_view_structures() -> None:
    """Platform segments and pickup item styles carry the asset key too.

    The two nested view-bearing structures (level ``platforms`` entries and
    progression ``drop_items`` styles) materialize ``"asset": ""`` per entry in
    the derived ``.tres``, so their runtime consumers (LevelController /
    PickupController) can read the reference unconditionally.
    """
    level = build_config.load_composed("data/json/level_config.json")
    rendered = build_config._render_field(
        "platforms", "platform_list", level["platforms"]
    )
    assert rendered.count('"asset": ""') == len(level["platforms"])

    progression = build_config.load_composed("data/json/progression_config.json")
    rendered = build_config._render_field(
        "drop_items", "item_style_map", progression["drop_items"]
    )
    assert rendered.count('"asset": ""') == len(progression["drop_items"])
