"""The gda command results are carried by typed models (ADR-0004)."""

import json

import jsonschema

from gda.models import (
    EngineVersion,
    GdaError,
    GdaErrorEnvelope,
    NodeAddResult,
    NodeListResult,
    SceneCreateResult,
    SceneDeleteResult,
    SceneGetResult,
    SceneListResult,
)


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


def test_error_envelope_schema_is_well_formed_json_schema():
    # The uniform `error` half of the --schema contract (#43) is produced from
    # this one shared model. check_schema raises if it is not itself valid JSON
    # Schema, so every command's emitted `error` is well-formed by construction.
    schema = GdaErrorEnvelope.model_json_schema()

    jsonschema.Draft202012Validator.check_schema(schema)


def test_error_envelope_round_trips_a_failure():
    # A real failure envelope validates against its own model — the wire shape
    # an agent branches on (the top-level `error` key discriminates failure).
    payload = {
        "error": {
            "category": "operation",
            "code": "path_not_found",
            "message": "scene file does not exist: res://missing.tscn",
            "diagnostics": "",
        }
    }

    envelope = GdaErrorEnvelope.model_validate(payload)

    assert isinstance(envelope.error, GdaError)
    assert envelope.error.code == "path_not_found"
    assert json.loads(envelope.model_dump_json()) == payload


def test_scene_create_result_round_trips():
    payload = {
        "path": "/p/main.tscn",
        "root_name": "main",
        "root_type": "Node2D",
        "created_dirs": ["/p"],
    }

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
                    "children": [{"name": "Hitbox", "type": "Area2D", "children": []}],
                }
            ],
        },
    }

    scene = SceneGetResult.model_validate(payload)

    assert scene.root.children[0].children[0].name == "Hitbox"
    assert json.loads(scene.model_dump_json()) == payload


def test_scene_list_result_round_trips_enumerated_scenes():
    # The scene-list operation enumerates the project's .tscn files (issue #54):
    # each entry carries its res:// path plus the root's name/type read cheaply
    # from the scene's stored state. A scene that fails to load still appears,
    # with null root info, so the listing names every .tscn it found.
    payload = {
        "scenes": [
            {"path": "res://main.tscn", "root_name": "main", "root_type": "Node2D"},
            {"path": "res://ui/menu.tscn", "root_name": "Menu", "root_type": "Control"},
            {"path": "res://broken.tscn", "root_name": None, "root_type": None},
        ]
    }

    listed = SceneListResult.model_validate(payload)

    assert listed.scenes[0].path == "res://main.tscn"
    assert listed.scenes[1].root_type == "Control"
    assert listed.scenes[2].root_name is None
    assert json.loads(listed.model_dump_json()) == payload


def test_scene_list_result_round_trips_an_empty_project():
    # A project with no scenes is a valid, empty listing — not an error.
    payload = {"scenes": []}

    listed = SceneListResult.model_validate(payload)

    assert listed.scenes == []
    assert json.loads(listed.model_dump_json()) == payload


def test_scene_delete_result_round_trips():
    # The scene-delete operation reports what it removed (issue #54): the path,
    # and the deleted scene's root name/type so the result names the content,
    # not just the file.
    payload = {
        "path": "res://main.tscn",
        "root_name": "main",
        "root_type": "Node2D",
    }

    deleted = SceneDeleteResult.model_validate(payload)

    assert deleted.path == "res://main.tscn"
    assert deleted.root_name == "main"
    assert json.loads(deleted.model_dump_json()) == payload


def test_node_add_result_round_trips():
    # The node-add operation reports the created node's address (issue #53):
    # its node path relative to the scene root, alongside name and type.
    # script_class is null for a built-in type, the class_name for a script one.
    payload = {
        "scene_path": "/p/main.tscn",
        "path": "Player/Hero",
        "name": "Hero",
        "type": "Sprite2D",
        "script_class": None,
    }

    added = NodeAddResult.model_validate(payload)

    assert added.path == "Player/Hero"
    assert json.loads(added.model_dump_json()) == payload


def test_node_add_result_carries_the_class_name_of_a_script_addition():
    payload = {
        "scene_path": "/p/main.tscn",
        "path": "Hero",
        "name": "Hero",
        "type": "Node2D",
        "script_class": "Hero",
    }

    added = NodeAddResult.model_validate(payload)

    assert added.type == "Node2D"
    assert added.script_class == "Hero"
    assert json.loads(added.model_dump_json()) == payload


def test_node_list_result_round_trips_a_nested_tree_with_paths():
    # The recursive ListedNode shape: like SceneNode but every node carries its
    # node path ('.' for the root), so a validated nested tree must dump back
    # to the identical payload (S2).
    payload = {
        "scene_path": "/p/main.tscn",
        "root": {
            "name": "main",
            "type": "Node2D",
            "path": ".",
            "children": [
                {
                    "name": "Hero",
                    "type": "Sprite2D",
                    "path": "Hero",
                    "children": [
                        {
                            "name": "Hitbox",
                            "type": "Area2D",
                            "path": "Hero/Hitbox",
                            "children": [],
                        }
                    ],
                }
            ],
        },
    }

    listed = NodeListResult.model_validate(payload)

    assert listed.root.path == "."
    assert listed.root.children[0].children[0].path == "Hero/Hitbox"
    assert json.loads(listed.model_dump_json()) == payload
