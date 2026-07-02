"""Logic seam (b) for S2 Laser Gun combat.

Exercises the pure combat decisions — ``CombatSystem.compute_damage`` /
``is_invulnerable`` / ``is_dead``, ``StatsSystem.init_from`` / ``apply_damage``,
and ``PlayerController.compute_facing`` — headless, through ``gda script run``
(ADR-0031). These are the functions the offline Monte-Carlo balancing sim reuses
(gADR-0001). Fast tier (``engine`` marker), never ``e2e``.
"""

from __future__ import annotations

import json
import subprocess

import pytest

_LOGIC_SCRIPT = "res://tests/gdscript/test_combat_logic.gd"


def _run(gda) -> subprocess.CompletedProcess:
    return gda("script", "run", _LOGIC_SCRIPT, "--json")


@pytest.mark.engine
def test_logic_seam_combat_decisions(gda) -> None:
    """The pure combat rules hold for every behavior the GDScript seam asserts.

    The seam covers: raw damage (zero defense), mitigation, the min-damage
    floor, attacker<->defender symmetry (both directions through the ONE
    function), the i-frame window (within / at expiry / past / -INF sentinel),
    StatsSystem init (all four stats) and damage clamping, the is_dead
    boundary, and facing. We read gda's passed-through ``exit_status`` (0 ==
    all assertions held) and require the PASS marker in stdout.
    """
    result = _run(gda)
    # gda itself succeeded (the script launched and ran to completion).
    assert result.returncode == 0, result.stdout + result.stderr
    doc = json.loads(result.stdout)
    # The script's own exit_status is passed through: 0 == every assertion held.
    assert doc["exit_status"] == 0, doc["stdout"] + doc["stderr"]
    assert "LOGIC_SEAM: PASS" in doc["stdout"], doc["stdout"] + doc["stderr"]
