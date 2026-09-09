"""Real-engine static LOD content and count-bound sampling."""

import os

import pytest

from tests.conftest import project_godot
from tests.lod_support import write_lod_sphere_glb
from tests.support import Gda, assert_windowed_ok


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX"),
]

LOD_PROJECT_GODOT = project_godot(
    name="gda-static-lod-e2e",
    extra=(
        'run/main_scene="res://main.tscn"\n\n'
        '[rendering]\n\nrenderer/rendering_method="gl_compatibility"'
    ),
)

LOD_MAIN_SCRIPT = """extends Node3D
func _ready() -> void:
    _add_model("ModelA", 1.0)
    _add_model("ModelB", 2.0)
    _add_model("IndexChanged", 1.0, 1, true)
    _add_budgeted_model()
    _add_wide_model()

func _add_model(model_name: String, first_edge: float, lod_count := 1,
        changed_indices := false) -> void:
    var instance := MeshInstance3D.new()
    instance.name = model_name
    var arrays := []
    arrays.resize(Mesh.ARRAY_MAX)
    arrays[Mesh.ARRAY_VERTEX] = PackedVector3Array([
        Vector3(-1, 0, 0), Vector3(1, 0, 0),
        Vector3(1, 1, 0), Vector3(-1, 1, 0)])
    arrays[Mesh.ARRAY_INDEX] = PackedInt32Array([0, 1, 2, 0, 2, 3])
    var lods := {}
    for index in lod_count:
        lods[first_edge + index] = (PackedInt32Array([0, 2, 3])
            if changed_indices else PackedInt32Array([0, 1, 2]))
    var mesh := ArrayMesh.new()
    mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays, [], lods)
    instance.mesh = mesh
    add_child(instance)

func _add_budgeted_model() -> void:
    var arrays := []
    arrays.resize(Mesh.ARRAY_MAX)
    arrays[Mesh.ARRAY_VERTEX] = PackedVector3Array([
        Vector3(-1, 0, 0), Vector3(1, 0, 0),
        Vector3(1, 1, 0), Vector3(-1, 1, 0)])
    arrays[Mesh.ARRAY_INDEX] = PackedInt32Array([0, 1, 2, 0, 2, 3])
    var lods := {}
    for index in 1024:
        lods[float(index + 1)] = PackedInt32Array([0, 1, 2])
    var template := ArrayMesh.new()
    template.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays, [], lods)
    # Construct a malformed stored entry only so the public readback boundary
    # can prove rejected entries still consume its processing budget.
    var stored: Array = template.get("_surfaces")
    var first: Dictionary = stored[0]
    var stored_lods: Array = first["lods"]
    stored_lods[stored_lods.size() - 1] = PackedByteArray([0])
    first["lods"] = stored_lods
    stored[0] = first
    var mesh := ArrayMesh.new()
    mesh.set("_surfaces", stored)
    mesh.add_surface_from_arrays(
        Mesh.PRIMITIVE_TRIANGLES, arrays, [],
        {2048.0: PackedInt32Array([0, 1, 2])})
    var instance := MeshInstance3D.new()
    instance.name = "Budgeted"
    instance.mesh = mesh
    add_child(instance)

func _add_wide_model() -> void:
    var instance := MeshInstance3D.new()
    instance.name = "WideModel"
    var vertices := PackedVector3Array()
    vertices.resize(65537)
    vertices[0] = Vector3(-1, 0, 0)
    vertices[1] = Vector3(1, 0, 0)
    vertices[65536] = Vector3(0, 1, 0)
    var arrays := []
    arrays.resize(Mesh.ARRAY_MAX)
    arrays[Mesh.ARRAY_VERTEX] = vertices
    arrays[Mesh.ARRAY_INDEX] = PackedInt32Array([0, 1, 65536, 0, 65536, 1])
    var mesh := ArrayMesh.new()
    mesh.add_surface_from_arrays(
        Mesh.PRIMITIVE_TRIANGLES, arrays, [],
        {1.0: PackedInt32Array([0, 1, 65536])})
    instance.mesh = mesh
    add_child(instance)
"""

LOD_MAIN_SCENE = """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://main.gd" id="1"]

[node name="Main" type="Node3D"]
script = ExtResource("1")
"""

IMPORTED_MAIN_SCRIPT = """extends Node3D
func _ready() -> void:
    var model := (load("res://model.glb") as PackedScene).instantiate()
    model.name = "Model"
    add_child(model)
"""

IMPORTED_LOD_ASSERTION = """extends SceneTree
func _initialize() -> void:
    var scene := load("res://model.glb") as PackedScene
    var root := scene.instantiate()
    var meshes := root.find_children("*", "MeshInstance3D", true, false)
    assert(meshes.size() == 1)
    var mesh := (meshes[0] as MeshInstance3D).mesh
    var surface := RenderingServer.mesh_get_surface(mesh.get_rid(), 0)
    assert((surface.get("lods", []) as Array).size() > 0)
    root.free()
    quit()
"""

BYTE_LIMIT_SCRIPT = """extends Node3D
func _ready() -> void:
    var instance := MeshInstance3D.new()
    instance.name = "Model"
    var arrays := []
    arrays.resize(Mesh.ARRAY_MAX)
    arrays[Mesh.ARRAY_VERTEX] = PackedVector3Array([
        Vector3(-1, 0, 0), Vector3(1, 0, 0),
        Vector3(1, 1, 0), Vector3(-1, 1, 0)])
    var base_indices := PackedInt32Array()
    base_indices.resize(4194309)
    for index in base_indices.size():
        base_indices[index] = index % 3
    arrays[Mesh.ARRAY_INDEX] = base_indices
    var lod_indices := PackedInt32Array()
    lod_indices.resize(4194306)
    for index in lod_indices.size():
        lod_indices[index] = index % 3
    var mesh := ArrayMesh.new()
    mesh.add_surface_from_arrays(
        Mesh.PRIMITIVE_TRIANGLES, arrays, [], {1.0: lod_indices})
    instance.mesh = mesh
    add_child(instance)
"""


def test_live_static_content_hashes_lods_and_bounds_their_count(
    tmp_path, daemon_runtime_dir
):
    (tmp_path / "project.godot").write_text(LOD_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(LOD_MAIN_SCENE, encoding="utf-8")
    (tmp_path / "main.gd").write_text(LOD_MAIN_SCRIPT, encoding="utf-8")
    run = Gda(tmp_path, json_output=True, timeout=120)

    try:
        assert run("daemon", "start").returncode == 0
        assert run("daemon", "wait-ready").returncode == 0
        first = run.json("game", "inspect-model-content", "--node", "/root/Main/ModelA")
        changed = run.json(
            "game", "inspect-model-content", "--node", "/root/Main/ModelB"
        )
        index_changed = run.json(
            "game", "inspect-model-content", "--node", "/root/Main/IndexChanged"
        )
        bounded = run.json(
            "game", "inspect-model-content", "--node", "/root/Main/Budgeted"
        )
        wide = run.json(
            "game", "inspect-model-content", "--node", "/root/Main/WideModel"
        )
    finally:
        run("daemon", "stop")

    for result in (first, changed, index_changed):
        assert result["content"]["measurement"] == "godot-static-model-content-v2"
        assert result["content"]["complete"] is True
        assert result["content"]["unsupported"] == []
        assert result["content"]["omitted"] == []
        assert len(result["content"]["digest"]) == 64
    assert first["content"]["digest"] != changed["content"]["digest"]
    assert first["content"]["digest"] != index_changed["content"]["digest"]
    assert wide["content"]["complete"] is True
    assert wide["content"]["unsupported"] == []
    assert wide["content"]["omitted"] == []
    assert len(wide["content"]["digest"]) == 64
    assert bounded["content"]["complete"] is False
    assert bounded["content"]["digest"] is None
    assert bounded["content"]["unsupported"] == [
        ".:surface:0: RenderingServer LOD representation is unsupported"
    ]
    assert bounded["content"]["omitted"] == ["LOD count limit exceeded at .:surface:1"]


@pytest.mark.parametrize(
    "windowed",
    [False, pytest.param(True, marks=pytest.mark.xdist_group("windowed"))],
)
def test_normally_imported_lod_sphere_matches_its_live_instance(
    tmp_path, daemon_runtime_dir, request, windowed
):
    if windowed:
        request.getfixturevalue("windowed_host")
    (tmp_path / "project.godot").write_text(LOD_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(LOD_MAIN_SCENE, encoding="utf-8")
    (tmp_path / "main.gd").write_text(IMPORTED_MAIN_SCRIPT, encoding="utf-8")
    (tmp_path / "assert_lods.gd").write_text(IMPORTED_LOD_ASSERTION, encoding="utf-8")
    write_lod_sphere_glb(tmp_path / "model.glb", marker="normal-import")
    run = Gda(tmp_path, json_output=True, timeout=120)

    run.json("resource", "import", "res://model.glb")
    settings = (tmp_path / "model.glb.import").read_text(encoding="utf-8")
    assert "meshes/generate_lods=true" in settings
    assertion = run.json("script", "run", "res://assert_lods.gd", "--strict")
    assert assertion["exit_status"] == 0
    resource = run.json(
        "resource", "inspect-model-content", "--path", "res://model.glb"
    )
    try:
        start = run("daemon", "start", *(["--windowed"] if windowed else []))
        if windowed:
            assert_windowed_ok(start)
        else:
            assert start.returncode == 0
        assert run("daemon", "wait-ready").returncode == 0
        live = run.json("game", "inspect-model-content", "--node", "/root/Main/Model")
        status = run.json("daemon", "status")
    finally:
        run("daemon", "stop")

    assert resource["content"]["measurement"] == "godot-static-model-content-v2"
    assert resource["content"]["complete"] is True
    assert resource["content"]["unsupported"] == []
    assert resource["content"]["omitted"] == []
    assert live["content"] == resource["content"]
    assert live["scene_file_path"] == "res://model.glb"
    assert status["windowed"] is windowed


def test_live_static_content_bounds_lod_index_bytes(tmp_path, daemon_runtime_dir):
    (tmp_path / "project.godot").write_text(LOD_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(LOD_MAIN_SCENE, encoding="utf-8")
    (tmp_path / "main.gd").write_text(BYTE_LIMIT_SCRIPT, encoding="utf-8")
    run = Gda(tmp_path, json_output=True, timeout=120)

    try:
        assert run("daemon", "start").returncode == 0
        assert run("daemon", "wait-ready").returncode == 0
        result = run.json("game", "inspect-model-content", "--node", "/root/Main/Model")
    finally:
        run("daemon", "stop")

    assert result["content"]["complete"] is False
    assert result["content"]["digest"] is None
    assert result["content"]["unsupported"] == []
    assert result["content"]["omitted"] == [
        "LOD index byte limit exceeded at .:surface:0"
    ]
