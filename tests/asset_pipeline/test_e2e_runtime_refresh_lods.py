"""Controlled same-path refresh where only imported static LOD content changes."""

import json
import os
from pathlib import Path

import pytest

from tests.conftest import project_godot
from tests.lod_support import write_lod_sphere_glb
from tests.support import Gda

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX"),
]

MODEL = "res://model.glb"
NODE = "/root/Test/Model"

POST_IMPORT = """@tool
extends EditorScenePostImport

func _post_import(scene: Node) -> Object:
    var variant := FileAccess.get_file_as_string("res://lod_variant.txt").strip_edges()
    _replace_mesh_lods(scene, variant)
    return scene

func _replace_mesh_lods(node: Node, variant: String) -> void:
    if node is MeshInstance3D and node.mesh is ArrayMesh:
        var source := node.mesh as ArrayMesh
        var replacement := ArrayMesh.new()
        for surface in source.get_surface_count():
            var arrays := source.surface_get_arrays(surface)
            var edge_length := 0.25 if variant == "A" else 0.75
            var lods := {edge_length: PackedInt32Array([0, 33, 1])}
            replacement.add_surface_from_arrays(
                source.surface_get_primitive_type(surface), arrays, [], lods)
            replacement.surface_set_material(surface, source.surface_get_material(surface))
        node.mesh = replacement
    for child in node.get_children():
        _replace_mesh_lods(child, variant)
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
        "--files",
        json.dumps([{"source": source, "target": MODEL}]),
        "--source-root",
        str(source_root),
        "--overwrite",
    ]
    if refresh is not None:
        args += ["--refresh", json.dumps(refresh)]
    return run.json(*args, timeout=180)


def _digest(sample: dict) -> str:
    content = sample["content"]
    assert content["measurement"] == "godot-static-model-content-v2"
    assert content["complete"] is True
    assert content["unsupported"] == []
    assert content["omitted"] == []
    assert len(content["digest"]) == 64
    return content["digest"]


def _base_geometry(report: dict) -> dict:
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
        "summary": report["summary"],
        "bounds": report["bounds"],
        "surfaces": surfaces,
    }


def test_refresh_rejects_stale_instance_then_adopts_lod_only_change(
    tmp_path, daemon_runtime_dir, monkeypatch
):
    project, source = tmp_path / "project", tmp_path / "source"
    project.mkdir()
    source.mkdir()
    (project / "project.godot").write_text(
        project_godot(
            name="gda-lod-refresh-e2e",
            extra=(
                'run/main_scene="res://test.tscn"\n\n'
                '[rendering]\n\nrenderer/rendering_method="gl_compatibility"'
            ),
        ),
        encoding="utf-8",
    )
    (project / "test.tscn").write_text(SCENE, encoding="utf-8")
    (project / "startup.gd").write_text(STARTUP, encoding="utf-8")
    (project / "lod_post_import.gd").write_text(POST_IMPORT, encoding="utf-8")
    write_lod_sphere_glb(source / "warmup.glb", marker="warmup")
    write_lod_sphere_glb(source / "a.glb", marker="variant-a")
    write_lod_sphere_glb(source / "b.glb", marker="variant-b")
    monkeypatch.setenv("GDA_USER_DATA_ROOT", str(tmp_path / "user-data"))
    run = Gda(project, json_output=True, timeout=180)

    _handoff(run, source, "warmup.glb")
    sidecar = project / "model.glb.import"
    settings = sidecar.read_text(encoding="utf-8")
    assert 'import_script/path=""' in settings
    sidecar.write_text(
        settings.replace(
            'import_script/path=""', 'import_script/path="res://lod_post_import.gd"'
        ),
        encoding="utf-8",
    )
    (project / "lod_variant.txt").write_text("A", encoding="utf-8")
    _handoff(run, source, "a.glb")
    imported_a = run.json("resource", "inspect-model-content", "--path", MODEL)
    report_a = run.json("resource", "inspect-model", MODEL)

    try:
        assert run("daemon", "start").returncode == 0
        run.json("daemon", "wait-ready", "--timeout", "25")
        live_a = run.json("game", "inspect-model-content", "--node", NODE)
        session_a = live_a["session_id"]
        assert _digest(live_a) == _digest(imported_a)

        (project / "lod_variant.txt").write_text("B", encoding="utf-8")
        _handoff(run, source, "b.glb")
        imported_b = run.json("resource", "inspect-model-content", "--path", MODEL)
        report_b = run.json("resource", "inspect-model", MODEL)
        stale_a = run.json("game", "inspect-model-content", "--node", NODE)

        assert _digest(imported_b) != _digest(imported_a)
        assert _digest(stale_a) == _digest(imported_a)
        assert stale_a["session_id"] == session_a
        assert _base_geometry(report_b) == _base_geometry(report_a)

        result = _handoff(
            run,
            source,
            "b.glb",
            refresh={"path": MODEL, "scene": "res://test.tscn", "node": NODE},
        )
        refresh = result["pipeline"]["refresh"]
        assert refresh["status"] == "verified"
        assert refresh["comparison"] == {"status": "match", "reasons": []}
        assert refresh["ready_session"]["session_id"] != session_a
        assert _digest(refresh["imported"]) == _digest(imported_b)
        assert _digest(refresh["instance"]) == _digest(imported_b)
    finally:
        run("daemon", "stop")
