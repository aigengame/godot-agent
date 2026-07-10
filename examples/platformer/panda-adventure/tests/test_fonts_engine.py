"""Engine proof — the derived HUD ``.fnt`` really loads as a Godot Font (P2-S9).

The fast tier ``test_fonts_deriver.py`` pins the deriver's TEXT (header, glyph
regions, determinism); it cannot prove the emitted ``.fnt`` is a *valid Godot
font*. This engine-tier test closes that gap: it copies the committed project
(carrying ``assets/fonts/hud_font.{png,fnt}`` and their ``.import`` sidecars),
imports it (so the ``.fnt``'s external PNG page resolves), then loads the font in
a headless Godot ``SceneTree`` and asserts it is a ``Font`` whose monospace
metrics match the deriver's grid — the exact property the styled HUD's
visual-smoke width checkpoint relies on (gADR-0007/gADR-0014).

``engine`` marker: fails loudly without a Godot binary (conftest), deselected in
the fast CI tier and run in the ``godot-e2e`` job / locally.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from gda.binary import resolve_godot_binary

from assets import game_config

import build_config

GODOT = resolve_godot_binary()
GAME_DIR = build_config.GAME_DIR
_COPY_IGNORE = shutil.ignore_patterns(".godot", "build", "__pycache__", "tests")

# The font's native size is the Scale spec's hud_font_size (gADR-0013 — read, never
# hardcoded), the SAME authority the build reads. Press Start 2P is a square
# monospace, so "HP 100/100" (10 glyphs) renders at 10 * hud_font_size px at that
# native size (1:1) — the metric the styled-HUD visual-smoke checkpoint asserts on.
_CELL = int(
    game_config.scale_value(game_config.load_style_config(), "hud_font_size", GAME_DIR)
)
_EXPECTED_WIDTH = 10 * _CELL

# Load the committed HUD font and print whether it is a Font plus the rendered width
# of a known HUD string at the Scale-spec size (__SIZE__ is substituted per run).
_PROBE = """extends SceneTree
func _initialize() -> void:
	var f = load("res://assets/fonts/hud_font.fnt")
	if f == null:
		print("RESULT=LOAD_FAILED")
		quit()
		return
	var font := f as Font
	var w := font.get_string_size("HP 100/100", 0, -1, __SIZE__).x
	print("RESULT=OK is_font=%s class=%s width=%s" % [f is Font, f.get_class(), w])
	quit()
"""


@pytest.mark.engine
def test_hud_font_loads_in_godot(tmp_path: Path) -> None:
    project = tmp_path / "game"
    shutil.copytree(GAME_DIR, project, ignore=_COPY_IGNORE)

    imported = subprocess.run(
        [str(GODOT), "--headless", "--path", str(project), "--import"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert imported.returncode == 0, imported.stdout + imported.stderr

    probe = tmp_path / "probe.gd"
    probe.write_text(_PROBE.replace("__SIZE__", str(_CELL)), encoding="utf-8")
    run = subprocess.run(
        [str(GODOT), "--headless", "--path", str(project), "--script", str(probe)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = run.stdout
    assert "RESULT=OK" in out, run.stdout + run.stderr
    assert "is_font=true" in out, out  # the .fnt loads as a Godot Font
    assert "class=FontFile" in out, out  # imported bitmap font -> FontFile
    # 10 glyphs * the Scale-spec advance, unscaled at the native size.
    assert f"width={_EXPECTED_WIDTH}" in out, out
