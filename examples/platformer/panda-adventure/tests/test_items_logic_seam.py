"""Logic seam (b) for S7 Consumable use + Spacesuit Equipment (gADR-0008).

Exercises the pure S7 decisions — ``ItemSystem``'s supply gate, count
decrement, and effective-defender composition, ``StatsSystem.restore_hp``
(the Bun's capped restore, ``restore_mp``'s mirror), and the composed
defender feeding ``CombatSystem.compute_damage``'s mitigation term with the
formula untouched — headless, through ``gda script run`` (ADR-0031), with
every value injected as a parameter. Fast tier (``engine`` marker), never
``e2e``.
"""

from __future__ import annotations

import json
import subprocess

import pytest

_LOGIC_SCRIPT = "res://tests/gdscript/test_items_logic.gd"


def _run(gda) -> subprocess.CompletedProcess:
    return gda("script", "run", _LOGIC_SCRIPT, "--json")


@pytest.mark.engine
def test_logic_seam_items_decisions(gda) -> None:
    """The pure items rules hold for every behavior the GDScript seam asserts.

    The seam covers: the one-input supply gate (empty refuses, held permits);
    the exactly-one decrement with its 0 floor; ``restore_hp``'s add / cap /
    at-cap-stays behaviors and its isolation from MP; the effective-defender
    composition (defense = base + bonus, other stats copied, the base NEVER
    mutated, a fresh instance returned, zero-bonus equivalence); the
    mitigation drop of exactly ``bonus * defense_scale`` through the
    untouched formula; and the ``min_damage`` floor under an overwhelming
    bonus. We read gda's passed-through ``exit_status`` (0 == all assertions
    held) and require the PASS marker in stdout.
    """
    result = _run(gda)
    # gda itself succeeded (the script launched and ran to completion).
    assert result.returncode == 0, result.stdout + result.stderr
    doc = json.loads(result.stdout)
    # The script's own exit_status is passed through: 0 == every assertion held.
    assert doc["exit_status"] == 0, doc["stdout"] + doc["stderr"]
    assert "LOGIC_SEAM: PASS" in doc["stdout"], doc["stdout"] + doc["stderr"]
