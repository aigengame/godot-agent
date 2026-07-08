"""Fast unit tier for the asset pipeline's deterministic stages (P2-S1, #439).

Pins every stage that does NOT touch the network or an image-gen API — preprocess
(query/prompt render), postprocess (the Pillow conform transforms), the manifest
writer/reader, and the acquire interface with its boundary MOCKED — plus
``build_config``'s asset-manifest composition and the FK/no-dangling config-gate
validators (gADR-0014). Pure Python (Pillow is a dev dependency); no Godot, no
network, so it runs in the CI ``not e2e and not engine and not acquire_live`` tier.
The live acquire tier (real fetch / real generation) is ``test_assets_acquire_live``.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from PIL import Image

import build_config
from assets import game_config, manifest, pipeline, postprocess, preprocess
from assets.acquire import AcquireError, search_download
from assets.backends import BuiltinBackend, BuiltinImageGenUnavailable
from assets.emitter import JsonManifestEmitter
from assets.model import AcquireMode, ManifestEntry, Source

STYLE = game_config.load_style_config()


# --------------------------------------------------------------------------- #
# Preprocess — the style descriptor composed into a per-asset query / prompt.
# --------------------------------------------------------------------------- #


def test_build_spec_reads_target_dims_from_scale_spec() -> None:
    """The obstacle spec carries the Scale spec's obstacle_size (gADR-0013)."""
    spec = pipeline.build_spec_for(STYLE, "obstacle_crate")
    assert spec.category == "textures"
    assert spec.target_dims == (40, 40)  # scale_spec.json obstacle_size


def test_render_search_query_and_prompt_carry_style() -> None:
    """One spec renders BOTH a search query and a generation prompt (gADR-0014)."""
    spec = pipeline.build_spec_for(STYLE, "obstacle_crate")
    query = preprocess.render_search_query(spec)
    assert "obstacle crate" in query
    assert "pixel art" in query.lower()

    prompt = preprocess.render_generation_prompt(spec)
    assert "obstacle crate" in prompt
    assert STYLE.style.chroma_key in prompt  # solid-background instruction
    assert "40x40" in prompt  # the target size


# --------------------------------------------------------------------------- #
# Postprocess — the Pillow conform transforms.
# --------------------------------------------------------------------------- #


def _solid(size: tuple[int, int], color: tuple[int, int, int, int]) -> Image.Image:
    return Image.new("RGBA", size, color)


def test_postprocess_conforms_to_exact_dims(tmp_path: Path) -> None:
    """A large source is downscaled to the exact target dimensions."""
    src = tmp_path / "src.png"
    _solid((256, 256), (120, 90, 40, 255)).save(src)
    out = postprocess.postprocess_image(
        src, tmp_path / "out.png", (40, 40), STYLE.style.palette
    )
    with Image.open(out) as img:
        assert img.size == (40, 40)


def test_postprocess_quantizes_to_bounded_palette(tmp_path: Path) -> None:
    """Every output pixel is a bounded-palette color (no off-palette colors)."""
    src = tmp_path / "grad.png"
    grad = Image.new("RGB", (64, 64))
    grad.putdata(
        [(x * 4 % 256, y * 4 % 256, 128) for y in range(64) for x in range(64)]
    )
    grad.convert("RGBA").save(src)
    out = postprocess.postprocess_image(
        src, tmp_path / "out.png", (40, 40), STYLE.style.palette
    )
    allowed = {postprocess._hex_to_rgb(c) for c in STYLE.style.palette}
    with Image.open(out) as img:
        colors = img.convert("RGBA").getcolors(4096) or []
        used = {color[:3] for _count, color in colors if color[3] > 0}
    assert used <= allowed, used - allowed


def test_postprocess_binary_alpha(tmp_path: Path) -> None:
    """Semi-transparent input is conformed to a hard 1-bit alpha edge."""
    src = tmp_path / "semi.png"
    _solid((32, 32), (200, 100, 50, 100)).save(src)  # alpha 100 < threshold
    out = postprocess.postprocess_image(
        src, tmp_path / "out.png", (16, 16), STYLE.style.palette
    )
    with Image.open(out) as img:
        colors = img.convert("RGBA").getcolors(4096) or []
        alphas = {color[3] for _count, color in colors}
    assert alphas <= {0, 255}


def test_chroma_key_crop_keys_out_background() -> None:
    """The chroma-key stage removes the solid background and crops to content."""
    img = Image.new("RGBA", (20, 20), (255, 0, 255, 255))  # all magenta
    for y in range(6, 14):
        for x in range(6, 14):
            img.putpixel((x, y), (200, 120, 40, 255))  # a content block
    keyed = postprocess.chroma_key_crop(img, "#FF00FF")
    assert keyed.size == (8, 8)  # cropped to the content bbox
    assert keyed.getchannel("A").getextrema()[1] == 255  # content stayed opaque


# --------------------------------------------------------------------------- #
# Manifest — the JSON emitter/reader round-trip.
# --------------------------------------------------------------------------- #


def _entry(asset_id: str, category: str = "textures") -> ManifestEntry:
    return ManifestEntry(
        id=asset_id,
        path=f"res://assets/{category}/{asset_id}.png",
        category=category,
        acquire_mode="search_download",
        source="opengameart",
        license="CC0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        target_dims=(40, 40),
        source_url="https://example.test/x.png",
    )


def test_emit_and_load_manifest_roundtrip(tmp_path: Path) -> None:
    """An emitted entry reads back identically through load_manifest."""
    emitter = JsonManifestEmitter(tmp_path, "assets")
    emitter.emit(_entry("obstacle_crate"))
    loaded = manifest.load_manifest(tmp_path, "assets")
    assert loaded["obstacle_crate"] == _entry("obstacle_crate")


def test_emit_is_deterministic_and_sorted(tmp_path: Path) -> None:
    """Re-emitting sorts ids and is byte-stable (clean manifest diffs)."""
    emitter = JsonManifestEmitter(tmp_path, "assets")
    emitter.emit(_entry("zeta"))
    emitter.emit(_entry("alpha"))
    frag = manifest.fragment_path(tmp_path, "assets", "textures")
    doc = json.loads(frag.read_text())
    assert list(doc) == ["alpha", "zeta"]
    before = frag.read_text()
    JsonManifestEmitter(tmp_path, "assets").emit(_entry("alpha"))  # idempotent upsert
    assert frag.read_text() == before


# --------------------------------------------------------------------------- #
# Acquire — the two-mode interface with the boundary MOCKED.
# --------------------------------------------------------------------------- #

_SRC = Source(
    name="opengameart",
    kind="search-download",
    base_url="https://opengameart.org",
    default_license="CC0",
    license_url="https://creativecommons.org/publicdomain/zero/1.0/",
)


def test_search_download_records_provenance(tmp_path: Path) -> None:
    """A mocked fetch writes the raw file and records source/license/url."""
    spec = pipeline.build_spec_for(STYLE, "obstacle_crate")
    recipe = {"url": "https://example.test/crate.png"}
    result = search_download(
        spec,
        recipe,
        _SRC,
        tmp_path / "raw.png",
        allowed_licenses=("CC0", "CC-BY"),
        fetch=lambda url: b"PNGBYTES",
    )
    assert result.acquire_mode is AcquireMode.SEARCH_DOWNLOAD
    assert result.source == "opengameart"
    assert result.license == "CC0"
    assert result.source_url == "https://example.test/crate.png"
    assert (tmp_path / "raw.png").read_bytes() == b"PNGBYTES"


def test_search_download_rejects_disallowed_license(tmp_path: Path) -> None:
    """A non-CC0/CC-BY license is refused before any fetch (gADR-0014)."""
    spec = pipeline.build_spec_for(STYLE, "obstacle_crate")
    recipe = {"url": "https://example.test/x.png", "license": "GPL"}
    with pytest.raises(AcquireError):
        search_download(
            spec,
            recipe,
            _SRC,
            tmp_path / "raw.png",
            allowed_licenses=("CC0", "CC-BY"),
            fetch=lambda url: b"x",
        )


class _FakeBackend:
    """A stand-in generation backend: writes a synthetic PNG (mocks the API)."""

    name = "mcp:fake"

    def generate(self, prompt: str, out_path: Path) -> None:
        Image.new("RGBA", (128, 128), (255, 0, 255, 255)).save(out_path)


def test_builtin_backend_raises_without_capability(tmp_path: Path) -> None:
    """BuiltinBackend NEVER silently no-ops: no capability + no fallback raises the
    clear, user-facing error (gADR-0014) — the Claude Code path, proven in CI."""
    backend = BuiltinBackend(command=None, fallback=None)
    assert backend.available is False
    with pytest.raises(BuiltinImageGenUnavailable):
        backend.generate("a prompt", tmp_path / "out.png")


def test_builtin_backend_uses_configured_fallback(tmp_path: Path) -> None:
    """A configured fallback backend is used when the agent cannot generate."""
    backend = BuiltinBackend(command=None, fallback=_FakeBackend())
    backend.generate("a prompt", tmp_path / "out.png")
    with Image.open(tmp_path / "out.png") as img:
        assert img.size == (128, 128)  # the fallback produced it


def test_shipped_builtin_backend_is_unavailable_on_claude_code() -> None:
    """The COMMITTED config's builtin backend has no command/fallback, so on an
    agent without image generation it fails loudly (the demo's chosen posture)."""
    backend = game_config.make_builtin_backend(STYLE)
    assert backend.available is False


def test_acquire_asset_generation_mocked(tmp_path: Path) -> None:
    """The full pipeline via GENERATION with a mocked backend: prompt+backend
    recorded, output conformed to the target size, manifest emitted."""
    _stage_scale_spec(tmp_path)
    entry = pipeline.acquire_asset(
        STYLE,
        "obstacle_crate",
        game_root=tmp_path,
        mode=AcquireMode.GENERATION,
        backend=_FakeBackend(),
        raw_dir=tmp_path / "raw",
    )
    assert entry.acquire_mode == "generation"
    assert entry.backend == "mcp:fake"
    assert entry.prompt and "obstacle crate" in entry.prompt
    out = tmp_path / "assets" / "textures" / "obstacle_crate.png"
    with Image.open(out) as img:
        assert img.size == (40, 40)  # conformed to obstacle_size
    loaded = manifest.load_manifest(tmp_path, "assets")
    assert "obstacle_crate" in loaded


def test_acquire_asset_search_download_mocked(tmp_path: Path) -> None:
    """The full pipeline via SEARCH_DOWNLOAD with a mocked fetch."""
    _stage_scale_spec(tmp_path)
    png = tmp_path / "payload.png"
    Image.new("RGBA", (200, 200), (150, 100, 40, 255)).save(png)
    entry = pipeline.acquire_asset(
        STYLE,
        "obstacle_crate",
        game_root=tmp_path,
        fetch=lambda url: png.read_bytes(),
        raw_dir=tmp_path / "raw",
    )
    assert entry.acquire_mode == "search_download"
    assert entry.license == "CC0"
    out = tmp_path / "assets" / "textures" / "obstacle_crate.png"
    with Image.open(out) as img:
        assert img.size == (40, 40)


def _stage_scale_spec(root: Path) -> None:
    """Copy the committed scale_spec into an isolated game root for acquire."""
    dst = root / "data" / "json" / "scale_spec.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(
        (build_config.GAME_DIR / "data/json/scale_spec.json").read_text("utf-8"),
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- #
# build_config — id -> path composition and the FK/no-dangling config gate.
# --------------------------------------------------------------------------- #


def test_compose_asset_refs_resolves_id_to_path() -> None:
    """The builder resolves the authored manifest id to the single-homed path."""
    doc = {"obstacle_asset": "obstacle_crate"}
    manifest_map = build_config.load_asset_manifest()
    build_config.compose_asset_refs(doc, build_config._GRAVITY_JSON_REL, manifest_map)
    assert doc["obstacle_asset"] == "res://assets/textures/obstacle_crate.png"


def test_compose_asset_refs_passthrough() -> None:
    """An empty ref stays empty; an unknown id passes through (the gate catches it)."""
    doc = {"obstacle_asset": ""}
    build_config.compose_asset_refs(doc, build_config._GRAVITY_JSON_REL, {})
    assert doc["obstacle_asset"] == ""
    doc = {"obstacle_asset": "not_in_manifest"}
    build_config.compose_asset_refs(doc, build_config._GRAVITY_JSON_REL, {})
    assert doc["obstacle_asset"] == "not_in_manifest"


def test_gravity_tres_carries_the_resolved_path() -> None:
    """The committed gravity_config.tres renders the resolved obstacle path."""
    tres = (build_config.GAME_DIR / "data/generated/gravity_config.tres").read_text()
    assert 'obstacle_asset = "res://assets/textures/obstacle_crate.png"' in tres


def test_validate_asset_refs_passes_on_committed_authority() -> None:
    """The committed manifest satisfies FK integrity + no-dangling (gADR-0014)."""
    m = build_config.validate_asset_refs()
    assert "obstacle_crate" in m


def test_committed_manifest_has_no_orphans() -> None:
    """Wave-close DoD: every recorded asset is referenced (gADR-0014)."""
    assert build_config.asset_ref_orphans() == []


def test_fk_integrity_fails_on_unrecorded_reference(tmp_path: Path) -> None:
    """A referenced id with no manifest entry fails the FK gate."""
    root = _copy_authority(tmp_path)
    # Drop the manifest entry the authority references.
    (root / "assets" / "manifest" / "textures.json").write_text("{}\n", "utf-8")
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_asset_refs(root)


def test_no_dangling_fails_on_missing_file(tmp_path: Path) -> None:
    """A manifest path with no file on disk fails the no-dangling gate."""
    root = _copy_authority(tmp_path)
    (root / "assets" / "textures" / "obstacle_crate.png").unlink()
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_asset_refs(root)


def _copy_authority(root: Path) -> Path:
    """Stage the committed authority + assets tree into an isolated root."""
    import shutil

    src = build_config.GAME_DIR
    for rel in {s.json_rel for s in build_config.SPECS} | {
        s.schema_rel for s in build_config.SPECS
    }:
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text((src / rel).read_text("utf-8"), encoding="utf-8")
    shutil.copytree(src / "assets", root / "assets")
    return root
