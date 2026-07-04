"""Logic seam (b) for the S5 Wave spawn system.

Exercises the pure Wave-progression decision — ``WaveSystem.resolve_death``
(gADR-0005) — headless, through ``gda script run`` (ADR-0031): the
advance-on-clear fold over whole schedules at wave counts 3, 4, AND 5 (the
issue-#334 no-hardcoded-count proof), the alive clamp, and the single-wave
boundary. Fast tier (``engine`` marker), never ``e2e``.
"""

from __future__ import annotations

import json
import subprocess

import pytest

_LOGIC_SCRIPT = "res://tests/gdscript/test_waves_logic.gd"


def _run(gda) -> subprocess.CompletedProcess:
    return gda("script", "run", _LOGIC_SCRIPT, "--json")


@pytest.mark.engine
def test_logic_seam_wave_progression_decisions(gda) -> None:
    """The advance-on-clear rule holds for every schedule the GDScript seam folds.

    The seam covers: full-schedule folds at counts 3, 4, and 5 with mixed
    per-wave spawn counts (alive decrements exactly; ``cleared`` fires on a
    wave's last death only; ``advance`` on every non-final clear;
    ``all_cleared`` exactly once, on the final clear); the alive-at-0 clamp;
    and the 1-wave schedule whose only clear is the completion. We read gda's
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
