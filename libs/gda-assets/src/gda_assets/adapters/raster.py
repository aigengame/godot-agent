"""PNG dimensions adapted from Panda's generic ``conform_dimensions`` operation.

The original MIT-licensed implementation lives in this repository's
examples/platformer/panda-adventure/tools/assets/postprocess.py. No game defaults or
runtime imports cross that boundary.
"""

from pathlib import Path

from gda_assets.domain.recipe import Resize


def resize_png(source: Path, destination: Path, size: Resize) -> None:
    from PIL import Image

    methods = {
        "nearest": Image.Resampling.NEAREST,
        "bilinear": Image.Resampling.BILINEAR,
        "lanczos": Image.Resampling.LANCZOS,
    }
    with Image.open(source) as image:
        # Palette and bilevel images otherwise force NEAREST even if another
        # method was requested. Preserve transparency in an explicit RGBA image.
        prepared = image.convert("RGBA") if image.mode in {"P", "1"} else image
        output = prepared.resize((size.width, size.height), methods[size.resampling])
        output.save(destination, format="PNG")
