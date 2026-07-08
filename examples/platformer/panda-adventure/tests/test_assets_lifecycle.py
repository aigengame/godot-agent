"""Fast unit tier for the asset-lifecycle tooling (P2-S1b, #478, gADR-0015).

Pins the pre-production infrastructure wave-3 consumes without reinventing:

- the **frames -> sheet packer** (loose frame files -> one spritesheet + a
  recorded frame layout, gADR-0015),
- the pure-Python **SpriteFrames.tres deriver** (the layout -> a byte-stable
  Godot ``SpriteFrames`` with per-frame ``AtlasTexture`` regions), and
- the **size-based Git-LFS gate** (an ``assets/**`` binary at/over the threshold
  ``T`` must be LFS-tracked, uniform across categories).

Pure Python (Pillow is a dev dependency; the LFS gate's core takes an injected
predicate, so no git is needed), so it runs in the CI
``not e2e and not engine and not acquire_live`` tier. The engine proof that a
derived ``.tres`` really loads in Godot is ``test_spriteframes_engine.py``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PIL import Image

import build_config
from assets import game_config, lifecycle, manifest
from assets.emitter import JsonManifestEmitter
from assets.lifecycle import OversizeAsset, find_unlfs_oversize
from assets.model import FrameLayout, ManifestEntry
from assets.packer import pack_frames
from assets.spriteframes import derive_spriteframes


# --------------------------------------------------------------------------- #
# Frames -> sheet packer (gADR-0015): loose frames in, one sheet + layout out.
# --------------------------------------------------------------------------- #


def _frames(dir: Path, count: int, dims: tuple[int, int]) -> list[Path]:
    """Synthesize ``count`` distinct solid PNG frames of ``dims`` (id-ordered)."""
    dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(count):
        p = dir / f"frame_{i:02d}.png"
        Image.new("RGBA", dims, (10 * i % 256, 40, 90, 255)).save(p)
        paths.append(p)
    return paths


def test_pack_frames_horizontal_strip(tmp_path: Path) -> None:
    """A small set packs into a single horizontal strip (default layout)."""
    frames = _frames(tmp_path / "in", 3, (40, 40))
    sheet = tmp_path / "player_run.png"
    layout = pack_frames(frames, sheet)

    assert layout == FrameLayout(frame_dims=(40, 40), columns=3, rows=1, count=3)
    with Image.open(sheet) as img:
        assert img.size == (120, 40)  # 3 frames wide, 1 tall


def test_pack_frames_grid_past_threshold(tmp_path: Path) -> None:
    """A set larger than the strip threshold packs into a near-square grid."""
    frames = _frames(tmp_path / "in", 9, (16, 16))  # > default threshold (8)
    sheet = tmp_path / "walk.png"
    layout = pack_frames(frames, sheet)

    assert layout == FrameLayout(frame_dims=(16, 16), columns=3, rows=3, count=9)
    with Image.open(sheet) as img:
        assert img.size == (48, 48)  # 3x3 grid


def test_pack_frames_rejects_mismatched_dims(tmp_path: Path) -> None:
    """Frames of differing sizes are a loud error, not a silently misaligned sheet."""
    frames = _frames(tmp_path / "in", 2, (40, 40))
    odd = tmp_path / "in" / "odd.png"
    Image.new("RGBA", (32, 32), (0, 0, 0, 255)).save(odd)
    with pytest.raises(ValueError, match="same size"):
        pack_frames([*frames, odd], tmp_path / "out.png")


def test_pack_frames_rejects_empty_set(tmp_path: Path) -> None:
    """An empty frame set is a clear error, not an opaque IndexError."""
    with pytest.raises(ValueError, match="no frames"):
        pack_frames([], tmp_path / "out.png")


# --------------------------------------------------------------------------- #
# Manifest — a sprite-set entry round-trips its frame layout (gADR-0015).
# --------------------------------------------------------------------------- #

_RUN_LAYOUT = FrameLayout(frame_dims=(32, 32), columns=6, rows=1, count=6)


def _sprite_entry() -> ManifestEntry:
    return ManifestEntry(
        id="player_run",
        path="res://assets/sprites/player_run.png",
        category="sprites",
        acquire_mode="search_download",
        source="kenney",
        license="CC0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        target_dims=(32, 32),
        source_url="https://example.test/player_run.png",
        frame_layout=_RUN_LAYOUT,
    )


def test_manifest_roundtrips_frame_layout(tmp_path: Path) -> None:
    """A sprite-set entry's frame layout survives emit -> load unchanged."""
    JsonManifestEmitter(tmp_path, "assets").emit(_sprite_entry())
    loaded = manifest.load_manifest(tmp_path, "assets")
    assert loaded["player_run"] == _sprite_entry()
    assert loaded["player_run"].frame_layout == _RUN_LAYOUT


def test_manifest_texture_entry_has_no_frame_layout(tmp_path: Path) -> None:
    """A plain texture entry omits frame_layout (it is a sprite-set-only field)."""
    entry = ManifestEntry(
        id="obstacle_crate",
        path="res://assets/textures/obstacle_crate.png",
        category="textures",
        acquire_mode="search_download",
        source="opengameart",
        license="CC0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        target_dims=(40, 40),
    )
    JsonManifestEmitter(tmp_path, "assets").emit(entry)
    frag = manifest.fragment_path(tmp_path, "assets", "textures")
    assert "frame_layout" not in frag.read_text()
    assert manifest.load_manifest(tmp_path, "assets")["obstacle_crate"] == entry


# --------------------------------------------------------------------------- #
# SpriteFrames deriver — layout -> a byte-stable Godot SpriteFrames .tres.
# --------------------------------------------------------------------------- #

_SHEET_RES = "res://assets/sprites/player_run.png"


def test_derive_spriteframes_regions_and_animation(tmp_path: Path) -> None:
    """The deriver emits one AtlasTexture per frame at the right region, and an
    animation that references each in order (gADR-0015)."""
    frames = _frames(tmp_path / "in", 3, (40, 40))
    layout = pack_frames(frames, tmp_path / "player_run.png")
    tres = derive_spriteframes(_SHEET_RES, layout, "run")

    assert tres.startswith('[gd_resource type="SpriteFrames" format=3]')
    assert f'[ext_resource type="Texture2D" path="{_SHEET_RES}"' in tres
    # One AtlasTexture sub-resource per frame, each keyed to its strip region.
    assert "region = Rect2(0, 0, 40, 40)" in tres
    assert "region = Rect2(40, 0, 40, 40)" in tres
    assert "region = Rect2(80, 0, 40, 40)" in tres
    # The animation is named for the state and references each frame in order.
    assert '"name": &"run"' in tres
    assert 'SubResource("AtlasTexture_run_0")' in tres
    assert 'SubResource("AtlasTexture_run_2")' in tres


def test_derive_spriteframes_grid_regions(tmp_path: Path) -> None:
    """A grid layout places frame k at (col*w, row*h) row-major (gADR-0015)."""
    frames = _frames(tmp_path / "in", 9, (16, 16))  # 3x3 grid
    layout = pack_frames(frames, tmp_path / "walk.png")
    tres = derive_spriteframes(_SHEET_RES, layout, "walk")

    assert "region = Rect2(0, 0, 16, 16)" in tres  # frame 0 -> (col 0, row 0)
    assert "region = Rect2(32, 0, 16, 16)" in tres  # frame 2 -> (col 2, row 0)
    assert "region = Rect2(0, 16, 16, 16)" in tres  # frame 3 -> (col 0, row 1)
    assert "region = Rect2(32, 32, 16, 16)" in tres  # frame 8 -> (col 2, row 2)


def test_derive_spriteframes_is_deterministic(tmp_path: Path) -> None:
    """Same input -> byte-identical output (a committed derived artifact)."""
    frames = _frames(tmp_path / "in", 4, (24, 24))
    layout = pack_frames(frames, tmp_path / "idle.png")
    a = derive_spriteframes(_SHEET_RES, layout, "idle")
    b = derive_spriteframes(_SHEET_RES, layout, "idle")
    assert a == b
    assert "uid://" not in a  # gda authors uid-free (gADR-0036 / gADR-0015)


# --------------------------------------------------------------------------- #
# Size-based Git-LFS gate (gADR-0015): >= T must be LFS-tracked, uniform.
# --------------------------------------------------------------------------- #

_T = 1_048_576  # the default threshold (1 MB)


def test_find_unlfs_oversize_flags_only_large_untracked() -> None:
    """A file at/over T that is NOT LFS-tracked is a violation; a tracked large
    file and any small file are fine — the rule is size-based and uniform."""
    files = [
        ("assets/music/bgm.ogg", 3_000_000),  # >= T, tracked -> ok
        ("assets/backgrounds/sky.png", 2_000_000),  # >= T, untracked -> VIOLATION
        ("assets/textures/crate.png", 5_000),  # < T -> ok (small pixel art)
    ]
    tracked = {"assets/music/bgm.ogg"}
    violations = find_unlfs_oversize(files, _T, lambda p: p in tracked)
    assert violations == [OversizeAsset("assets/backgrounds/sky.png", 2_000_000)]


def test_find_unlfs_oversize_threshold_is_inclusive() -> None:
    """A file exactly at T must be LFS-tracked (>= T, not > T)."""
    files = [("assets/audio/hit.wav", _T)]
    assert find_unlfs_oversize(files, _T, lambda p: False) == [
        OversizeAsset("assets/audio/hit.wav", _T)
    ]
    assert find_unlfs_oversize(files, _T, lambda p: True) == []


# --------------------------------------------------------------------------- #
# Size gate wiring: enumerate the real assets/ tree + the git check-attr predicate.
# --------------------------------------------------------------------------- #

GAME_DIR = build_config.GAME_DIR


def test_committed_asset_files_enumerates_the_assets_tree() -> None:
    """The enumerator lists real files under assets/ with their on-disk sizes."""
    files = dict(lifecycle.committed_asset_files(GAME_DIR))
    assert "assets/textures/obstacle_crate.png" in files
    assert files["assets/textures/obstacle_crate.png"] > 0


def test_validate_committed_asset_sizes_passes_on_real_repo() -> None:
    """The committed assets/ tree carries no >= T binary outside LFS (gADR-0015)."""
    lifecycle.validate_committed_asset_sizes(GAME_DIR, _T)  # no raise


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def test_validate_committed_asset_sizes_raises_on_untracked_large(
    tmp_path: Path,
) -> None:
    """A >= T asset with no LFS attribute fails the gate (born-in-LFS rule)."""
    _git(tmp_path, "init")
    big = tmp_path / "assets" / "textures" / "big.bin"
    big.parent.mkdir(parents=True)
    big.write_bytes(b"\0" * (_T + 16))
    with pytest.raises(lifecycle.AssetSizeError, match="big.bin"):
        lifecycle.validate_committed_asset_sizes(tmp_path, _T)


def test_validate_committed_asset_sizes_accepts_lfs_tracked_large(
    tmp_path: Path,
) -> None:
    """The same >= T asset PASSES once a matching LFS attribute covers it."""
    _git(tmp_path, "init")
    (tmp_path / ".gitattributes").write_text(
        "assets/**/*.bin filter=lfs diff=lfs merge=lfs -text\n", encoding="utf-8"
    )
    big = tmp_path / "assets" / "textures" / "big.bin"
    big.parent.mkdir(parents=True)
    big.write_bytes(b"\0" * (_T + 16))
    lifecycle.validate_committed_asset_sizes(tmp_path, _T)  # no raise


# --------------------------------------------------------------------------- #
# Threshold + .gitattributes: T is committed config; the seed tracks music in LFS.
# --------------------------------------------------------------------------- #


def test_style_config_carries_lfs_threshold() -> None:
    """T is pipeline-config spec-data in panda_adventure.style.json (gADR-0015)."""
    config = game_config.load_style_config()
    assert config.lfs_size_threshold_bytes == _T  # 1 MB default


def test_committed_repo_passes_the_configured_gate() -> None:
    """The committed assets tree passes the gate at the CONFIGURED threshold —
    the end-to-end wiring the CI test tier runs (gADR-0015)."""
    config = game_config.load_style_config()
    lifecycle.validate_committed_asset_sizes(GAME_DIR, config.lfs_size_threshold_bytes)


def test_gitattributes_tracks_music_dir_in_lfs() -> None:
    """The seeded .gitattributes tracks the BGM/music dir in LFS (gate-driven
    convention), while KB-scale pixel art stays in plain git (gADR-0015)."""
    tracked = lifecycle.git_lfs_tracked(GAME_DIR)
    assert tracked("assets/music/bgm_main.ogg")
    assert not tracked("assets/textures/obstacle_crate.png")
