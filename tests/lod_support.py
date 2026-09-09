"""Maintained untextured GLB fixture for Godot-generated static LOD tests."""

import json
import math
import struct
from pathlib import Path


def write_lod_sphere_glb(path: Path, *, marker: str) -> None:
    """Write equal-geometry sphere GLBs whose marker can drive a test import hook."""
    segments = 32
    rings = 16
    positions: list[float] = []
    for ring in range(rings + 1):
        latitude = math.pi * ring / rings
        for segment in range(segments + 1):
            longitude = 2.0 * math.pi * segment / segments
            positions.extend(
                (
                    math.sin(latitude) * math.cos(longitude),
                    math.cos(latitude),
                    math.sin(latitude) * math.sin(longitude),
                )
            )
    indices: list[int] = []
    for ring in range(rings):
        for segment in range(segments):
            top = ring * (segments + 1) + segment
            bottom = top + segments + 1
            indices.extend((top, bottom, top + 1, top + 1, bottom, bottom + 1))

    position_bytes = struct.pack(f"<{len(positions)}f", *positions)
    index_bytes = struct.pack(f"<{len(indices)}H", *indices)
    binary = position_bytes + index_bytes
    binary += b"\0" * (-len(binary) % 4)
    document = {
        "asset": {"version": "2.0", "generator": f"gda issue 953 {marker}"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "Sphere", "mesh": 0}],
        "meshes": [
            {
                "name": "SphereMesh",
                "primitives": [{"attributes": {"POSITION": 0}, "indices": 1}],
            }
        ],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(position_bytes)},
            {
                "buffer": 0,
                "byteOffset": len(position_bytes),
                "byteLength": len(index_bytes),
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(positions) // 3,
                "type": "VEC3",
                "min": [-1.0, -1.0, -1.0],
                "max": [1.0, 1.0, 1.0],
            },
            {
                "bufferView": 1,
                "componentType": 5123,
                "count": len(indices),
                "type": "SCALAR",
            },
        ],
    }
    payload = json.dumps(document, separators=(",", ":")).encode()
    payload += b" " * (-len(payload) % 4)
    chunks = (
        struct.pack("<I4s", len(payload), b"JSON")
        + payload
        + struct.pack("<I4s", len(binary), b"BIN\0")
        + binary
    )
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks)
