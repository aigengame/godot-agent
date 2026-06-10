"""S3: gda scene failure modes map to structured JSON errors + stable exit codes.

Issue #18's acceptance: scene-command failures reuse the shared classification
(no parallel decision tree) and are distinguishable — environment vs operation
vs parse by exit code, finer modes (missing path, not-a-scene, bad root type)
by stable ``GdaError.code`` values. The finer codes ride the ``gda-error:``
stderr marker the operations payload emits on a structured failure.
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult
from tests.support import inject_runner


def test_scene_get_missing_file_maps_to_stable_path_not_found_code(monkeypatch):
    # The operation found no file at the target path and reported a structured
    # failure: exit 4 (operation category), but a finer stable code than the
    # generic operation_failed so an agent can react to the mode specifically.
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="Godot Engine v4.6.3.stable.official\n",
            stderr="gda-error:path_not_found: scene file does not exist: /x/missing.tscn\n",
            exit_code=1,
        ),
    )

    result = CliRunner().invoke(app, ["scene", "get", "/x/missing.tscn"])

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "path_not_found"
    assert "/x/missing.tscn" in err["message"]
    # The raw stderr still rides along as diagnostics (ADR-0002).
    assert "path_not_found" in err["diagnostics"]


def test_scene_get_unloadable_file_maps_to_stable_not_a_scene_code(monkeypatch):
    # The file exists but Godot cannot load it as a PackedScene — distinct
    # stable code, same operation category and exit code.
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="",
            stderr="gda-error:not_a_scene: failed to load as a scene: /x/notes.txt\n",
            exit_code=1,
        ),
    )

    result = CliRunner().invoke(app, ["scene", "get", "/x/notes.txt"])

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "not_a_scene"


def test_scene_create_unknown_root_type_maps_to_stable_invalid_root_type_code(
    monkeypatch,
):
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="",
            stderr="gda-error:invalid_root_type: not an instantiable Node class: Foo\n",
            exit_code=1,
        ),
    )

    result = CliRunner().invoke(
        app, ["scene", "create", "/x/main.tscn", "--root-type", "Foo"]
    )

    assert result.exit_code == 4
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == "invalid_root_type"
    assert "Foo" in err["message"]


def test_scene_get_broken_sentinel_maps_to_parse_error(monkeypatch):
    # Exit 0 but no result sentinel: the structured-output contract (ADR-0002)
    # was violated — the shared parse classification applies to scene commands
    # exactly as it does to info.
    inject_runner(
        monkeypatch,
        RunResult(stdout="no sentinel here\n", stderr="", exit_code=0),
    )

    result = CliRunner().invoke(app, ["scene", "get", "/x/main.tscn"])

    assert result.exit_code == 5
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "parse"
    assert err["code"] == "contract_violation"


def test_scene_create_missing_binary_maps_to_environment_error(monkeypatch):
    # The runner's synthetic exit 127 flows through the same shared environment
    # branch for scene commands as for info.
    inject_runner(
        monkeypatch,
        RunResult(
            stdout="", stderr="gda: Godot binary not found: /x/Godot\n", exit_code=127
        ),
    )

    result = CliRunner().invoke(
        app, ["scene", "create", "/x/main.tscn", "--root-type", "Node2D"]
    )

    assert result.exit_code == 127
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "environment"
    assert err["code"] == "binary_not_found"
