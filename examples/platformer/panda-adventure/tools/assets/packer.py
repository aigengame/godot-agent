"""Frames -> sheet packer — loose frame files into one spritesheet.

Many open-asset sources deliver a sprite-frame set as loose files (B-form). The
committed sprite artifact, though, is always ONE spritesheet per animation state
(A-form): far fewer files, one ``.import`` per set, atlas- and pixel-grid-friendly.
This reusable postprocess tool packs the loose frames into that sheet
and records the frame layout the manifest carries and the :mod:`spriteframes`
deriver turns into ``AtlasTexture`` regions.

Pure Pillow (a dev dependency, so this runs in the fast CI tier); no network, no
game code, no Godot.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image

from .model import FrameLayout

__all__ = ["FrameLayout", "pack_frames"]

# Past this many frames a horizontal strip grows unwieldy (and hits texture-width
# limits), so the packer switches to a near-square grid. Spec-ish default; a
# caller can override per set.
_DEFAULT_GRID_THRESHOLD = 8


def pack_frames(
    frame_paths: list[Path],
    dst: Path,
    *,
    grid_threshold: int = _DEFAULT_GRID_THRESHOLD,
) -> FrameLayout:
    """Pack ``frame_paths`` into one spritesheet at ``dst``; return its layout.

    Up to ``grid_threshold`` frames tile into a single horizontal strip; a larger
    set tiles into a near-square grid (columns = ``ceil(sqrt(count))``), filled
    left-to-right then top-to-bottom. Returns the :class:`FrameLayout` describing
    the result.
    """
    if not frame_paths:
        raise ValueError("cannot pack a sprite set with no frames")
    images = [Image.open(p).convert("RGBA") for p in frame_paths]
    width, height = images[0].size
    for path, img in zip(frame_paths, images):
        if img.size != (width, height):
            raise ValueError(
                f"frame {path.name} is {img.size}, expected {(width, height)} — "
                "all frames of a set must be the same size to tile into one sheet"
            )
    count = len(images)
    if count > grid_threshold:
        columns = math.ceil(math.sqrt(count))
        rows = math.ceil(count / columns)
    else:
        columns, rows = count, 1

    sheet = Image.new("RGBA", (columns * width, rows * height), (0, 0, 0, 0))
    for index, img in enumerate(images):
        col, row = index % columns, index // columns
        sheet.paste(img, (col * width, row * height))

    dst.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dst, format="PNG")
    return FrameLayout(
        frame_dims=(width, height), columns=columns, rows=rows, count=count
    )
