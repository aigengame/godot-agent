"""Postprocess — conform an acquired image to the pixel-art regime + target size.

The deterministic tail of the pipeline: whatever the acquire stage
produced (a downloaded pixel sheet or a high-resolution generated render), this
conforms it to the size spec's exact target dimensions and the bounded pixel-art
palette, so assets from BOTH acquire modes read as one style. Pure Pillow, no
network, no game code — the CI-tested stage (Pillow is a dev dependency, the
acquire boundary is mocked, so these transforms run in the fast suite).

Stages, in order:

1. **chroma-key crop** (generation only) — a generated subject is asked to sit on
   a solid background color (the Style descriptor's ``chroma_key``); this keys
   that color out to transparency and crops to the remaining content, so a
   generated asset arrives with a transparent background like a downloaded sprite.
2. **downscale to the pixel grid** — resize to the exact target dimensions with a
   box-averaging filter, collapsing a high-resolution source onto the 1:1 pixel
   grid (PPU 1).
3. **palette-quantize** — snap every RGB pixel to the nearest bounded-palette
   color (no dithering — pixel art wants flat blocks), preserving a binary alpha.
4. **exact-dimension conform** — guarantee the output is exactly ``target_dims``.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

# Alpha at or above this is opaque, below it transparent — pixel art wants a hard
# 1-bit alpha edge, never a semi-transparent fringe.
_ALPHA_THRESHOLD = 128


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    """Parse ``#rrggbb`` (or ``rrggbb``) into an 8-bit RGB triple."""
    h = value.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"palette color {value!r} is not #rrggbb")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def palette_image(palette: tuple[str, ...] | list[str]) -> Image.Image:
    """A Pillow ``P``-mode image carrying the bounded palette (padded to 256).

    Pillow's ``quantize(palette=...)`` maps each pixel to the nearest entry of
    this palette. The palette is padded to 256 entries (repeating the first) so
    Pillow accepts it; only the real colors are ever nearest to a source pixel.
    """
    if not palette:
        raise ValueError("the bounded palette is empty")
    flat: list[int] = []
    for color in palette:
        flat.extend(_hex_to_rgb(color))
    pad = flat[:3] if flat else [0, 0, 0]
    while len(flat) < 256 * 3:
        flat.extend(pad)
    pal = Image.new("P", (1, 1))
    pal.putpalette(flat[: 256 * 3])
    return pal


def detect_background_key(
    img: Image.Image, fallback: str, *, consistency: int = 24
) -> str:
    """The solid background color to key out, sampled from the four corners.

    A generation backend often APPROXIMATES the requested chroma color rather than
    hitting it exactly (Gemini renders the asked-for ``#FF00FF`` as a near-magenta
    pink), so keying the fixed configured color leaves the real background behind.
    When the four corners agree within ``consistency`` (a centered subject on a
    solid field), key their mean — the color actually produced; otherwise fall back
    to the configured key. Pure sampling, no mutation.
    """
    rgba = img.convert("RGBA")
    w, h = rgba.size
    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    rgbs = [rgba.getpixel(p)[:3] for p in corners]
    r0, g0, b0 = rgbs[0]
    if all(
        abs(r - r0) <= consistency
        and abs(g - g0) <= consistency
        and abs(b - b0) <= consistency
        for r, g, b in rgbs[1:]
    ):
        n = len(rgbs)
        mr = sum(c[0] for c in rgbs) // n
        mg = sum(c[1] for c in rgbs) // n
        mb = sum(c[2] for c in rgbs) // n
        return f"#{mr:02x}{mg:02x}{mb:02x}"
    return fallback


def chroma_key_crop(img: Image.Image, key: str, tolerance: int = 40) -> Image.Image:
    """Key ``key`` out to transparency and crop to the remaining content.

    A generated subject sits on a solid ``key`` background; every pixel within
    ``tolerance`` (per channel) of it becomes transparent, then the image is
    cropped to the bounding box of what remains (falling back to the full frame
    when nothing is keyed, so an already-transparent input passes through).
    """
    rgba = img.convert("RGBA")
    kr, kg, kb = _hex_to_rgb(key)
    px = rgba.load()
    assert px is not None
    width, height = rgba.size
    for y in range(height):
        for x in range(width):
            r, g, b, a = px[x, y]
            if (
                abs(r - kr) <= tolerance
                and abs(g - kg) <= tolerance
                and abs(b - kb) <= tolerance
            ):
                px[x, y] = (r, g, b, 0)
    bbox = rgba.getchannel("A").point(lambda a: 255 if a > 0 else 0).getbbox()
    return rgba.crop(bbox) if bbox is not None else rgba


def downscale_to_grid(img: Image.Image, dims: tuple[int, int]) -> Image.Image:
    """Resize onto the pixel grid — exact target dims, box-averaged for downscale."""
    return img.convert("RGBA").resize(dims, Image.LANCZOS)


def quantize_to_palette(
    img: Image.Image, palette: tuple[str, ...] | list[str]
) -> Image.Image:
    """Snap RGB to the nearest bounded-palette color, preserving a binary alpha."""
    rgba = img.convert("RGBA")
    alpha = rgba.getchannel("A").point(lambda a: 255 if a >= _ALPHA_THRESHOLD else 0)
    rgb = rgba.convert("RGB").quantize(
        palette=palette_image(palette), dither=Image.Dither.NONE
    )
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def conform_dimensions(img: Image.Image, dims: tuple[int, int]) -> Image.Image:
    """Guarantee the image is exactly ``dims`` (nearest, to stay on the grid)."""
    return img if img.size == dims else img.resize(dims, Image.NEAREST)


def postprocess_image(
    src: Path,
    dst: Path,
    dims: tuple[int, int],
    palette: tuple[str, ...] | list[str],
    *,
    chroma_key: str | None = None,
) -> Path:
    """Run the full conform pipeline on ``src`` and write the PNG to ``dst``.

    ``chroma_key`` is passed only for generated inputs (a solid-background subject
    to key out); a downloaded sprite already carries its own transparency and
    passes ``None``. The actual background is sampled from the corners (a backend
    may approximate the requested chroma color), so a near-magenta field keys out
    cleanly; the keying tolerance is widened because the sampled color is the real
    background and the centered subject is far from it. Returns ``dst``.
    """
    img = Image.open(src)
    if chroma_key is not None:
        key = detect_background_key(img, chroma_key)
        img = chroma_key_crop(img, key, tolerance=60)
    img = downscale_to_grid(img, dims)
    img = quantize_to_palette(img, palette)
    img = conform_dimensions(img, dims)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, format="PNG")
    return dst
