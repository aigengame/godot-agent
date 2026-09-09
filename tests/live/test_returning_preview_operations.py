"""Returning seams for the live operations composed by model preview."""

from gda.commands.diag import (
    DiagErrorsParams,
    DiagErrorsResult,
    run_diag_errors_operation,
)
from gda.commands.game import (
    GameGetParams,
    GameGetResult,
    GameSetParams,
    GameSetResult,
    run_game_get_operation,
    run_game_set_operation,
)
from gda.errors import Failure
from gda.runner import RunResult
from tests.support import FakeRunner, error_sentinel, minimal_project, sentinel


def _runner(result: RunResult):
    fake = FakeRunner(result)

    def make_runner(binary, project):
        assert binary is None
        return fake

    return fake, make_runner


def test_game_get_returning_seam_projects_typed_result_and_params(tmp_path):
    fake, make_runner = _runner(
        RunResult(
            stdout=sentinel(
                {
                    "path": "/root/Preview/Model",
                    "name": "Model",
                    "type": "MeshInstance3D",
                    "properties": [],
                }
            ),
            stderr="",
            exit_code=0,
        )
    )
    params = GameGetParams(node="/root/Preview/Model", property="visible")

    result = run_game_get_operation(
        minimal_project(tmp_path), params, make_runner=make_runner
    )

    assert isinstance(result, GameGetResult)
    assert result.path == params.node
    assert fake.calls == [("game-get", params.model_dump(mode="json"))]


def test_game_set_returning_seam_projects_typed_result_and_params(tmp_path):
    fake, make_runner = _runner(
        RunResult(
            stdout=sentinel(
                {
                    "path": "/root/Preview/Model",
                    "property": "visible",
                    "type": "bool",
                    "value": True,
                    "verified": True,
                }
            ),
            stderr="",
            exit_code=0,
        )
    )
    params = GameSetParams(node="/root/Preview/Model", property="visible", value="true")

    result = run_game_set_operation(
        minimal_project(tmp_path), params, make_runner=make_runner
    )

    assert isinstance(result, GameSetResult)
    assert result.verified is True
    assert fake.calls == [("game-set", params.model_dump(mode="json"))]


def test_diag_errors_returning_seam_projects_typed_result_and_params(tmp_path):
    fake, make_runner = _runner(
        RunResult(stdout=sentinel({"errors": []}), stderr="", exit_code=0)
    )
    params = DiagErrorsParams(limit=3)

    result = run_diag_errors_operation(
        minimal_project(tmp_path), params, make_runner=make_runner
    )

    assert isinstance(result, DiagErrorsResult)
    assert result.errors == []
    assert fake.calls == [("diag-errors", {"limit": 3})]


def test_returning_seams_forward_native_failure_without_emitting(tmp_path):
    fake, make_runner = _runner(
        RunResult(
            stdout=error_sentinel("daemon_not_running", "start the daemon"),
            stderr="native diagnostics\n",
            exit_code=1,
        )
    )

    result = run_game_get_operation(
        minimal_project(tmp_path),
        GameGetParams(node="/root/Preview"),
        make_runner=make_runner,
    )

    assert isinstance(result, Failure)
    assert result.error.code == "daemon_not_running"
    assert result.child_stderr == "native diagnostics\n"
    assert fake.calls == [
        (
            "game-get",
            {"node": "/root/Preview", "property": None, "texture_digest": False},
        )
    ]
