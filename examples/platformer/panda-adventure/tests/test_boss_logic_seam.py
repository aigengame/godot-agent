"""Logic seam (b) for S8's Boss Warp kit (gADR-0009).

Exercises the pure Warp-kit decisions — ``WarpSystem.has_warp`` /
``should_warp`` / ``warp_landing`` / ``is_inside_field`` — headless, through
``gda script run`` (ADR-0031): the presence gate (a kind without the block
never warps), the anti-kite warp window (dormant beyond the Aggro Range,
shut at/inside the trigger range, open in between), the cooldown boundary
(ready at expiry, not within, -INF sentinel), the deterministic far-side
landing (both sides, the dx == 0 tie-break, arena clamping at both edges),
and the field membership rule, with positions and time injected as
parameters. Fast tier (``engine`` marker), never ``e2e``.
"""

from __future__ import annotations

import json
import subprocess

import pytest

_LOGIC_SCRIPT = "res://tests/gdscript/test_boss_logic.gd"


def _run(gda) -> subprocess.CompletedProcess:
    return gda("script", "run", _LOGIC_SCRIPT, "--json")


@pytest.mark.engine
def test_logic_seam_warp_kit_decisions(gda) -> None:
    """The pure Warp-kit rules hold for every behavior the GDScript seam asserts.

    We read gda's passed-through ``exit_status`` (0 == all assertions held)
    and require the PASS marker in stdout.
    """
    result = _run(gda)
    # gda itself succeeded (the script launched and ran to completion).
    assert result.returncode == 0, result.stdout + result.stderr
    doc = json.loads(result.stdout)
    # The script's own exit_status is passed through: 0 == every assertion held.
    assert doc["exit_status"] == 0, doc["stdout"] + doc["stderr"]
    assert "LOGIC_SEAM: PASS" in doc["stdout"], doc["stdout"] + doc["stderr"]
