"""Real-Godot load observations for imported PNG and GLB assets (#908)."""

import json
import struct
import zlib
from pathlib import Path

import pytest

from gda.commands.resource import (
    ResourceImportParams,
    ResourceLoadResult,
    run_resource_import_operation,
    run_resource_load_operation,
)
from gda.errors import Failure


def _png(path: Path, width: int = 3, height: int = 2) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _glb(path: Path) -> None:
    document = json.dumps(
        {
            "asset": {"version": "2.0"},
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [{"name": "Root"}],
        },
        separators=(",", ":"),
    ).encode()
    document += b" " * ((4 - len(document) % 4) % 4)
    chunk = struct.pack("<I4s", len(document), b"JSON") + document
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(chunk)) + chunk)


def _import(project: Path, asset: str):
    outcome = run_resource_import_operation(
        project, ResourceImportParams(assets=[asset]), godot=None
    )
    assert not isinstance(outcome, Failure), outcome


@pytest.mark.e2e
def test_load_observes_imported_png_dimensions(godot_project):
    _png(godot_project / "icon.png")
    _import(godot_project, "res://icon.png")

    outcome = run_resource_load_operation(godot_project, "res://icon.png")

    assert isinstance(outcome, ResourceLoadResult)
    assert outcome.path == "res://icon.png"
    assert outcome.resource_type.endswith("Texture2D")
    assert outcome.texture_size == [3, 2]
    assert outcome.scene_node_count is None
    assert outcome.engine_version.major >= 4


@pytest.mark.e2e
def test_load_observes_imported_glb_scene(godot_project):
    _glb(godot_project / "model.glb")
    _import(godot_project, "res://model.glb")

    outcome = run_resource_load_operation(godot_project, "res://model.glb")

    assert isinstance(outcome, ResourceLoadResult)
    assert outcome.path == "res://model.glb"
    assert outcome.resource_type == "PackedScene"
    # Godot's glTF importer supplies a PackedScene root plus the declared node.
    assert outcome.scene_node_count == 2
    assert outcome.texture_size is None


@pytest.mark.e2e
@pytest.mark.parametrize("path", ["res://missing.png", "res://broken.png"])
def test_load_rejects_missing_or_malformed_resource(godot_project, path):
    if path.endswith("broken.png"):
        (godot_project / "broken.png").write_bytes(b"not a png")

    outcome = run_resource_load_operation(godot_project, path)

    assert isinstance(outcome, Failure)
    assert outcome.error.code in {"path_not_found", "invalid_path"}


@pytest.mark.e2e
def test_load_rejects_path_escape_without_loading(godot_project, tmp_path):
    outside = tmp_path.parent / "outside-908.png"
    _png(outside)

    outcome = run_resource_load_operation(godot_project, outside)

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "target_outside_project"
