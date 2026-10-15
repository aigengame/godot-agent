"""The rules that every Live command answers in the same way (#1212).

A Live command reaches the running game through ``gda-daemon``, and five failures
do not depend on which command it is: no daemon runs, the project does not
resolve, the host platform is not supported, the live runner relays a registered
Live error, and the live runner returns, with exit 0, a Live error whose code is
not registered. Each rule is one test, parametrized over the table of the Live
leaves, so the rule is stated once and every leaf answers it. A guard keeps the
table equal to the Live leaves of the command tree, so a new Live command cannot
miss a rule.

A test of one command keeps what is specific to that command: a message that the
harness composes, a file that a refusal must not write, or the codes that one
command tells apart.
"""

import json

import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.core.engine.execution import ExecutionKind
from gda.core.engine.launch import RunResult
from gda.core.project.paths import GDA_PROJECT_ENV
from gda.daemon.protocol import error_reply
from gda.exit_codes import EXIT_LIVE, EXIT_NOT_FOUND, EXIT_OPERATION, EXIT_PARSE
from gda.surface.manifest import build_surface_manifest
from tests.support import invoke_live, minimal_project

# The smallest argv that each Live leaf accepts, without ``--project`` and
# ``--json``. The output paths are relative: each test runs in its own directory.
LIVE_LEAVES: dict[str, list[str]] = {
    "game tree": ["game", "tree"],
    "game find": ["game", "find", "--name", "Player"],
    "game get": ["game", "get", "/root/Main", "--property", "position"],
    "game rect": ["game", "rect", "/root/Main/HUD"],
    "game set": [
        "game",
        "set",
        "/root/Main",
        "--property",
        "visible",
        "--value",
        "true",
    ],
    "game call": ["game", "call", "/root/Main", "--method", "reset"],
    "diag errors": ["diag", "errors"],
    "logger tail": ["logger", "tail"],
    "perf monitors": ["perf", "monitors"],
    "perf monitor": ["perf", "monitor", "/root/Main", "--property", "position"],
    "input key": ["input", "key", "Right"],
    "input mouse-click": ["input", "mouse-click", "10", "20"],
    "input mouse-move": ["input", "mouse-move", "10", "20"],
    "input action": ["input", "action", "ui_accept"],
    "input tap": ["input", "tap", "--action", "ui_accept"],
    "input sequence": [
        "input",
        "sequence",
        "--events",
        json.dumps([{"type": "key", "key": "Right"}]),
    ],
    "screen capture": ["screen", "capture", "--output", "shot.png"],
    "screen frames": ["screen", "frames", "--frames", "2", "--output-dir", "frames"],
    "daemon wait-ready": ["daemon", "wait-ready"],
}

LEAVES = list(LIVE_LEAVES)


@pytest.fixture(autouse=True)
def _outside_any_project(monkeypatch, tmp_path):
    # The working directory holds no project.godot, and GDA_PROJECT names none:
    # a test that needs a project names one with --project.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(GDA_PROJECT_ENV, raising=False)


def _in_project(leaf: str, tmp_path) -> list[str]:
    project = minimal_project(tmp_path / "project")
    return [*LIVE_LEAVES[leaf], "--project", str(project), "--json"]


def _error(result) -> dict:
    return json.loads(result.stdout)["error"]


def test_the_table_names_each_live_leaf_once_and_nothing_else():
    live = {
        command.name
        for command in build_surface_manifest(app).commands
        if command.kind is ExecutionKind.LIVE
    }
    assert sorted(live - set(LIVE_LEAVES)) == [], "Live leaves with no row"
    assert sorted(set(LIVE_LEAVES) - live) == [], "rows that are not Live leaves"


@pytest.mark.parametrize("leaf", LEAVES)
def test_with_no_daemon_a_live_command_says_to_start_one(monkeypatch, tmp_path, leaf):
    # No fake: the real live runner and discovery look in an empty runtime directory.
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    result = CliRunner().invoke(app, _in_project(leaf, tmp_path))

    assert result.exit_code == EXIT_LIVE, result.output
    error = _error(result)
    assert (error["category"], error["code"]) == ("live", "daemon_not_running")
    assert "gda daemon start" in error["message"]


@pytest.mark.parametrize("leaf", LEAVES)
def test_outside_a_project_a_live_command_is_project_not_found(leaf):
    # A project-resolution error, not a daemon error (ADR-0021).
    result = CliRunner().invoke(app, [*LIVE_LEAVES[leaf], "--json"])

    assert result.exit_code == EXIT_OPERATION, result.output
    error = _error(result)
    assert (error["category"], error["code"]) == ("operation", "project_not_found")


@pytest.mark.parametrize("leaf", LEAVES)
def test_on_an_unsupported_platform_a_live_command_refuses(monkeypatch, tmp_path, leaf):
    # A host that the schema does not list: refused before the daemon is touched.
    monkeypatch.setattr("gda.core.engine.execution.sys.platform", "unsupported")
    result = CliRunner().invoke(app, _in_project(leaf, tmp_path))

    assert result.exit_code == EXIT_NOT_FOUND, result.output
    error = _error(result)
    assert (error["category"], error["code"]) == (
        "environment",
        "live_unsupported_platform",
    )


# The two shapes in which the live runner returns a registered Live error. The
# daemon passes on a harness reply with exit 0, and returns a Live error that it
# builds itself with exit EXIT_LIVE. The code does not matter: every registered
# code takes the same relay.
RELAYED = [
    pytest.param(
        "live_node_not_found",
        "no node at /root/Main",
        lambda code, message: {"error": {"code": code, "message": message}},
        id="harness-reply",
    ),
    pytest.param(
        "engine_disconnected",
        "the Engine session closed the connection",
        lambda code, message: RunResult(**error_reply(code, message)),
        id="daemon-reply",
    ),
]


@pytest.mark.parametrize(("code", "message", "reply"), RELAYED)
@pytest.mark.parametrize("leaf", LEAVES)
def test_a_live_command_relays_a_registered_live_error(
    monkeypatch, tmp_path, leaf, code, message, reply
):
    result, _ = invoke_live(
        monkeypatch, _in_project(leaf, tmp_path), reply(code, message)
    )

    assert result.exit_code == EXIT_LIVE, result.output
    error = _error(result)
    assert (error["category"], error["code"]) == ("live", code)
    assert error["message"] == message


@pytest.mark.parametrize("leaf", LEAVES)
def test_an_unregistered_live_error_is_a_contract_violation(
    monkeypatch, tmp_path, leaf
):
    # Exit 0 is the shape of a harness reply. An unregistered code there is a
    # broken contract, never a result: an empty result would hide it.
    result, _ = invoke_live(
        monkeypatch,
        _in_project(leaf, tmp_path),
        {"error": {"code": "not_a_registered_code", "message": "unexpected"}},
    )

    assert result.exit_code == EXIT_PARSE, result.output
    error = _error(result)
    assert (error["category"], error["code"]) == ("parse", "contract_violation")
