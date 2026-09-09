"""Final combined LOD and embedded-albedo runtime-refresh witness (#907)."""

import json
import os
from pathlib import Path

import pytest

from tests.conftest import project_godot
from tests.support import Gda, assert_windowed_ok

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX"),
    pytest.mark.xdist_group("windowed"),
]

MODEL = "res://model.glb"
NODE = "/root/Test/Model"

GENERATOR = """extends SceneTree

func _initialize() -> void:
    DirAccess.make_dir_absolute("res://generated")
    _write_model("res://generated/a.glb", Color8(255, 32, 16, 255))
    _write_model("res://generated/b.glb", Color8(16, 32, 255, 255))
    quit()

func _write_model(path: String, color: Color) -> void:
    var root := Node3D.new()
    root.name = "AssetRoot"
    var instance := MeshInstance3D.new()
    instance.name = "Body"
    var mesh := SphereMesh.new()
    mesh.radial_segments = 32
    mesh.rings = 16
    var image := Image.create(2, 2, false, Image.FORMAT_RGBA8)
    image.fill(color)
    var material := StandardMaterial3D.new()
    material.resource_name = "BodyMaterial"
    material.albedo_texture = ImageTexture.create_from_image(image)
    mesh.material = material
    instance.mesh = mesh
    root.add_child(instance)
    instance.owner = root
    var document := GLTFDocument.new()
    var state := GLTFState.new()
    assert(document.append_from_scene(root, state) == OK)
    assert(document.write_to_filesystem(state, path) == OK)
    root.free()
"""

PROBE = """extends SceneTree

func _initialize() -> void:
    var packed := load("res://model.glb") as PackedScene
    assert(packed != null)
    var root := packed.instantiate()
    var instance := _mesh_instance(root)
    assert(instance != null and instance.mesh is ArrayMesh)
    var mesh := instance.mesh as ArrayMesh
    var lods := 0
    for surface_index in mesh.get_surface_count():
        var surface := RenderingServer.mesh_get_surface(mesh.get_rid(), surface_index)
        var levels: Variant = surface.get("lods", [])
        assert(levels is Array)
        lods += levels.size()
    var material := instance.get_active_material(0) as StandardMaterial3D
    assert(material != null and material.albedo_texture != null)
    var image := material.albedo_texture.get_image()
    assert(image != null and not image.is_empty())
    var hashing := HashingContext.new()
    assert(hashing.start(HashingContext.HASH_SHA256) == OK)
    assert(hashing.update(image.get_data()) == OK)
    print("COMBINED_FACTS=" + JSON.stringify({
        "lods": lods,
        "image_width": image.get_width(),
        "image_height": image.get_height(),
        "image_bytes": image.get_data_size(),
        "image_sha256": hashing.finish().hex_encode(),
    }))
    root.free()
    quit()

func _mesh_instance(node: Node) -> MeshInstance3D:
    if node is MeshInstance3D:
        return node
    for child in node.get_children():
        var found := _mesh_instance(child)
        if found != null:
            return found
    return null
"""

STARTUP = """extends Node3D
func _ready() -> void:
    var model := (load("res://model.glb") as PackedScene).instantiate()
    model.name = "Model"
    add_child(model)
"""

SCENE = """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://startup.gd" id="1"]

[node name="Test" type="Node3D"]
script = ExtResource("1")
"""


def _handoff(run: Gda, source_root: Path, source: str, *, refresh=None) -> dict:
    args = [
        "asset-pipeline",
        "run",
        "--source-root",
        str(source_root),
        "--files",
        json.dumps([{"source": source, "target": MODEL}]),
        "--overwrite",
    ]
    if refresh is not None:
        args += ["--refresh", json.dumps(refresh)]
    return run.json(*args)


def _digest(sample: dict) -> str:
    content = sample["content"]
    assert content["measurement"] == "godot-static-model-content-v3"
    assert content["complete"] is True, content
    assert content["unsupported"] == []
    assert content["omitted"] == []
    assert len(content["digest"]) == 64
    return content["digest"]


def _geometry(report: dict) -> dict:
    surfaces = []
    for node in report["nodes"]:
        mesh = node.get("mesh")
        if mesh is None:
            continue
        surfaces.extend(
            {
                "node": node["path"],
                "primitive": surface["primitive"],
                "vertex_count": surface["vertex_count"],
                "index_count": surface["index_count"],
                "triangle_count": surface["triangle_count"],
            }
            for surface in mesh["surfaces"]
        )
    return {
        "path": report["path"],
        "node_paths": [node["path"] for node in report["nodes"]],
        "summary": report["summary"],
        "bounds": report["bounds"],
        "surfaces": surfaces,
    }


def _native_facts(run: Gda) -> dict:
    result = run.json("script", "run", "res://combined_probe.gd", "--strict")
    line = next(
        line
        for line in result["stdout"].splitlines()
        if line.startswith("COMBINED_FACTS=")
    )
    return json.loads(line.removeprefix("COMBINED_FACTS="))


@pytest.mark.usefixtures("windowed_host", "daemon_runtime_dir")
def test_normal_import_refreshes_combined_lod_and_embedded_albedo_model(
    tmp_path, monkeypatch
):
    project, source = tmp_path / "project", tmp_path / "source"
    project.mkdir()
    source.mkdir()
    (project / "project.godot").write_text(
        project_godot(
            name="gda-combined-refresh-e2e",
            extra=(
                'run/main_scene="res://test.tscn"\n\n'
                '[rendering]\n\nrenderer/rendering_method="gl_compatibility"'
            ),
        ),
        encoding="utf-8",
    )
    (project / "test.tscn").write_text(SCENE, encoding="utf-8")
    (project / "startup.gd").write_text(STARTUP, encoding="utf-8")
    (project / "generate.gd").write_text(GENERATOR, encoding="utf-8")
    (project / "combined_probe.gd").write_text(PROBE, encoding="utf-8")
    monkeypatch.setenv("GDA_USER_DATA_ROOT", str(tmp_path / "user-data"))
    run = Gda(project, json_output=True, timeout=180)

    generated = project / "generated"
    assert (
        run.json("script", "run", "res://generate.gd", "--strict")["exit_status"] == 0
    )
    for name in ("a.glb", "b.glb"):
        (source / name).write_bytes((generated / name).read_bytes())
        (generated / name).unlink()
    generated.rmdir()

    try:
        _handoff(run, source, "a.glb")
        imported_a = run.json("resource", "inspect-model-content", "--path", MODEL)
        report_a = run.json("resource", "inspect-model", MODEL)
        facts_a = _native_facts(run)
        assert facts_a["lods"] > 0
        assert facts_a["image_width"] == facts_a["image_height"] == 2
        assert facts_a["image_bytes"] > 0
        assert len(facts_a["image_sha256"]) == 64

        assert_windowed_ok(run("daemon", "start", "--windowed"))
        run.json("daemon", "wait-ready", "--timeout", "25")
        live_a = run.json("game", "inspect-model-content", "--node", NODE)
        assert _digest(live_a) == _digest(imported_a)

        _handoff(run, source, "b.glb")
        imported_b = run.json("resource", "inspect-model-content", "--path", MODEL)
        report_b = run.json("resource", "inspect-model", MODEL)
        facts_b = _native_facts(run)
        stale_a = run.json("game", "inspect-model-content", "--node", NODE)

        assert _geometry(report_b) == _geometry(report_a)
        assert facts_b["lods"] == facts_a["lods"]
        assert facts_b["image_width"] == facts_a["image_width"]
        assert facts_b["image_height"] == facts_a["image_height"]
        assert facts_b["image_bytes"] == facts_a["image_bytes"]
        assert facts_b["image_sha256"] != facts_a["image_sha256"]
        assert _digest(imported_b) != _digest(imported_a)
        assert _digest(stale_a) == _digest(imported_a)
        assert stale_a["session_id"] == live_a["session_id"]

        result = _handoff(
            run,
            source,
            "b.glb",
            refresh={
                "path": MODEL,
                "scene": "res://test.tscn",
                "node": NODE,
                "windowed": True,
            },
        )
        refresh = result["pipeline"]["refresh"]
        assert refresh["status"] == "verified"
        assert refresh["comparison"] == {"status": "match", "reasons": []}
        assert refresh["ready_session"]["session_id"] != live_a["session_id"]
        assert _digest(refresh["imported"]) == _digest(imported_b)
        assert _digest(refresh["instance"]) == _digest(imported_b)
    finally:
        stopped = run("daemon", "stop")
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
