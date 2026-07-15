"""Live acquire tier for the asset pipeline (P2-S1, #439, gADR-0014).

The tests that cross the REAL boundary the fast tier mocks — a network fetch
(SearchDownload) and an image-generation API call (Generation → McpBackend), plus
the BuiltinBackend error path on THIS agent. Marked ``acquire_live`` and deselected
in CI (network, API keys, cost); run on demand:

    uv run --group assets-live pytest \\
        examples/platformer/panda-adventure/tests/test_assets_acquire_live.py \\
        -m acquire_live -rs

They write only into a throwaway ``tmp_path`` game root and emit into a temp
manifest — never the committed asset tree — so a live run leaves no orphan behind
(the tracer's committed Obstacle is wired via SearchDownload; these prove the modes
work, they do not add wired assets).
"""

from __future__ import annotations

import os
import urllib.error
from pathlib import Path

import pytest
from PIL import Image

import build_config
import panda_assets
from assets import config as assets_config
from assets import pipeline
from assets.backends import BuiltinImageGenUnavailable
from assets.model import AcquireMode

pytestmark = pytest.mark.acquire_live

STYLE = assets_config.load_style_config(panda_assets.STYLE_PATH)


def _game_root(tmp_path: Path) -> Path:
    """A throwaway game root carrying just the Scale spec the acquire needs."""
    dst = tmp_path / "data" / "json" / "scale_spec.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(
        (build_config.GAME_DIR / "data/json/scale_spec.json").read_text("utf-8"),
        encoding="utf-8",
    )
    return tmp_path


def test_search_download_real_fetch(tmp_path: Path) -> None:
    """SearchDownload really fetches the CC0 Obstacle crate and records it.

    The committed obstacle recipe's configurable OpenGameArt source, over the real
    network, postprocessed to the Scale spec size and recorded with its CC0 license
    and source URL (gADR-0014).
    """
    root = _game_root(tmp_path)
    try:
        entry = pipeline.acquire_asset(
            STYLE,
            "obstacle_crate",
            game_root=root,
            mode=AcquireMode.SEARCH_DOWNLOAD,
            raw_dir=tmp_path / "raw",
        )
    except urllib.error.URLError as exc:  # offline / host down — a skip, not a fail
        pytest.skip(f"network unavailable for the live fetch: {exc}")

    assert entry.acquire_mode == "search_download"
    assert entry.license == "CC0"
    assert entry.source == "opengameart"
    assert entry.source_url and entry.source_url.startswith("https://")
    out = root / "assets" / "textures" / "obstacle_crate.png"
    with Image.open(out) as img:
        assert img.size == (40, 40)
        assert img.mode == "RGBA"


@pytest.mark.parametrize(
    ("asset_id", "dims"),
    [("pickup_gold", (14, 14)), ("laser_bolt", (18, 6))],
)
def test_search_download_real_fetch_p2_s3_assets(
    tmp_path: Path, asset_id: str, dims: tuple[int, int]
) -> None:
    """The P2-S3 CC0 recipes (#442) really fetch and conform to the Scale size.

    The wired Pickup coin and the player Laser bolt, over the real network, each
    postprocessed to its Scale-spec box and recorded with its CC0 license and
    source URL (gADR-0014). The bun/wine Pickups are intentionally absent from this
    search-download parametrization — they are real Gemini GENERATIONS (the
    generation tier below / ``test_assets_pipeline`` covers that path), not
    search-download fetches.
    """
    root = _game_root(tmp_path)
    try:
        entry = pipeline.acquire_asset(
            STYLE,
            asset_id,
            game_root=root,
            mode=AcquireMode.SEARCH_DOWNLOAD,
            raw_dir=tmp_path / "raw",
        )
    except urllib.error.URLError as exc:  # offline / host down — a skip, not a fail
        pytest.skip(f"network unavailable for the live fetch: {exc}")

    assert entry.acquire_mode == "search_download"
    assert entry.license == "CC0"
    assert entry.source == "opengameart"
    assert entry.source_url and entry.source_url.startswith("https://")
    out = root / "assets" / "textures" / f"{asset_id}.png"
    with Image.open(out) as img:
        assert img.size == dims
        assert img.mode == "RGBA"


def test_mcp_gemini_real_generation(tmp_path: Path) -> None:
    """Generation → McpBackend really generates one image through the Gemini channel.

    Launches ``scripts/mcp/gemini_img_gen.py`` as an MCP server, calls its
    ``generate_image`` tool for real, then ingests + postprocesses the result and
    records it in a temp manifest (gADR-0014). Requires GEMINI_API_KEY and the
    ``assets-live`` dependency group (``google-genai``).
    """
    if not os.environ.get("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY is not set — the Gemini channel needs it")
    pytest.importorskip("google.genai", reason="install the assets-live group")

    root = _game_root(tmp_path)
    backend = assets_config.make_mcp_backend(STYLE, "gemini")
    entry = pipeline.acquire_asset(
        STYLE,
        "obstacle_crate",
        game_root=root,
        mode=AcquireMode.GENERATION,
        backend=backend,
        raw_dir=tmp_path / "raw",
    )
    assert entry.acquire_mode == "generation"
    assert entry.backend == "mcp:gemini"
    assert entry.prompt and "obstacle crate" in entry.prompt
    out = root / "assets" / "textures" / "obstacle_crate.png"
    with Image.open(out) as img:
        assert img.size == (40, 40)  # conformed to the Scale spec size


def test_builtin_backend_error_path_on_this_agent(tmp_path: Path) -> None:
    """Generation → BuiltinBackend on the running agent.

    Where the agent has built-in image generation (a configured command), it would
    generate for real; where it does not (Claude Code — the committed config has no
    command and no fallback), it fails LOUDLY with the clear user-facing error,
    never a silent no-op (gADR-0014).
    """
    backend = assets_config.make_builtin_backend(STYLE)
    if backend.available:
        pytest.skip("this agent has built-in image generation — see the real-gen path")
    with pytest.raises(BuiltinImageGenUnavailable):
        backend.generate("a single obstacle crate, pixel art", tmp_path / "out.png")
