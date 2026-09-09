"""Contract tests for the shared embedded-albedo GLB fixture."""

import json
from pathlib import Path
import struct

import pytest

from tests.albedo_support import write_albedo_glb


def _glb(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    magic, version, total = struct.unpack_from("<4sII", data)
    assert (magic, version, total) == (b"glTF", 2, len(data))
    json_size, json_kind = struct.unpack_from("<I4s", data, 12)
    assert json_kind == b"JSON"
    document = json.loads(data[20 : 20 + json_size])
    binary_header = 20 + json_size
    binary_size, binary_kind = struct.unpack_from("<I4s", data, binary_header)
    assert binary_kind == b"BIN\0"
    binary = data[binary_header + 8 :]
    assert len(binary) == binary_size
    return document, binary


@pytest.mark.parametrize("size", [1, 2, 1024, 2048])
def test_albedo_variants_change_only_embedded_image_bytes(tmp_path, size):
    first = tmp_path / "first.glb"
    second = tmp_path / "second.glb"
    write_albedo_glb(first, color=(240, 40, 80, 255), size=size)
    write_albedo_glb(second, color=(20, 170, 230, 255), size=size)

    first_document, first_binary = _glb(first)
    second_document, second_binary = _glb(second)
    image_view = first_document["bufferViews"][4]
    image_offset = image_view["byteOffset"]
    image_end = image_offset + image_view["byteLength"]

    assert first_document == second_document
    assert [node["name"] for node in first_document["nodes"]] == [
        "AssetRoot",
        "Body",
    ]
    assert [mesh["name"] for mesh in first_document["meshes"]] == ["BodyMesh"]
    assert [material["name"] for material in first_document["materials"]] == [
        "BodyMaterial"
    ]
    assert len(first_document["textures"]) == len(first_document["images"]) == 1
    assert "uri" not in first_document["images"][0]
    assert first_binary[:image_offset] == second_binary[:image_offset]
    assert first_binary[image_offset:image_end].startswith(b"\x89PNG\r\n\x1a\n")
    assert second_binary[image_offset:image_end].startswith(b"\x89PNG\r\n\x1a\n")
    assert first_binary[image_offset:image_end] != second_binary[image_offset:image_end]
    assert first_binary[image_end:] == second_binary[image_end:]
    assert first_document["accessors"][0] == {
        "bufferView": 0,
        "componentType": 5126,
        "count": 4,
        "type": "VEC3",
        "min": [-1.0, -1.0, 0.0],
        "max": [1.0, 1.0, 0.0],
    }
    assert first_document["accessors"][3]["count"] == 6
    assert "extensionsUsed" not in first_document
