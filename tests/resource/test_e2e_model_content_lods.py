"""Real-engine refusal for ArrayMesh LOD content outside #890's initial scope."""

import os

import pytest

from tests.conftest import LIVE_PROJECT_GODOT
from tests.support import Gda


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX"),
]

LOD_MAIN_SCRIPT = """extends Node3D
func _ready() -> void:
    var instance := MeshInstance3D.new()
    instance.name = "Model"
    var arrays := []
    arrays.resize(Mesh.ARRAY_MAX)
    arrays[Mesh.ARRAY_VERTEX] = PackedVector3Array([
        Vector3(-1, 0, 0), Vector3(1, 0, 0),
        Vector3(1, 1, 0), Vector3(-1, 1, 0)])
    arrays[Mesh.ARRAY_INDEX] = PackedInt32Array([0, 1, 2, 0, 2, 3])
    var lods := {1.0: PackedInt32Array([0, 1, 2])}
    var mesh := ArrayMesh.new()
    mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays, [], lods)
    instance.mesh = mesh
    add_child(instance)
"""

LOD_MAIN_SCENE = """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://main.gd" id="1"]

[node name="Main" type="Node3D"]
script = ExtResource("1")
"""


def test_live_static_content_refuses_a_real_arraymesh_lod(tmp_path, daemon_runtime_dir):
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(LOD_MAIN_SCENE, encoding="utf-8")
    (tmp_path / "main.gd").write_text(LOD_MAIN_SCRIPT, encoding="utf-8")
    run = Gda(tmp_path, json_output=True, timeout=120)

    try:
        assert run("daemon", "start").returncode == 0
        assert run("daemon", "wait-ready").returncode == 0
        result = run.json("game", "inspect-model-content", "--node", "/root/Main/Model")
    finally:
        run("daemon", "stop")

    assert result["content"]["complete"] is False
    assert result["content"]["digest"] is None
    assert result["content"]["unsupported"] == [".:surface:0: LODs are unsupported"]
