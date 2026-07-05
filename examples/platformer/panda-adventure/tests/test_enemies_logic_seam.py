"""Logic seam (b) for S4 enemy taxonomy + Archetype AI.

Exercises the pure Archetype-AI decisions — ``EnemyAI.compute_move_dir`` /
``can_attack`` / ``is_attack_ready`` (gADR-0003) — headless, through ``gda
script run`` (ADR-0031): the closing-distance (Melee) and keeping-distance
(Ranged) steering, the aggro/attack-range/cooldown gating, and the deferred
Tank behavior, with positions and time injected as parameters. Fast tier
(``engine`` marker), never ``e2e``.
"""

from __future__ import annotations

import json
import subprocess

import pytest

_LOGIC_SCRIPT = "res://tests/gdscript/test_enemies_logic.gd"


def _run(gda) -> subprocess.CompletedProcess:
    return gda("script", "run", _LOGIC_SCRIPT, "--json")


@pytest.mark.engine
def test_logic_seam_archetype_ai_decisions(gda) -> None:
    """The pure Archetype-AI rules hold for every behavior the GDScript seam asserts.

    The seam covers: Melee closing distance (both sides) and holding
    point-blank; Ranged closing to, holding, and defending its Steering Band
    (keeping distance both sides); the Aggro Range gate; full-2D distance and
    the dx == 0 no-steer case; the Tank running the same band rule (un-deferred, gADR-0009);
    the cooldown boundary (ready at expiry, not within, -INF sentinel); and
    can_attack's range x cooldown x aggro composition. We read gda's
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
