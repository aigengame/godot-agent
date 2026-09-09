"""Deterministic embedded-albedo GLB fixtures shared by native tests."""

import json
from pathlib import Path
import struct
import zlib


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def _rgba_png(*, color: tuple[int, int, int, int], size: int) -> bytes:
    compressor = zlib.compressobj(level=9)
    pixel = bytes(color)
    row = b"\0" + pixel * size
    compressed = [compressor.compress(row) for _ in range(size)]
    compressed.append(compressor.flush())
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + _png_chunk(b"IDAT", b"".join(compressed))
        + _png_chunk(b"IEND", b"")
    )


def write_albedo_glb(
    path: Path,
    *,
    color: tuple[int, int, int, int],
    size: int = 2,
) -> None:
    """Write one fixed quad whose only variable content is an embedded RGBA PNG."""
    if size < 1:
        raise ValueError("size must be at least 1")
    if len(color) != 4 or any(
        type(channel) is not int or not 0 <= channel <= 255 for channel in color
    ):
        raise ValueError("color must contain four integer channels in 0..255")

    positions = struct.pack(
        "<12f",
        -1.0,
        -1.0,
        0.0,
        1.0,
        -1.0,
        0.0,
        1.0,
        1.0,
        0.0,
        -1.0,
        1.0,
        0.0,
    )
    normals = struct.pack("<12f", *(0.0, 0.0, 1.0) * 4)
    texcoords = struct.pack("<8f", 0.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0)
    indices = struct.pack("<6H", 0, 1, 2, 0, 2, 3)
    geometry = positions + normals + texcoords + indices
    geometry += b"\0" * (-len(geometry) % 4)
    image = _rgba_png(color=color, size=size)
    binary = geometry + image
    binary += b"\0" * (-len(binary) % 4)

    document = {
        "asset": {"version": "2.0", "generator": "gda embedded albedo fixture"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [
            {"name": "AssetRoot", "children": [1]},
            {"name": "Body", "mesh": 0},
        ],
        "materials": [
            {
                "name": "BodyMaterial",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [1.0, 1.0, 1.0, 1.0],
                    "baseColorTexture": {"index": 0},
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.5,
                },
            }
        ],
        "meshes": [
            {
                "name": "BodyMesh",
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": 0,
                            "NORMAL": 1,
                            "TEXCOORD_0": 2,
                        },
                        "indices": 3,
                        "material": 0,
                    }
                ],
            }
        ],
        "textures": [{"source": 0}],
        "images": [{"bufferView": 4, "mimeType": "image/png"}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {
                "buffer": 0,
                "byteOffset": 0,
                "byteLength": len(positions),
                "target": 34962,
            },
            {
                "buffer": 0,
                "byteOffset": len(positions),
                "byteLength": len(normals),
                "target": 34962,
            },
            {
                "buffer": 0,
                "byteOffset": len(positions) + len(normals),
                "byteLength": len(texcoords),
                "target": 34962,
            },
            {
                "buffer": 0,
                "byteOffset": len(positions) + len(normals) + len(texcoords),
                "byteLength": len(indices),
                "target": 34963,
            },
            {
                "buffer": 0,
                "byteOffset": len(geometry),
                "byteLength": len(image),
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 4,
                "type": "VEC3",
                "min": [-1.0, -1.0, 0.0],
                "max": [1.0, 1.0, 0.0],
            },
            {
                "bufferView": 1,
                "componentType": 5126,
                "count": 4,
                "type": "VEC3",
            },
            {
                "bufferView": 2,
                "componentType": 5126,
                "count": 4,
                "type": "VEC2",
            },
            {
                "bufferView": 3,
                "componentType": 5123,
                "count": 6,
                "type": "SCALAR",
            },
        ],
    }
    payload = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()
    payload += b" " * (-len(payload) % 4)
    chunks = (
        struct.pack("<I4s", len(payload), b"JSON")
        + payload
        + struct.pack("<I4s", len(binary), b"BIN\0")
        + binary
    )
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, len(chunks) + 12) + chunks)
