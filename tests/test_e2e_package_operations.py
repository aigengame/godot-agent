"""Real exported-PCK structural inspection without source/cache fallback (#892)."""

import json
from pathlib import Path
import struct

import pytest

from gda.commands.resource import (
    PackageResourcePresenceParams,
    PackageResourcePresenceResult,
    ResourceInspectModelParams,
    ResourceInspectModelResult,
    run_package_inspect_model_operation,
    run_package_resource_presence_operation,
)
from gda.errors import Failure
from tests.support import Gda, GODOT


pytestmark = pytest.mark.e2e


def _glb(path: Path, name: str) -> None:
    vertices = struct.pack("<9f", -1, 0, 0, 1, 0, 0, 0, 1, 0.00001)
    indices = struct.pack("<3H", 0, 1, 2)
    binary = vertices + indices
    binary += b"\0" * (-len(binary) % 4)
    document = json.dumps(
        {
            "asset": {"version": "2.0"},
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [{"name": name, "mesh": 0}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
            "buffers": [{"byteLength": len(binary)}],
            "bufferViews": [
                {"buffer": 0, "byteOffset": 0, "byteLength": len(vertices)},
                {
                    "buffer": 0,
                    "byteOffset": len(vertices),
                    "byteLength": len(indices),
                },
            ],
            "accessors": [
                {
                    "bufferView": 0,
                    "componentType": 5126,
                    "count": 3,
                    "type": "VEC3",
                    "min": [-1, 0, 0],
                    "max": [1, 1, 0.00001],
                },
                {
                    "bufferView": 1,
                    "componentType": 5123,
                    "count": 3,
                    "type": "SCALAR",
                },
            ],
        },
        separators=(",", ":"),
    ).encode()
    document += b" " * (-len(document) % 4)
    chunks = (
        struct.pack("<I4s", len(document), b"JSON")
        + document
        + struct.pack("<I4s", len(binary), b"BIN\0")
        + binary
    )
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, len(chunks) + 12) + chunks)


def _project(root: Path) -> None:
    root.mkdir()
    (root / "project.godot").write_text(
        'config_version=5\n[application]\nconfig/name="package-inspection"\n'
        'run/main_scene="res://main.tscn"\n'
    )
    (root / "main.tscn").write_text(
        "[gd_scene load_steps=2 format=3]\n\n"
        '[ext_resource type="PackedScene" path="res://included.glb" id="1"]\n\n'
        '[node name="Main" type="Node3D"]\n'
        '[node name="Included" parent="." instance=ExtResource("1")]\n'
    )
    (root / "export_presets.cfg").write_text(
        '[preset.0]\n\nname="Linux/X11"\nplatform="Linux/X11"\n'
        'runnable=true\ncustom_features=""\nexport_filter="all_resources"\n'
        'include_filter=""\nexclude_filter="omitted.glb"\n'
        'export_path="build/game.x86_64"\n\n[preset.0.options]\n\n'
        "binary_format/embed_pck=false\n"
    )
    _glb(root / "included.glb", "IncludedMesh")
    _glb(root / "omitted.glb", "OmittedMesh")


def test_package_only_inspection_sees_imported_remap_and_exclusion(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    package = tmp_path / "game.pck"
    _project(source)
    monkeypatch.setenv("GDA_USER_DATA_ROOT", str(tmp_path / "user-data"))
    export = Gda(source, json_output=True).json(
        "export",
        "run",
        "--preset",
        "Linux/X11",
        "--mode",
        "pack",
        "--output",
        str(package),
        timeout=120,
    )
    assert export["mode"] == "pack" and package.is_file()

    # The package calls receive only the PCK. Rename the source tree so neither
    # its project nor its warm .godot cache can satisfy a resource lookup.
    source.rename(tmp_path / "source-hidden")
    report = run_package_inspect_model_operation(
        package,
        ResourceInspectModelParams(path="res://included.glb"),
        godot=str(GODOT),
    )
    presence = run_package_resource_presence_operation(
        package,
        PackageResourcePresenceParams(
            paths=["res://included.glb", "res://omitted.glb", "res://main.tscn"]
        ),
        godot=str(GODOT),
    )

    assert isinstance(report, ResourceInspectModelResult), report
    assert report.path == "res://included.glb"
    assert report.summary.mesh_instance_count == 1
    assert report.bounds is not None
    assert report.truncated is False and report.omissions == []
    assert report.engine_version.major == 4
    assert isinstance(presence, PackageResourcePresenceResult), presence
    assert [(item.path, item.present) for item in presence.resources] == [
        ("res://included.glb", True),
        ("res://omitted.glb", False),
        ("res://main.tscn", True),
    ]
    assert presence.engine_version.hash == report.engine_version.hash

    omitted = run_package_inspect_model_operation(
        package,
        ResourceInspectModelParams(path="res://omitted.glb"),
        godot=str(GODOT),
    )
    assert isinstance(omitted, Failure)
    assert omitted.error.code == "path_not_found"
