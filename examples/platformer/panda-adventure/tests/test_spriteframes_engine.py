"""Engine proof — a derived SpriteFrames.tres really loads in Godot (P2-S1b, #478).

The fast tier ``test_assets_lifecycle.py`` pins the deriver's TEXT (regions,
animation structure, determinism); it cannot prove the emitted ``.tres`` is a
*valid Godot resource*. This engine-tier test closes that gap: it packs a fixture
frame set into a project copy, derives the ``SpriteFrames`` next to it, imports the
copy (so the sheet texture the ``AtlasTexture`` sub-resources reference resolves),
then loads the resource in a headless Godot ``SceneTree`` and asserts the frame
count and that frame 0 is an ``AtlasTexture`` at the expected region (gADR-0015).

``engine`` marker: fails loudly without a Godot binary (conftest), deselected in
the fast CI tier and run in the ``godot-e2e`` job / locally.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from gda.binary import resolve_godot_binary

import build_config

GODOT = resolve_godot_binary()
GAME_DIR = build_config.GAME_DIR
_COPY_IGNORE = shutil.ignore_patterns(".godot", "build", "__pycache__", "tests")

# A headless SceneTree script: load the derived resource and print its frame count
# and frame-0 atlas region so the test can assert on stdout.
_PROBE = """extends SceneTree
func _initialize() -> void:
	var sf = load("res://content/assets/sprites/hero_run_frames.tres")
	if sf == null:
		print("RESULT=LOAD_FAILED")
		quit()
		return
	var tex = sf.get_frame_texture("run", 0)
	var is_atlas := tex is AtlasTexture
	print("RESULT=OK count=%d atlas=%s region=%s" % [
		sf.get_frame_count("run"), is_atlas, tex.region if is_atlas else Rect2()])
	quit()
"""


def _frames(dir: Path, count: int, dims: tuple[int, int]) -> list[Path]:
    dir.mkdir(parents=True, exist_ok=True)
    out = []
    for i in range(count):
        p = dir / f"frame_{i:02d}.png"
        Image.new("RGBA", dims, (10 * i % 256, 40, 90, 255)).save(p)
        out.append(p)
    return out


@pytest.mark.engine
def test_derived_spriteframes_loads_in_godot(tmp_path: Path) -> None:
    from assets.packer import pack_frames
    from assets.spriteframes import derive_spriteframes

    project = tmp_path / "game"
    shutil.copytree(GAME_DIR, project, ignore=_COPY_IGNORE)

    # Pack a fixture frame set into the copy and derive its SpriteFrames next to it.
    sprites = project / "content" / "assets" / "sprites"
    layout = pack_frames(
        _frames(tmp_path / "in", 5, (16, 16)), sprites / "hero_run.png"
    )
    (sprites / "hero_run_frames.tres").write_text(
        derive_spriteframes("res://content/assets/sprites/hero_run.png", layout, "run"),
        encoding="utf-8",
    )

    # Import so the sheet texture (the AtlasTexture ext_resource) resolves on load.
    imported = subprocess.run(
        [str(GODOT), "--headless", "--path", str(project), "--import"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert imported.returncode == 0, imported.stdout + imported.stderr

    probe = tmp_path / "probe.gd"
    probe.write_text(_PROBE, encoding="utf-8")
    run = subprocess.run(
        [str(GODOT), "--headless", "--path", str(project), "--script", str(probe)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = run.stdout
    assert "RESULT=OK" in out, run.stdout + run.stderr
    assert "count=5" in out, out  # all 5 frames sequenced into the animation
    assert "atlas=true" in out, out  # frame 0 is an AtlasTexture region of the sheet
    # Frame 0's region is the top-left 16x16 box (Godot prints Rect2 as P/S).
    assert "region=[P: (0.0, 0.0), S: (16.0, 16.0)]" in out, out
