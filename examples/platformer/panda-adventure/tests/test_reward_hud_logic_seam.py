"""Logic seam (b) for S6a Kill reward (EXP/Gold per Tier) + HUD.

Exercises the pure S6a decisions — ``StatsSystem.gain_reward`` accumulation
(gADR-0004 on gADR-0001's runtime holder) and ``HudController``'s static
format functions (the readout the HUD renders from the Player's
``hud_state()`` snapshot) — headless, through ``gda script run`` (ADR-0031),
with every value injected as a parameter. Fast tier (``engine`` marker),
never ``e2e``.
"""

from __future__ import annotations

import json
import subprocess

import pytest

_LOGIC_SCRIPT = "res://tests/gdscript/test_reward_hud_logic.gd"


def _run(gda) -> subprocess.CompletedProcess:
    return gda("script", "run", _LOGIC_SCRIPT, "--json")


@pytest.mark.engine
def test_logic_seam_reward_and_hud_decisions(gda) -> None:
    """The pure reward/HUD rules hold for every behavior the GDScript seam asserts.

    The seam covers: the EXP/Gold accumulation identity (0 at init_from);
    single and repeated ``gain_reward`` accumulation (never replacement); the
    zero-reward no-op; reward isolation from HP/MP; ``format_bar``'s
    never-0-while-alive ceili readout; ``format_amount``'s never-overstate
    floori readout; ``format_weapon`` for both weapon identifiers; and
    ``format_lines`` mapping a full snapshot to the five display strings. We
    read gda's passed-through ``exit_status`` (0 == all assertions held) and
    require the PASS marker in stdout.
    """
    result = _run(gda)
    # gda itself succeeded (the script launched and ran to completion).
    assert result.returncode == 0, result.stdout + result.stderr
    doc = json.loads(result.stdout)
    # The script's own exit_status is passed through: 0 == every assertion held.
    assert doc["exit_status"] == 0, doc["stdout"] + doc["stderr"]
    assert "LOGIC_SEAM: PASS" in doc["stdout"], doc["stdout"] + doc["stderr"]
