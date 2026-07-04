"""Logic seam (b) for S3 Gravity Gun / Gravity Field / MP economy.

Exercises the pure S3 decisions — ``PlayerController.compute_next_weapon``
(weapon-switch state), ``StatsSystem.spend_mp`` / ``restore_mp`` (the MP
economy rules), and ``GravitySystem.compute_field_velocity`` /
``compute_clamped_offset`` (the field's data-driven effect, gADR-0002) —
headless, through ``gda script run`` (ADR-0031). Fast tier (``engine``
marker), never ``e2e``.
"""

from __future__ import annotations

import json
import subprocess

import pytest

_LOGIC_SCRIPT = "res://tests/gdscript/test_gravity_logic.gd"


def _run(gda) -> subprocess.CompletedProcess:
    return gda("script", "run", _LOGIC_SCRIPT, "--json")


@pytest.mark.engine
def test_logic_seam_gravity_decisions(gda) -> None:
    """The pure S3 rules hold for every behavior the GDScript seam asserts.

    The seam covers: the weapon-switch toggle (laser <-> gravity, unknown falls
    back to the laser default), spend_mp (affordable / exact-cost boundary /
    refused at 0 MP / all-or-nothing on insufficient MP), restore_mp (add,
    clamp at max_mp, hold at the cap), compute_field_velocity (lift/slam/
    redirect as data through one function, normalization, the zero-direction
    null field), compute_clamped_offset (integration, the total-length
    clamp, holding at the clamp, zero velocity, diagonal length-clamping), and
    should_affect — the opt-in contract filter (gADR-0002): affected only with
    BOTH the "gravity_affectable" group and the apply_gravity_field method
    (negative cases: method without group, group without method). We read
    gda's passed-through ``exit_status`` (0 == all assertions held) and
    require the PASS marker in stdout.
    """
    result = _run(gda)
    # gda itself succeeded (the script launched and ran to completion).
    assert result.returncode == 0, result.stdout + result.stderr
    doc = json.loads(result.stdout)
    # The script's own exit_status is passed through: 0 == every assertion held.
    assert doc["exit_status"] == 0, doc["stdout"] + doc["stderr"]
    assert "LOGIC_SEAM: PASS" in doc["stdout"], doc["stdout"] + doc["stderr"]
