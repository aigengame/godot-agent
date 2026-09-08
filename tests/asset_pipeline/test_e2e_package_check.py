"""Cold exported-PCK acceptance through the public package workflow (#892)."""

import hashlib
import json
import shutil
import struct
from pathlib import Path

import pytest

from tests.conftest import project_godot
from tests.support import Gda

pytestmark = pytest.mark.e2e


def _glb(path: Path) -> None:
    positions = struct.pack("<12f", -2, -1, 0, 3, -1, 0, 3, 2, 0, -2, 2, 0)
    indices = struct.pack("<6H", 0, 1, 2, 0, 2, 3)
    times = struct.pack("<2f", 0, 1)
    translations = struct.pack("<6f", 0, 0, 0, 1, 0, 0)
    binary = positions + indices + times + translations
    binary += b"\0" * (-len(binary) % 4)
    document = {
        "asset": {"version": "2.0", "generator": "gda #892 fixture"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "Asset", "children": [1]}, {"name": "Body", "mesh": 0}],
        "materials": [
            {
                "name": "BodyMaterial",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.2, 0.5, 0.8, 1.0],
                    "metallicFactor": 0.4,
                    "roughnessFactor": 0.6,
                },
            }
        ],
        "meshes": [
            {
                "name": "BodyMesh",
                "primitives": [
                    {"attributes": {"POSITION": 0}, "indices": 1, "material": 0}
                ],
            }
        ],
        "animations": [
            {
                "name": "Move",
                "samplers": [{"input": 2, "output": 3, "interpolation": "LINEAR"}],
                "channels": [
                    {"sampler": 0, "target": {"node": 1, "path": "translation"}}
                ],
            }
        ],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
            {"buffer": 0, "byteOffset": len(positions), "byteLength": len(indices)},
            {
                "buffer": 0,
                "byteOffset": len(positions) + len(indices),
                "byteLength": len(times),
            },
            {
                "buffer": 0,
                "byteOffset": len(positions) + len(indices) + len(times),
                "byteLength": len(translations),
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 4,
                "type": "VEC3",
                "min": [-2, -1, 0],
                "max": [3, 2, 0],
            },
            {"bufferView": 1, "componentType": 5123, "count": 6, "type": "SCALAR"},
            {
                "bufferView": 2,
                "componentType": 5126,
                "count": 2,
                "type": "SCALAR",
                "min": [0],
                "max": [1],
            },
            {"bufferView": 3, "componentType": 5126, "count": 2, "type": "VEC3"},
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


def _preset(name: str, index: int, *, exclude: str, include: str = "") -> str:
    return f'''[preset.{index}]

name="{name}"
platform="Linux/X11"
runnable=true
custom_features=""
export_filter="all_resources"
include_filter="{include}"
exclude_filter="{exclude}"
export_path="dist/{name}.pck"

[preset.{index}.options]

binary_format/embed_pck=false
'''


def _project(root: Path) -> tuple[Path, Path]:
    root.mkdir()
    model = root / "model.glb"
    _glb(model)
    (root / "dev.txt").write_text("development-only\n")
    (root / "main.tscn").write_text(
        "[gd_scene load_steps=2 format=3]\n\n"
        '[ext_resource type="PackedScene" path="res://model.glb" id="1"]\n\n'
        '[node name="Main" type="Node3D"]\n\n'
        '[node name="Model" parent="." instance=ExtResource("1")]\n'
    )
    (root / "project.godot").write_text(
        project_godot(name="gda-892-e2e", extra='run/main_scene="res://main.tscn"')
    )
    (root / "export_presets.cfg").write_text(
        _preset("Included", 0, exclude="dev.txt")
        + "\n"
        + _preset("DevPresent", 1, exclude="", include="*.txt")
        + "\n"
        + _preset("ModelOmitted", 2, exclude="model.glb,main.tscn")
    )
    expectations = root / "expectations.json"
    expectations.write_text(
        json.dumps(
            {
                "checks": [
                    {
                        "id": "body",
                        "kind": "node",
                        "node": "Asset/Body",
                        "type": "MeshInstance3D",
                    },
                    {
                        "id": "nodes",
                        "kind": "count",
                        "metric": "node_count",
                        "min": 4,
                        "max": 4,
                    },
                    {
                        "id": "meshes",
                        "kind": "count",
                        "metric": "mesh_instance_count",
                        "min": 1,
                        "max": 1,
                    },
                    {
                        "id": "size",
                        "kind": "dimensions",
                        "min": [4.99, 2.99, 0],
                        "max": [5.01, 3.01, 0.001],
                    },
                    {
                        "id": "material",
                        "kind": "material",
                        "node": "Asset/Body",
                        "surface": 0,
                        "name": "BodyMaterial",
                    },
                    {
                        "id": "animation",
                        "kind": "animation_target",
                        "node": "AnimationPlayer",
                        "animation": "Move",
                        "track": 0,
                        "target": "Asset/Body",
                    },
                ]
            }
        )
    )
    return model, expectations


def _export(run: Gda, preset: str, output: Path) -> None:
    result = run.json(
        "export",
        "run",
        "--preset",
        preset,
        "--mode",
        "pack",
        "--output",
        str(output),
        timeout=300,
    )
    assert result["mode"] == "pack"
    assert result["output_path"] == str(output)
    assert output.is_file()


def _package(run: Gda, package: Path, expectations: Path, *extra: str) -> dict:
    return run.json(
        "asset-pipeline",
        "check-package",
        "--package",
        str(package),
        "--path",
        "res://model.glb",
        "--expectations",
        str(expectations),
        *extra,
        timeout=180,
    )


def _assert_identity(result: dict, package: Path) -> dict:
    checked = result["package_check"]
    assert checked["origin"] == "package_editor_inspection"
    assert checked["package"]["source"] == str(package)
    assert (
        Path(checked["package"]["path"])
        == Path(checked["package"]["root"]) / "package.pck"
    )
    assert (
        checked["package"]["sha256"] == hashlib.sha256(package.read_bytes()).hexdigest()
    )
    assert checked["package"]["size_bytes"] == package.stat().st_size
    assert checked["presence"]["engine"]["version"]
    assert checked["presence"]["engine"]["build_hash"]
    assert checked["cleanup"] == {"staging_removed": True, "issues": []}
    assert not Path(checked["package"]["root"]).exists()
    assert not Path(checked["package"]["path"]).exists()
    return checked


def test_cold_exported_packages_use_only_imported_remaps_for_checks_and_exclusions(
    tmp_path, monkeypatch
):
    project = tmp_path / "source"
    model, expectations = _project(project)
    run = Gda(project, json_output=True, timeout=300)
    monkeypatch.setenv("GDA_USER_DATA_ROOT", str(tmp_path / "user-data"))
    model_before = model.read_bytes()
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "project.godot").write_text(project_godot(name="unrelated"))
    (unrelated / "keep.txt").write_text("must stay\n")
    unrelated_before = {
        path.relative_to(unrelated): path.read_bytes()
        for path in unrelated.rglob("*")
        if path.is_file()
    }

    run.json("resource", "import", "res://model.glb", timeout=180)
    source_check = run.json(
        "asset-pipeline",
        "check",
        "--path",
        "res://model.glb",
        "--expectations",
        str(expectations),
    )
    assert source_check["verdict"] == "pass"
    assert source_check["observation_source"] == "godot"

    shutil.rmtree(project / ".godot")
    included = tmp_path / "included.pck"
    _export(run, "Included", included)
    included_before = included.read_bytes()
    package_result = _package(
        Gda(unrelated, json_output=True),
        included,
        expectations,
        "--exclude",
        "res://dev.txt",
    )
    checked = _assert_identity(package_result, included)
    assert checked["completed"] == [
        "validate",
        "stage",
        "presence",
        "inspect",
        "evaluate",
        "cleanup",
    ]
    assert checked["failure"] is None
    assert checked["verdict"] == "pass"
    assert checked["inspection"]["model"]["resource"] == "res://model.glb"
    assert checked["inspection"]["engine"] == checked["presence"]["engine"]
    assert checked["check"]["verdict"] == "pass"
    assert checked["check"]["observation_source"] == "supplied_report"
    assert {item["id"]: item["verdict"] for item in checked["check"]["checks"]} == {
        "body": "pass",
        "nodes": "pass",
        "meshes": "pass",
        "size": "pass",
        "material": "pass",
        "animation": "pass",
    }
    assert checked["exclusions"] == [
        {"path": "res://dev.txt", "present": False, "verdict": "pass"}
    ]
    assert included.read_bytes() == included_before

    present = tmp_path / "dev-present.pck"
    _export(run, "DevPresent", present)
    present_result = _package(
        Gda(None, json_output=True),
        present,
        expectations,
        "--exclude",
        "res://dev.txt",
    )
    present_checked = _assert_identity(present_result, present)
    assert present_checked["check"]["verdict"] == "pass"
    assert present_checked["exclusions"] == [
        {"path": "res://dev.txt", "present": True, "verdict": "fail"}
    ]
    assert present_checked["verdict"] == "fail"

    omitted = tmp_path / "model-omitted.pck"
    _export(run, "ModelOmitted", omitted)
    failure = Gda(None, json_output=True).error(
        "asset-pipeline",
        "check-package",
        "--package",
        str(omitted),
        "--path",
        "res://model.glb",
        "--expectations",
        str(expectations),
        code="path_not_found",
        timeout=180,
    )
    partial = _assert_identity(failure["partial_result"], omitted)
    assert partial["failure"]["stage"] in {"presence", "inspect"}
    assert partial["verdict"] is None
    assert partial["inspection"] is None
    assert partial["check"] is None

    assert model.read_bytes() == model_before
    assert {
        path.relative_to(unrelated): path.read_bytes()
        for path in unrelated.rglob("*")
        if path.is_file()
    } == unrelated_before
