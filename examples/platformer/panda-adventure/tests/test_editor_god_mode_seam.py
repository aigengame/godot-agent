"""God-mode regression seam for the Panda Adventure Editor (#476 review).

Drives the debug palette's god-mode correctness through ``gda script run``
(ADR-0031): the review found that refilling HP next-frame does NOT stop the
synchronous death latch in ``PlayerController.take_hit``. The fix routes god-mode
through a Player invulnerability API the palette drives, so a lethal hit is
refused at the source. This seam boots the real game, enables god-mode, lands a
lethal hit, and asserts the Player survives; then disables god-mode and lands the
same hit to prove it kills (god-mode was the difference).

Engine tier (fast, no daemon): a one-shot headless call against a THROWAWAY COPY
(kept read-only, but copied for isolation like the round-trip seam).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

import pytest

import build_config

GDA_CMD = [sys.executable, "-m", "gda"]
GAME_DIR = build_config.GAME_DIR
_GOD_MODE_SCRIPT = "res://tests/gdscript/test_editor_god_mode.gd"

# Keep tests/ (the seam script) and content/data/generated (Gameplay loads the derived
# .tres). Drop only the editor cache, the build artifact, and pycache.
_COPY_IGNORE = shutil.ignore_patterns(".godot", "build", "__pycache__")


@pytest.mark.engine
def test_god_mode_prevents_death(tmp_path) -> None:
    """A lethal hit under god-mode does NOT end the run; without it, it kills."""
    project = tmp_path / "panda_copy"
    shutil.copytree(GAME_DIR, project, ignore=_COPY_IGNORE)

    result = subprocess.run(
        [
            *GDA_CMD,
            "script",
            "run",
            _GOD_MODE_SCRIPT,
            "--project",
            str(project),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    doc = json.loads(result.stdout)
    assert doc["exit_status"] == 0, doc["stdout"] + doc["stderr"]
    assert "GOD_MODE: PASS" in doc["stdout"], doc["stdout"] + doc["stderr"]
