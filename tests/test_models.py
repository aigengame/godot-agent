"""The gda command results are carried by typed models (ADR-0004)."""

import json

from gda.models import EngineVersion, SceneCreateResult, SceneGetResult


def test_validates_from_engine_get_version_info_dict():
    # The shape Godot's Engine.get_version_info() emits through the sentinel.
    payload = {
        "major": 4,
        "minor": 6,
        "patch": 3,
        "hex": 0x040603,
        "status": "stable",
        "build": "official",
        "hash": "7d41c59c457bd5a245092b4e7eb2d833e3b3f8c3",
        "string": "4.6.3-stable (official)",
        "timestamp": 0,
    }

    version = EngineVersion.model_validate(payload)

    assert version.major == 4
    assert version.minor == 6
    assert version.patch == 3
    assert version.status == "stable"
    assert version.string == "4.6.3-stable (official)"
    assert version.timestamp == 0


def test_round_trips_to_json_object():
    payload = {
        "major": 4,
        "minor": 6,
        "patch": 3,
        "hex": 0x040603,
        "status": "stable",
        "build": "official",
        "hash": "7d41c59c457bd5a245092b4e7eb2d833e3b3f8c3",
        "string": "4.6.3-stable (official)",
        "timestamp": 0,
    }

    version = EngineVersion.model_validate(payload)
    dumped = json.loads(version.model_dump_json())

    assert dumped["major"] == 4
    assert dumped["minor"] == 6
    assert dumped["string"] == "4.6.3-stable (official)"


def test_scene_create_result_round_trips():
    payload = {"path": "/p/main.tscn", "root_name": "main", "root_type": "Node2D"}

    created = SceneCreateResult.model_validate(payload)

    assert json.loads(created.model_dump_json()) == payload


def test_scene_get_result_round_trips_a_nested_tree():
    # The recursive SceneNode shape, as the scene-get operation emits it: a
    # validated nested tree must dump back to the identical payload (S2).
    payload = {
        "path": "/p/main.tscn",
        "root": {
            "name": "main",
            "type": "Node2D",
            "children": [
                {
                    "name": "Hero",
                    "type": "Sprite2D",
                    "children": [
                        {"name": "Hitbox", "type": "Area2D", "children": []}
                    ],
                }
            ],
        },
    }

    scene = SceneGetResult.model_validate(payload)

    assert scene.root.children[0].children[0].name == "Hitbox"
    assert json.loads(scene.model_dump_json()) == payload
