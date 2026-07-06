"""Logic seam (b) for the S9 End-state machine.

Exercises the pure game-flow decision — ``GameStateSystem.resolve_event`` /
``can_retry`` (gADR-0010) — headless, through ``gda script run`` (ADR-0031):
the two live transitions (playing -> won on the schedule's clear, playing ->
lost on the Player's death), the first-transition latch in either order, the
unknown-event no-op, and the End-state-only retry gate. Fast tier (``engine``
marker), never ``e2e``.
"""

from __future__ import annotations

import json
import subprocess

import pytest

_LOGIC_SCRIPT = "res://tests/gdscript/test_level_logic.gd"


def _run(gda) -> subprocess.CompletedProcess:
    return gda("script", "run", _LOGIC_SCRIPT, "--json")


@pytest.mark.engine
def test_logic_seam_end_state_decisions(gda) -> None:
    """Every End-state transition and boundary the GDScript seam pins holds.

    The seam covers: playing ends won on ``all_waves_cleared`` and lost on
    ``player_died``; the latch (a post-win death and a post-loss clear change
    nothing, both orders); unknown events never transition from any state;
    and ``can_retry`` is true ONLY in an End state. We read gda's
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
