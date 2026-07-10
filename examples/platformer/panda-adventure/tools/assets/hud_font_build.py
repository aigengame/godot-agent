"""Acquire + wire the HUD's bitmap font through the asset pipeline (P2-S9, #445).

The UI branch's one-shot acquisition step (gADR-0014), the analogue of a sprite
slice's ``pack_sprite_set`` call: it produces the committed glyph sheet, derives
its Godot font, and records the Asset manifest entry, reusing the pipeline's
deep modules rather than re-implementing them —

1. **raster the glyph sheet** — render a uniform grid of printable ASCII glyphs
   (U+0020..U+007E) from the acquired pixel font into fixed cells, then conform it
   through :func:`assets.postprocess.postprocess_image` (the pipeline's shared
   image conform: snap to the bounded palette, hard 1-bit alpha) so the font reads
   in the same regime as every other asset;
2. **derive the font** — :func:`assets.fonts.derive_bitmap_font` turns the sheet +
   its grid into a byte-stable AngelCode ``.fnt`` Godot loads as a ``FontFile``;
3. **record provenance** — :class:`assets.emitter.JsonManifestEmitter` writes the
   ``fonts.json`` fragment with the license entry.

Acquisition: the glyph sheet is rasterized from **Press Start 2P** — a genuine
arcade/space-opera pixel font under the **SIL Open Font License 1.1** (Reserved
Font Name; CodeMan38 / The Press Start 2P Project Authors), search-downloaded from
Google Fonts. The committed ``PressStart2P-Regular.ttf`` (its ``OFL.txt`` alongside)
is the rasterization SOURCE; the game loads only the derived ``.fnt`` bitmap. Press
Start 2P is a perfect square monospace (advance = em), so at the **native size read
from the Scale spec** (``hud_font_size``, gADR-0013 — the single size authority, NOT
a literal here) every glyph fills its square cell 1:1 (crisp, no scaling) and the
HUD's LINES read at a glance; retuning ``hud_font_size`` regenerates the font at the
new native size rather than scaling a stale bitmap.

Run once, commit its outputs (``assets/fonts/hud_font.png``,
``assets/fonts/hud_font.fnt``, ``assets/manifest/fonts.json``, plus the committed
``.ttf``/``OFL.txt`` source). This module uses package-relative imports, so it must
be run as a MODULE, not as a file script — from the game directory
(``examples/platformer/panda-adventure``)::

    PYTHONPATH=tools python -m assets.hud_font_build

(the ``python -m assets`` invocation the pipeline uses; running ``python
tools/assets/hud_font_build.py`` fails with ``ImportError``). The committed
artifacts are the source of truth (no network — the ``.ttf`` is in-repo). What
re-derives **byte-identically** is the ``.fnt`` layout and the manifest — they
describe the glyph GRID, not pixels; the rendered ``.png`` sheet is a valid
Scale-spec-sized atlas but is **not** cross-environment byte-reproducible (freetype
rasterization varies by version/platform — gADR-0015). ``test_fonts_deriver``
asserts exactly that split.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import acquire, game_config
from .acquire import Fetch
from .emitter import JsonManifestEmitter
from .fonts import derive_bitmap_font
from .model import AssetSpec, FrameLayout, ManifestEntry
from .postprocess import postprocess_image

# The committed HUD-font asset id — the manifest primary key, the id the HUD's
# `hud_font` reference resolves against, AND the key of this font's acquire recipe
# in the Style descriptor's `assets` (its category/source/url/license live there).
ASSET_ID = "hud_font"

# The committed rasterization SOURCE: the acquired OFL pixel font (in-repo, so
# re-derivation needs no network). The game never loads this — only the derived
# .fnt bitmap sheet — but committing it keeps the sheet reproducible.
SOURCE_TTF_REL = "assets/fonts/PressStart2P-Regular.ttf"

# The glyph run the sheet covers: printable ASCII, space (0x20) through tilde
# (0x7E) — every character the HUD's LINES render (digits, uppercase letters,
# space, slash) and then some.
FIRST_CODEPOINT = 0x20
LAST_CODEPOINT = 0x7E
GLYPH_COUNT = LAST_CODEPOINT - FIRST_CODEPOINT + 1

# The glyph grid's column count; the row count follows from the glyph total. The
# per-cell SIZE is NOT a literal — it is read from the Scale spec's hud_font_size
# at build time (see native_cell_size), so the Scale spec stays the single size
# authority (gADR-0013). Press Start 2P is a perfect square monospace (advance =
# em), so one native size sizes both the cell width and height.
COLUMNS = 16
ROWS = (GLYPH_COUNT + COLUMNS - 1) // COLUMNS

# The Scale-spec key that owns the HUD font's native (design-space) pixel size.
NATIVE_SIZE_SCALE_KEY = "hud_font_size"


def native_cell_size(config: game_config.StyleConfig, game_root: Path) -> int:
    """The font's native square-cell size, read from the Scale spec (gADR-0013).

    The HUD renders at ``hud_font_size``, so baking the bitmap at that native size
    makes it render 1:1 (crisp). Read here, never hardcoded, so the Scale spec is
    the single authority — retuning it regenerates the font at the new size.
    """
    return int(game_config.scale_value(config, NATIVE_SIZE_SCALE_KEY, game_root))


def _committed_source_fetch(ttf_path: Path) -> Fetch:
    """A :data:`~assets.acquire.Fetch` returning the committed source TTF's bytes.

    The acquire boundary is injected (acquire.py): the recipe's ``url`` records where
    the OFL font was verified from (Google Fonts), while re-derivation reads the
    in-repo committed TTF — the verified snapshot of that url — so the font build is
    reproducible offline. Pass ``acquire.default_fetch`` to ``build`` instead for a
    live re-acquire from the recorded url.
    """

    def _fetch(_url: str) -> bytes:
        return ttf_path.read_bytes()

    return _fetch


def raster_glyph_sheet(dst: Path, ttf_path: Path, cell: int) -> tuple[int, int]:
    """Render the printable-ASCII glyph grid from ``ttf_path`` to ``dst``.

    Deterministic (a fixed font at a fixed integer size ``cell``): cell ``k`` holds
    codepoint ``FIRST_CODEPOINT + k`` (row-major), drawn white on transparent so
    :func:`postprocess_image` keeps it in the bounded palette. Press Start 2P's
    square glyphs fill each ``cell``x``cell`` box from its origin, so no inset is
    needed. Returns the sheet dimensions.

    Antialiasing is DISABLED (``draw.fontmode = "1"`` -> freetype ``MONO`` target):
    a pixel font at its native size is designed to land on the pixel grid, so a hard
    on/off raster is the correct look (crisp 1:1, matching gADR-0013's
    nearest-neighbor / no-AA regime) and drops the freetype-version-dependent
    grayscale edges an AA raster carries. It does NOT make the ``.png`` sheet
    cross-environment byte-reproducible, though — freetype's monochrome rasterization
    can still differ by version/platform (gADR-0015); the byte-stable artifact is the
    ``.fnt`` layout (the grid), not the rendered sheet.
    """
    width, height = COLUMNS * cell, ROWS * cell
    sheet = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    # monochrome (no AA): the crisp pixel-font look; drops the AA gray edges
    draw.fontmode = "1"
    font = ImageFont.truetype(str(ttf_path), cell)
    for index in range(GLYPH_COUNT):
        col, row = index % COLUMNS, index // COLUMNS
        draw.text(
            (col * cell, row * cell),
            chr(FIRST_CODEPOINT + index),
            fill=(255, 255, 255, 255),
            font=font,
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dst, format="PNG")
    return width, height


def build(
    game_root: Path = game_config.GAME_ROOT, *, fetch: Fetch | None = None
) -> ManifestEntry:
    """Produce the committed sheet + ``.fnt`` and emit the manifest entry.

    Acquisition flows through the configured pipeline recipe (gADR-0014): the
    ``hud_font`` asset's ``acquire`` recipe in the Style descriptor names the source,
    url, license, and attribution, and :func:`assets.acquire.search_download` fetches
    the TTF and records that provenance — nothing hardcoded here. ``fetch`` defaults
    to reading the committed source TTF (offline, reproducible); pass
    ``acquire.default_fetch`` for a live re-acquire from the recipe url.
    """
    config = game_config.load_style_config()
    cell = native_cell_size(config, game_root)
    request = config.assets[ASSET_ID]
    recipe = dict(request["acquire"])
    category = str(request["category"])
    source = config.sources[str(recipe["source"])]
    ttf_path = game_root / SOURCE_TTF_REL

    sheet_res = f"res://{config.assets_root}/{category}/{ASSET_ID}.png"
    fnt_res = f"res://{config.assets_root}/{category}/{ASSET_ID}.fnt"
    sheet_path = game_root / config.assets_root / category / f"{ASSET_ID}.png"
    fnt_path = game_root / config.assets_root / category / f"{ASSET_ID}.fnt"

    spec = AssetSpec(
        id=ASSET_ID, category=category, target_dims=(cell, cell), style=config.style
    )

    with tempfile.TemporaryDirectory() as tmp:
        raw_ttf = Path(tmp) / "source.ttf"
        # Acquire through the recipe boundary: search_download records the source /
        # url / license / attribution from the recipe (provenance is data, not
        # hardcoded); the injected fetch returns the committed TTF snapshot.
        result = acquire.search_download(
            spec,
            recipe,
            source,
            raw_ttf,
            # The fonts-category download allowlist (CC0/CC-BY + OFL), not the global
            # rule — OFL is a font-only license (gADR-0014/GDD, scoped in #445).
            allowed_licenses=config.download_licenses_for(category),
            fetch=fetch or _committed_source_fetch(ttf_path),
        )
        # The font-specific postprocess: rasterize the acquired TTF into the uniform
        # glyph sheet, then conform through the pipeline's shared image stage (snap
        # to the bounded palette + hard 1-bit alpha; no chroma key — the sheet is
        # already transparent-backed).
        raw_sheet = Path(tmp) / "raw.png"
        dims = raster_glyph_sheet(raw_sheet, result.raw_path, cell)
        postprocess_image(
            raw_sheet, sheet_path, dims, config.style.palette, chroma_key=None
        )

    layout = FrameLayout(
        frame_dims=(cell, cell), columns=COLUMNS, rows=ROWS, count=GLYPH_COUNT
    )
    fnt_path.write_text(
        derive_bitmap_font(sheet_res, layout, first_codepoint=FIRST_CODEPOINT),
        encoding="utf-8",
    )

    entry = ManifestEntry(
        id=ASSET_ID,
        # The manifest path is the resource the HUD LOADS — the derived font, not
        # the raw sheet (the sheet is the .fnt's external page) nor the .ttf source.
        # Mirrors the sprite slice, whose manifest path is the derived SpriteFrames.
        path=fnt_res,
        category=category,
        acquire_mode=result.acquire_mode.value,
        source=result.source,
        license=result.license,
        license_url=result.license_url,
        target_dims=dims,
        source_url=result.source_url,
        attribution=result.attribution,
        frame_layout=layout,
    )
    JsonManifestEmitter(game_root, config.assets_root).emit(entry)
    return entry


def main() -> None:
    entry = build()
    print(f"hud_font_build: wrote {entry.path} + its glyph sheet and manifest entry")


if __name__ == "__main__":
    main()
