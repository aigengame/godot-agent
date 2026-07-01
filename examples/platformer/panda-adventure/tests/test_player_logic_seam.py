"""Logic seam (a) for S1 player traversal.

Exercises ``PlayerController.compute_velocity`` — the pure config+state -> velocity
decision — headless, through ``gda script run`` (ADR-0031). This replaces S0's
direct ``godot --headless --script`` shell-out: gda now runs the user script and
passes its ``exit_status``/stdout/stderr through verbatim, so a deliberate
``quit(1)`` on a failed assertion is data we read, not a gda failure. Fast tier
(``engine`` marker), never ``e2e``.
"""

from __future__ import annotations

import json
import subprocess

import pytest

_LOGIC_SCRIPT = "res://tests/gdscript/test_player_logic.gd"


def _run(gda) -> subprocess.CompletedProcess:
    return gda("script", "run", _LOGIC_SCRIPT, "--json")


@pytest.mark.engine
def test_logic_seam_movement_decisions(gda) -> None:
    """compute_velocity derives velocity from config+state for every behavior.

    The GDScript seam asserts each movement rule and ``quit(0)`` only if all hold.
    We read gda's passed-through ``exit_status`` (0 == all assertions held) and
    require the PASS marker in stdout.
    """
    result = _run(gda)
    # gda itself succeeded (the script launched and ran to completion).
    assert result.returncode == 0, result.stdout + result.stderr
    doc = json.loads(result.stdout)
    # The script's own exit_status is passed through: 0 == every assertion held.
    assert doc["exit_status"] == 0, doc["stdout"] + doc["stderr"]
    assert "LOGIC_SEAM: PASS" in doc["stdout"], doc["stdout"] + doc["stderr"]
