from dataclasses import replace

from gda_assets.domain.model import (
    AnimationFacts,
    BindFacts,
    MaterialFacts,
    ModelFacts,
    NodeFacts,
    SurfaceFacts,
    TrackFacts,
)
from gda_assets.domain.model_diff import compare_models


def _facts(*nodes: NodeFacts, omissions=(), resource="res://before.glb") -> ModelFacts:
    mesh_count = sum(node.type == "MeshInstance3D" for node in nodes)
    return ModelFacts(
        resource=resource,
        subtree=".",
        engine=(4, 6),
        measurement=("resource", "static_mesh_aabb"),
        nodes=nodes,
        counts={
            "node_count": len(nodes),
            "mesh_instance_count": mesh_count,
            "unique_mesh_count": mesh_count,
        },
        bounds={"position": [0, 0, 0], "size": [2, 2, 2]},
        omissions=omissions,
    )


def test_compare_models_reports_stable_relevant_changes() -> None:
    material = MaterialFacts(
        "StandardMaterial3D",
        "Fur",
        "res://fur.tres",
        "mesh_surface",
        (("albedo", "Texture2D", "res://old.png"),),
    )
    before = _facts(
        NodeFacts(
            "Body",
            "MeshInstance3D",
            transform=(1.0,) * 12,
            surface_count=1,
            surfaces=(SurfaceFacts(0, {"vertices": 8}, material),),
            animation_count=1,
            animations=(
                AnimationFacts(
                    "walk",
                    1.0,
                    0,
                    1,
                    (
                        TrackFacts(
                            0,
                            "position_3d",
                            "Arm:position",
                            True,
                            "Arm",
                            None,
                            "resolved",
                            "node",
                            None,
                        ),
                    ),
                ),
            ),
        )
    )
    changed_material = replace(
        material, textures=(("albedo", "Texture2D", "res://new.png"),)
    )
    after = _facts(
        replace(
            before.nodes[0],
            transform=(2.0,) * 12,
            surfaces=(SurfaceFacts(0, {"vertices": 12}, changed_material),),
            animations=(
                replace(
                    before.nodes[0].animations[0],
                    tracks=(
                        replace(before.nodes[0].animations[0].tracks[0], target="Hand"),
                    ),
                ),
            ),
        ),
        NodeFacts("Tail", "Node3D"),
        resource="res://after.glb",
    )

    result = compare_models(before, after)

    assert result["status"] == "comparable"
    assert result["reasons"] == []
    assert result["resources"] == {
        "before": "res://before.glb",
        "after": "res://after.glb",
    }
    assert [(c["section"], c["location"], c["kind"]) for c in result["changes"]] == [
        ("nodes", {"node": "Body"}, "changed"),
        ("surfaces", {"node": "Body", "surface": 0}, "changed"),
        ("textures", {"node": "Body", "surface": 0, "texture": "albedo"}, "changed"),
        ("tracks", {"node": "Body", "animation": "walk", "track": 0}, "changed"),
        ("nodes", {"node": "Tail"}, "added"),
        ("counts", {"count": "node_count"}, "changed"),
    ]
    assert result["incomplete_sections"] == []


def test_compare_models_does_not_infer_removals_from_omitted_collections() -> None:
    surface = SurfaceFacts(0, {"vertices": 8})
    track = TrackFacts(
        0, "position_3d", "Arm:position", True, "Arm", None, "resolved", "node", None
    )
    complete = _facts(
        NodeFacts(
            "Body",
            "MeshInstance3D",
            surface_count=1,
            surfaces=(surface,),
            bind_count=1,
            binds=(BindFacts(0, 2, None),),
        ),
        NodeFacts(
            "Anim",
            "AnimationPlayer",
            animation_count=1,
            animations=(AnimationFacts("walk", 1, 0, 1, (track,)),),
        ),
        NodeFacts("Tail", "Node3D"),
    )
    partial = _facts(
        NodeFacts("Body", "MeshInstance3D", surface_count=1, bind_count=1),
        NodeFacts(
            "Anim",
            "AnimationPlayer",
            animation_count=1,
            animations=(AnimationFacts("walk", 1, 0, 1),),
        ),
        omissions=(
            (".", "nodes"),
            ("Body", "surfaces"),
            ("Body", "skin_binds"),
            ("Anim", "animation_tracks"),
        ),
        resource="res://partial.glb",
    )

    result = compare_models(complete, partial)

    assert result["status"] == "partial"
    assert not any(change["kind"] == "removed" for change in result["changes"])
    assert result["incomplete_sections"] == [
        {
            "section": "animation_tracks",
            "node": "Anim",
            "reason": "observation omitted",
        },
        {"section": "nodes", "reason": "observation omitted"},
        {"section": "skin_binds", "node": "Body", "reason": "observation omitted"},
        {"section": "surfaces", "node": "Body", "reason": "observation omitted"},
    ]


def test_texture_omission_is_partial_without_false_removal_and_keeps_aggregates() -> (
    None
):
    material = MaterialFacts(
        "StandardMaterial3D",
        "Fur",
        "res://fur.tres",
        "mesh_surface",
        (("albedo", "Texture2D", "res://fur.png"),),
    )
    before = _facts(
        NodeFacts(
            "Body",
            "MeshInstance3D",
            surface_count=1,
            surfaces=(SurfaceFacts(0, {"vertices": 8}, material),),
        )
    )
    after = replace(
        before,
        resource="res://after.glb",
        nodes=(
            replace(
                before.nodes[0],
                surfaces=(
                    SurfaceFacts(0, {"vertices": 8}, replace(material, textures=())),
                ),
            ),
        ),
        counts={
            "node_count": 2,
            "mesh_instance_count": 1,
            "unique_mesh_count": 1,
        },
        bounds={"position": [0, 0, 0], "size": [3, 2, 2]},
        omissions=(("Body", "textures"),),
    )

    result = compare_models(before, after)

    assert result["status"] == "partial"
    assert not any(change["section"] == "textures" for change in result["changes"])
    assert [
        (change["section"], change["location"]) for change in result["changes"]
    ] == [
        ("counts", {"count": "node_count"}),
        ("bounds", {}),
    ]
    assert result["incomplete_sections"] == [
        {"section": "textures", "node": "Body", "reason": "observation omitted"}
    ]


def test_unknown_material_path_is_incomplete_not_a_proved_change() -> None:
    before_material = MaterialFacts("StandardMaterial3D", "Fur", None, "mesh_surface")
    after_material = replace(before_material, path="res://fur.tres")
    before = _facts(
        NodeFacts(
            "Body",
            "MeshInstance3D",
            surface_count=1,
            surfaces=(SurfaceFacts(0, {}, before_material),),
        )
    )
    after = replace(
        before,
        resource="res://after.glb",
        nodes=(
            replace(before.nodes[0], surfaces=(SurfaceFacts(0, {}, after_material),)),
        ),
    )

    result = compare_models(before, after)

    assert result["status"] == "partial"
    assert not any(change["section"] == "materials" for change in result["changes"])
    assert result["incomplete_sections"] == [
        {"section": "materials", "node": "Body", "reason": "material path unavailable"}
    ]


def test_unavailable_textures_are_partial_without_an_omission_record() -> None:
    material = MaterialFacts(
        "ShaderMaterial",
        "Fur",
        "res://fur.tres",
        "mesh_surface",
        textures_available=False,
    )
    before = _facts(
        NodeFacts(
            "Body",
            "MeshInstance3D",
            surface_count=1,
            surfaces=(SurfaceFacts(0, {}, material),),
        )
    )

    result = compare_models(before, replace(before, resource="res://after.glb"))

    assert result["status"] == "partial"
    assert result["changes"] == []
    assert result["incomplete_sections"] == [
        {"section": "textures", "node": "Body", "reason": "texture details unavailable"}
    ]


def test_unknown_geometry_and_skin_are_explicitly_partial() -> None:
    before = _facts(
        NodeFacts(
            "Body",
            "MeshInstance3D",
            surface_count=1,
            surfaces=(
                SurfaceFacts(
                    0,
                    {
                        "primitive": None,
                        "vertices": None,
                        "counts_unavailable_reason": "non-ArrayMesh geometry",
                    },
                ),
            ),
            skin_present=False,
            skin_unavailable="no explicit Skin resource",
        )
    )
    after = replace(
        before,
        resource="res://after.glb",
        nodes=(
            replace(
                before.nodes[0],
                surfaces=(
                    SurfaceFacts(
                        0,
                        {
                            "primitive": "triangles",
                            "vertices": 8,
                            "counts_unavailable_reason": None,
                        },
                    ),
                ),
                skin_present=True,
                skin_unavailable=None,
                skeleton="Rig",
            ),
        ),
    )

    result = compare_models(before, after)

    assert result["status"] == "partial"
    assert not any(
        change["section"] in {"surfaces", "skin"} for change in result["changes"]
    )
    assert result["incomplete_sections"] == [
        {"section": "geometry", "node": "Body", "reason": "non-ArrayMesh geometry"},
        {"section": "skin", "node": "Body", "reason": "no explicit Skin resource"},
    ]


def test_compare_models_refuses_incompatible_scope_measurement_or_engine() -> None:
    before = _facts(NodeFacts("Body", "Node3D"))
    after = replace(
        before,
        subtree="Body",
        engine=(4, 7),
        measurement=("world", "static_mesh_aabb"),
    )

    result = compare_models(before, after)

    assert result["status"] == "non_comparable"
    assert result["reasons"] == [
        "subtree differs: . != Body",
        "measurement differs: ('resource', 'static_mesh_aabb') != ('world', 'static_mesh_aabb')",
        "engine major/minor differs: 4.6 != 4.7",
    ]
    assert result["changes"] == []


def test_compare_models_treats_patch_build_difference_as_compatible() -> None:
    before = replace(_facts(NodeFacts("Body", "Node3D")), engine=(4, 6, 2))  # type: ignore[arg-type]
    after = replace(before, engine=(4, 6, 5), resource="res://after.glb")  # type: ignore[arg-type]

    assert compare_models(before, after)["status"] == "comparable"
