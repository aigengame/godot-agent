"""Bitmap-font deriver — a packed glyph sheet + its grid into a Godot font.

The UI-branch counterpart of the :mod:`spriteframes` deriver (gADR-0014): given a
committed glyph sheet's ``res://`` path and its uniform-grid
:class:`~assets.model.FrameLayout` (reused — a glyph grid is a frame grid whose
cells are read as glyphs), this emits an **AngelCode BMFont** ``.fnt`` that maps a
contiguous run of codepoints onto the sheet's cells. Godot's font importer loads
that ``.fnt`` natively as a ``FontFile`` (a ``Font``), so a wave-3 UI slice turns a
loose glyph sheet into a ready HUD font without hand-authoring per-glyph metrics.

Why ``.fnt`` and not a ``.tres`` (the shape :mod:`spriteframes` emits): a
``SpriteFrames`` serializes cleanly as text with an ``ext_resource`` pointing at
the external sheet, so its ``.tres`` stays byte-stable and references (never
inlines) the sheet. A bitmap ``FontFile`` does NOT — Godot **embeds** the glyph
atlas into the ``.tres`` when it serializes one, which would inline the sheet and
lose byte-stability. The AngelCode ``.fnt`` is Godot's native *external-page*
bitmap-font format: deterministic text that references the sheet PNG by a relative
page filename — the same "reference the sheet, don't inline it" property, in the
format Godot actually supports for it.

Pure text emission, the ``build_config`` idiom: byte-stable output (fixed field
order, no ``uid`` — a ``.fnt`` carries none; gda authors uid-free, gADR-0036), no
Godot, no IO, so it runs in the fast CI tier. That the emitted ``.fnt`` really
loads as a Godot ``Font`` is proven by the engine-tier ``test_fonts_engine.py``.
"""

from __future__ import annotations

from .model import FrameLayout

# The first codepoint the sheet's cell 0 holds. Printable ASCII starts at U+0020
# (space); cell ``i`` holds ``first_codepoint + i`` (row-major, like the packer).
_DEFAULT_FIRST_CODEPOINT = 0x20

# The BMFont channel mask meaning "the glyph uses all four texture channels" — the
# whole cell is the glyph (a non-packed page). A stable literal so the emit is
# byte-identical per run.
_ALL_CHANNELS = 15


def _page_basename(sheet_res_path: str) -> str:
    """The sheet's bare filename — a BMFont ``page`` references it *relatively*.

    AngelCode ``page file="…"`` is resolved relative to the ``.fnt``'s own
    directory, so the committed sheet (which sits beside the ``.fnt``, both under
    ``assets/fonts/``) is named by basename, not by the ``res://`` path the deriver
    is handed. Keeps the ``.fnt`` self-contained and relocatable with its page.
    """
    return sheet_res_path.rsplit("/", 1)[-1]


def _default_face(sheet_res_path: str) -> str:
    """The BMFont face name when the caller gives none — the sheet's file stem."""
    return _page_basename(sheet_res_path).rsplit(".", 1)[0]


def derive_bitmap_font(
    sheet_res_path: str,
    layout: FrameLayout,
    *,
    first_codepoint: int = _DEFAULT_FIRST_CODEPOINT,
    face: str | None = None,
    size: int | None = None,
    base: int | None = None,
    advance: int | None = None,
) -> str:
    """Derive an AngelCode ``.fnt`` for one packed glyph sheet + its grid.

    ``sheet_res_path`` is the committed sheet's ``res://`` path (its basename
    becomes the BMFont page reference); ``layout`` is the uniform grid the glyphs
    fill (``frame_dims`` the per-cell ``(width, height)``, ``columns``/``rows`` the
    grid, ``count`` the glyph total). Cell ``k`` (row-major: column ``k % columns``,
    row ``k // columns``) holds codepoint ``first_codepoint + k``.

    ``size`` is the font's native/fixed pixel size (default: the cell height), so a
    consumer requesting that ``font_size`` renders the bitmap 1:1 (crisp, no
    scaling); ``base`` is the baseline offset from the line top (default: 3px of
    descender room); ``advance`` is the monospace pen advance per glyph (default:
    the cell width). Returns byte-stable ``.fnt`` text (uid-free).
    """
    cell_w, cell_h = layout.frame_dims
    face_name = face if face is not None else _default_face(sheet_res_path)
    native_size = size if size is not None else cell_h
    baseline = base if base is not None else cell_h - 3
    pen_advance = advance if advance is not None else cell_w
    sheet_w, sheet_h = layout.columns * cell_w, layout.rows * cell_h

    header = (
        f'info face="{face_name}" size={native_size} bold=0 italic=0 charset="" '
        "unicode=1 stretchH=100 smooth=0 aa=1 padding=0,0,0,0 spacing=0,0\n"
        f"common lineHeight={cell_h} base={baseline} scaleW={sheet_w} "
        f"scaleH={sheet_h} pages=1 packed=0\n"
        f'page id=0 file="{_page_basename(sheet_res_path)}"\n'
        f"chars count={layout.count}\n"
    )

    chars = "".join(
        f"char id={first_codepoint + index} "
        f"x={(index % layout.columns) * cell_w} "
        f"y={(index // layout.columns) * cell_h} "
        f"width={cell_w} height={cell_h} xoffset=0 yoffset=0 "
        f"xadvance={pen_advance} page=0 chnl={_ALL_CHANNELS}\n"
        for index in range(layout.count)
    )
    return header + chars
