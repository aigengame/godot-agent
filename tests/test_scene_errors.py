"""S3: gda scene failure modes map to structured JSON errors + stable exit codes.

Issue #18's acceptance: scene-command failures reuse the shared classification
(no parallel decision tree) and are distinguishable — environment vs operation
vs parse by exit code, finer modes (missing path, not-a-scene, bad root type)
by stable ``GdaError.code`` values. The finer codes ride the ADR-0002 error
envelope the operations payload emits on a structured failure.
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.runner import LaunchFailure, RunResult
from tests.support import (
    assert_operation_error,
    inject_runner,
    invoke_cli,
    invoke_operation_error,
)


def test_scene_get_missing_file_maps_to_stable_path_not_found_code(monkeypatch):
    # The operation found no file at the target path and reported a structured
    # failure: exit 4 (operation category), but a finer stable code than the
    # generic operation_failed so an agent can react to the mode specifically.
    result = invoke_operation_error(
        monkeypatch,
        ["scene", "get", "/x/missing.tscn", "--json"],
        "path_not_found",
        "scene file does not exist: /x/missing.tscn",
        "scene-get",
    )

    # The raw stderr still rides along as diagnostics (ADR-0002).
    assert_operation_error(
        result,
        "path_not_found",
        "/x/missing.tscn",
        diagnostics="gda: running operation: scene-get\n",
    )


def test_scene_get_unloadable_file_maps_to_stable_not_a_scene_code(monkeypatch):
    # The file exists but Godot cannot load it as a PackedScene — distinct
    # stable code, same operation category and exit code.
    result = invoke_operation_error(
        monkeypatch,
        ["scene", "get", "/x/notes.txt", "--json"],
        "not_a_scene",
        "failed to load as a scene: /x/notes.txt",
        "scene-get",
    )

    assert_operation_error(result, "not_a_scene")


def test_scene_get_exports_missing_file_maps_to_stable_path_not_found_code(monkeypatch):
    # scene get-exports reuses the shared load-failure ladder (issue #58): a
    # target that does not exist is the file-level path_not_found, exit 4, so an
    # agent can tell "no such scene" apart from other get-exports failures.
    result = invoke_operation_error(
        monkeypatch,
        ["scene", "get-exports", "/x/missing.tscn", "--json"],
        "path_not_found",
        "scene file does not exist: /x/missing.tscn",
        "scene-get-exports",
    )

    assert_operation_error(result, "path_not_found", "/x/missing.tscn")


def test_scene_get_exports_unloadable_file_maps_to_stable_not_a_scene_code(monkeypatch):
    # The file exists but Godot cannot load it as a PackedScene — get-exports
    # reuses the same stable not_a_scene code scene get / delete report, so a
    # stray non-scene file is refused rather than mis-handled (issue #58).
    result = invoke_operation_error(
        monkeypatch,
        ["scene", "get-exports", "/x/notes.txt", "--json"],
        "not_a_scene",
        "failed to load as a scene: /x/notes.txt",
        "scene-get-exports",
    )

    assert_operation_error(result, "not_a_scene")


def test_scene_create_unknown_root_type_maps_to_stable_invalid_root_type_code(
    monkeypatch,
):
    result = invoke_operation_error(
        monkeypatch,
        ["scene", "create", "/x/main.tscn", "--root-type", "Foo", "--json"],
        "invalid_root_type",
        "not an instantiable Node class: Foo",
        "scene-create",
    )

    assert_operation_error(result, "invalid_root_type", "Foo")


def test_scene_create_save_failure_maps_to_stable_save_failed_code(monkeypatch):
    # The op built the scene but could not write it (unwritable destination,
    # read-only filesystem): the structured error envelope maps to the stable
    # save_failed code so an agent can tell "fix the destination" apart from
    # "fix the request" (issue #35).
    result = invoke_operation_error(
        monkeypatch,
        ["scene", "create", "/x/demo/main.tscn", "--root-type", "Node2D", "--json"],
        "save_failed",
        "failed to save scene to /x/demo/main.tscn: Can't open",
        "scene-create",
    )

    assert_operation_error(result, "save_failed", "/x/demo/main.tscn")


def test_scene_get_broken_sentinel_maps_to_parse_error(monkeypatch):
    # Exit 0 but no result sentinel: the structured-output contract (ADR-0002)
    # was violated — the shared parse classification applies to scene commands
    # exactly as it does to info.
    result, _ = invoke_cli(
        monkeypatch, ["scene", "get", "/x/main.tscn", "--json"], stdout="no sentinel\n"
    )

    assert result.exit_code == 5
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "parse"
    assert err["code"] == "contract_violation"


def test_scene_delete_missing_file_maps_to_stable_path_not_found_code(monkeypatch):
    # scene delete reuses the shared load-failure ladder (issue #54): a target
    # that does not exist is the file-level path_not_found, exit 4, so an agent
    # can tell "no such scene" apart from other delete failures.
    result = invoke_operation_error(
        monkeypatch,
        ["scene", "delete", "/x/missing.tscn", "--json"],
        "path_not_found",
        "scene file does not exist: /x/missing.tscn",
        "scene-delete",
    )

    assert_operation_error(result, "path_not_found", "/x/missing.tscn")


def test_scene_delete_non_scene_file_maps_to_stable_not_a_scene_code(monkeypatch):
    # delete refuses a target that is not loadable as a scene (issue #54): the
    # safety boundary is that delete only removes things that load as a
    # PackedScene, so a stray file is not_a_scene rather than silently deleted.
    result = invoke_operation_error(
        monkeypatch,
        ["scene", "delete", "/x/notes.txt", "--json"],
        "not_a_scene",
        "failed to load as a scene: /x/notes.txt",
        "scene-delete",
    )

    assert_operation_error(result, "not_a_scene")


def test_scene_delete_unlink_failure_maps_to_stable_delete_failed_code(monkeypatch):
    # The op loaded the scene but the underlying unlink/remove failed (a
    # read-only filesystem, a permission boundary): this is a delete IO failure,
    # not a save/pack failure, so it maps to the stable delete_failed code rather
    # than reusing save_failed (whose contract is "a scene could not be packed or
    # saved"). An agent can then tell "deletion was blocked" apart from "writing
    # the scene failed".
    result = invoke_operation_error(
        monkeypatch,
        ["scene", "delete", "/x/main.tscn", "--json"],
        "delete_failed",
        "failed to delete scene /x/main.tscn: Permission denied",
        "scene-delete",
    )

    assert_operation_error(result, "delete_failed", "/x/main.tscn")


def test_scene_list_without_project_maps_to_stable_project_not_found_code(monkeypatch):
    # scene list enumerates res:// in a project, so it cannot run projectless
    # (issue #54): with no resolvable project, the operation reports the new
    # project_not_found code — a finer mode than the generic operation_failed so
    # an agent knows to pass --project rather than retry.
    result = invoke_operation_error(
        monkeypatch,
        ["scene", "list", "--json"],
        "project_not_found",
        "scene list requires a Godot project; none was resolved — pass --project",
        "scene-list",
    )

    assert_operation_error(result, "project_not_found", "--project")


def test_scene_create_missing_binary_maps_to_environment_error(monkeypatch):
    # The runner's synthetic exit 127 flows through the same shared environment
    # branch for scene commands as for info.
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="",
            stderr="gda: Godot binary not found: /x/Godot\n",
            exit_code=127,
            launch_failure=LaunchFailure.NOT_FOUND,
        ),
    )

    result = CliRunner().invoke(
        app, ["scene", "create", "/x/main.tscn", "--root-type", "Node2D", "--json"]
    )

    assert result.exit_code == 127
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "environment"
    assert err["code"] == "binary_not_found"
