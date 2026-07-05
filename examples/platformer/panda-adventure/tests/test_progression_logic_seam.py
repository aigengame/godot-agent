"""Logic seam (b) for S6b Leveling curve + drop tables (gADR-0006).

Exercises the pure S6b decisions — ``GrowthSystem.resolve_level`` (the
leveling curve: level as a function of the EXP total, max level = curve
length + 1), ``EconomySystem.resolve_drops``/``drop_offset`` (the Drop-table
roll with parameter-injected rolls, and the deterministic scatter row), and
``StatsSystem.gain_gold`` (the Pickup path's gold accumulation) — headless,
through ``gda script run`` (ADR-0031), with every value injected as a
parameter. Fast tier (``engine`` marker), never ``e2e``.
"""

from __future__ import annotations

import json
import subprocess

import pytest

_LOGIC_SCRIPT = "res://tests/gdscript/test_progression_logic.gd"


def _run(gda) -> subprocess.CompletedProcess:
    return gda("script", "run", _LOGIC_SCRIPT, "--json")


@pytest.mark.engine
def test_logic_seam_progression_decisions(gda) -> None:
    """The pure progression rules hold for every behavior the GDScript seam asserts.

    The seam covers: level 1 at the accumulation identity and below the first
    threshold; a threshold REACHED is a level-up (>=); one total crossing
    several thresholds yields them all (multi-level-up); the max-level cap is
    the curve length + 1 and follows the curve's length (the no-hardcoded-
    count proof, an empty curve pinning level 1); drop inclusion iff
    roll <= chance (the inclusive boundary that makes chance 1.0 guaranteed
    against randf()'s 1.0-inclusive domain); resolved drops keeping table
    order and carrying item+amount only; an empty table resolving empty; the
    deterministic centered scatter row; and ``gain_gold`` accumulating gold
    alone. We read gda's passed-through ``exit_status`` (0 == all assertions
    held) and require the PASS marker in stdout.
    """
    result = _run(gda)
    # gda itself succeeded (the script launched and ran to completion).
    assert result.returncode == 0, result.stdout + result.stderr
    doc = json.loads(result.stdout)
    # The script's own exit_status is passed through: 0 == every assertion held.
    assert doc["exit_status"] == 0, doc["stdout"] + doc["stderr"]
    assert "LOGIC_SEAM: PASS" in doc["stdout"], doc["stdout"] + doc["stderr"]
