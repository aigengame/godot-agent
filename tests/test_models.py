"""The gda command results are carried by typed models (ADR-0004)."""

import json

import jsonschema

from gda.models import (
    EngineVersion,
    GdaError,
    GdaErrorEnvelope,
    NodeAddResult,
    NodeGetResult,
    NodeListResult,
    NodeSetResult,
    SceneCreateResult,
    SceneDeleteResult,
    SceneGetResult,
    SceneListResult,
    ScriptCreateResult,
    ScriptDeleteResult,
    ScriptGetResult,
    ScriptAttachResult,
    ScriptListResult,
    ScriptSetResult,
    ScriptValidateResult,
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


def test_node_get_result_round_trips_typed_properties():
    # node get reports a node's storage properties as typed JSON (issue #55):
    # each property carries its name, its declared Godot type, and its value in
    # the JSON projection the operation emits. The value is left as arbitrary
    # JSON so the model carries every Godot type uniformly (a number, a string,
    # a list for a Vector2, …) without a per-type field.
    payload = {
        "scene_path": "/p/main.tscn",
        "path": "Hero",
        "name": "Hero",
        "type": "Sprite2D",
        "properties": [
            {"name": "position", "type": "Vector2", "value": [10.0, 20.0]},
            {"name": "visible", "type": "bool", "value": True},
            {"name": "z_index", "type": "int", "value": 3},
        ],
    }

    got = NodeGetResult.model_validate(payload)

    assert got.path == "Hero"
    assert got.properties[0].name == "position"
    assert got.properties[0].type == "Vector2"
    assert got.properties[0].value == [10.0, 20.0]
    assert json.loads(got.model_dump_json()) == payload


def test_script_create_result_round_trips_with_metadata():
    # script create echoes the saved path plus the class_name/extends the
    # written source declares (issue #110), so an agent verifies the effect
    # without a second call.
    payload = {
        "path": "res://hero.gd",
        "class_name": "Hero",
        "extends": "Node2D",
        "created_dirs": ["res://scripts"],
    }

    created = ScriptCreateResult.model_validate(payload)

    assert created.path == "res://hero.gd"
    assert created.class_name == "Hero"
    assert created.extends == "Node2D"
    assert json.loads(created.model_dump_json()) == payload


def test_script_create_result_round_trips_null_metadata():
    # A template script with no class_name carries null class_name/extends; the
    # null metadata round-trips faithfully.
    payload = {
        "path": "res://util.gd",
        "class_name": None,
        "extends": None,
        "created_dirs": [],
    }

    created = ScriptCreateResult.model_validate(payload)

    assert created.class_name is None
    assert created.extends is None
    assert json.loads(created.model_dump_json()) == payload


def test_script_get_result_round_trips_source_and_metadata():
    # script get carries the source verbatim alongside the parsed metadata, so a
    # create round-trips through a get (issue #110): the source dumps back
    # byte-identical, including its trailing newline.
    payload = {
        "path": "res://hero.gd",
        "source": "class_name Hero\nextends Node2D\n\nfunc _ready() -> void:\n\tpass\n",
        "class_name": "Hero",
        "extends": "Node2D",
    }

    got = ScriptGetResult.model_validate(payload)

    assert got.source.endswith("pass\n")
    assert got.class_name == "Hero"
    assert got.extends == "Node2D"
    assert json.loads(got.model_dump_json()) == payload


def test_script_list_result_round_trips_enumerated_scripts():
    # The script-list operation enumerates the project's .gd files (issue #117):
    # each entry carries its res:// path plus the class_name/extends parsed
    # cheaply from the script's raw source (no compilation, issue #30). A script
    # that declares neither carries null metadata, so the listing names every
    # .gd it found.
    payload = {
        "scripts": [
            {"path": "res://hero.gd", "class_name": "Hero", "extends": "Node2D"},
            {"path": "res://util.gd", "class_name": None, "extends": "RefCounted"},
            {"path": "res://empty.gd", "class_name": None, "extends": None},
        ]
    }

    listed = ScriptListResult.model_validate(payload)

    assert listed.scripts[0].path == "res://hero.gd"
    assert listed.scripts[0].class_name == "Hero"
    assert listed.scripts[1].extends == "RefCounted"
    assert listed.scripts[2].class_name is None
    assert json.loads(listed.model_dump_json()) == payload


def test_script_list_result_round_trips_an_empty_project():
    # A project with no scripts is a valid, empty listing — not an error.
    payload = {"scripts": []}

    listed = ScriptListResult.model_validate(payload)

    assert listed.scripts == []
    assert json.loads(listed.model_dump_json()) == payload


def test_script_delete_result_round_trips():
    # The script-delete operation reports what it removed (issue #117): the path,
    # and the deleted script's class_name/extends so the result names the content,
    # not just the file.
    payload = {
        "path": "res://hero.gd",
        "class_name": "Hero",
        "extends": "Node2D",
    }

    deleted = ScriptDeleteResult.model_validate(payload)

    assert deleted.path == "res://hero.gd"
    assert deleted.class_name == "Hero"
    assert deleted.extends == "Node2D"
    assert json.loads(deleted.model_dump_json()) == payload


def test_script_set_result_round_trips_metadata():
    # script set re-parses the written source's class_name/extends (issue #118),
    # so an edit round-trips through script get: the metadata dumps back faithfully.
    payload = {
        "path": "res://hero.gd",
        "class_name": "Hero",
        "extends": "Node2D",
    }

    edited = ScriptSetResult.model_validate(payload)

    assert edited.path == "res://hero.gd"
    assert edited.class_name == "Hero"
    assert edited.extends == "Node2D"
    assert json.loads(edited.model_dump_json()) == payload


def test_script_attach_result_round_trips_with_class_name():
    # script attach (issue #118) echoes the scene, node, attached script, and the
    # script's declared class_name — the result an agent asserts to confirm the
    # binding took effect. attach is overwrite-and-report (issue #132): here the
    # node already carried a script, so replaced_script names the displaced path.
    payload = {
        "scene_path": "res://main.tscn",
        "node": "Hero",
        "script": "res://hero.gd",
        "class_name": "Hero",
        "replaced_script": "res://old.gd",
    }

    attached = ScriptAttachResult.model_validate(payload)

    assert attached.node == "Hero"
    assert attached.script == "res://hero.gd"
    assert attached.class_name == "Hero"
    assert attached.replaced_script == "res://old.gd"
    assert json.loads(attached.model_dump_json()) == payload


def test_script_attach_result_round_trips_null_class_name():
    # A script with no class_name attaches fine; the result carries null. The node
    # had no prior script, so replaced_script is null (issue #132).
    payload = {
        "scene_path": "res://main.tscn",
        "node": ".",
        "script": "res://util.gd",
        "class_name": None,
        "replaced_script": None,
    }

    attached = ScriptAttachResult.model_validate(payload)

    assert attached.class_name is None
    assert attached.replaced_script is None
    assert json.loads(attached.model_dump_json()) == payload


def test_script_validate_result_round_trips_a_valid_script():
    # A valid script (issue #118): valid=true, no error_string, no diagnostics —
    # the successful-op shape.
    payload = {
        "path": "res://ok.gd",
        "valid": True,
        "error_string": None,
        "diagnostics": [],
    }

    validated = ScriptValidateResult.model_validate(payload)

    assert validated.valid is True
    assert validated.error_string is None
    assert validated.diagnostics == []
    assert json.loads(validated.model_dump_json()) == payload


def test_script_validate_result_round_trips_an_invalid_script_with_diagnostics():
    # An invalid script carries valid=false, the engine's one-line summary, and a
    # best-effort diagnostic (line + message; column always null on the standard
    # build).
    payload = {
        "path": "res://broken.gd",
        "valid": False,
        "error_string": "Parse error.",
        "diagnostics": [
            {"line": 3, "column": None, "message": "Parse Error: bad token."}
        ],
    }

    validated = ScriptValidateResult.model_validate(payload)

    assert validated.valid is False
    assert validated.diagnostics[0].line == 3
    assert validated.diagnostics[0].column is None
    assert validated.diagnostics[0].message == "Parse Error: bad token."
    assert json.loads(validated.model_dump_json()) == payload


def test_node_set_result_round_trips_the_coerced_property():
    # node set echoes the one property it changed (issue #55): its name, the
    # property's declared type the CLI value was coerced to, and the coerced
    # value as the node now holds it — the result an agent asserts without a
    # second `get`.
    payload = {
        "scene_path": "/p/main.tscn",
        "path": "Hero",
        "property": "position",
        "type": "Vector2",
        "value": [3.0, 4.0],
    }

    was_set = NodeSetResult.model_validate(payload)

    assert was_set.property == "position"
    assert was_set.type == "Vector2"
    assert was_set.value == [3.0, 4.0]
    assert json.loads(was_set.model_dump_json()) == payload
