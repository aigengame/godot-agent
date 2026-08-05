"""Fast unit tier for the bitmap-font deriver (P2-S9, #445, gADR-0014).

Pins :func:`assets.fonts.derive_bitmap_font` — a glyph sheet's ``res://`` path +
its uniform-grid :class:`~assets.model.FrameLayout` into a byte-stable AngelCode
``.fnt`` (the UI-branch analogue of the SpriteFrames deriver). Pure Python (no
Godot, no IO), so it runs in the CI ``not e2e and not engine and not
acquire_live`` tier; the engine proof that the emitted ``.fnt`` really loads as a
Godot ``Font`` is ``test_fonts_engine.py``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

import build_config
import panda_assets
from assets import config as assets_config
from assets.fonts import derive_bitmap_font
from assets.manifest import load_manifest
from assets.model import FrameLayout
from panda_assets import font_build

_SHEET_RES = "res://content/assets/fonts/hud_font.png"

# The font's native square-cell size comes from the Scale spec's hud_font_size
# (gADR-0013 — the single size authority), the SAME value the build reads. Asserting
# against it (never a literal 16) makes these tests catch drift if the font stopped
# tracking the Scale spec.
_CELL = int(
    assets_config.scale_value(
        assets_config.load_style_config(panda_assets.STYLE_PATH),
        "hud_font_size",
        build_config.GAME_DIR,
    )
)


def _grid() -> FrameLayout:
    """The committed HUD font's grid: 16 columns x 6 rows of square cells sized by
    the Scale spec's ``hud_font_size`` (gADR-0013), 95 printable-ASCII glyphs."""
    return FrameLayout(frame_dims=(_CELL, _CELL), columns=16, rows=6, count=95)


def test_header_declares_native_size_and_relative_page() -> None:
    """The ``.fnt`` header carries the native size (= the Scale-spec cell) and
    references the sheet by its RELATIVE basename (BMFont page resolution), not the
    res:// path — self-contained beside its page (gADR-0014)."""
    fnt = derive_bitmap_font(_SHEET_RES, _grid(), first_codepoint=0x20)
    assert fnt.startswith(f'info face="hud_font" size={_CELL}')
    assert (
        f"common lineHeight={_CELL} base={_CELL - 3} "
        f"scaleW={16 * _CELL} scaleH={6 * _CELL} pages=1 packed=0" in fnt
    )
    assert 'page id=0 file="hud_font.png"' in fnt  # basename, never res://
    assert "res://" not in fnt
    assert "chars count=95" in fnt


def test_glyphs_map_codepoints_to_row_major_cells() -> None:
    """Cell ``k`` holds codepoint ``first + k`` at (col*w, row*h), row-major —
    a monospace advance per glyph (gADR-0014)."""
    fnt = derive_bitmap_font(_SHEET_RES, _grid(), first_codepoint=0x20)
    # Cell 0 -> U+0020 (space) at the sheet origin.
    assert (
        f"char id=32 x=0 y=0 width={_CELL} height={_CELL} xoffset=0 yoffset=0 "
        f"xadvance={_CELL} page=0 chnl=15" in fnt
    )
    # Cell 16 wraps to row 1 col 0 -> codepoint 0x30 ('0') at (0, cell).
    assert f"char id=48 x=0 y={_CELL} width={_CELL} height={_CELL}" in fnt
    # Cell 17 -> '1' at col 1 row 1 -> (cell, cell).
    assert f"char id=49 x={_CELL} y={_CELL} width={_CELL} height={_CELL}" in fnt
    assert fnt.count("char id=") == 95


def test_is_deterministic_and_uid_free() -> None:
    """Same input -> byte-identical output, no ``uid`` (a committed derived
    artifact; gda authors uid-free, gADR-0036)."""
    a = derive_bitmap_font(_SHEET_RES, _grid(), first_codepoint=0x20)
    b = derive_bitmap_font(_SHEET_RES, _grid(), first_codepoint=0x20)
    assert a == b
    assert "uid://" not in a


def test_size_base_and_advance_overrides() -> None:
    """The native size, baseline, and monospace advance are overridable per
    call (the deriver retune knobs, like the SpriteFrames speed/loop)."""
    layout = FrameLayout(frame_dims=(8, 8), columns=8, rows=2, count=10)
    fnt = derive_bitmap_font(
        _SHEET_RES, layout, first_codepoint=0x41, size=8, base=7, advance=6
    )
    assert 'info face="hud_font" size=8' in fnt
    assert "common lineHeight=8 base=7" in fnt
    assert "char id=65 x=0 y=0 width=8 height=8 xoffset=0 yoffset=0 xadvance=6" in fnt
    assert fnt.count("char id=") == 10


def test_committed_hud_font_fnt_is_a_fresh_derive() -> None:
    """The committed ``hud_font.fnt`` is byte-identical to a fresh derive from the
    manifest's recorded layout — the committed derived artifact stays in sync with
    the deriver (the SpriteFrames freshness argument, gADR-0014/gADR-0015)."""
    entry = load_manifest(build_config.GAME_DIR, "content/assets")["hud_font"]
    assert entry.frame_layout is not None
    expected = derive_bitmap_font(
        _SHEET_RES, entry.frame_layout, first_codepoint=font_build.FIRST_CODEPOINT
    )
    committed = (build_config.GAME_DIR / "content" / "assets" / "fonts" / "hud_font.fnt").read_text(
        encoding="utf-8"
    )
    assert committed == expected


def test_documented_rebuild_command_runs_and_regenerates_valid_assets(
    tmp_path: Path,
) -> None:
    """The DOCUMENTED re-derivation command runs and regenerates valid font assets.

    font_build uses package imports, so it must run as a MODULE
    (``PYTHONPATH=tools python -m panda_assets.font_build``) — ``python
    tools/panda_assets/font_build.py`` fails with ``ImportError``. This runs the
    exact documented command against an ISOLATED copy of the project — NEVER the
    tracked tree, so the test can neither discard a developer's uncommitted edits
    nor leave the worktree dirty on failure — and asserts (a) it exits 0, (b) the
    TEXT artifacts (the ``.fnt`` layout + the manifest) match the committed ones:
    they describe the glyph GRID, not pixels, so they ARE byte-deterministic, and
    (c) the rendered ``.png`` sheet is a valid atlas at the Scale-spec grid size.
    The PNG is deliberately NOT asserted byte-identical: freetype's rasterization
    is not byte-reproducible across freetype versions/platforms (gADR-0015), so the
    committed sheet is a valid committed artifact, not a cross-env-reproducible
    one. (No network — the injected fetch reads the in-repo TTF.)"""
    src = build_config.GAME_DIR
    game = tmp_path / "game"
    # Copy ONLY what build() + the style config + the injected fetch read, so the
    # command writes into the copy (the copied style.json's game_root resolves to
    # the copy's root, gADR-0019): the tools/ packages (framework + plug-in with
    # the style config), the Scale spec (the native size authority), and the
    # source TTF (+ its license).
    shutil.copytree(
        src / "tools", game / "tools", ignore=shutil.ignore_patterns("__pycache__")
    )
    (game / "content" / "data" / "json").mkdir(parents=True)
    shutil.copy(src / "content" / "data" / "json" / "scale_spec.json", game / "content" / "data" / "json")
    (game / "content" / "assets" / "fonts").mkdir(parents=True)
    for name in ("PressStart2P-Regular.ttf", "OFL.txt"):
        shutil.copy(src / "content" / "assets" / "fonts" / name, game / "content" / "assets" / "fonts")

    env = {**os.environ, "PYTHONPATH": str(game / "tools")}
    run = subprocess.run(
        [sys.executable, "-m", "panda_assets.font_build"],
        cwd=game,
        env=env,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stdout + run.stderr

    # The .fnt layout + manifest describe the grid, not pixels — byte-deterministic, so
    # the copy's fresh derive is byte-identical to the committed artifacts.
    for rel in (
        "content/assets/fonts/hud_font.fnt",
        "content/assets/manifest/fonts.json",
    ):
        assert (game / rel).read_bytes() == (src / rel).read_bytes(), (
            f"{rel} is not byte-stable across a fresh re-derivation"
        )
    # The rendered sheet is a valid atlas at the Scale-spec grid (structure, not bytes
    # — the freetype raster is not byte-reproducible across versions).
    with Image.open(game / "content" / "assets" / "fonts" / "hud_font.png") as sheet:
        assert sheet.format == "PNG"
        assert sheet.size == (16 * _CELL, 6 * _CELL)
