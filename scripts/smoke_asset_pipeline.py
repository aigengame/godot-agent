"""Verify an installed gda file handoff outside the checkout (#908).

Run with the clean environment's Python and pass its gda executable. Fixtures and
Godot caches live in an owned temporary directory and are removed on completion.
"""

import argparse
import hashlib
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
                    "max": [1, 1, 0.0001],
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
    for resource in ("adapters/blender.py", "adapters/_blender_worker.py"):
        assert files("gda_assets").joinpath(resource).is_file(), resource
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
        observations_output = root / "content-observations.json"
        declared_model_hash = hashlib.sha256(
            (source / "model.glb").read_bytes()
        ).hexdigest()
        assert not observations_output.exists()
        first = call(
            "asset-pipeline",
            "run",
            "--files",
            json.dumps(mapping),
            "--source-root",
            str(source),
            "--collect-observations",
            "--observations-output",
            str(observations_output),
            "--declared-output-sha256",
            json.dumps({"res://art/model.glb": declared_model_hash}),
            *common,
        )["pipeline"]
        assert first["completed"] == [
            "validate",
            "stage",
            "install",
            "import",
            "load",
            "observe",
        ]
        assert first["observations"][0]["texture_size"] == [2, 1]
        assert first["observations"][1]["resource_type"] == "PackedScene"
        assert first["observations"][1]["scene_node_count"] >= 1
        assert all(
            observation["engine"]["major"] >= 4 for observation in first["observations"]
        )
        collected = first["content_observations"]
        assert collected["status"] == "stable"
        assert collected["saved_to"] == str(observations_output.resolve())
        assert collected["declared_output_sha256"] == {
            "res://art/model.glb": declared_model_hash
        }
        assert collected["issues"] == []
        assert collected["changes"] == []
        assert json.loads(observations_output.read_text()) == collected
        assert [item["path"] for item in collected["assets"]] == [
            "res://art/icon.png",
            "res://art/model.glb",
        ]
        for asset in collected["assets"]:
            assert asset["import_before"]["cache_status"] == "missing"
            assert asset["import_after"]["cache_status"] == "cached"
            assert asset["configuration_before"] is None
            for digest in (
                asset["source_before"],
                asset["source_after"],
                asset["configuration_after"],
                *asset["artifacts"],
            ):
                assert digest["state"] == "observed"
                assert len(digest["sha256"]) == 64
                assert digest["size"] > 0
                assert digest["reason"] is None
            assert asset["source_before"] == asset["source_after"]
            assert asset["artifacts"]
            assert asset["engine"]["major"] >= 4
        model_collection = collected["assets"][1]
        assert model_collection["source_before"]["sha256"] == declared_model_hash
        assert (source / "icon.png").read_bytes() == original
        expectations = root / "model.expectations.json"
        expectations.write_text(
            json.dumps(
                {
                    "checks": [
                        {
                            "id": "mesh",
                            "kind": "count",
                            "metric": "mesh_instance_count",
                            "min": 1,
                            "max": 1,
                        },
                        {
                            "id": "size",
                            "kind": "dimensions",
                            "min": [1, 1, 0],
                            "max": [1, 1, 0.0001],
                        },
                    ]
                }
            )
        )
        checked = call(
            "asset-pipeline",
            "check",
            "--expectations",
            str(expectations),
            "--path",
            "res://art/model.glb",
            *common,
        )
        assert checked["verdict"] == "pass", checked
        report = root / "inspection.json"
        report.write_text(
            json.dumps(
                call("resource", "inspect-model", "res://art/model.glb", *common)
            )
        )
        offline = call(
            "asset-pipeline",
            "check",
            "--expectations",
            str(expectations),
            "--report",
            str(report),
            "--baseline",
            str(report),
            "--json",
        )
        assert offline["verdict"] == "pass", offline
        assert offline["comparison"]["changes"] == []
        assert offline["observation_source"] == "supplied_report"
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
        "Installed asset pipeline smoke passed: PNG resize, GLB load, selected disk/import observations, saved observation JSON, model expectations, saved comparison, repeat, declarations, refusal, cleanup."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gda", required=True, type=Path, help="Installed gda executable"
    )
    parser.add_argument("--godot", help="Godot executable override")
    args = parser.parse_args()
    smoke(args.gda.resolve(), args.godot)
