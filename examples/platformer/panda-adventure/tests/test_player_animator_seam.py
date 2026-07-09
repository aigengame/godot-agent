"""Logic seam for the Player animation state machine (PlayerAnimator, P2-S5 #443).

Exercises the view driver headless, through ``gda script run`` (ADR-0031): a
synthetic controller carrying the view-integration hook signals plus a real
``AnimatedSprite2D`` drive ``tests/gdscript/test_player_animator_logic.gd``, which
pins the state machine — the locomotion base plays at init; each verb hook plays
its one-shot (``fired``->fire, ``hurt``->hurt, ``consumed``->consume,
``leveled_up``->level_up); a one-shot resumes the current locomotion base on
``animation_finished``; a locomotion change re-bases; and death latches
(``death_started``->death, every later hook ignored). Fast tier (``engine`` marker),
never ``e2e`` — the windowed visual-smoke checkpoint proves it renders on screen;
this proves the transition logic without a display.
"""

from __future__ import annotations

import json
import subprocess

import pytest

_LOGIC_SCRIPT = "res://tests/gdscript/test_player_animator_logic.gd"


def _run(gda) -> subprocess.CompletedProcess:
    return gda("script", "run", _LOGIC_SCRIPT, "--json")


@pytest.mark.engine
def test_logic_seam_player_animator(gda) -> None:
    """Every PlayerAnimator transition holds exactly.

    The GDScript seam builds a synthetic controller + AnimatedSprite2D and asserts
    the resulting animation state through the whole machine (verbs, one-shot resume,
    locomotion re-base, death latch). We read gda's passed-through ``exit_status``
    (0 == all assertions held) and require the PASS marker in stdout.
    """
    result = _run(gda)
    assert result.returncode == 0, result.stdout + result.stderr
    doc = json.loads(result.stdout)
    assert doc["exit_status"] == 0, doc["stdout"] + doc["stderr"]
    assert "ANIMATOR_SEAM: PASS" in doc["stdout"], doc["stdout"] + doc["stderr"]
