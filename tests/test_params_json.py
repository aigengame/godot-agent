"""`gda <group> <command> --params-json` structured params input (issue #199, ADR-0015).

A caller may supply a command's params as one JSON object via `--params-json`
(or `-` to read the object from stdin) instead of the individual CLI arguments.
The object is deserialized into the command's input model and dispatched through
the same runner seam as the argv path, producing identical params (normalization
included). These are fast tests; one e2e drives a real command via --params-json.
"""

import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from gda.cli import app
from gda.models import ScriptSetMode
from gda.runner import RunResult
from tests.support import (
    NODE_ADD_RESULT,
    NODE_GET_RESULT,
    RESOURCE_CREATE_RESULT,
    SCENE_CREATE_RESULT,
    SCENE_GET_RESULT,
    SCRIPT_CREATE_RESULT,
    SCRIPT_SET_RESULT,
    SHADER_CREATE_RESULT,
    inject_runner,
    sentinel,
)


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

    monkeypatch.setattr("gda.dispatch._make_runner", boom)

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


# --- the model is the single source of input semantics (PR #201 review) --------
# argv derives/validates in the CLI body; for parity these must live in the model
# so --params-json gets the SAME derivation/validation, not a wider or divergent API.


def test_wrong_typed_path_is_a_structured_error_not_a_traceback(monkeypatch):
    # A non-string NormalizedPath value must surface as structured invalid_params,
    # not a TypeError traceback: NormalizedPath uses AfterValidator, so the value is
    # validated as a str FIRST (ADR-0015). Regression for the BeforeValidator crash.
    inject_runner(
        monkeypatch,
        RunResult(stdout=sentinel(SCENE_CREATE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        ["scene", "create", "--params-json", '{"path": 123, "root_type": "Node2D"}'],
    )

    assert result.exit_code != 0
    err = json.loads(result.stdout)["error"]
    assert err["code"] == "invalid_params"
    assert err["category"] == "operation"


def test_node_add_params_json_derives_default_name_like_argv(monkeypatch):
    # Parity: omitting name derives it from the type model-side, exactly like the
    # argv path (which used to do this in the CLI body).
    fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(NODE_ADD_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        [
            "node",
            "add",
            "--params-json",
            '{"path": "/tmp/proj/main.tscn", "type": "Sprite2D"}',
        ],
    )

    assert result.exit_code == 0, result.stdout
    op, params = fake.calls[0]
    assert op == "node-add"
    assert params["name"] == "Sprite2D"


def test_script_create_params_json_rejects_content_and_extends(monkeypatch):
    # The content/extends mutual exclusivity is enforced model-side, so
    # --params-json cannot bypass it (it is rejected, not silently resolved).
    inject_runner(
        monkeypatch,
        RunResult(stdout=sentinel(SCRIPT_CREATE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "script",
            "create",
            "--params-json",
            '{"path": "/tmp/proj/hero.gd", "content": "extends Node\\n", "extends_type": "Node2D"}',
        ],
    )

    assert result.exit_code != 0
    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"


def test_shader_create_params_json_rejects_content_and_shader_type(monkeypatch):
    inject_runner(
        monkeypatch,
        RunResult(stdout=sentinel(SHADER_CREATE_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "shader",
            "create",
            "--params-json",
            '{"path": "/tmp/proj/wave.gdshader", "content": "shader_type spatial;", "shader_type": "spatial"}',
        ],
    )

    assert result.exit_code != 0
    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"


def test_script_set_params_json_rejects_inconsistent_edit_fields(monkeypatch):
    # The edit-mode rule is enforced model-side: a half-specified mode (search
    # without replace) is invalid_params via --params-json, not a silent dispatch.
    inject_runner(
        monkeypatch,
        RunResult(stdout=sentinel(SCRIPT_SET_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "script",
            "set",
            "--params-json",
            '{"path": "/tmp/proj/hero.gd", "search": "a"}',
        ],
    )

    assert result.exit_code != 0
    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"


def test_perf_monitor_params_json_rejects_both_selectors(monkeypatch):
    # Exactly one of property/signal is enforced model-side (PerfMonitorParams,
    # ADR-0015), so --params-json cannot pass both (the harness would otherwise
    # silently prefer signal) — it is structured invalid_params, not a silent pick.
    result = CliRunner().invoke(
        app,
        [
            "perf",
            "monitor",
            "--params-json",
            '{"node": "/root/Main/Player", "property": "position", "signal": "hit"}',
        ],
    )

    assert result.exit_code != 0
    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"


def test_perf_monitor_params_json_rejects_neither_selector(monkeypatch):
    # Neither property nor signal is also invalid_params via --params-json: the
    # request is ambiguous, not a default-to-something dispatch.
    result = CliRunner().invoke(
        app,
        ["perf", "monitor", "--params-json", '{"node": "/root/Main/Player"}'],
    )

    assert result.exit_code != 0
    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"


def test_perf_monitor_params_json_rejects_frames_over_range(monkeypatch):
    # frames is bounded 1..MAX_WINDOW_FRAMES model-side, so an over-range value is
    # rejected (NOT silently clamped) as structured invalid_params via --params-json.
    result = CliRunner().invoke(
        app,
        [
            "perf",
            "monitor",
            "--params-json",
            '{"node": "/root/Main/Player", "property": "position", "frames": 601}',
        ],
    )

    assert result.exit_code != 0
    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"


def test_perf_monitor_params_json_rejects_frames_below_range(monkeypatch):
    # The lower bound (>= 1) is enforced model-side too: frames 0 is invalid_params.
    result = CliRunner().invoke(
        app,
        [
            "perf",
            "monitor",
            "--params-json",
            '{"node": "/root/Main/Player", "property": "position", "frames": 0}',
        ],
    )

    assert result.exit_code != 0
    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"


def test_script_set_params_json_derives_mode_like_argv(monkeypatch):
    # Parity: the edit mode is derived from the supplied fields model-side, so a
    # --params-json caller need not (and should not) supply it.
    fake = inject_runner(
        monkeypatch,
        RunResult(stdout=sentinel(SCRIPT_SET_RESULT), stderr="", exit_code=0),
    )

    result = CliRunner().invoke(
        app,
        [
            "script",
            "set",
            "--params-json",
            '{"path": "/tmp/proj/hero.gd", "content": "extends Node\\n"}',
        ],
    )

    assert result.exit_code == 0, result.stdout
    op, params = fake.calls[0]
    assert op == "script-set"
    assert params["mode"] == ScriptSetMode.FULL


def _leaf_commands(command, prefix=()):
    """Yield ``(name_path, leaf_click_command)`` for every leaf of the Typer tree.

    Recurses the live Click command tree (``typer.main.get_command(app)``),
    descending into groups (those with a ``.commands`` mapping) and yielding only
    the leaves — the actual ``gda <group> <command>`` invocables.
    """
    sub = getattr(command, "commands", None)
    if not sub:
        yield prefix, command
        return
    for name, child in sub.items():
        yield from _leaf_commands(child, prefix + (name,))


def _params_json_leaves():
    """The leaf-command param table for the coverage test, as ``(name, params)``.

    Walks the live Typer tree so a newly-added command that forgot
    ``--params-json`` is caught here automatically, not only in a hand-kept list.
    """
    root = typer.main.get_command(app)
    return [(" ".join(name), command.params) for name, command in _leaf_commands(root)]


# ``gda schema`` is the one documented exception (ADR-0015): the parameterless
# manifest emitter has no operation to drive, so it carries no --params-json.
_PARAMS_JSON_EXEMPT = {"schema"}


@pytest.mark.parametrize(
    "name, params",
    _params_json_leaves(),
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_every_leaf_command_exposes_params_json(name, params):
    # Coverage: every leaf command must expose --params-json so gda-mcp can drive
    # ANY command from a JSON object (ADR-0015), with the single `schema` meta
    # exception. Driven off the LIVE Typer tree, so a future command that omits
    # the option fails here without anyone maintaining a list.
    exposes = any("--params-json" in param.opts for param in params)
    if name in _PARAMS_JSON_EXEMPT:
        assert not exposes, f"{name} must NOT expose --params-json (the exception)"
    else:
        assert exposes, f"{name} is missing --params-json"


# The argv↔JSON parity table: representative commands covering the distinct
# field shapes (single path; path + node; path + a renamed --type option; two
# path-like fields; a --target). Each row drives the SAME logical input through
# BOTH the argv form and the --params-json form with a `~/…`-prefixed path, so a
# field that did NOT get NormalizedPath would diverge (the argv body passes raw,
# the model normalizes) — exactly the silent regression this guards. Only
# ``fake.calls`` is asserted, so any valid canned result works.
_HOME_TSCN = "~/proj/main.tscn"
_HOME_GD = "~/proj/hero.gd"
_HOME_TRES = "~/proj/palette.tres"

_PARITY_TABLE = [
    # (id, argv-tail, params-json object, canned result)
    (
        "scene-get",
        ["scene", "get", _HOME_TSCN],
        {"path": _HOME_TSCN},
        SCENE_GET_RESULT,
    ),
    (
        "node-get",
        ["node", "get", _HOME_TSCN, "--node", "Hero"],
        {"path": _HOME_TSCN, "node": "Hero"},
        NODE_GET_RESULT,
    ),
    (
        "resource-create",
        ["resource", "create", _HOME_TRES, "--type", "Gradient"],
        {"path": _HOME_TRES, "type": "Gradient"},
        RESOURCE_CREATE_RESULT,
    ),
    (
        "script-attach",
        ["script", "attach", _HOME_TSCN, "--node", "Hero", "--script", _HOME_GD],
        {"path": _HOME_TSCN, "node": "Hero", "script": _HOME_GD},
        # Any valid canned result works; only fake.calls is asserted.
        SCENE_GET_RESULT,
    ),
    (
        "find-references",
        ["project", "find-references", _HOME_TSCN],
        {"target": _HOME_TSCN},
        SCENE_GET_RESULT,
    ),
]


@pytest.mark.parametrize(
    "case_id, argv, params_object, canned",
    _PARITY_TABLE,
    ids=[row[0] for row in _PARITY_TABLE],
)
def test_argv_and_params_json_dispatch_identically(
    case_id, argv, params_object, canned, monkeypatch
):
    # The argv form and the --params-json form of the SAME command, given the same
    # logical input (a `~/…` path that normalization must expand), dispatch the
    # IDENTICAL (operation, params) call. Proves argv ≡ JSON parity and catches
    # any path-bearing field that did not get NormalizedPath.
    argv_fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(canned), stderr="", exit_code=0)
    )
    CliRunner().invoke(app, argv)

    json_fake = inject_runner(
        monkeypatch, RunResult(stdout=sentinel(canned), stderr="", exit_code=0)
    )
    CliRunner().invoke(
        app, [argv[0], argv[1], "--params-json", json.dumps(params_object)]
    )

    assert argv_fake.calls == json_fake.calls, case_id
    # And the path was actually normalized (~ expanded), so the parity is not a
    # vacuous "both stayed raw".
    assert "~" not in json.dumps(json_fake.calls), case_id
