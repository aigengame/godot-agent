"""Godot-loaded structure and static geometry facts through resource inspect-model."""

import json
import struct
from pathlib import Path

import pytest

from tests.support import Gda

pytestmark = pytest.mark.e2e


@pytest.fixture
def imported_model(godot_project):
    generator = Path(__file__).parent / "fixtures" / "model_inspection.gd"
    (godot_project / "create_model.gd").write_bytes(generator.read_bytes())
    run = Gda(godot_project, json_output=True)
    generated = run.json("script", "run", "res://create_model.gd", "--strict")
    assert generated["exit_status"] == 0
    # GLTFDocument emits one mesh definition per instance. This fixture instead
    # explicitly shares mesh 0, so the imported-resource identity has a known
    # expectation independent of how the authoring exporter duplicates meshes.
    model = godot_project / "model.glb"
    data = model.read_bytes()
    json_length = struct.unpack_from("<I", data, 12)[0]
    document = json.loads(data[20 : 20 + json_length])
    for node in document["nodes"]:
        if "mesh" in node:
            node["mesh"] = 0
    payload = json.dumps(document, separators=(",", ":")).encode()
    payload += b" " * (-len(payload) % 4)
    chunks = (
        struct.pack("<I4s", len(payload), b"JSON") + payload + data[20 + json_length :]
    )
    model.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks)
    run.json("resource", "import", "res://model.glb")
    return godot_project


def test_selected_mesh_root_includes_children_and_excludes_studio(imported_model):
    run = Gda(imported_model, json_output=True)
    source = (imported_model / "model.glb").read_bytes()
    settings = (imported_model / "model.glb.import").read_bytes()
    whole = run.json("resource", "inspect-model", "res://model.glb")
    body_path = next(
        node["path"] for node in whole["nodes"] if node["path"].endswith("Asset/Body")
    )
    selected = run.json(
        "resource", "inspect-model", "res://model.glb", "--subtree", body_path
    )
    assert selected["path"] == "res://model.glb"
    assert selected["engine_version"]["major"] >= 4
    assert selected["summary"]["node_count"] == 2
    assert selected["summary"]["mesh_instance_count"] == 2
    assert selected["summary"]["unique_mesh_count"] == 1
    assert selected["bounds"]["position"] == pytest.approx([1, -1, 0], abs=1e-4)
    assert selected["bounds"]["size"] == pytest.approx([2, 5, 0], abs=1e-4)
    assert selected["measurement"]["geometry"] == "static_mesh_aabb"
    assert selected["measurement"]["coordinate_space"] == "resource"
    assert selected["truncated"] is False
    assert (imported_model / "model.glb").read_bytes() == source
    assert (imported_model / "model.glb.import").read_bytes() == settings


def test_surfaces_report_counts_and_effective_texture_references(imported_model):
    report = Gda(imported_model, json_output=True).json(
        "resource", "inspect-model", "res://model.glb"
    )
    body = next(n for n in report["nodes"] if n["path"].endswith("Asset/Body"))
    mesh = body["mesh"]
    assert mesh["surface_count"] == 1
    surface = mesh["surfaces"][0]
    assert surface["primitive"] == "triangles"
    assert surface["vertex_count"] == 3
    assert surface["index_count"] == 3
    assert surface["triangle_count"] == 1
    assert surface["counts_unavailable_reason"] is None
    material = surface["material"]
    assert material["source"] == "mesh_surface"
    albedo = next(t for t in material["textures"] if t["role"] == "albedo")
    assert (
        albedo["resource"]["type"].endswith("Texture2D")
        or albedo["resource"]["type"] == "ImageTexture"
    )
    assert albedo["resource"]["path"] or albedo["resource"]["unavailable_reason"]


@pytest.fixture
def authored_model(godot_project):
    generator = Path(__file__).parent / "fixtures" / "model_bindings.gd"
    (godot_project / "create_bindings.gd").write_bytes(generator.read_bytes())
    result = Gda(godot_project, json_output=True).json(
        "script", "run", "res://create_bindings.gd", "--strict"
    )
    assert result["exit_status"] == 0
    return godot_project


def test_explicit_skin_names_and_indices_resolve_against_skeleton(authored_model):
    report = Gda(authored_model, json_output=True).json(
        "resource", "inspect-model", "res://bindings.tscn"
    )
    rig = next(n for n in report["nodes"] if n["path"] == "Rig")["skeleton"]
    assert rig["bone_count"] == 2
    assert rig["bones"][1]["name"] == "Arm_L"
    assert rig["bones"][1]["parent"] == 0
    assert rig["bones"][1]["rest"]["origin"] == [0, 2, 0]
    mesh = next(n for n in report["nodes"] if n["path"] == "Body")["mesh"]
    skin = mesh["skin"]
    assert skin["skeleton_path"] == "../Rig"
    assert skin["resolved_skeleton_path"] == "Rig"
    assert skin["bind_count"] == 3
    assert [b["resolved_bone_index"] for b in skin["binds"]] == [1, 0, None]
    assert skin["binds"][2]["unresolved_reason"] == "bone not found"
    assert mesh["surfaces"][0]["vertex_count"] is None  # BoxMesh is not ArrayMesh.
    assert mesh["surfaces"][0]["counts_unavailable_reason"]


def test_animation_targets_use_full_paths_and_report_missing_bones(authored_model):
    report = Gda(authored_model, json_output=True).json(
        "resource", "inspect-model", "res://bindings.tscn"
    )
    player = next(n for n in report["nodes"] if n["path"] == "AnimationPlayer")[
        "animation_player"
    ]
    assert player["resolved_root_path"] == "."
    animation = next(a for a in player["animations"] if a["name"] == "Walk")
    assert animation["length"] == 1.25
    assert animation["track_count"] == 8
    targets = {t["path"]: t for t in animation["tracks"]}
    assert targets["Body"]["target_node_path"] == "Body"
    assert targets["Studio/Body"]["target_node_path"] == "Studio/Body"
    assert targets["Rig:Arm_L"]["status"] == "resolved"
    assert targets["Rig:Arm_L"]["bone_name"] == "Arm_L"
    assert targets["Rig:MissingBone"]["status"] == "unresolved"
    assert targets["Missing/Body"]["status"] == "unresolved"
    assert targets["Missing/Body"]["target_node_path"] is None
    assert targets["Body:position"]["resolution_scope"] == "declared_property"
    assert targets["Body:mesh:size"]["status"] == "unavailable"
    assert targets["Body:missing"]["status"] == "unresolved"


def test_real_skinned_animated_glb_reports_rest_bindings_without_sampling(
    authored_model,
):
    run = Gda(authored_model, json_output=True)
    run.json("resource", "import", "res://skinned.glb")
    report = run.json("resource", "inspect-model", "res://skinned.glb")
    skeletons = [n["skeleton"] for n in report["nodes"] if n["skeleton"]]
    assert any(
        {b["name"] for b in s["bones"]} >= {"Arm_L", "RootBone"} for s in skeletons
    )
    skins = [
        n["mesh"]["skin"] for n in report["nodes"] if n["mesh"] and n["mesh"]["skin"]
    ]
    assert skins
    assert all(b["unresolved_reason"] is None for s in skins for b in s["binds"])
    players = [n["animation_player"] for n in report["nodes"] if n["animation_player"]]
    tracks = [t for p in players for a in p["animations"] for t in a["tracks"]]
    assert tracks and all(t["status"] == "resolved" for t in tracks)
    assert report["measurement"]["geometry"] == "static_mesh_aabb"
    assert any(
        "no animation sampling" in text for text in report["measurement"]["limitations"]
    )


def test_node_and_detail_limits_identify_partial_coverage(imported_model):
    run = Gda(imported_model, json_output=True)
    partial = run.json(
        "resource", "inspect-model", "res://model.glb", "--max-nodes", "1"
    )
    assert len(partial["nodes"]) == 1
    assert partial["truncated"] is True
    assert partial["bounds"] is None
    assert partial["omissions"] == [
        {"node_path": ".", "section": "nodes", "reason": "node_limit"}
    ]
    details = run.json(
        "resource", "inspect-model", "res://model.glb", "--max-items", "1"
    )
    assert details["truncated"] is True
    assert details["summary"]["mesh_instance_count"] == 3
    surfaces = [s for n in details["nodes"] if n["mesh"] for s in n["mesh"]["surfaces"]]
    assert len(surfaces) == 1
    assert surfaces[0]["material"]["textures"] == []
    assert {o["section"] for o in details["omissions"]} == {"textures", "surfaces"}
    assert all(o["reason"] == "detail_limit" for o in details["omissions"])
    assert (
        details["bounds"] is not None
    )  # Detail truncation does not discard node bounds.


def test_empty_subtree_and_distinct_load_failures(godot_project, imported_model):
    run = Gda(godot_project, json_output=True)
    run.json("scene", "create", "res://empty.tscn", "--root-type", "Node3D")
    empty = run.json(
        "resource", "inspect-model", "res://empty.tscn", "--max-nodes", "1"
    )
    assert empty["bounds"] is None
    assert empty["summary"] == {
        "node_count": 1,
        "mesh_instance_count": 0,
        "unique_mesh_count": 0,
    }
    assert empty["truncated"] is False
    assert empty["omissions"] == []
    run.error("resource", "inspect-model", "res://absent.glb", code="path_not_found")
    run.error(
        "resource",
        "inspect-model",
        "res://empty.tscn",
        "--subtree",
        "Missing",
        code="node_not_found",
    )
    run.error(
        "resource",
        "inspect-model",
        "res://empty.tscn",
        "--subtree",
        "/root",
        code="invalid_params",
    )
    run.error(
        "resource",
        "inspect-model",
        "res://empty.tscn",
        "--subtree",
        ".:position",
        code="invalid_params",
    )
    run.json("resource", "create", "res://gradient.tres", "--type", "Gradient")
    wrong_type = run.error(
        "resource", "inspect-model", "res://gradient.tres", code="not_a_scene"
    )
    assert "resource is Gradient, not PackedScene" in wrong_type["message"]
    (godot_project / "garbage.tscn").write_text("not a scene document")
    corrupt = run.error(
        "resource", "inspect-model", "res://garbage.tscn", code="not_a_scene"
    )
    assert "could not be loaded as PackedScene" in corrupt["message"]
    # Valid source bytes with no sidecar/cache under this NEW path cannot load.
    source = (imported_model / "model.glb").read_bytes()
    (godot_project / "cold.glb").write_bytes(source)
    cold = run.error("resource", "inspect-model", "res://cold.glb", code="not_a_scene")
    assert "could not be loaded as PackedScene" in cold["message"]
    assert "resource import" in cold["message"]
    assert not (godot_project / "cold.glb.import").exists()
    assert (godot_project / "cold.glb").read_bytes() == source


def test_resource_transforms_respect_spatial_inheritance_and_returning_seam(
    godot_project,
):
    from gda.commands.resource import (
        ResourceInspectModelParams,
        ResourceInspectModelResult,
        run_resource_inspect_model_operation,
    )

    source = """[gd_scene load_steps=2 format=3]
[sub_resource type="BoxMesh" id="Box"]
size = Vector3(2, 2, 2)
[node name="Root" type="Node3D"]
position = Vector3(10, 0, 0)
[node name="Parent" type="Node3D" parent="."]
position = Vector3(2, 0, 0)
[node name="Inherited" type="MeshInstance3D" parent="Parent"]
position = Vector3(1, 0, 0)
mesh = SubResource("Box")
[node name="Group" type="Node" parent="Parent"]
[node name="Independent" type="MeshInstance3D" parent="Parent/Group"]
position = Vector3(4, 0, 0)
mesh = SubResource("Box")
[node name="Top" type="MeshInstance3D" parent="Parent"]
top_level = true
position = Vector3(7, 0, 0)
mesh = SubResource("Box")
"""
    path = godot_project / "spaces.tscn"
    path.write_text(source)
    report = run_resource_inspect_model_operation(
        godot_project, ResourceInspectModelParams(path=str(path))
    )
    assert isinstance(report, ResourceInspectModelResult), report
    data = report.model_dump(mode="json")
    assert data["path"] == "res://spaces.tscn"
    origins = {
        n["path"]: n["resource_transform"]["origin"] for n in data["nodes"] if n["mesh"]
    }
    assert origins == {
        "Parent/Inherited": [13, 0, 0],
        "Parent/Group/Independent": [4, 0, 0],
        "Parent/Top": [7, 0, 0],
    }
    assert data["bounds"] == {"position": [3, -1, -1], "size": [11, 2, 2]}
    assert data["summary"]["unique_mesh_count"] == 1
    assert path.read_text() == source


def test_effective_material_precedence_and_engine_named_texture_roles(godot_project):
    (godot_project / "materials.tscn").write_text("""[gd_scene load_steps=6 format=3]
[sub_resource type="GradientTexture2D" id="Texture"]
width = 2
height = 2
[sub_resource type="StandardMaterial3D" id="Base"]
resource_name = "Base"
[sub_resource type="StandardMaterial3D" id="Slot"]
resource_name = "Slot"
[sub_resource type="StandardMaterial3D" id="Override"]
resource_name = "Override"
rim_texture = SubResource("Texture")
detail_normal = SubResource("Texture")
[sub_resource type="BoxMesh" id="Mesh"]
material = SubResource("Base")
[node name="Root" type="Node3D"]
[node name="Surface" type="MeshInstance3D" parent="."]
mesh = SubResource("Mesh")
surface_material_override/0 = SubResource("Slot")
[node name="Instance" type="MeshInstance3D" parent="."]
mesh = SubResource("Mesh")
surface_material_override/0 = SubResource("Slot")
material_override = SubResource("Override")
""")
    run = Gda(godot_project, json_output=True)
    report = run.json("resource", "inspect-model", "res://materials.tscn")
    materials = {
        n["path"]: n["mesh"]["surfaces"][0]["material"]
        for n in report["nodes"]
        if n["mesh"]
    }
    assert materials["Surface"]["source"] == "surface_override"
    assert materials["Surface"]["resource"]["name"] == "Slot"
    assert materials["Instance"]["source"] == "material_override"
    assert materials["Instance"]["resource"]["name"] == "Override"
    assert {t["role"] for t in materials["Instance"]["textures"]} == {
        "rim",
        "detail_normal",
    }
