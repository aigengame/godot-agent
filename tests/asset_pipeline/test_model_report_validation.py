"""Semantic admission checks for caller-supplied inspect-model reports."""

from copy import deepcopy

import pytest

from gda.commands.resource import ResourceInspectModelResult
from gda.integrations.model_report_validation import validate_model_report


def _report() -> dict:
    identity = {
        "origin": [0.0, 0.0, 0.0],
        "basis": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
    }
    return {
        "path": "res://model.glb",
        "subtree": ".",
        "engine_version": {
            "major": 4,
            "minor": 5,
            "patch": 0,
            "hex": 0x40500,
            "status": "stable",
            "build": "official",
            "hash": "abc",
            "string": "4.5.stable",
            "timestamp": 0,
        },
        "measurement": {
            "coordinate_space": "resource",
            "geometry": "static_mesh_aabb",
            "limitations": [],
        },
        "nodes": [
            {
                "path": ".",
                "type": "Node3D",
                "local_transform": identity,
                "resource_transform": identity,
                "mesh": None,
                "skeleton": None,
                "animation_player": None,
            },
            {
                "path": "Body",
                "type": "MeshInstance3D",
                "local_transform": identity,
                "resource_transform": identity,
                "mesh": {
                    "resource": {
                        "type": "ArrayMesh",
                        "name": "Body",
                        "path": None,
                        "unavailable_reason": "resource has no stored path",
                    },
                    "surface_count": 1,
                    "surfaces": [
                        {
                            "index": 0,
                            "primitive": "triangles",
                            "vertex_count": 3,
                            "index_count": 3,
                            "triangle_count": 1,
                            "triangle_count_basis": "index_slots",
                            "counts_unavailable_reason": None,
                            "material": None,
                        }
                    ],
                    "skin": None,
                    "skin_unavailable_reason": "no explicit Skin resource; runtime-generated bindings are not observed",
                },
                "skeleton": None,
                "animation_player": None,
            },
        ],
        "summary": {"node_count": 2, "mesh_instance_count": 1, "unique_mesh_count": 1},
        "bounds": {"position": [0.0, 0.0, 0.0], "size": [1.0, 2.0, 3.0]},
        "truncated": False,
        "omissions": [],
    }


def _model(payload: dict) -> ResourceInspectModelResult:
    return ResourceInspectModelResult.model_validate(payload)


def test_accepts_a_complete_engine_shaped_report():
    validate_model_report(_model(_report()))


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda value: value["summary"].update(node_count=3), "node_count"),
        (lambda value: value["nodes"].append(deepcopy(value["nodes"][1])), "node path"),
        (lambda value: value["nodes"][1].update(path="../Body"), "node path"),
        (lambda value: value["bounds"]["size"].__setitem__(0, float("nan")), "finite"),
        (lambda value: value["bounds"]["size"].__setitem__(0, -1.0), "non-negative"),
        (lambda value: value["nodes"][1]["mesh"].update(surface_count=2), "surfaces"),
    ],
)
def test_rejects_semantically_contradictory_complete_reports(mutate, match):
    payload = _report()
    mutate(payload)
    with pytest.raises(ValueError, match=match):
        validate_model_report(_model(payload))


def test_accepts_engine_prefixes_when_matching_omissions_locate_them():
    payload = _report()
    payload["nodes"][1]["mesh"].update(surface_count=2)
    payload["truncated"] = True
    payload["omissions"] = [
        {"node_path": "Body", "section": "surfaces", "reason": "detail_limit"}
    ]
    validate_model_report(_model(payload))


@pytest.mark.parametrize(
    "omission",
    [
        {"node_path": ".", "section": "nodes", "reason": "detail_limit"},
        {"node_path": "Missing", "section": "surfaces", "reason": "detail_limit"},
        {"node_path": ".", "section": "bones", "reason": "detail_limit"},
    ],
)
def test_rejects_unrecognized_or_unlocatable_omissions(omission):
    payload = _report()
    payload["truncated"] = True
    payload["omissions"] = [omission]
    with pytest.raises(ValueError, match="omission"):
        validate_model_report(_model(payload))


def test_rejects_truncation_flag_without_coverage_records():
    payload = _report()
    payload["truncated"] = True
    with pytest.raises(ValueError, match="truncated"):
        validate_model_report(_model(payload))


def test_accepts_node_truncation_at_the_selected_subtree():
    payload = _report()
    payload["nodes"] = payload["nodes"][:1]
    payload["summary"] = {
        "node_count": 1,
        "mesh_instance_count": 0,
        "unique_mesh_count": 0,
    }
    payload["bounds"] = None
    payload["truncated"] = True
    payload["omissions"] = [
        {"node_path": ".", "section": "nodes", "reason": "node_limit"}
    ]
    validate_model_report(_model(payload))


def test_rejects_resolution_fields_that_contradict_their_status():
    payload = _report()
    payload["nodes"].append(
        {
            "path": "AnimationPlayer",
            "type": "AnimationPlayer",
            "local_transform": None,
            "resource_transform": None,
            "mesh": None,
            "skeleton": None,
            "animation_player": {
                "root_path": "..",
                "resolved_root_path": ".",
                "unresolved_reason": "animation root not found",
                "animation_count": 0,
                "animations": [],
            },
        }
    )
    payload["summary"]["node_count"] = 3
    with pytest.raises(ValueError, match="animation root resolution"):
        validate_model_report(_model(payload))
