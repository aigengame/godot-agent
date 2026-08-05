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
import panda_assets
from assets import config as assets_config
from assets import lifecycle, manifest, pipeline
from assets.emitter import JsonManifestEmitter
from assets.lifecycle import (
    LicenseModeError,
    LicenseModeViolation,
    OversizeAsset,
    find_license_mode_violations,
    find_unlfs_oversize,
)
from assets.model import FrameLayout, ManifestEntry, SpriteAnimation
from assets.packer import pack_frames
from assets.spriteframes import derive_spriteframes, derive_spriteframes_set


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
        path="res://content/assets/sprites/player_run.png",
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
        path="res://content/assets/textures/obstacle_crate.png",
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

_SHEET_RES = "res://content/assets/sprites/player_run.png"


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
# Multi-animation deriver (P2-S5, #443): several per-state sheets -> ONE
# SpriteFrames an AnimatedSprite2D plays by name (idle/run/jump/...).
# --------------------------------------------------------------------------- #


def _anim(
    name: str, count: int, dims: tuple[int, int], *, loop: bool = True, speed=8.0
):
    return SpriteAnimation(
        name=name,
        sheet_res_path=f"res://content/assets/sprites/player_{name}.png",
        layout=FrameLayout(frame_dims=dims, columns=count, rows=1, count=count),
        speed=speed,
        loop=loop,
    )


def test_derive_spriteframes_set_composes_named_animations() -> None:
    """A set derives one ext_resource per sheet and one named, per-state animation
    with its own frames, regions, and loop flag (gADR-0015/#443)."""
    tres = derive_spriteframes_set(
        [
            _anim("idle", 2, (48, 64), loop=True),
            _anim("fire", 3, (48, 64), loop=False, speed=12.0),
        ]
    )
    assert tres.startswith('[gd_resource type="SpriteFrames" format=3]')
    # One ext_resource per state's sheet, deterministically id'd "{i+1}_{name}".
    assert (
        '[ext_resource type="Texture2D" path="res://content/assets/sprites/player_idle.png" id="1_idle"]'
        in tres
    )
    assert (
        '[ext_resource type="Texture2D" path="res://content/assets/sprites/player_fire.png" id="2_fire"]'
        in tres
    )
    # Each state's AtlasTexture regions reference its own sheet.
    assert 'atlas = ExtResource("1_idle")' in tres
    assert 'atlas = ExtResource("2_fire")' in tres
    assert "region = Rect2(96, 0, 48, 64)" in tres  # fire frame 2
    # Both animations land in the SpriteFrames, named + with their loop flag.
    assert '"name": &"idle"' in tres and '"loop": true' in tres
    assert '"name": &"fire"' in tres and '"loop": false' in tres
    assert '"speed": 12.0' in tres
    assert 'SubResource("AtlasTexture_idle_1")' in tres
    assert 'SubResource("AtlasTexture_fire_2")' in tres


def test_derive_spriteframes_set_is_deterministic_and_uid_free() -> None:
    """Same states -> byte-identical, uid-free output (a committed derived artifact)."""
    states = [_anim("idle", 2, (16, 16)), _anim("run", 4, (16, 16))]
    a = derive_spriteframes_set(states)
    b = derive_spriteframes_set(states)
    assert a == b
    assert "uid://" not in a


def test_derive_spriteframes_set_rejects_empty() -> None:
    """A set with no animation states is a clear error, not empty malformed text."""
    with pytest.raises(ValueError, match="no animation states"):
        derive_spriteframes_set([])


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
    """The enumerator lists real files under content/assets with their sizes."""
    files = dict(lifecycle.committed_asset_files(GAME_DIR, "content/assets"))
    assert "content/assets/textures/obstacle_crate.png" in files
    assert files["content/assets/textures/obstacle_crate.png"] > 0


def test_validate_committed_asset_sizes_passes_on_real_repo() -> None:
    """The committed Content assets carry no >= T binary outside LFS."""
    lifecycle.validate_committed_asset_sizes(
        GAME_DIR, _T, assets_root="content/assets"
    )


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def _commit_binary(root: Path, rel: str, size: int) -> Path:
    """Write and `git add` a binary file (NUL bytes -> binary) of `size` at rel."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x89PNG\r\n" + b"\0" * size)
    _git(root, "add", rel)
    return p


def test_size_gate_flags_tracked_binary_without_lfs(tmp_path: Path) -> None:
    """A COMMITTED (tracked) binary >= T with no LFS attribute fails the gate."""
    _git(tmp_path, "init")
    _commit_binary(tmp_path, "assets/textures/big.png", _T)
    with pytest.raises(lifecycle.AssetSizeError, match="big.png"):
        lifecycle.validate_committed_asset_sizes(tmp_path, _T)


def test_size_gate_accepts_lfs_tracked_binary(tmp_path: Path) -> None:
    """The same >= T binary PASSES once a matching LFS attribute covers it."""
    _git(tmp_path, "init")
    (tmp_path / ".gitattributes").write_text(
        "assets/**/*.png filter=lfs diff=lfs merge=lfs -text\n", encoding="utf-8"
    )
    _git(tmp_path, "add", ".gitattributes")
    _commit_binary(tmp_path, "assets/textures/big.png", _T)
    lifecycle.validate_committed_asset_sizes(tmp_path, _T)  # no raise


def test_size_gate_ignores_untracked_large_file(tmp_path: Path) -> None:
    """An UNTRACKED (uncommitted) large binary is not the gate's concern — the
    rule is about COMMITTED assets, so a local scratch file must not fail it."""
    _git(tmp_path, "init")
    scratch = tmp_path / "assets" / "textures" / "scratch.png"
    scratch.parent.mkdir(parents=True)
    scratch.write_bytes(b"\x89PNG\r\n" + b"\0" * _T)  # NOT git-added
    lifecycle.validate_committed_asset_sizes(tmp_path, _T)  # no raise


def test_size_gate_ignores_large_text_asset(tmp_path: Path) -> None:
    """A large TRACKED text asset is not forced into LFS — the rule is
    binary-only (a big generated JSON stays diff-friendly plain git)."""
    _git(tmp_path, "init")
    big = tmp_path / "assets" / "data" / "huge.json"
    big.parent.mkdir(parents=True)
    big.write_text("[" + ",".join(["0"] * _T) + "]", encoding="utf-8")  # > T, no NUL
    _git(tmp_path, "add", "assets/data/huge.json")
    lifecycle.validate_committed_asset_sizes(tmp_path, _T)  # no raise


# --------------------------------------------------------------------------- #
# Threshold + .gitattributes: T is committed config; the seed tracks music in LFS.
# --------------------------------------------------------------------------- #


def test_style_config_carries_lfs_threshold() -> None:
    """T is pipeline-config spec-data in the plug-in's style.json (gADR-0015)."""
    config = assets_config.load_style_config(panda_assets.STYLE_PATH)
    assert config.lfs_size_threshold_bytes == _T  # 1 MB default


def test_committed_repo_passes_the_configured_gate() -> None:
    """The committed assets tree passes the gate at the CONFIGURED threshold —
    the end-to-end wiring the CI test tier runs (gADR-0015)."""
    config = assets_config.load_style_config(panda_assets.STYLE_PATH)
    lifecycle.validate_committed_asset_sizes(
        GAME_DIR,
        config.lfs_size_threshold_bytes,
        assets_root=config.assets_root,
    )


def test_gitattributes_tracks_music_dir_in_lfs() -> None:
    """The seeded .gitattributes tracks the BGM/music dir in LFS (gate-driven
    convention), while KB-scale pixel art stays in plain git (gADR-0015)."""
    tracked = lifecycle.git_lfs_tracked(GAME_DIR)
    assert tracked("content/assets/music/bgm_main.ogg")
    assert not tracked("content/assets/textures/obstacle_crate.png")


# --------------------------------------------------------------------------- #
# Config-gate wiring: the size gate runs from build_config, not only tests.
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# License/acquire-mode consistency gate (gADR-0015 §5d): a generated asset records
# its BACKEND's usage terms, a downloaded asset a download license (CC0/CC-BY).
# --------------------------------------------------------------------------- #

_DOWNLOAD = ("CC0", "CC-BY")


def test_license_gate_generation_backend_terms_pass() -> None:
    """A generation-mode entry with its backend's usage terms is consistent."""
    entries = [("player", "generation", "Gemini-Generated")]
    assert find_license_mode_violations(entries, _DOWNLOAD) == []


def test_license_gate_generation_mislabeled_download_is_caught() -> None:
    """A generated asset mislabeled with a DOWNLOAD license (CC0) is a violation —
    the exact review finding (gADR-0015 §5d): generated != downloaded."""
    entries = [("player", "generation", "CC0")]
    violations = find_license_mode_violations(entries, _DOWNLOAD)
    assert len(violations) == 1
    assert violations[0] == LicenseModeViolation(
        "player", "generation", "CC0", violations[0].reason
    )
    assert "backend" in violations[0].reason


def test_license_gate_generation_empty_license_is_caught() -> None:
    """A generated asset with no recorded license is a violation (must record terms)."""
    assert len(find_license_mode_violations([("x", "generation", "")], _DOWNLOAD)) == 1


def test_license_gate_search_download_requires_download_license() -> None:
    """A downloaded asset must carry a download license: CC0 passes, a generation
    token on a downloaded asset is caught (the rule is symmetric)."""
    assert (
        find_license_mode_violations([("o", "search_download", "CC0")], _DOWNLOAD) == []
    )
    caught = find_license_mode_violations(
        [("o", "search_download", "Gemini-Generated")], _DOWNLOAD
    )
    assert len(caught) == 1


def test_validate_license_modes_raises_and_names_the_asset() -> None:
    """The wired gate raises LicenseModeError naming the offending asset."""
    from assets import lifecycle

    with pytest.raises(LicenseModeError, match="player"):
        lifecycle.validate_license_modes([("player", "generation", "CC0")], _DOWNLOAD)


def test_build_config_license_gate_passes_on_committed_repo() -> None:
    """The committed manifest is consistent: the Obstacle is a CC0 download, the
    Player set records its Gemini generation terms (the wiring the build runs)."""
    build_config.validate_asset_licenses()  # no raise


def test_build_config_license_gate_catches_mislabeled_generation(
    tmp_path: Path,
) -> None:
    """`build_config.validate_asset_licenses` fails a manifest that records a
    generation-mode asset under a download license (general — reused by every
    asset slice, e.g. #442's generated items)."""
    frag = tmp_path / "content" / "assets" / "manifest" / "sprites.json"
    frag.parent.mkdir(parents=True)
    frag.write_text(
        '{"bad": {"acquire_mode": "generation", "license": "CC0"}}\n',
        encoding="utf-8",
    )
    with pytest.raises(LicenseModeError, match="bad"):
        build_config.validate_asset_licenses(tmp_path)


def test_build_config_size_gate_passes_on_committed_repo() -> None:
    """build_config exposes the size gate at the config gate, reading T from the
    committed Style descriptor; the committed repo passes (review S1)."""
    build_config.validate_asset_sizes()  # no raise


def test_build_config_main_enforces_the_size_gate(monkeypatch) -> None:
    """`python scripts/build_config.py` (main) mechanically enforces the size gate
    — a violation fails the authoritative build, not merely an optional test path
    (review S1). Proven by making the gate raise and asserting main propagates it
    before any .tres is written."""

    def _boom(root: Path = build_config.GAME_DIR):
        raise lifecycle.AssetSizeError("size gate ran from main")

    monkeypatch.setattr(build_config, "validate_asset_sizes", _boom)
    with pytest.raises(lifecycle.AssetSizeError, match="size gate ran from main"):
        build_config.main()


# --------------------------------------------------------------------------- #
# Pipeline wiring: one orchestration entry packs + records a sprite set, so
# wave-3 slices consume the tooling without re-inventing the choreography.
# --------------------------------------------------------------------------- #


def test_pack_sprite_set_packs_sheet_and_emits_entry(tmp_path: Path) -> None:
    """`pack_sprite_set` orchestrates loose frames -> committed sheet ->
    manifest sprite-set entry (with frame_layout) in one call (review Spec-1)."""
    frames = _frames(tmp_path / "in", 4, (16, 16))
    sheet = tmp_path / "assets" / "sprites" / "hero_run.png"
    emitter = JsonManifestEmitter(tmp_path, "assets")

    entry = pipeline.pack_sprite_set(
        frames,
        sheet,
        "res://content/assets/sprites/hero_run.png",
        "hero_run",
        "sprites",
        source="kenney",
        license_name="CC0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        emitter=emitter,
    )

    # The committed sheet exists at the given path.
    with Image.open(sheet) as img:
        assert img.size == (64, 16)  # 4 frames wide
    # The returned entry carries the layout + provenance.
    assert entry.frame_layout == FrameLayout((16, 16), 4, 1, 4)
    assert (entry.id, entry.category, entry.license) == ("hero_run", "sprites", "CC0")
    assert entry.target_dims == (16, 16)  # defaults to the frame box
    # It was emitted into the manifest, round-tripping the layout.
    loaded = manifest.load_manifest(tmp_path, "assets")
    assert loaded["hero_run"].frame_layout == FrameLayout((16, 16), 4, 1, 4)


def test_pack_sprite_set_can_skip_emit(tmp_path: Path) -> None:
    """With no emitter the sheet is still packed but nothing is written (a caller
    that only wants the sheet + entry, e.g. a dry run)."""
    frames = _frames(tmp_path / "in", 2, (24, 24))
    sheet = tmp_path / "out" / "walk.png"
    entry = pipeline.pack_sprite_set(
        frames,
        sheet,
        "res://content/assets/sprites/walk.png",
        "walk",
        "sprites",
        source="kenney",
        license_name="CC0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
    )
    assert sheet.exists()
    assert entry.frame_layout == FrameLayout((24, 24), 2, 1, 2)
    assert manifest.load_manifest(tmp_path, "assets") == {}  # nothing emitted
