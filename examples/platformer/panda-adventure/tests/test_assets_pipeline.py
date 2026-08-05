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
from PIL import Image, ImageDraw

import build_config
import panda_assets
from assets import cli
from assets import config as assets_config
from assets import manifest, pipeline, postprocess, preprocess
from assets.acquire import AcquireError, search_download
from assets.backends import (
    BuiltinBackend,
    BuiltinImageGenUnavailable,
    GenerationError,
    McpBackend,
)
from assets.emitter import JsonManifestEmitter
from assets.model import AcquireMode, ManifestEntry, Source

STYLE = assets_config.load_style_config(panda_assets.STYLE_PATH)


# --------------------------------------------------------------------------- #
# Preprocess — the style descriptor composed into a per-asset query / prompt.
# --------------------------------------------------------------------------- #


def test_build_spec_reads_target_dims_from_scale_spec() -> None:
    """The obstacle spec carries the Scale spec's obstacle_size (gADR-0013)."""
    spec = pipeline.build_spec_for(STYLE, "obstacle_crate")
    assert spec.category == "textures"
    assert spec.target_dims == (40, 40)  # scale_spec.json obstacle_size


def test_target_dims_resolves_a_nested_scale_key() -> None:
    """A dotted scale_key addresses a nested Scale-spec box (P2-S3, #442).

    The per-item Pickup boxes live under ``pickup_sizes`` — a Pickup spec points
    at ``pickup_sizes.<item>`` and resolves to that box; a plain (single-segment)
    key still resolves the top-level ``player_projectile_size`` (gADR-0013).
    """
    assert assets_config.target_dims(STYLE, "pickup_sizes.bun") == (18, 14)
    assert assets_config.target_dims(STYLE, "pickup_sizes.wine") == (12, 20)
    assert assets_config.target_dims(STYLE, "player_projectile_size") == (18, 6)
    with pytest.raises(assets_config.ConfigError):
        assets_config.target_dims(STYLE, "pickup_sizes.nope")


def test_pickup_and_bolt_specs_read_their_nested_dims() -> None:
    """The wired P2-S3 specs carry their Scale-spec box (#442, gADR-0013)."""
    assert pipeline.build_spec_for(STYLE, "pickup_gold").target_dims == (14, 14)
    assert pipeline.build_spec_for(STYLE, "laser_bolt").target_dims == (18, 6)


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


def test_recipe_subject_and_hint_override_the_prompt() -> None:
    """A recipe's subject/category_hint override the id-derived subject and the
    shared category hint, so a namespaced item id (pickup_bun) generates a food
    icon rather than an environment prop (#442). Assets without overrides keep the
    id-derived subject and the category's shared hint."""
    bun = pipeline.build_spec_for(STYLE, "pickup_bun")
    assert bun.subject_terms == "steamed bun, a round pale bread roll food"
    bun_prompt = preprocess.render_generation_prompt(bun)
    assert "steamed bun" in bun_prompt
    assert "environment prop" not in bun_prompt  # the textures hint was overridden

    obstacle = pipeline.build_spec_for(STYLE, "obstacle_crate")
    assert obstacle.subject_terms == "obstacle crate"  # no override -> humanized id
    assert "environment prop" in preprocess.render_generation_prompt(obstacle)


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


def test_detect_background_key_samples_the_corners() -> None:
    """A near-magenta solid field (a backend approximating the chroma color) is
    keyed on the ACTUAL corner color, not the fixed configured key (#442)."""
    img = Image.new("RGBA", (32, 32), (215, 67, 136, 255))  # Gemini-ish pink
    for y in range(10, 22):
        for x in range(10, 22):
            img.putpixel((x, y), (240, 220, 180, 255))  # a pale centered subject
    key = postprocess.detect_background_key(img, "#FF00FF")
    assert key.lower() == "#d74388"  # the sampled background, not the fallback
    keyed = postprocess.chroma_key_crop(img, key, tolerance=60)
    assert keyed.size == (12, 12)  # cropped to the pale subject
    assert keyed.getchannel("A").getextrema()[1] == 255  # subject stayed opaque


def test_detect_background_key_falls_back_when_corners_disagree() -> None:
    """No solid field (corners differ) -> the configured key is used unchanged."""
    img = Image.new("RGBA", (4, 4))
    img.putpixel((0, 0), (255, 0, 255, 255))
    img.putpixel((3, 0), (0, 255, 0, 255))
    img.putpixel((0, 3), (0, 0, 255, 255))
    img.putpixel((3, 3), (255, 255, 0, 255))
    assert postprocess.detect_background_key(img, "#123456") == "#123456"


def test_postprocess_keys_a_near_magenta_generated_background(tmp_path: Path) -> None:
    """End to end: a generated subject on an APPROXIMATE magenta field conforms to a
    transparent-background pixel-art icon (the Gemini pickups' path, #442)."""
    src = tmp_path / "gen.png"
    img = Image.new("RGBA", (128, 128), (238, 40, 150, 255))  # not exactly #FF00FF
    # A ROUND subject (like the real bun): its bounding box has transparent corners.
    ImageDraw.Draw(img).ellipse((34, 34, 94, 94), fill=(235, 220, 175, 255))
    img.save(src)
    out = postprocess.postprocess_image(
        src, tmp_path / "out.png", (18, 14), STYLE.style.palette, chroma_key="#FF00FF"
    )
    with Image.open(out) as conformed:
        rgba = conformed.convert("RGBA")
        assert rgba.getpixel((0, 0))[3] == 0  # the pink field keyed to transparent
        assert rgba.getchannel("A").getextrema() == (0, 255)  # subject opaque, bg clear


# --------------------------------------------------------------------------- #
# Manifest — the JSON emitter/reader round-trip.
# --------------------------------------------------------------------------- #


def _entry(asset_id: str, category: str = "textures") -> ManifestEntry:
    return ManifestEntry(
        id=asset_id,
        path=f"res://content/assets/{category}/{asset_id}.png",
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
    backend = assets_config.make_builtin_backend(STYLE)
    assert backend.available is False


def test_mcp_backend_enforces_timeout(tmp_path: Path) -> None:
    """A hung MCP image-gen call does NOT hang forever: the configured timeout
    cancels it and surfaces a clear GenerationError (reliability, gADR-0014).

    Drives a real MCP stdio server whose tool sleeps past the timeout (mcp is a
    dev dependency; no network / API, so this is a fast-tier test)."""
    import sys

    pytest.importorskip("mcp")
    server = Path(__file__).parent / "_mcp_hang_server.py"
    backend = McpBackend("hang", [sys.executable, str(server)], timeout=1.0)
    with pytest.raises(GenerationError):
        backend.generate("a prompt", tmp_path / "out.png")


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
    out = tmp_path / "content" / "assets" / "textures" / "obstacle_crate.png"
    with Image.open(out) as img:
        assert img.size == (40, 40)  # conformed to obstacle_size
    loaded = manifest.load_manifest(tmp_path, "content/assets")
    assert "obstacle_crate" in loaded


class _ModelBackend:
    """A generation backend that reports a concrete model (the McpBackend shape)."""

    name = "mcp:gemini"
    model = "gemini-2.5-flash-image"

    def generate(self, prompt: str, out_path: Path) -> None:
        Image.new("RGBA", (128, 128), (255, 0, 255, 255)).save(out_path)


def test_generation_records_the_backend_model(tmp_path: Path) -> None:
    """A generated entry records the backend's model as reproducible provenance
    (gADR-0014, #442) — recorded on the entry and round-tripped through the manifest."""
    _stage_scale_spec(tmp_path)
    entry = pipeline.acquire_asset(
        STYLE,
        "obstacle_crate",
        game_root=tmp_path,
        mode=AcquireMode.GENERATION,
        backend=_ModelBackend(),
        raw_dir=tmp_path / "raw",
    )
    assert entry.model == "gemini-2.5-flash-image"
    assert manifest.load_manifest(tmp_path, "content/assets")[
        "obstacle_crate"
    ].model == ("gemini-2.5-flash-image")


def test_per_asset_model_wins_and_defaults_to_pro() -> None:
    """The image model is a PER-ASSET recipe field, never a shared-channel arg
    (#442 review): the Pickups pin 2.5-Flash, and an asset whose recipe omits a
    model (the Player, from #443) resolves to the pipeline default (Nano Banana
    Pro) — so one asset's model can never silently regenerate a sibling."""

    def resolved_model(asset_id: str) -> str | None:
        backend = pipeline._default_backend(
            STYLE, dict(STYLE.assets[asset_id]["acquire"]), build_config.GAME_DIR
        )
        assert isinstance(backend, McpBackend)
        return backend.model

    assert resolved_model("player") == "gemini-3-pro-image-preview"  # recipe omits
    assert resolved_model("pickup_bun") == "gemini-2.5-flash-image"
    assert resolved_model("pickup_wine") == "gemini-2.5-flash-image"
    # The shared channel must NOT pin a model (it would regress every sibling).
    channel_args = STYLE.generation["mcp"]["channels"]["gemini"].get("arguments", {})
    assert "model" not in channel_args


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
    out = tmp_path / "content" / "assets" / "textures" / "obstacle_crate.png"
    with Image.open(out) as img:
        assert img.size == (40, 40)


def _stage_scale_spec(root: Path) -> None:
    """Copy the committed scale_spec into an isolated game root for acquire."""
    dst = root / "content" / "data" / "json" / "scale_spec.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(
        (build_config.GAME_DIR / "content/data/json/scale_spec.json").read_text(
            "utf-8"
        ),
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- #
# Structured refusals — the schema boundary and the CLI envelope (gADR-0019).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad_value", ["OFL", 123, {"license": "OFL"}])
def test_category_licenses_value_must_be_string_array(
    tmp_path: Path, bad_value
) -> None:
    """A wrong-typed category_licenses VALUE refuses structured at load (#497
    review): a bare string would otherwise silently iterate into a
    per-character allowlist feeding the license gate, and a non-iterable would
    be a raw TypeError instead of the schema boundary's ConfigError."""
    doc = json.loads(panda_assets.STYLE_PATH.read_text("utf-8"))
    doc["constraints"]["category_licenses"] = {"fonts": bad_value}
    bad = tmp_path / "style.json"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(assets_config.ConfigError) as exc:
        assets_config.load_style_config(bad)
    assert exc.value.code == "config_invalid"
    assert "category_licenses.fonts" in exc.value.detail


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda d: d["style"]["keywords"].append(123), "style.keywords"),
        (lambda d: d["style"]["palette"].append(7), "style.palette"),
        (lambda d: d["constraints"]["formats"].append(1), "constraints.formats"),
        (
            lambda d: d["constraints"]["allowed_licenses"].append(0),
            "constraints.allowed_licenses",
        ),
        (
            lambda d: d["style"].__setitem__("category_hints", {"textures": 5}),
            "style.category_hints.textures",
        ),
        (
            lambda d: d["generation"]["mcp"]["channels"]["gemini"].__setitem__(
                "command", []
            ),
            "command",
        ),
        (
            lambda d: d["generation"]["mcp"]["channels"]["gemini"].__setitem__(
                "command", ["ok", 3]
            ),
            "command",
        ),
        (
            lambda d: d["generation"]["builtin"].__setitem__("command", "run-me"),
            "generation.builtin.command",
        ),
    ],
    ids=[
        "keywords-int",
        "palette-int",
        "formats-int",
        "licenses-int",
        "hint-nonstring",
        "channel-command-empty",
        "channel-command-int",
        "builtin-command-string",
    ],
)
def test_malformed_nested_config_refuses_at_load(
    tmp_path: Path, mutate, needle: str
) -> None:
    """ELEMENT-level bad nested config refuses structured AT LOAD (#497 review
    pass 2): a stray number in keywords/palette/formats/allowed_licenses, a
    non-string category hint, or a malformed generation command used to load
    fine and crash later (e.g. `query` joining an int keyword raised a raw
    TypeError past the JSON envelope). The schema boundary now owns the whole
    class."""
    doc = json.loads(panda_assets.STYLE_PATH.read_text("utf-8"))
    mutate(doc)
    bad = tmp_path / "style.json"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(assets_config.ConfigError) as exc:
        assets_config.load_style_config(bad)
    assert exc.value.code == "config_invalid"
    assert needle in exc.value.detail


def test_builtin_backend_missing_executable_is_a_generation_error(
    tmp_path: Path,
) -> None:
    """A configured-but-unrunnable builtin command is normalized to the backend's
    one GenerationError contract (#497 review pass 2) — never a raw
    FileNotFoundError out of the acquire path (the CLI maps it to the exit-2
    envelope like every generation failure)."""
    backend = BuiltinBackend(command=["/nonexistent/imagegen", "{prompt}", "{output}"])
    with pytest.raises(GenerationError, match="could not run"):
        backend.generate("a prompt", tmp_path / "out.png")


def test_builtin_backend_timeout_is_a_generation_error(tmp_path: Path) -> None:
    """A hung builtin command is bounded by the backend timeout and surfaces as
    a GenerationError, not a raw subprocess.TimeoutExpired (#497 review pass 2)."""
    import sys

    backend = BuiltinBackend(
        command=[sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5
    )
    with pytest.raises(GenerationError, match="timed out"):
        backend.generate("a prompt", tmp_path / "out.png")


def test_mcp_backend_missing_executable_is_a_generation_error(tmp_path: Path) -> None:
    """An MCP channel whose server executable cannot launch fails as a
    GenerationError (#497 review pass 2): startup/transport failures are
    normalized at the backend boundary, not just tool-call errors."""
    pytest.importorskip("mcp")
    backend = McpBackend("bad", ["/nonexistent/mcp-server"], timeout=5.0)
    with pytest.raises(GenerationError, match="failed to start or communicate"):
        backend.generate("a prompt", tmp_path / "out.png")


def test_cli_generation_failure_is_a_structured_refusal(capsys) -> None:
    """An acquire whose generation backend is unavailable (no builtin image gen,
    no fallback — the committed config's posture) exits 2 with a JSON envelope,
    never a traceback (#497 review). Forces the builtin backend onto a
    generation-mode asset; the failure is raised before any network/API call."""
    rc = cli.main(
        [
            "--config",
            str(panda_assets.STYLE_PATH),
            "acquire",
            "pickup_bun",
            "--backend",
            "builtin",
            "--no-emit",
        ]
    )
    assert rc == cli.EXIT_REFUSED
    err = json.loads(capsys.readouterr().err)
    assert err["error"] == "generation_failed"
    assert "no built-in image generation" in err["detail"]


# --------------------------------------------------------------------------- #
# build_config — id -> path composition and the FK/no-dangling config gate.
# --------------------------------------------------------------------------- #


def test_compose_asset_refs_resolves_id_to_path() -> None:
    """The builder resolves the authored manifest id to the single-homed path."""
    doc = {"obstacle_asset": "obstacle_crate"}
    manifest_map = build_config.load_asset_manifest()
    build_config.compose_asset_refs(doc, build_config._GRAVITY_JSON_REL, manifest_map)
    assert doc["obstacle_asset"] == "res://content/assets/textures/obstacle_crate.png"


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
    tres = (
        build_config.GAME_DIR / "content/data/generated/gravity_config.tres"
    ).read_text()
    assert 'obstacle_asset = "res://content/assets/textures/obstacle_crate.png"' in tres


def test_compose_asset_refs_resolves_a_top_level_projectile_ref() -> None:
    """The Laser bolt ref resolves id -> path on the combat source (#442)."""
    doc = {"projectile_asset": "laser_bolt"}
    manifest_map = build_config.load_asset_manifest()
    build_config.compose_asset_refs(doc, build_config._COMBAT_JSON_REL, manifest_map)
    assert doc["projectile_asset"] == "res://content/assets/textures/laser_bolt.png"


def test_compose_asset_refs_resolves_nested_pickup_refs() -> None:
    """Each drop_items style's id resolves to its single-homed path (#442).

    An empty/absent nested ref passes through (the FK gate catches a bad id),
    mirroring the top-level passthrough — the nested compose is the twin of
    ``_authored_asset_refs``' nested scan.
    """
    doc = {
        "drop_items": {
            "gold": {"asset": "pickup_gold"},
            "bun": {"asset": ""},
            "nostyle": {},
        }
    }
    build_config.compose_asset_refs(
        doc, build_config._PROGRESSION_JSON_REL, build_config.load_asset_manifest()
    )
    assert (
        doc["drop_items"]["gold"]["asset"]
        == "res://content/assets/textures/pickup_gold.png"
    )
    assert doc["drop_items"]["bun"]["asset"] == ""
    assert "asset" not in doc["drop_items"]["nostyle"]


def test_combat_tres_carries_the_resolved_projectile_path() -> None:
    """The committed combat_config.tres renders the resolved Laser bolt path."""
    tres = (
        build_config.GAME_DIR / "content/data/generated/combat_config.tres"
    ).read_text()
    assert 'projectile_asset = "res://content/assets/textures/laser_bolt.png"' in tres


def test_progression_tres_carries_the_resolved_pickup_paths() -> None:
    """The committed progression_config.tres renders each resolved Pickup path."""
    tres = (
        build_config.GAME_DIR / "content/data/generated/progression_config.tres"
    ).read_text()
    for item in ("gold", "bun", "wine"):
        assert f'"asset": "res://content/assets/textures/pickup_{item}.png"' in tres


def test_validate_asset_refs_passes_on_committed_authority() -> None:
    """The committed manifest satisfies FK integrity + no-dangling (gADR-0014)."""
    m = build_config.validate_asset_refs()
    assert "obstacle_crate" in m


def test_committed_manifest_has_no_orphans() -> None:
    """Wave-close DoD: every recorded asset is referenced (gADR-0014)."""
    assert build_config.asset_ref_orphans() == []


def test_committed_generated_pickups_record_generation_provenance() -> None:
    """The bun/wine pickups are real Gemini generations, not placeholders (#442):
    the committed manifest records the generation mode, channel, model, and prompt.
    A GENERATED asset records its BACKEND's usage terms, NOT a CC0 download license
    (gADR-0015) — the generation license mode the #443 license gate enforces."""
    m = build_config.load_asset_manifest()
    for pid in ("pickup_bun", "pickup_wine"):
        rec = m[pid]
        assert rec["acquire_mode"] == "generation", pid
        assert rec["source"] == "mcp:gemini", pid
        assert rec["backend"] == "mcp:gemini", pid
        assert rec["model"] == "gemini-2.5-flash-image", pid
        assert rec["license"] == "Gemini-Generated", pid
        assert rec["license_url"] == "https://ai.google.dev/gemini-api/terms", pid
        assert rec["license"] != "CC0", pid  # not a download license (gADR-0015)
        assert rec["prompt"], pid


def test_committed_cc0_assets_stay_search_download() -> None:
    """The already-real CC0 assets were NOT touched by the generation round (#442)."""
    m = build_config.load_asset_manifest()
    for aid in ("pickup_gold", "laser_bolt", "obstacle_crate"):
        assert m[aid]["acquire_mode"] == "search_download", aid
        assert m[aid]["source"] == "opengameart", aid


def test_fk_integrity_fails_on_unrecorded_reference(tmp_path: Path) -> None:
    """A referenced id with no manifest entry fails the FK gate."""
    root = _copy_authority(tmp_path)
    # Drop the manifest entry the authority references.
    (root / "content" / "assets" / "manifest" / "textures.json").write_text(
        "{}\n", "utf-8"
    )
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_asset_refs(root)


def test_no_dangling_fails_on_missing_file(tmp_path: Path) -> None:
    """A manifest path with no file on disk fails the no-dangling gate."""
    root = _copy_authority(tmp_path)
    (root / "content" / "assets" / "textures" / "obstacle_crate.png").unlink()
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_asset_refs(root)


def test_record_shape_fails_on_missing_license_or_source(tmp_path: Path) -> None:
    """A referenced entry missing required provenance/license fields FAILS the gate
    — an unprovenanced/unlicensed asset must not ship (gADR-0014)."""
    root = _copy_authority(tmp_path)
    frag = root / "content" / "assets" / "manifest" / "textures.json"
    doc = json.loads(frag.read_text())
    del doc["obstacle_crate"]["license"]
    del doc["obstacle_crate"]["source"]
    frag.write_text(json.dumps(doc, indent=2) + "\n", "utf-8")
    with pytest.raises(jsonschema.ValidationError):
        build_config.validate_asset_refs(root)


def test_build_all_enforces_the_manifest_gate(tmp_path: Path) -> None:
    """build_all FAILS on a missing referenced id — the gate is in the BUILD path,
    not just tests (gADR-0014) — and leaves no partial derived set behind."""
    root = _copy_authority(tmp_path)
    (root / "content" / "assets" / "manifest" / "textures.json").write_text(
        "{}\n", "utf-8"
    )
    with pytest.raises(jsonschema.ValidationError):
        build_config.build_all(root=root)
    # The gate ran before the spec loop: no partial writes (gADR-0000 no-drift).
    assert not (root / "content" / "data" / "generated").exists()


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
    shutil.copytree(src / "content" / "assets", root / "content" / "assets")
    return root
