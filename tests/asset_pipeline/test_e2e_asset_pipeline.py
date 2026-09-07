"""Real-Godot public handoff checks for PNG resize and GLB (#908)."""

import json
import struct
import zlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gda.cli import app


def _png(path: Path, width: int = 2, height: int = 3) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    rows = b"".join(b"\x00" + bytes([255, 0, 0, 255]) * width for _ in range(height))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
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
    document += b" " * (-len(document) % 4)
    chunk = struct.pack("<I4s", len(document), b"JSON") + document
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(chunk)) + chunk)


def _run(project: Path, source_root: Path, files: list[dict]):
    return CliRunner().invoke(
        app,
        [
            "asset-pipeline",
            "run",
            "--files",
            json.dumps(files),
            "--source-root",
            str(source_root),
            "--project",
            str(project),
            "--json",
        ],
    )


@pytest.mark.e2e
def test_png_handoff_resizes_preserves_source_and_loads_in_godot(
    godot_project, tmp_path
):
    source_root = tmp_path / "inputs"
    source_root.mkdir()
    source = source_root / "icon.png"
    _png(source)
    original = source.read_bytes()

    result = _run(
        godot_project,
        source_root,
        [
            {
                "source": "icon.png",
                "target": "res://art/icon.png",
                "resize": {"width": 8, "height": 5, "resampling": "nearest"},
            }
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)["pipeline"]
    assert payload["completed"] == ["validate", "stage", "install", "import", "load"]
    assert payload["observations"][0]["texture_size"] == [8, 5]
    assert source.read_bytes() == original


@pytest.mark.e2e
def test_glb_handoff_loads_as_a_scene_in_godot(godot_project, tmp_path):
    source_root = tmp_path / "inputs"
    source_root.mkdir()
    _glb(source_root / "model.glb")

    result = _run(
        godot_project,
        source_root,
        [{"source": "model.glb", "target": "res://models/model.glb"}],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    observation = json.loads(result.stdout)["pipeline"]["observations"][0]
    assert observation["resource_type"] == "PackedScene"
    assert observation["scene_node_count"] >= 2
