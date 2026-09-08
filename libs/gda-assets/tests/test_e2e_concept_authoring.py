"""Real selected-reference consumption by the two bounded #913 examples."""

import hashlib
import json
import os
from pathlib import Path
import struct

from PIL import Image
import pytest

from gda_assets.adapters.concept_authoring import (
    BlenderReferenceBlockoutAuthor,
    SpriteSheetReferenceAuthor,
)
from gda_assets.domain.concept import (
    ConceptAuthorRequest,
    ConceptBrief,
    ConceptBriefSnapshot,
    ConceptSelection,
    SelectedConcept,
    SpriteSheetLayout,
)


pytestmark = pytest.mark.e2e


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _glb_base_color(path: Path):
    payload = path.read_bytes()
    json_size = struct.unpack_from("<I", payload, 12)[0]
    document = json.loads(payload[20 : 20 + json_size])
    return document["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"]


def _selection(root: Path, name: str, color: tuple[int, int, int, int]):
    root.mkdir()
    image = root / name
    Image.new("RGBA", (4, 2), color).save(image)
    selected = SelectedConcept(
        0,
        "../attempt/prompt.json",
        name,
        "resolved-prompt-sha256",
        image,
        _digest(image),
        image.stat().st_size,
        4,
        2,
        True,
    )
    return ConceptSelection(
        1,
        root,
        ConceptBrief("model", "colored block", "flat", views=("front",)),
        ConceptBriefSnapshot(root / "concept-brief.json", "brief", 1),
        (selected,),
    )


def test_blender_uses_the_selected_png_bytes_for_exported_material(tmp_path):
    blender = Path(
        os.environ.get(
            "GDA_BLENDER", "/Applications/Blender.app/Contents/MacOS/Blender"
        )
    )
    assert blender.is_file(), "real Blender is required for the concept authoring E2E"
    red = _selection(tmp_path / "red-handoff", "red.png", (255, 0, 0, 255))
    blue = _selection(tmp_path / "blue-handoff", "blue.png", (0, 0, 255, 255))
    red_output, blue_output = tmp_path / "red-output", tmp_path / "blue-output"
    author = BlenderReferenceBlockoutAuthor()

    red_result = author.author(
        ConceptAuthorRequest(
            red.handoff,
            "blender-reference-blockout",
            red_output,
            blender_executable=blender,
        ),
        red,
    )
    blue_result = author.author(
        ConceptAuthorRequest(
            blue.handoff,
            "blender-reference-blockout",
            blue_output,
            blender_executable=blender,
        ),
        blue,
    )

    assert red_result.reference_loaded and blue_result.reference_loaded
    assert red_result.consumed.sha256 == red.selected[0].sha256
    assert blue_result.consumed.sha256 == blue.selected[0].sha256
    assert red_result.material_color == pytest.approx((1, 0, 0, 1))
    assert blue_result.material_color == pytest.approx((0, 0, 1, 1))
    assert [item.role for item in red_result.artifacts] == ["blend_source", "godot_glb"]
    assert all(
        item.path.is_file() and item.size_bytes > 0 for item in red_result.artifacts
    )
    assert _glb_base_color(red_result.artifacts[1].path) == pytest.approx((1, 0, 0, 1))
    assert _glb_base_color(blue_result.artifacts[1].path) == pytest.approx((0, 0, 1, 1))
    native = json.loads((red_output / "blender-result.json").read_text())
    assert native["completed"][:3] == [
        "read_reference",
        "decode_reference",
        "create_reference",
    ]
    assert native["scene_objects"] == ["ReferenceBlockout", "SelectedConceptReference"]


def test_sprite_sheet_pixels_and_digest_follow_the_selected_png(tmp_path):
    red = _selection(tmp_path / "red-handoff", "red.png", (255, 0, 0, 255))
    blue = _selection(tmp_path / "blue-handoff", "blue.png", (0, 0, 255, 255))
    layout = SpriteSheetLayout(16, 16, 8, 8, 4)
    author = SpriteSheetReferenceAuthor()
    results = []
    for name, selection in (("red", red), ("blue", blue)):
        output = tmp_path / f"{name}-output"
        results.append(
            author.author(
                ConceptAuthorRequest(
                    selection.handoff,
                    "sprite-sheet-reference",
                    output,
                    sprite_layout=layout,
                ),
                selection,
            )
        )

    red_result, blue_result = results
    assert red_result.consumed.sha256 == red.selected[0].sha256
    assert blue_result.consumed.sha256 == blue.selected[0].sha256
    assert red_result.artifacts[0].sha256 != blue_result.artifacts[0].sha256
    assert red_result.sprite_sheet is not None
    assert red_result.sprite_sheet.frames == 4
    with Image.open(red_result.artifacts[0].path) as sheet:
        sheet.load()
        assert sheet.size == (16, 16)
        assert sheet.getpixel((0, 0)) == (255, 0, 0, 255)
    with Image.open(blue_result.artifacts[0].path) as sheet:
        sheet.load()
        assert sheet.getpixel((0, 0)) == (0, 0, 255, 255)
