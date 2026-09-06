"""The gda command results are carried by typed models (ADR-0004)."""

import json

import jsonschema
import pytest
from pydantic import ValidationError

from gda.commands.node import (
    NodeAddResult,
    NodeConnectSignalResult,
    NodeDisconnectSignalResult,
    NodeDuplicateResult,
    NodeGetResult,
    NodeListResult,
    NodeMoveResult,
    NodeRemoveResult,
    NodeSetResult,
)
from gda.commands.scene import (
    SceneCreateResult,
    SceneDeleteResult,
    SceneExport,
    SceneGetExportsResult,
    SceneGetResult,
    SceneListResult,
)
from gda.commands.resource import (
    ResourceCreateResult,
    ResourceGetResult,
    ResourceSetResult,
)
from gda.commands.script import (
    ScriptCreateResult,
    ScriptDeleteResult,
    ScriptGetResult,
    ScriptAttachResult,
    ScriptListResult,
    ScriptSetResult,
    ScriptValidateResult,
)
from gda.commands.export import (
    ExportGetResult,
    ExportListResult,
    ExportRunMode,
    ExportRunResult,
)
from gda.commands.project import (
    InputActionJoyAxisEvent,
    InputActionJoyButtonEvent,
    InputActionKeyEvent,
    ListedProjectSetting,
    ProjectAddAutoloadResult,
    ProjectAddInputActionResult,
    ProjectGetResult,
    ProjectInfoResult,
    ProjectRemoveAutoloadResult,
    ProjectRemoveInputActionResult,
    ProjectSetResult,
)
from gda.commands.game import GameSetResult
from gda.models import (
    EngineVersion,
    ErrorCategory,
    FailureEvidence,
    GdaError,
    GdaErrorEnvelope,
    InlineValueProjection,
    NodeProperty,
    ReferenceProjection,
    TextureProjection,
)
from gda.script_errors import ScriptError, ScriptErrorKind


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
    # `exclude_none` is the public emit convention (ADR-0004 amendment, #667): the
    # envelope's optional context keys are OMITTED, never emitted as `null`, so a
    # failure that sets none is byte-identical to the pre-amendment contract.
    assert json.loads(envelope.model_dump_json(exclude_none=True)) == payload
    # And the ONLY thing that convention drops is the optional context. Pinning the
    # difference — rather than just asserting the filtered form — keeps this a real
    # guard: a future optional key that a consumer would see as `null` fails here.
    raw = json.loads(envelope.model_dump_json())
    assert set(raw["error"]) - set(payload["error"]) == {"probe", "hint", "evidence"}
    assert raw["error"]["probe"] is None
    # `hint` (#670) joined `probe` on the same optional-context axis and under the
    # same convention: a failure that offers no correction must not grow a `null`.
    assert raw["error"]["hint"] is None
    # `evidence` (#687) is the third key on that axis, and the first whose VALUE is
    # a nested object — so the convention has to hold one level deeper too, which
    # the test below measures on a failure that sets some of its fields.
    assert raw["error"]["evidence"] is None


def test_the_evidence_key_omits_its_own_unset_fields_too():
    # The property that lets ONE fixed evidence shape serve every operation (#687,
    # the ADR-0004 amendment): a timeout populates the clocks, a strict script
    # failure populates the child's status, and neither pays for the other's
    # fields — because `exclude_none` filters RECURSIVELY, so an unset field inside
    # `evidence` is absent rather than `null`. Without that, the universal shape
    # would put five keys on every envelope that carries any evidence at all, and
    # the "one shape, per-operation variability inside it" argument would fail.
    error = GdaError(
        category=ErrorCategory.OPERATION,
        code="script_failed",
        message="script run --strict: res://t.gd exited with status 3",
        diagnostics="",
        evidence=FailureEvidence(exit_status=3),
    )

    emitted = json.loads(
        GdaErrorEnvelope(error=error).model_dump_json(exclude_none=True)
    )["error"]

    assert emitted["evidence"] == {"exit_status": 3}
    assert set(emitted) == {"category", "code", "message", "diagnostics", "evidence"}


def test_a_nested_script_error_reads_the_same_on_both_halves_of_the_contract():
    # The #687 review's P1: `exclude_none` recurses, so the SAME record used to lose
    # its null `path`/`line` inside `evidence` while keeping them on `script run`'s
    # success `diagnostics` — two key sets for the one published `ScriptError`
    # schema, whose field descriptions say "or null". An engine-side load failure
    # carries no line, so this is the COMMON record, not an edge case.
    #
    # The omit-when-None rule is about the envelope's optional keys and evidence's
    # own fields; it stops at a nested model that is also published on a success
    # result. Measured as an equality between the two halves rather than as a key
    # list, so the guard states the property instead of a snapshot.
    record = ScriptError(
        kind=ScriptErrorKind.SCRIPT_MISSING,
        message="Attempt to open script 'res://absent.gd' resulted in error 'File not found'.",
        path="res://absent.gd",
    )
    error = GdaError(
        category=ErrorCategory.OPERATION,
        code="script_failed",
        message="script run --strict: res://t.gd exited with status 1",
        diagnostics="",
        evidence=FailureEvidence(exit_status=1, script_errors=[record]),
    )

    on_the_failure_half = json.loads(
        GdaErrorEnvelope(error=error).model_dump_json(exclude_none=True)
    )["error"]["evidence"]["script_errors"][0]
    on_the_success_half = json.loads(record.model_dump_json())

    assert on_the_failure_half == on_the_success_half
    assert on_the_failure_half["line"] is None
    # Evidence's OWN fields still follow the rule the amendment rests on: the four
    # clocks this failure did not compute are absent, not null.
    assert set(
        json.loads(GdaErrorEnvelope(error=error).model_dump_json(exclude_none=True))[
            "error"
        ]["evidence"]
    ) == {"exit_status", "script_errors"}


def test_an_empty_script_errors_list_is_published_as_a_finding_not_as_absence():
    # `script_errors` has THREE states, and the middle one is the reason the field
    # is not collapsed to None when empty (#687 review): absent = this failure's
    # channel does not parse stderr, so read `diagnostics`; `[]` = it parsed and
    # recognized nothing, which is itself a finding (a run that died silently);
    # non-empty = what it recognized. `[]` is not None, so `exclude_none` keeps it —
    # this pins that, because collapsing it would erase the distinction the field
    # description now publishes.
    parsed_none = GdaError(
        category=ErrorCategory.OPERATION,
        code="script_failed",
        message="script run --strict: res://t.gd exited with status 3",
        diagnostics="",
        evidence=FailureEvidence(exit_status=3, script_errors=[]),
    )
    does_not_parse = GdaError(
        category=ErrorCategory.ENVIRONMENT,
        code="launch_timeout",
        message="Godot launched but did not return before the timeout",
        diagnostics="",
        evidence=FailureEvidence(elapsed_seconds=5.0),
    )

    def evidence_of(error: GdaError) -> dict[str, object]:
        return json.loads(
            GdaErrorEnvelope(error=error).model_dump_json(exclude_none=True)
        )["error"]["evidence"]

    assert evidence_of(parsed_none) == {"exit_status": 3, "script_errors": []}
    assert "script_errors" not in evidence_of(does_not_parse)


def test_every_evidence_field_is_optional_in_the_published_schema():
    # The shape is published once, for every command (ADR-0004), so a REQUIRED
    # field here would be a promise no operation can keep: a `launch_timeout` has
    # no exit status and a compile failure has no clock. A consumer must be able to
    # read any subset.
    schema = FailureEvidence.model_json_schema()

    assert schema.get("required", []) == []
    assert set(schema["properties"]) == {
        "exit_status",
        "elapsed_seconds",
        "timeout_seconds",
        "termination_phase",
        "script_errors",
        # The three coordinates of a `target_outside_project` refusal
        # (#697/#763): where the target is, which project gda used, and which
        # one owns it.
        "target_location",
        "project_root",
        "owning_project",
    }


def test_the_emitted_failure_envelope_omits_probe_entirely():
    # The ABI guard for the ADR-0004 amendment, through the REAL emit path rather
    # than a hand-rolled dump (#667 review): dropping `exclude_none` from
    # emit_failure would add `"probe": null` to EVERY failure gda emits, which is
    # exactly the break the amendment's additive argument rests on not happening.
    # `--godot ""` fails binary resolution before anything is spawned, so this is a
    # fast, engine-free, ungated check that runs in every CI tier.
    from typer.testing import CliRunner

    from gda.cli import app

    result = CliRunner().invoke(app, ["info", "--godot", "", "--json"])

    assert result.exit_code == 127
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "binary_not_found"
    assert "probe" not in error
    assert set(error) == {"category", "code", "message", "diagnostics"}


def test_error_envelope_round_trips_a_failure_carrying_probe_context():
    # The other half of the amendment: a host-probe ENVIRONMENT failure DOES carry
    # the deciding call as data, and that shape round-trips through the same model.
    payload = {
        "error": {
            "category": "environment",
            "code": "live_windowed_permission_denied",
            "message": "denied the macOS window-server lookup",
            "diagnostics": "",
            "probe": {
                "name": "bootstrap_look_up(com.apple.windowserver.active)",
                "platform": "darwin",
            },
        }
    }

    envelope = GdaErrorEnvelope.model_validate(payload)

    assert envelope.error.probe is not None
    assert envelope.error.probe.platform == "darwin"
    assert json.loads(envelope.model_dump_json(exclude_none=True)) == payload


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


def test_scene_get_result_round_trips_an_instanced_node_marker():
    payload = {
        "path": "/p/main.tscn",
        "root": {
            "name": "main",
            "type": "Node2D",
            "children": [
                {
                    "name": "Hud",
                    "type": "CanvasLayer",
                    "instance_path": "res://scenes/hud.tscn",
                    "instance_status": "resolved",
                    "children": [],
                }
            ],
        },
    }

    scene = SceneGetResult.model_validate(payload)

    hud = scene.root.children[0]
    assert hud.instance_path == "res://scenes/hud.tscn"
    assert hud.instance_status == "resolved"
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


def test_scene_list_result_round_trips_an_inherited_root_marker():
    payload = {
        "scenes": [
            {
                "path": "res://inherited_hud.tscn",
                "root_name": "InheritedHud",
                "root_type": "CanvasLayer",
                "root_instance_path": "res://scenes/hud.tscn",
                "root_instance_status": "resolved",
            }
        ]
    }

    listed = SceneListResult.model_validate(payload)

    assert listed.scenes[0].root_instance_path == "res://scenes/hud.tscn"
    assert listed.scenes[0].root_instance_status == "resolved"
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
        "instance": None,
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
        "instance": None,
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
    # A valid script (issue #118): the aggregate is true and its one entry carries
    # valid=true, no error_string, no diagnostics — the successful-op shape. A
    # single path is a batch of one (#663), so this is the same shape a six-script
    # batch emits, with one entry instead of six.
    payload = {
        "valid": True,
        "scripts": [
            {
                "path": "res://ok.gd",
                "valid": True,
                "error_string": None,
                "diagnostics": [],
            }
        ],
    }

    validated = ScriptValidateResult.model_validate(payload)

    assert validated.valid is True
    assert validated.scripts[0].error_string is None
    assert validated.scripts[0].diagnostics == []
    # `project_root` is NOT in the sentinel payload: the engine is told the
    # project through --path and never reports it back, so the CLI stamps the
    # ADR-0006-resolved root onto the result after classification (#658). The
    # model therefore defaults it to null and the emitted object always carries
    # the key.
    assert json.loads(validated.model_dump_json()) == {
        **payload,
        "project_root": None,
    }


def test_script_validate_result_round_trips_a_batch_with_per_file_diagnostics():
    # A batch (#663): the aggregate is false as soon as ONE entry is invalid, and
    # each entry keeps its own engine summary plus its own best-effort diagnostic
    # (line + message; column always null on the standard build).
    payload = {
        "valid": False,
        "scripts": [
            {
                "path": "res://ok.gd",
                "valid": True,
                "error_string": None,
                "diagnostics": [],
            },
            {
                "path": "res://broken.gd",
                "valid": False,
                "error_string": "Parse error.",
                "diagnostics": [
                    {"line": 3, "column": None, "message": "Parse Error: bad token."}
                ],
            },
        ],
    }

    validated = ScriptValidateResult.model_validate(payload)

    assert validated.valid is False
    assert [entry.valid for entry in validated.scripts] == [True, False]
    broken = validated.scripts[1]
    assert broken.diagnostics[0].line == 3
    assert broken.diagnostics[0].column is None
    assert broken.diagnostics[0].message == "Parse Error: bad token."
    # Sentinel-absent, CLI-stamped — see the valid-script round-trip above.
    assert json.loads(validated.model_dump_json()) == {
        **payload,
        "project_root": None,
    }


def test_export_list_result_round_trips_enumerated_presets():
    # The export-list operation enumerates the project's export presets (issue
    # #114) read from export_presets.cfg: each entry carries its 0-based index,
    # display name, target platform, and runnable flag. A non-runnable preset
    # carries runnable=false, so the listing names every preset the file defines.
    payload = {
        "presets": [
            {
                "index": 0,
                "name": "Linux/X11",
                "platform": "Linux/X11",
                "runnable": True,
            },
            {"index": 1, "name": "Web", "platform": "Web", "runnable": False},
        ]
    }

    listed = ExportListResult.model_validate(payload)

    assert listed.presets[0].index == 0
    assert listed.presets[0].name == "Linux/X11"
    assert listed.presets[0].runnable is True
    assert listed.presets[1].platform == "Web"
    assert listed.presets[1].runnable is False
    assert json.loads(listed.model_dump_json()) == payload


def test_export_list_result_round_trips_a_project_with_no_presets():
    # A project whose export_presets.cfg defines no presets is a valid, empty
    # listing — not an error (distinct from a project with no cfg at all, which
    # is the export_presets_not_found failure).
    payload = {"presets": []}

    listed = ExportListResult.model_validate(payload)

    assert listed.presets == []
    assert json.loads(listed.model_dump_json()) == payload


def test_export_get_result_round_trips_preset_details_and_template_status():
    # export get reports one preset's details plus export-template readiness
    # (issue #114): the preset's index/name/platform/runnable and export_path,
    # then whether the running engine version's templates are installed and which
    # version directory was checked — the readiness an agent asserts before an
    # export run.
    payload = {
        "index": 1,
        "name": "Web",
        "platform": "Web",
        "runnable": False,
        "export_path": "build/index.html",
        "templates_installed": True,
        "templates_version": "4.6.3.stable",
    }

    got = ExportGetResult.model_validate(payload)

    assert got.index == 1
    assert got.name == "Web"
    assert got.export_path == "build/index.html"
    assert got.templates_installed is True
    assert got.templates_version == "4.6.3.stable"
    assert json.loads(got.model_dump_json()) == payload


def test_export_get_result_round_trips_missing_templates():
    # Templates not installed: templates_installed=false carries the version
    # directory the agent should install, and export_path may be empty (unset).
    payload = {
        "index": 0,
        "name": "Linux/X11",
        "platform": "Linux/X11",
        "runnable": True,
        "export_path": "",
        "templates_installed": False,
        "templates_version": "4.6.3.stable",
    }

    got = ExportGetResult.model_validate(payload)

    assert got.templates_installed is False
    assert got.export_path == ""
    assert json.loads(got.model_dump_json()) == payload


def test_export_run_result_round_trips_each_mode():
    # The result's `mode` reflects the selected export flavor (issue #170): each
    # of release/debug/pack round-trips to its native-flag string, so a result
    # serialized for any --mode reports the mode that ran.
    for mode in (ExportRunMode.RELEASE, ExportRunMode.DEBUG, ExportRunMode.PACK):
        payload = {
            "preset": "Linux/X11",
            "platform": "Linux/X11",
            "mode": mode.value,
            "output_path": "/tmp/project/build/game.x86_64",
            "created_dirs": [],
            "warnings": [],
        }

        ran = ExportRunResult.model_validate(payload)

        assert ran.mode is mode
        assert ran.output_path == "/tmp/project/build/game.x86_64"
        assert ran.created_dirs == []
        assert json.loads(ran.model_dump_json()) == payload


def test_export_run_result_reports_overridden_output_path():
    # With --output (issue #170) the result's output_path is the EFFECTIVE
    # destination — the override, not the preset's configured export_path — so an
    # agent reads back where the artifact actually landed.
    payload = {
        "preset": "Linux/X11",
        "platform": "Linux/X11",
        "mode": "pack",
        "output_path": "/tmp/dist/game.pck",
        "created_dirs": ["/tmp/dist"],
        "warnings": ["No export template found at the expected icon path."],
    }

    ran = ExportRunResult.model_validate(payload)

    assert ran.mode is ExportRunMode.PACK
    assert ran.output_path == "/tmp/dist/game.pck"
    assert ran.created_dirs == ["/tmp/dist"]
    assert ran.warnings == ["No export template found at the expected icon path."]
    assert json.loads(ran.model_dump_json()) == payload


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


def test_node_remove_result_round_trips():
    # The node-remove operation reports what it removed (issue #56): the removed
    # node's address (its node path relative to the scene root) alongside its
    # name and type, captured off the tree before the re-save — so the result
    # names the content removed, not just the path.
    payload = {
        "scene_path": "/p/main.tscn",
        "path": "Player/Hero",
        "name": "Hero",
        "type": "Sprite2D",
    }

    removed = NodeRemoveResult.model_validate(payload)

    assert removed.path == "Player/Hero"
    assert removed.name == "Hero"
    assert removed.type == "Sprite2D"
    assert json.loads(removed.model_dump_json()) == payload


def test_node_duplicate_result_round_trips():
    # The node-duplicate operation reports the new copy's address (issue #56):
    # its node path relative to the scene root, plus the source node it copied,
    # so an agent can address the duplicate without re-listing. The copy lands
    # under the source's own parent with a fresh, non-colliding name.
    payload = {
        "scene_path": "/p/main.tscn",
        "source_path": "Player/Hero",
        "path": "Player/Hero2",
        "name": "Hero2",
        "type": "Sprite2D",
    }

    duplicated = NodeDuplicateResult.model_validate(payload)

    assert duplicated.source_path == "Player/Hero"
    assert duplicated.path == "Player/Hero2"
    assert duplicated.name == "Hero2"
    assert duplicated.type == "Sprite2D"
    assert json.loads(duplicated.model_dump_json()) == payload


def test_node_move_result_round_trips():
    # The node-move operation reports the reparented node's new address (issue
    # #56): the source path it moved, the new parent it landed under, and the
    # node's new node path/name/type relative to the scene root.
    payload = {
        "scene_path": "/p/main.tscn",
        "source_path": "Hero",
        "new_parent": "Enemies",
        "path": "Enemies/Hero",
        "name": "Hero",
        "type": "Sprite2D",
    }

    moved = NodeMoveResult.model_validate(payload)

    assert moved.source_path == "Hero"
    assert moved.new_parent == "Enemies"
    assert moved.path == "Enemies/Hero"
    assert moved.name == "Hero"
    assert moved.type == "Sprite2D"
    assert json.loads(moved.model_dump_json()) == payload


def test_node_connect_signal_result_round_trips_the_four_part_connection():
    # node connect-signal echoes the connection it recorded (issue #57): the
    # source node and its signal, the target node and its method — the four
    # parts of a .tscn [connection], so an agent asserts the wiring without
    # re-reading the scene file.
    payload = {
        "scene_path": "/p/main.tscn",
        "from": "Emitter",
        "signal": "timeout",
        "to": "Receiver",
        "method": "on_timeout",
    }

    connected = NodeConnectSignalResult.model_validate(payload)

    assert connected.scene_path == "/p/main.tscn"
    assert (connected.from_node, connected.signal) == ("Emitter", "timeout")
    assert (connected.to, connected.method) == ("Receiver", "on_timeout")
    # `from` is a Python keyword, so the field is aliased; the JSON projection
    # still serializes the wire key as `from`.
    assert json.loads(connected.model_dump_json(by_alias=True)) == payload


def test_node_disconnect_signal_result_round_trips_the_removed_connection():
    # node disconnect-signal echoes the connection it removed (issue #57), the
    # same four-part shape as connect — the result an agent asserts to confirm
    # the unwiring took effect.
    payload = {
        "scene_path": "/p/main.tscn",
        "from": "Emitter",
        "signal": "timeout",
        "to": "Receiver",
        "method": "on_timeout",
    }

    disconnected = NodeDisconnectSignalResult.model_validate(payload)

    assert disconnected.scene_path == "/p/main.tscn"
    assert (disconnected.from_node, disconnected.signal) == ("Emitter", "timeout")
    assert (disconnected.to, disconnected.method) == ("Receiver", "on_timeout")
    assert json.loads(disconnected.model_dump_json(by_alias=True)) == payload


def test_resource_create_result_round_trips_with_type_and_dirs():
    # resource create echoes the saved path and the resource type it wrote
    # (issue #112), plus any parent directories created before saving — so an
    # agent verifies the effect (path + type) without a second call.
    payload = {
        "path": "res://palette.tres",
        "type": "Gradient",
        "created_dirs": ["res://art"],
    }

    created = ResourceCreateResult.model_validate(payload)

    assert created.path == "res://palette.tres"
    assert created.type == "Gradient"
    assert created.created_dirs == ["res://art"]
    assert json.loads(created.model_dump_json()) == payload


def test_resource_get_result_round_trips_typed_properties():
    # resource get reports a resource's storage properties as typed JSON (issue
    # #112), reusing the same NodeProperty projection as node get: each property
    # carries its name, declared Godot type, and value as arbitrary JSON, so the
    # model carries every Godot type uniformly without a per-type field. A
    # resource get round-trips a create (create → get reports the resource).
    payload = {
        "path": "res://palette.tres",
        "type": "Gradient",
        "properties": [
            {"name": "resource_name", "type": "String", "value": "Sunset"},
            {"name": "interpolation_mode", "type": "int", "value": 0},
            {"name": "offsets", "type": "PackedFloat32Array", "value": "[0, 1]"},
        ],
    }

    got = ResourceGetResult.model_validate(payload)

    assert got.path == "res://palette.tres"
    assert got.type == "Gradient"
    assert got.properties[0].name == "resource_name"
    assert got.properties[0].type == "String"
    assert got.properties[0].value == "Sunset"
    assert got.properties[1].value == 0
    assert json.loads(got.model_dump_json()) == payload


def test_scene_get_exports_result_round_trips_per_node_exports():
    # scene get-exports reports, per node (by node path), the @export properties
    # the node's attached script declares (issue #58): each export carries its
    # name, declared Godot type, hint/hint_string, and current value in the same
    # JSON projection node get uses. A node carries the script that declares the
    # exports, so an agent knows where they came from.
    payload = {
        "path": "/p/main.tscn",
        "nodes": [
            {
                "path": ".",
                "name": "main",
                "type": "Node2D",
                "script": "res://main.gd",
                "exports": [
                    {
                        "name": "speed",
                        "type": "float",
                        "hint": 0,
                        "hint_string": "",
                        "value": 3.5,
                    },
                    {
                        "name": "title",
                        "type": "String",
                        "hint": 0,
                        "hint_string": "",
                        "value": "Hello",
                    },
                ],
            }
        ],
    }

    got = SceneGetExportsResult.model_validate(payload)

    assert got.path == "/p/main.tscn"
    node = got.nodes[0]
    assert (node.path, node.name, node.type) == (".", "main", "Node2D")
    assert node.script == "res://main.gd"
    assert node.exports[0].name == "speed"
    assert node.exports[0].type == "float"
    assert node.exports[0].value == 3.5
    assert json.loads(got.model_dump_json()) == payload


def test_project_info_result_round_trips_metadata_and_engine_version():
    # project info reports the project's core metadata (issue #111): name and
    # main scene from ProjectSettings, the configured viewport size, and the
    # nested engine_version the project runs on (the same shape gda info reports).
    payload = {
        "name": "My Game",
        "main_scene": "res://main.tscn",
        "viewport_width": 1920,
        "viewport_height": 1080,
        "engine_version": {
            "major": 4,
            "minor": 6,
            "patch": 3,
            "hex": 0x040603,
            "status": "stable",
            "build": "official",
            "hash": "7d41c59c457bd5a245092b4e7eb2d833e3b3f8c3",
            "string": "4.6.3-stable (official)",
            "timestamp": 0,
        },
    }

    info = ProjectInfoResult.model_validate(payload)

    assert info.name == "My Game"
    assert info.main_scene == "res://main.tscn"
    assert (info.viewport_width, info.viewport_height) == (1920, 1080)
    assert info.engine_version.string == "4.6.3-stable (official)"
    assert json.loads(info.model_dump_json()) == payload


def test_project_info_result_round_trips_a_brand_new_project():
    # A brand-new project that never set a main scene reports the empty string for
    # main_scene and the engine's built-in viewport defaults — a complete, valid
    # result rather than an error.
    payload = {
        "name": "",
        "main_scene": "",
        "viewport_width": 1152,
        "viewport_height": 648,
        "engine_version": {
            "major": 4,
            "minor": 6,
            "patch": 3,
            "hex": 0x040603,
            "status": "stable",
            "build": "official",
            "hash": "7d41c59c457bd5a245092b4e7eb2d833e3b3f8c3",
            "string": "4.6.3-stable (official)",
            "timestamp": 0,
        },
    }

    info = ProjectInfoResult.model_validate(payload)

    assert info.main_scene == ""
    assert (info.viewport_width, info.viewport_height) == (1152, 648)
    assert json.loads(info.model_dump_json()) == payload


def test_project_get_result_round_trips_a_typed_setting():
    # project get echoes one setting (issue #111): its full section/key name, its
    # declared Godot type name, and its value in the same JSON projection node get
    # uses for a property — a packed type projects to a list (Vector2 → [x, y]).
    payload = {
        "setting": "display/window/size/viewport_width",
        "type": "int",
        "value": 1920,
    }

    got = ProjectGetResult.model_validate(payload)

    assert got.setting == "display/window/size/viewport_width"
    assert got.type == "int"
    assert got.value == 1920
    assert json.loads(got.model_dump_json()) == payload


# The residual-mutation report every project WRITE result carries (#843), empty:
# what a save that changed nothing besides the request reports. Spelled once so the
# five round-trip payloads below stay a statement about their OWN echo.
NO_RESIDUAL_MUTATION = {
    "added_settings": [],
    "rewritten_settings": [],
    "restored_settings": [],
    "sections_reordered": False,
}


def test_project_set_result_round_trips_the_coerced_setting():
    # project set echoes the one setting it wrote (issue #111): the setting name,
    # the declared type the CLI value was coerced to, and the coerced value as
    # ProjectSettings now holds it — the same projection project get reports, so a
    # set round-trips through a get.
    payload = {
        "setting": "application/config/name",
        "type": "String",
        "value": "Renamed Game",
    }

    was_set = ProjectSetResult.model_validate(payload)

    assert was_set.setting == "application/config/name"
    assert was_set.type == "String"
    assert was_set.value == "Renamed Game"
    assert json.loads(was_set.model_dump_json()) == payload | NO_RESIDUAL_MUTATION


def test_project_add_autoload_result_round_trips_the_registered_autoload():
    # project add-autoload echoes the autoload it registered (issue #119): the
    # global name and the path AS PERSISTED — the enabled-singleton form with the
    # leading * prefix, the same value a project get of autoload/<name> reads back.
    payload = {
        "name": "Global",
        "path": "*res://global.gd",
    }

    added = ProjectAddAutoloadResult.model_validate(payload)

    assert added.name == "Global"
    assert added.path == "*res://global.gd"
    assert json.loads(added.model_dump_json()) == payload | NO_RESIDUAL_MUTATION


def test_project_remove_autoload_result_round_trips_the_unregistered_name():
    # project remove-autoload echoes the name it unregistered (issue #119), so an
    # agent can confirm which singleton was removed.
    payload = {"name": "Global"}

    removed = ProjectRemoveAutoloadResult.model_validate(payload)

    assert removed.name == "Global"
    assert json.loads(removed.model_dump_json()) == payload | NO_RESIDUAL_MUTATION


def test_project_add_input_action_result_round_trips_the_registered_action():
    # project add-input-action echoes the action it registered (issue #380): the
    # name, the persisted deadzone, and each key event with the raw token, the
    # resolved keycode, and whether it was bound as physical_keycode.
    payload = {
        "name": "jump",
        "deadzone": 0.2,
        "events": [
            {"kind": "key", "key": "J", "keycode": 74, "physical": False},
            {"kind": "key", "key": "4194320", "keycode": 4194320, "physical": True},
        ],
    }

    added = ProjectAddInputActionResult.model_validate(payload)

    assert added.name == "jump"
    assert added.deadzone == 0.2
    keys = [event for event in added.events if isinstance(event, InputActionKeyEvent)]
    assert [event.keycode for event in keys] == [74, 4194320]
    assert keys[0].kind == "key"
    assert keys[1].physical is True
    assert json.loads(added.model_dump_json()) == payload | NO_RESIDUAL_MUTATION


def test_project_add_input_action_result_round_trips_joypad_events():
    # `kind` was put on the key event so joypad kinds could extend it (#380);
    # #842 is that extension, as a DISCRIMINATED union: each kind validates into
    # its own model with its own fields, and a wrong-kind field is a refusal
    # rather than a silently ignored extra.
    payload = {
        "name": "jump",
        "deadzone": 0.5,
        "events": [
            {"kind": "joy_button", "button": "A", "button_index": 0, "device": -1},
            {
                "kind": "joy_axis",
                "axis": "LeftX:-",
                "axis_index": 0,
                "axis_value": -1.0,
                "device": 1,
            },
        ],
    }

    added = ProjectAddInputActionResult.model_validate(payload)

    button, axis = added.events
    assert isinstance(button, InputActionJoyButtonEvent)
    assert (button.button, button.button_index, button.device) == ("A", 0, -1)
    assert isinstance(axis, InputActionJoyAxisEvent)
    assert (axis.axis, axis.axis_index, axis.axis_value, axis.device) == (
        "LeftX:-",
        0,
        -1.0,
        1,
    )
    assert json.loads(added.model_dump_json()) == payload | NO_RESIDUAL_MUTATION


def test_project_add_input_action_result_rejects_an_unknown_event_kind():
    # The discriminator is closed: an event kind the contract does not publish is
    # a validation refusal, not an untyped passthrough.
    with pytest.raises(ValidationError):
        ProjectAddInputActionResult.model_validate(
            {
                "name": "jump",
                "deadzone": 0.5,
                "events": [{"kind": "mouse_button", "button_index": 1}],
            }
        )


def test_project_remove_input_action_result_round_trips_the_unregistered_name():
    # project remove-input-action echoes the name it unregistered (issue #380),
    # so an agent can confirm which action was removed.
    payload = {"name": "jump"}

    removed = ProjectRemoveInputActionResult.model_validate(payload)

    assert removed.name == "jump"
    assert json.loads(removed.model_dump_json()) == payload | NO_RESIDUAL_MUTATION


def test_a_project_write_result_round_trips_its_residual_mutation():
    # The report is part of the write contract (#843), not a CLI-only decoration:
    # it validates and re-emits like every other field of the result.
    payload = {
        "name": "jump",
        "added_settings": ["application/config/features"],
        "rewritten_settings": [],
        "restored_settings": ["debug/file_logging/enable_file_logging"],
        "sections_reordered": True,
    }

    removed = ProjectRemoveInputActionResult.model_validate(payload)

    assert removed.restored_settings == ["debug/file_logging/enable_file_logging"]
    assert removed.sections_reordered is True
    assert json.loads(removed.model_dump_json()) == payload


def test_shader_create_result_round_trips_path_and_metadata():
    # shader create echoes what it wrote (issue #115): the saved path, the
    # shader_type parsed from the written source, and the parent dirs created —
    # so an agent asserts the effect without a second call.
    from gda.commands.shader import ShaderCreateResult

    payload = {
        "path": "/p/wave.gdshader",
        "shader_type": "canvas_item",
        "created_dirs": ["/p/shaders"],
    }

    created = ShaderCreateResult.model_validate(payload)

    assert created.path == "/p/wave.gdshader"
    assert created.shader_type == "canvas_item"
    assert created.created_dirs == ["/p/shaders"]
    assert json.loads(created.model_dump_json()) == payload


def test_shader_get_result_carries_source_verbatim():
    # shader get is the verifier (issue #115): it echoes the source byte-for-byte
    # plus the shader_type the source declares, so a create round-trips.
    from gda.commands.shader import ShaderGetResult

    payload = {
        "path": "/p/wave.gdshader",
        "source": "shader_type canvas_item;\n",
        "shader_type": "canvas_item",
    }

    got = ShaderGetResult.model_validate(payload)

    assert got.source == "shader_type canvas_item;\n"
    assert got.shader_type == "canvas_item"
    assert json.loads(got.model_dump_json()) == payload


def test_shader_set_params_reuse_the_script_set_edit_mode_enum():
    # shader set reuses the script set edit-mode interface (issue #115): the mode
    # discriminator is the SAME ScriptSetMode enum, not a parallel one.
    from gda.commands.script import ScriptSetMode
    from gda.commands.shader import ShaderSetParams

    params = ShaderSetParams(
        path="/p/wave.gdshader",
        mode=ScriptSetMode.SEARCH_REPLACE,
        search="0.5",
        replace="1.0",
    )

    assert params.mode is ScriptSetMode.SEARCH_REPLACE
    assert params.search == "0.5"
    assert params.replace == "1.0"


def test_shader_set_result_round_trips_path_and_metadata():
    from gda.commands.shader import ShaderSetResult

    payload = {"path": "/p/wave.gdshader", "shader_type": "spatial"}

    edited = ShaderSetResult.model_validate(payload)

    assert edited.path == "/p/wave.gdshader"
    assert edited.shader_type == "spatial"
    assert json.loads(edited.model_dump_json()) == payload


def test_theme_create_result_round_trips_path_type_and_dirs():
    # theme create echoes the saved .tres path, the resource type written
    # (Theme), and the parent dirs created (issue #115).
    from gda.commands.theme import ThemeCreateResult

    payload = {
        "path": "/p/ui.tres",
        "type": "Theme",
        "created_dirs": [],
    }

    created = ThemeCreateResult.model_validate(payload)

    assert created.path == "/p/ui.tres"
    assert created.type == "Theme"
    assert created.created_dirs == []
    assert json.loads(created.model_dump_json()) == payload


def test_diag_errors_result_round_trips_a_multi_frame_callstack():
    # A runtime GDScript error carries its ordered call stack (#283): each frame
    # is {function, file, line}, most-recent-first. Frame [0] equals the top
    # {function,file,line} for THIS class, because GDScript raised the error
    # itself — see the push_error test below for the class where it does not
    # (#722). The whole result round-trips byte-identical.
    from gda.commands.diag import DiagErrorsResult

    payload = {
        "errors": [
            {
                "level": "script_error",
                "message": "Invalid call. Nonexistent function 'do_thing' in base 'Nil'.",
                "function": "b",
                "file": "res://main.gd",
                "line": 9,
                "callstack": [
                    {"function": "b", "file": "res://main.gd", "line": 9},
                    {"function": "a", "file": "res://main.gd", "line": 6},
                    {"function": "_ready", "file": "res://main.gd", "line": 3},
                ],
            }
        ]
    }

    result = DiagErrorsResult.model_validate(payload)

    error = result.errors[0]
    assert [f.function for f in error.callstack] == ["b", "a", "_ready"]
    assert error.callstack[0].file == "res://main.gd"
    assert error.callstack[0].line == 9
    assert json.loads(result.model_dump_json()) == payload


def test_diag_error_keeps_a_push_error_frame_zero_apart_from_the_top_fields():
    # The model contract `--schema` publishes (#722): frame [0] is the innermost
    # GDScript frame, NOT necessarily the top {function,file,line}. A push_error is
    # raised by the engine's own C++ helper, so the top fields name that helper
    # while frame [0] names the .gd line that called it. Values reproduced from a
    # real Godot 4.6.3 headless capture (see MIXED_RAISER_LOG in
    # tests/live/test_diag_log_parser.py). The model must carry both without collapsing
    # or cross-filling them.
    from gda.commands.diag import DiagError

    payload = {
        "level": "error",
        "message": "probe: invariant violated",
        "function": "push_error",
        "file": "core/variant/variant_utility.cpp",
        "line": 1024,
        "callstack": [
            {"function": "_inner", "file": "res://main.gd", "line": 10},
            {"function": "_ready", "file": "res://main.gd", "line": 5},
        ],
    }

    error = DiagError.model_validate(payload)

    assert error.file == "core/variant/variant_utility.cpp"
    assert error.callstack[0].file == "res://main.gd"
    assert error.callstack[0].line == 10
    assert (
        error.callstack[0].function,
        error.callstack[0].file,
        error.callstack[0].line,
    ) != (
        error.function,
        error.file,
        error.line,
    )
    assert json.loads(error.model_dump_json()) == payload


def test_diag_error_callstack_defaults_to_empty_for_a_bare_error():
    # An error raised outside any GDScript call stack carries no backtrace:
    # callstack defaults to [] and the existing single-frame fields stay None — no
    # callstack key required on input. (A push_error is NOT such an error: it does
    # carry a backtrace on the build gda drives, #722.)
    from gda.commands.diag import DiagError

    error = DiagError.model_validate(
        {
            "level": "error",
            "message": "boom",
            "function": None,
            "file": None,
            "line": None,
        }
    )

    assert error.callstack == []
    assert error.function is None


# --- value projection models (ADR-0035, #381) --------------------------------


def test_reference_projection_round_trips_and_schema_is_valid():
    # The read-side mirror of ADR-0033: a Resource-valued read renders as
    # {type, resource_path} — never inlined. The named model surfaces the shape
    # through the --schema / model chain (ADR-0004) rather than leaving it
    # prose-only.
    schema = ReferenceProjection.model_json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)

    payload = {"type": "RectangleShape2D", "resource_path": "res://box.tres"}
    ref = ReferenceProjection.model_validate(payload)

    assert ref.type == "RectangleShape2D"
    assert ref.resource_path == "res://box.tres"
    dumped = json.loads(ref.model_dump_json())
    assert dumped == payload
    jsonschema.validate(dumped, schema)


def test_inline_value_projection_preserves_extra_storage_properties():
    # The whitelisted path-less value Object shape (ADR-0035): `type` is the
    # declared discriminator; the class's own storage properties ride as extra
    # fields (extra="allow") and survive a model_dump_json round trip intact.
    schema = InlineValueProjection.model_json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)

    payload = {
        "type": "InputEventKey",
        "keycode": 74,
        "physical_keycode": 0,
        "pressed": False,
        "device": -1,
    }
    inline = InlineValueProjection.model_validate(payload)

    assert inline.type == "InputEventKey"
    dumped = json.loads(inline.model_dump_json())
    assert dumped == payload
    jsonschema.validate(dumped, schema)
    # The projector excludes the Resource base bookkeeping, so the branch
    # between the two Object projection kinds stays unambiguous: an inline
    # projection never carries a resource_path.
    assert "resource_path" not in dumped


def test_node_property_round_trips_an_inline_value_projection_dict():
    # A NodeProperty whose value is a compound projection stays plain JSON:
    # `value` is Any (the recorded, bounded ADR-0035 exception to ADR-0004), so
    # pydantic must NOT materialize the dict into a model instance — the human
    # renderer json.dumps's it as-is.
    payload = {
        "name": "fire",
        "type": "Dictionary",
        "value": {
            "deadzone": 0.5,
            "events": [{"type": "InputEventKey", "keycode": 74, "pressed": False}],
        },
    }

    prop = NodeProperty.model_validate(payload)

    assert isinstance(prop.value, dict)
    assert prop.value["deadzone"] == 0.5
    assert prop.value["events"][0]["type"] == "InputEventKey"
    assert prop.value["events"][0]["keycode"] == 74
    assert json.loads(prop.model_dump_json()) == payload


def test_node_property_round_trips_a_reference_projection_value():
    # An Object-typed property read back after an ADR-0033 set: the value is
    # the reference projection dict, distinguished from an inline value
    # projection by the presence of resource_path.
    payload = {
        "name": "shape",
        "type": "Object",
        "value": {"type": "RectangleShape2D", "resource_path": "res://box.tres"},
    }

    prop = NodeProperty.model_validate(payload)

    assert isinstance(prop.value, dict)
    assert prop.value["type"] == "RectangleShape2D"
    assert prop.value["resource_path"] == "res://box.tres"
    assert json.loads(prop.model_dump_json()) == payload


def test_game_set_result_round_trips_observed_value_and_verification_signal():
    payload = {
        "path": "/root/Main/Player",
        "property": "spawn",
        "type": "bool",
        "value": False,
        "verified": False,
    }

    result = GameSetResult.model_validate(payload)

    assert result.value is False
    assert result.verified is False
    assert json.loads(result.model_dump_json()) == payload
    schema = GameSetResult.model_json_schema()
    value_description = schema["properties"]["value"]["description"]
    assert "observed read-back value" in value_description
    assert "coerced value" not in value_description
    assert schema["properties"]["verified"]["type"] == "boolean"


def test_every_projected_value_field_exposes_the_named_projection_defs():
    # ADR-0035 carries the projection ABI into the --schema / model chain
    # (ADR-0004): `value` stays Any (the recorded, bounded exception), so the
    # stable Object-projection shapes ride the field's $defs instead — named
    # and consumable in every emitted command schema, not prose-only. Every
    # model whose `value` flows through the shared projection must expose them.
    projected_value_models = [
        NodeProperty,  # node get / resource get / game get per-property value
        SceneExport,  # scene get-exports per-export value
        ProjectGetResult,
        ListedProjectSetting,  # project list per-entry value
        NodeSetResult,
        ResourceSetResult,
        ProjectSetResult,
        GameSetResult,
    ]
    for model in projected_value_models:
        schema = model.model_json_schema()
        jsonschema.Draft202012Validator.check_schema(schema)
        defs = schema["properties"]["value"]["$defs"]
        assert defs == {
            "ReferenceProjection": ReferenceProjection.model_json_schema(),
            "TextureProjection": TextureProjection.model_json_schema(),
            "InlineValueProjection": InlineValueProjection.model_json_schema(),
        }, model.__name__
