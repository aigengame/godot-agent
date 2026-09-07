"""Verify an installed gda file handoff outside the checkout (#908).

Run with the clean environment's Python and pass its gda executable. Fixtures and
Godot caches live in an owned temporary directory and are removed on completion.
"""

import argparse
from importlib.resources import files
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import zlib


def png(path: Path) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data))
        )

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 2, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + b"\xff\0\0" * 4) * 2))
        + chunk(b"IEND", b"")
    )


def glb(path: Path) -> None:
    vertices = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    data = vertices + struct.pack("<3H", 0, 1, 2)
    document = json.dumps(
        {
            "asset": {"version": "2.0"},
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [{"name": "Triangle", "mesh": 0}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
            "buffers": [{"byteLength": len(data)}],
            "bufferViews": [
                {"buffer": 0, "byteOffset": 0, "byteLength": 36},
                {"buffer": 0, "byteOffset": 36, "byteLength": 6},
            ],
            "accessors": [
                {
                    "bufferView": 0,
                    "componentType": 5126,
                    "count": 3,
                    "type": "VEC3",
                    "min": [0, 0, 0],
                    "max": [1, 1, 0],
                },
                {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"},
            ],
        },
        separators=(",", ":"),
    ).encode()
    document += b" " * (-len(document) % 4)
    data += b"\0" * (-len(data) % 4)
    payload = (
        struct.pack("<I4s", len(document), b"JSON")
        + document
        + struct.pack("<I4s", len(data), b"BIN\0")
        + data
    )
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, len(payload) + 12) + payload)


def smoke(gda: Path, godot: str | None) -> None:
    import gda_assets.api  # noqa: F401 — also prove library installation

    for resource in ("ops/operations.gd", "harness/gda_harness.gd", "skill/SKILL.md"):
        assert files("gda").joinpath(resource).is_file(), resource
    with tempfile.TemporaryDirectory(prefix="gda-assets-smoke-") as directory:
        root = Path(directory)
        source, project = root / "source", root / "consumer"
        source.mkdir()
        project.mkdir()
        (project / "project.godot").write_text(
            'config_version=5\n[application]\nconfig/name="Asset handoff smoke"\n'
            '[rendering]\nrenderer/rendering_method="gl_compatibility"\n'
            "[debug]\nfile_logging/enable_file_logging=false\n"
        )
        png(source / "icon.png")
        glb(source / "model.glb")
        original = (source / "icon.png").read_bytes()

        def call(*args: str, success: bool = True) -> dict:
            command = [str(gda), *args]
            process = subprocess.run(
                command, cwd=root, text=True, capture_output=True, timeout=120
            )
            assert (process.returncode == 0) == success, (
                command,
                process.stdout,
                process.stderr,
            )
            return json.loads(process.stdout)

        schema = call("asset-pipeline", "run", "--schema")
        assert "files" in schema["input"]["properties"]
        assert schema["kind"] == "composite"
        common = ["--project", str(project), "--json"]
        if godot:
            common += ["--godot", godot]
        mapping = [
            {
                "source": "icon.png",
                "target": "res://art/icon.png",
                "resize": {"width": 2, "height": 1, "resampling": "nearest"},
            },
            {"source": "model.glb", "target": "res://art/model.glb"},
        ]
        first = call(
            "asset-pipeline",
            "run",
            "--files",
            json.dumps(mapping),
            "--source-root",
            str(source),
            *common,
        )["pipeline"]
        assert first["completed"] == ["validate", "stage", "install", "import", "load"]
        assert first["observations"][0]["texture_size"] == [2, 1]
        assert first["observations"][1]["resource_type"] == "PackedScene"
        assert first["observations"][1]["scene_node_count"] >= 1
        assert all(
            observation["engine"]["major"] >= 4 for observation in first["observations"]
        )
        assert (source / "icon.png").read_bytes() == original
        repeat = call(
            "asset-pipeline",
            "run",
            "--params-json",
            json.dumps(
                {
                    "files": mapping,
                    "source_root": str(source),
                    "source_mode": "imagegen",
                    "provenance": {"note": "caller-declared smoke fixture"},
                }
            ),
            *common,
        )["pipeline"]
        assert [item["state"] for item in repeat["outputs"]] == [
            "unchanged",
            "unchanged",
        ]
        assert repeat["caller_declared_provenance"] == {
            "note": "caller-declared smoke fixture"
        }
        assert repeat["observations"] == first["observations"]

        missing = call(
            "asset-pipeline",
            "run",
            "--files",
            json.dumps(
                [
                    {"source": "icon.png", "target": "res://not-installed.png"},
                    {"source": "missing.png", "target": "res://missing.png"},
                ]
            ),
            "--source-root",
            str(source),
            *common,
            success=False,
        )
        assert missing["error"]["partial_result"]["failure"]["stage"] == "validate"
        assert not (project / "not-installed.png").exists()
        assert not (project / "missing.png").exists()
    print(
        "Installed asset pipeline smoke passed: PNG resize, GLB load, repeat, declarations, refusal, cleanup."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gda", required=True, type=Path, help="Installed gda executable"
    )
    parser.add_argument("--godot", help="Godot executable override")
    args = parser.parse_args()
    smoke(args.gda.resolve(), args.godot)
