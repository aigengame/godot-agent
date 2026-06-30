"""Logic seam (a) for the S0 walking skeleton.

The controller's pure config -> plan decision, exercised headless. gda exposes no
``gda script run``, so the seam shells out to ``godot --headless --script``
directly (a known gda dogfooding gap). A second check boots the main scene
headless to confirm ``_ready`` runs to completion without parse/load errors. Fast
tier (``engine`` marker), never ``e2e``.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from gda.binary import resolve_godot_binary

import build_config

GAME_DIR = build_config.GAME_DIR
_LOGIC_SCRIPT = "res://tests/gdscript/test_boot_logic.gd"


def _run_godot(*args: str) -> subprocess.CompletedProcess:
    """Run the project headless with the given extra args."""
    godot = resolve_godot_binary()
    return subprocess.run(
        [str(godot), "--headless", "--path", str(GAME_DIR), *args],
        capture_output=True,
        text=True,
    )


@pytest.mark.engine
def test_logic_seam_plan_matches_config() -> None:
    """BootController.plan_from_config derives the block plan from the Resource."""
    build_config.build()  # ensure the .tres reflects the current JSON
    result = _run_godot("--script", _LOGIC_SCRIPT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "LOGIC_SEAM: PASS" in result.stdout, result.stdout + result.stderr


@pytest.mark.engine
def test_main_scene_boots_clean() -> None:
    """The main scene boots headless: _ready completes, no script/parse errors."""
    build_config.build()
    result = _run_godot("--quit-after", "5")
    combined = result.stdout + result.stderr
    # _ready ran to its last statement -> the GameLog fallback line printed.
    assert "[info] boot" in result.stdout, combined
    # No GDScript parse or runtime errors during boot.
    assert "SCRIPT ERROR" not in combined, combined
    assert "Parse Error" not in combined, combined


@pytest.mark.engine
def test_clean_checkout_boots_without_rebuild(tmp_path) -> None:
    """A fresh checkout boots from the COMMITTED .tres — no build step.

    The committed ``data/generated/boot_config.tres`` is what makes a clean
    checkout (and the exported ``.app``) boot. Copy the project WITHOUT rebuilding
    — excluding only machine-local import/build artifacts, keeping the committed
    .tres — and boot it headless. Unlike ``test_main_scene_boots_clean`` (which
    rebuilds first), this proves the on-disk derived Resource is present and loads:
    no ``Cannot open file``, no script/parse error, and the boot line prints.
    """
    dst = tmp_path / "game"
    shutil.copytree(
        GAME_DIR,
        dst,
        ignore=shutil.ignore_patterns(".godot", "build", "__pycache__", "*.uid"),
    )
    assert (dst / "data" / "generated" / "boot_config.tres").exists(), (
        "committed .tres missing from the checkout — run scripts/build_config.py"
    )

    godot = resolve_godot_binary()
    result = subprocess.run(
        [str(godot), "--headless", "--path", str(dst), "--quit-after", "5"],
        capture_output=True,
        text=True,
    )
    combined = result.stdout + result.stderr
    assert "[info] boot" in result.stdout, combined
    assert "Cannot open file" not in combined, combined
    assert "SCRIPT ERROR" not in combined, combined
    assert "Parse Error" not in combined, combined
