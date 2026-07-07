"""Logic seam for the P2-S2 view-construction seam (ViewBuilder, #436).

Exercises the ONE shared blockout builder headless, through ``gda script run``
(ADR-0031): the box blockout with and without the center pivot, the circle
field shape, and the asset-reference resolution decision point (a non-empty
asset reference is the future sprite path, so the block fallback is NOT applied
— asset references are data, gADR-0000). The construction path every controller
now routes through, pinned so "renders exactly as before P2-S2" holds. Fast tier
(``engine`` marker), never ``e2e``.
"""

from __future__ import annotations

import json
import subprocess

import pytest

_LOGIC_SCRIPT = "res://tests/gdscript/test_view_builder_logic.gd"


def _run(gda) -> subprocess.CompletedProcess:
    return gda("script", "run", _LOGIC_SCRIPT, "--json")


@pytest.mark.engine
def test_logic_seam_view_builder(gda) -> None:
    """Every blockout the shared view seam produces holds exactly.

    The GDScript seam builds synthetic Visual/Collision node pairs and asserts
    the EXACT view ViewBuilder produces — box (centered ColorRect + same-size
    RectangleShape2D, with/without the center pivot), circle (2·radius square
    ColorRect + CircleShape2D), and the asset-reference resolution (block
    fallback skipped when an asset reference is present). We read gda's
    passed-through ``exit_status`` (0 == all assertions held) and require the
    PASS marker in stdout.
    """
    result = _run(gda)
    # gda itself succeeded (the script launched and ran to completion).
    assert result.returncode == 0, result.stdout + result.stderr
    doc = json.loads(result.stdout)
    # The script's own exit_status is passed through: 0 == every assertion held.
    assert doc["exit_status"] == 0, doc["stdout"] + doc["stderr"]
    assert "LOGIC_SEAM: PASS" in doc["stdout"], doc["stdout"] + doc["stderr"]
