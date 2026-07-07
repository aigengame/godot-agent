"""Round-trip seam for the Panda Adventure Editor (gADR-0012, #438).

Drives the editor's SAVE + DERIVE path headless through ``gda script run``
(ADR-0031) against a THROWAWAY PROJECT COPY, then asserts the edit landed on the
JSON authority AND propagated into the freshly derived ``.tres`` — proving the
editor writes ONLY JSON and re-derives through the ONE Python builder
(``scripts/build_config.py``), never a second GDScript derivation (gADR-0012).
Fast tier (``engine`` marker), never ``e2e``: a one-shot headless call, no daemon
(so no ``project.godot`` mutation and no cross-worktree contention).

Isolation: the editor mutates ``data/json`` and rebuilds ``data/generated`` IN
PLACE, so it must NEVER run against the worktree — hence the copy. The builder is
invoked with ``PANDA_EDITOR_PYTHON`` pointed at THIS interpreter (which carries
the build deps: jsonschema), so the derive is hermetic and independent of whatever
a system ``python3`` happens to have installed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

import build_config

GDA_CMD = [sys.executable, "-m", "gda"]
GAME_DIR = build_config.GAME_DIR
_ROUNDTRIP_SCRIPT = "res://tests/gdscript/test_editor_roundtrip.gd"

# Unlike the daemon e2e copies, KEEP ``tests/`` (the round-trip script runs from
# ``res://tests``) and ``data/generated`` (the pre-edit baseline the derive
# overwrites). Drop only the editor cache, the build artifact, and pycache.
_COPY_IGNORE = shutil.ignore_patterns(".godot", "build", "__pycache__")

# The edits the GDScript applies to Level 1 (segment 0 up one tile + widened,
# arena_min nudged in one tile, first spawn moved) — asserted here on the JSON.
_EXPECT_SEG0_POSITION = [560.0, 484.0]  # was [560, 500]
_EXPECT_SEG0_SIZE = [1792.0, 48.0]  # was [1760, 48]
_EXPECT_ARENA_MIN = -144.0  # was -160
_EXPECT_SPAWN0_POSITION = [688.0, 436.0]  # was [640, 452]


@pytest.mark.engine
def test_editor_roundtrip_json_and_derived(tmp_path) -> None:
    """edit -> save -> derive -> reload holds on the JSON authority + the .tres."""
    project = tmp_path / "panda_copy"
    shutil.copytree(GAME_DIR, project, ignore=_COPY_IGNORE)

    env = {**os.environ, "PANDA_EDITOR_PYTHON": sys.executable}
    result = subprocess.run(
        [
            *GDA_CMD,
            "script",
            "run",
            _ROUNDTRIP_SCRIPT,
            "--project",
            str(project),
            "--json",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    # gda itself succeeded (the script launched and ran to completion).
    assert result.returncode == 0, result.stdout + result.stderr
    doc = json.loads(result.stdout)
    # The script's own exit_status is passed through: 0 == every assertion held.
    assert doc["exit_status"] == 0, doc["stdout"] + doc["stderr"]
    assert "EDITOR_ROUNDTRIP: PASS" in doc["stdout"], doc["stdout"] + doc["stderr"]

    # Belt-and-braces at the Python tier: the SAVED JSON authority carries the
    # edits (numeric ==, so Godot's int/float JSON formatting is irrelevant).
    level = json.loads(
        (project / "data/json/level_config.json").read_text(encoding="utf-8")
    )
    assert level["platforms"][0]["position"] == _EXPECT_SEG0_POSITION
    assert level["platforms"][0]["size"] == _EXPECT_SEG0_SIZE
    assert level["arena_min_x"] == _EXPECT_ARENA_MIN
    enemies = json.loads(
        (project / "data/json/enemies_config.json").read_text(encoding="utf-8")
    )
    assert enemies["waves"][0]["spawns"][0]["position"] == _EXPECT_SPAWN0_POSITION

    # And the worktree authority is untouched (the copy took all writes).
    worktree_level = json.loads(
        (GAME_DIR / "data/json/level_config.json").read_text(encoding="utf-8")
    )
    assert worktree_level["platforms"][0]["position"] == [560.0, 500.0]
