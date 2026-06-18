"""`gda <group> <command> --params-json` structured params input (issue #199, ADR-0015).

A caller may supply a command's params as one JSON object via `--params-json`
(or `-` to read the object from stdin) instead of the individual CLI arguments.
The object is deserialized into the command's input model and dispatched through
the same runner seam as the argv path, producing identical params (normalization
included). These are fast tests; one e2e drives a real command via --params-json.
"""

import json
from pathlib import Path

from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult
from tests.support import SCENE_CREATE_RESULT, inject_runner, sentinel


def test_scene_create_params_json_dispatches_like_argv(monkeypatch):
    # The --params-json path builds the model from a JSON object and dispatches
    # through the SAME runner seam as the argv path, applying the same
    # normalization (~ expanded, root_name derived from the filename). Proves the
    # central mechanism end-to-end and the argv/JSON parity in one shot.
    fake = inject_runner(
        monkeypatch,
        RunResult(stdout=sentinel(SCENE_CREATE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "scene",
            "create",
            "--params-json",
            '{"path": "~/proj/main.tscn", "root_type": "Node2D"}',
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert fake.calls == [
        (
            "scene-create",
            {
                "path": str(Path("~/proj/main.tscn").expanduser()),
                "root_type": "Node2D",
                "root_name": "main",
            },
        )
    ]


def test_params_json_conflicting_with_individual_args_is_a_structured_usage_error(
    monkeypatch,
):
    # Mutual exclusivity (ADR-0015): --params-json alongside an individual arg is a
    # registered usage_error (ADR-0002), emitted as a structured GdaError envelope
    # on a non-zero exit — never an ad-hoc message.
    inject_runner(
        monkeypatch,
        RunResult(stdout=sentinel(SCENE_CREATE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "scene",
            "create",
            "/tmp/proj/main.tscn",
            "--params-json",
            '{"path": "/tmp/proj/main.tscn", "root_type": "Node2D"}',
        ],
    )

    assert result.exit_code != 0
    err = json.loads(result.stdout)["error"]
    assert err["code"] == "usage_error"
    assert err["category"] == "operation"


def test_invalid_json_params_is_a_structured_error(monkeypatch):
    # Malformed JSON → a registered invalid_params GdaError, not a traceback.
    inject_runner(
        monkeypatch,
        RunResult(stdout=sentinel(SCENE_CREATE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(app, ["scene", "create", "--params-json", "{not json"])

    assert result.exit_code != 0
    err = json.loads(result.stdout)["error"]
    assert err["code"] == "invalid_params"
    assert err["category"] == "operation"


def test_schema_invalid_params_object_is_a_structured_error(monkeypatch):
    # Valid JSON but missing a required field (root_type) → invalid_params.
    inject_runner(
        monkeypatch,
        RunResult(stdout=sentinel(SCENE_CREATE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app, ["scene", "create", "--params-json", '{"path": "/tmp/proj/main.tscn"}']
    )

    assert result.exit_code != 0
    err = json.loads(result.stdout)["error"]
    assert err["code"] == "invalid_params"


def test_schema_takes_precedence_over_params_json(monkeypatch):
    # A bare --schema wins: it emits the contract and ignores --params-json,
    # dispatching nothing (ADR-0015 / ADR-0004).
    def boom(*args, **kwargs):
        raise AssertionError("--schema must not dispatch the operation")

    monkeypatch.setattr("gda.cli._make_runner", boom)

    result = CliRunner().invoke(
        app,
        [
            "scene",
            "create",
            "--params-json",
            '{"path": "/tmp/proj/main.tscn", "root_type": "Node2D"}',
            "--schema",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert set(json.loads(result.stdout)) >= {"input", "output", "error"}


def test_json_output_composes_with_params_json(monkeypatch):
    # --json (a result projection) composes with --params-json (an input source):
    # the success result is emitted as a single JSON object.
    inject_runner(
        monkeypatch,
        RunResult(stdout=sentinel(SCENE_CREATE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "scene",
            "create",
            "--params-json",
            '{"path": "/tmp/proj/main.tscn", "root_type": "Node2D"}',
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    data = json.loads(result.stdout)
    assert data["path"] == "/tmp/proj/main.tscn"
    assert data["root_type"] == "Node2D"


def test_params_json_dash_reads_the_object_from_stdin(monkeypatch):
    # `--params-json -` reads the JSON object from stdin, so large payloads
    # (script/shader content) avoid argv length limits (ADR-0015).
    fake = inject_runner(
        monkeypatch,
        RunResult(stdout=sentinel(SCENE_CREATE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        ["scene", "create", "--params-json", "-"],
        input='{"path": "/tmp/proj/level.tscn", "root_type": "Node2D"}',
    )

    assert result.exit_code == 0, result.stdout
    assert fake.calls == [
        (
            "scene-create",
            {
                "path": "/tmp/proj/level.tscn",
                "root_type": "Node2D",
                "root_name": "level",
            },
        )
    ]
