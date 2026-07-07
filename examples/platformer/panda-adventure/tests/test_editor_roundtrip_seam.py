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
_PLAY_ABORT_SCRIPT = "res://tests/gdscript/test_editor_play_abort.gd"

# Unlike the daemon e2e copies, KEEP ``tests/`` (the round-trip script runs from
# ``res://tests``) and ``data/generated`` (the pre-edit baseline the derive
# overwrites). Drop only the editor cache, the build artifact, and pycache.
_COPY_IGNORE = shutil.ignore_patterns(".godot", "build", "__pycache__")

# The edits the GDScript applies to Level 1 (segment 0 up one tile + widened,
# arena_min nudged in one tile, first spawn moved, backdrop recolored) —
# asserted here on the JSON. The backdrop uses power-of-two components, exact
# in float32 and JSON, so plain equality holds.
_EXPECT_SEG0_POSITION = [560.0, 484.0]  # was [560, 500]
_EXPECT_SEG0_SIZE = [1792.0, 48.0]  # was [1760, 48]
_EXPECT_ARENA_MIN = -144.0  # was -160
_EXPECT_SPAWN0_POSITION = [688.0, 436.0]  # was [640, 452]
_EXPECT_BACKDROP = [0.25, 0.5, 0.75, 1.0]  # was [0.07, 0.06, 0.12, 1.0]


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
    assert level["background_color"] == _EXPECT_BACKDROP
    enemies = json.loads(
        (project / "data/json/enemies_config.json").read_text(encoding="utf-8")
    )
    assert enemies["waves"][0]["spawns"][0]["position"] == _EXPECT_SPAWN0_POSITION

    # And the worktree authority is untouched (the copy took all writes).
    worktree_level = json.loads(
        (GAME_DIR / "data/json/level_config.json").read_text(encoding="utf-8")
    )
    assert worktree_level["platforms"][0]["position"] == [560.0, 500.0]


@pytest.mark.engine
def test_play_entry_aborts_when_derive_fails(tmp_path) -> None:
    """A failed derive ABORTS the edit->play switch (review-round finding 1).

    The builder is forced to fail — ``PANDA_EDITOR_PYTHON`` points at
    ``/usr/bin/false``, so ``EditorBuilder.run`` gets a non-zero exit — and the
    GDScript seam asserts the editor stays in edit mode with NO play instance
    (playing would silently run STALE derived ``.tres``). The derived resources
    in the copy must stay byte-identical to the pre-edit baseline: nothing
    re-derived, nothing refreshed.
    """
    project = tmp_path / "panda_copy"
    shutil.copytree(GAME_DIR, project, ignore=_COPY_IGNORE)
    baseline_tres = (project / "data/generated/level_config.tres").read_text(
        encoding="utf-8"
    )

    env = {**os.environ, "PANDA_EDITOR_PYTHON": "/usr/bin/false"}
    result = subprocess.run(
        [
            *GDA_CMD,
            "script",
            "run",
            _PLAY_ABORT_SCRIPT,
            "--project",
            str(project),
            "--json",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    doc = json.loads(result.stdout)
    assert doc["exit_status"] == 0, doc["stdout"] + doc["stderr"]
    assert "PLAY_ABORT: PASS" in doc["stdout"], doc["stdout"] + doc["stderr"]
    # The structured abort trail is on the script's output (GameLog print fallback).
    assert "editor_derive_failed" in doc["stdout"], doc["stdout"]
    assert "editor_play_aborted" in doc["stdout"], doc["stdout"]
    assert "editor_play_entered" not in doc["stdout"], doc["stdout"]

    # The failed builder wrote nothing: the derived .tres is the pre-edit baseline
    # (the save half DID write the JSON authority — that is the expected split).
    assert (project / "data/generated/level_config.tres").read_text(
        encoding="utf-8"
    ) == baseline_tres
    saved = json.loads(
        (project / "data/json/level_config.json").read_text(encoding="utf-8")
    )
    assert saved["arena_min_x"] == -144.0  # the seam's one edit landed on JSON
