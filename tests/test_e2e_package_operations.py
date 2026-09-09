"""Real exported-PCK structural inspection without source/cache fallback (#892)."""

import json
from pathlib import Path
import struct
import zipfile

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
from gda.runner import launch
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


def _simple_export_project(root: Path, *, exclude: str) -> None:
    root.mkdir()
    (root / "project.godot").write_text(
        'config_version=5\n[application]\nconfig/name="package-header-probe"\n'
        'run/main_scene="res://main.tscn"\n'
    )
    (root / "main.tscn").write_text(
        '[gd_scene format=3]\n\n[node name="Main" type="Node"]\n'
    )
    (root / "export_presets.cfg").write_text(
        '[preset.0]\n\nname="Probe"\nplatform="Linux/X11"\n'
        'runnable=true\ncustom_features=""\nexport_filter="all_resources"\n'
        f'include_filter=""\nexclude_filter="{exclude}"\n'
        'export_path="build/probe.pck"\n\n[preset.0.options]\n\n'
        "binary_format/embed_pck=false\n"
    )


def _pck_directory(package: Path) -> tuple[int, int]:
    data = package.read_bytes()
    offset = struct.unpack_from("<Q", data, 32)[0]
    return offset, struct.unpack_from("<I", data, offset)[0]


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


def test_failed_export_header_is_refused_without_rejecting_valid_v3_controls(
    tmp_path, monkeypatch
):
    failed_source = tmp_path / "failed-source"
    minimal_source = tmp_path / "minimal-source"
    normal_source = tmp_path / "normal-source"
    failed_package = tmp_path / "failed.pck"
    minimal_package = tmp_path / "minimal.pck"
    normal_package = tmp_path / "normal.pck"
    empty_package = tmp_path / "empty.pck"
    _simple_export_project(failed_source, exclude="*")
    _simple_export_project(minimal_source, exclude="")
    _project(normal_source)
    monkeypatch.setenv("GDA_USER_DATA_ROOT", str(tmp_path / "user-data"))

    failed_export = Gda(failed_source, json_output=True).error(
        "export",
        "run",
        "--preset",
        "Probe",
        "--mode",
        "pack",
        "--output",
        str(failed_package),
        code="export_failed",
        timeout=120,
    )
    assert "Must select at least one file to export" in failed_export["diagnostics"]
    failed_bytes = failed_package.read_bytes()
    assert len(failed_bytes) == 112
    assert failed_bytes[:4] == b"GDPC"
    assert struct.unpack_from("<I", failed_bytes, 4)[0] == 3
    assert struct.unpack_from("<Q", failed_bytes, 32)[0] == 0

    for source, output, preset in (
        (minimal_source, minimal_package, "Probe"),
        (normal_source, normal_package, "Linux/X11"),
    ):
        exported = Gda(source, json_output=True).json(
            "export",
            "run",
            "--preset",
            preset,
            "--mode",
            "pack",
            "--output",
            str(output),
            timeout=180,
        )
        assert exported["mode"] == "pack"

    generator = tmp_path / "empty-pck.gd"
    generator.write_text(
        "extends SceneTree\n\n"
        "func _initialize() -> void:\n"
        "    var packer := PCKPacker.new()\n"
        "    var started := packer.pck_start(OS.get_cmdline_user_args()[0])\n"
        "    var flushed := packer.flush()\n"
        '    print("EMPTY_PCK_RESULTS:", started, ":", flushed)\n'
        "    quit(0 if started == OK and flushed == OK else 9)\n"
    )
    empty_cwd = tmp_path / "empty-cwd"
    empty_cwd.mkdir()
    generated = launch(
        GODOT,
        ["--script", str(generator), "--", str(empty_package)],
        cwd=empty_cwd,
        timeout=15,
        timeout_label="Godot empty PCK generation",
    )
    assert generated.exit_code == 0, generated
    assert "EMPTY_PCK_RESULTS:0:0" in generated.stdout

    empty_offset, empty_count = _pck_directory(empty_package)
    minimal_offset, minimal_count = _pck_directory(minimal_package)
    normal_offset, normal_count = _pck_directory(normal_package)
    assert empty_offset > 0 and empty_count == 0
    assert minimal_offset > 0 and minimal_count > 0
    assert normal_offset > 0 and normal_count > minimal_count

    expectations = tmp_path / "expectations.json"
    expectations.write_text(
        '{"checks":[{"id":"nodes","kind":"count","metric":"node_count","min":1}]}'
    )
    refusal = Gda(None, json_output=True).error(
        "asset-pipeline",
        "check-package",
        "--package",
        str(failed_package),
        "--path",
        "res://main.tscn",
        "--expectations",
        str(expectations),
        code="operation_failed",
        timeout=30,
    )
    assert "incomplete Godot PCK" in refusal["message"]
    partial = refusal["partial_result"]["package_check"]
    assert partial["completed"] == ["validate", "stage", "cleanup"]
    assert partial["package"]["source"] == str(failed_package)
    assert partial["package"]["size_bytes"] == 112
    assert partial["cleanup"] == {"staging_removed": True, "issues": []}
    assert not Path(partial["package"]["root"]).exists()

    for package, paths, expected in (
        (empty_package, ["res://missing.tscn"], [("res://missing.tscn", False)]),
        (minimal_package, ["res://main.tscn"], [("res://main.tscn", True)]),
        (
            normal_package,
            ["res://included.glb", "res://omitted.glb", "res://main.tscn"],
            [
                ("res://included.glb", True),
                ("res://omitted.glb", False),
                ("res://main.tscn", True),
            ],
        ),
    ):
        presence = run_package_resource_presence_operation(
            package,
            PackageResourcePresenceParams(paths=paths),
            godot=str(GODOT),
        )
        assert isinstance(presence, PackageResourcePresenceResult), presence
        assert [(item.path, item.present) for item in presence.resources] == expected


def test_public_package_check_refuses_an_installed_release_template_before_script(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GDA_USER_DATA_ROOT", str(tmp_path / "user-data"))
    archive = (
        Path.home()
        / "Library/Application Support/Godot/export_templates/4.6.3.stable/macos.zip"
    )
    if not archive.is_file():
        pytest.skip("Godot 4.6.3 macOS export template is not installed")
    member = "macos_template.app/Contents/MacOS/godot_macos_release.universal"
    with zipfile.ZipFile(archive) as bundle:
        if member not in bundle.namelist():
            pytest.skip("installed template has no macOS release binary")
        bundle.extract(member, tmp_path)
    template = tmp_path / member
    template.chmod(0o755)
    package = tmp_path / "probe.pck"
    package.write_bytes(b"capability probe stops before package loading")
    expectations = tmp_path / "expectations.json"
    expectations.write_text(
        '{"checks":[{"id":"nodes","kind":"count","metric":"node_count","min":1}]}'
    )

    failure = Gda(None, godot=template, json_output=True).error(
        "asset-pipeline",
        "check-package",
        "--package",
        str(package),
        "--path",
        "res://model.glb",
        "--expectations",
        str(expectations),
        code="operation_failed",
        timeout=60,
    )
    partial = failure["partial_result"]["package_check"]
    assert "requires a Godot desktop editor binary" in failure["message"]
    assert "release export template" in failure["diagnostics"]
    assert partial["completed"] == ["validate", "stage", "cleanup"]
    assert partial["presence"] is None and partial["inspection"] is None
    assert partial["cleanup"] == {"staging_removed": True, "issues": []}
    assert not Path(partial["package"]["root"]).exists()
