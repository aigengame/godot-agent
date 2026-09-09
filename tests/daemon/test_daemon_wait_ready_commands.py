"""`gda daemon wait-ready` — the bounded session-readiness wait (#657).

Engine-free: a fake daemon runner at the LIVE seam exercises the full
Typer -> classify_live -> JSON pipeline, and the no-daemon attach-or-fail path
runs the real ``DaemonRunner`` against an empty runtime dir. The daemon-side
launch behavior is in the socket-lifecycle suite; the served-first-read
regression is the e2e.
"""

import json

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from gda.cli import app
from gda.commands.daemon import (
    DaemonWaitReadyResult,
    run_daemon_wait_ready_operation,
)
from gda.errors import Failure
from gda.exit_codes import EXIT_LIVE
from gda.runner import RunResult
from tests.support import (
    assert_operation_error,
    error_sentinel,
    FakeRunner,
    inject_live_runner,
    minimal_project,
    sentinel,
)


READY = {"pid": 4242, "launched": True}


def _returning_runner(result: RunResult):
    fake = FakeRunner(result)

    def make_runner(binary, project):
        assert binary is None
        return fake

    return fake, make_runner


def test_returning_wait_ready_reports_typed_ready_and_forwards_timeout(tmp_path):
    project = minimal_project(tmp_path)
    fake, make_runner = _returning_runner(
        RunResult(stdout=sentinel(READY), stderr="", exit_code=0)
    )

    outcome = run_daemon_wait_ready_operation(
        project, timeout=10.0, make_runner=make_runner
    )

    assert isinstance(outcome, DaemonWaitReadyResult)
    assert outcome == DaemonWaitReadyResult(pid=4242, launched=True)
    assert fake.calls == [("daemon-wait-ready", {"timeout": 10.0})]


def test_returning_wait_ready_with_no_daemon_returns_live_failure(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    outcome = run_daemon_wait_ready_operation(minimal_project(tmp_path))

    assert isinstance(outcome, Failure)
    assert outcome.error.category == "live"
    assert outcome.error.code == "daemon_not_running"


def test_returning_wait_ready_forwards_daemon_failure_and_stderr(tmp_path):
    fake, make_runner = _returning_runner(
        RunResult(
            stdout=error_sentinel(
                "engine_session_not_running", "engine did not become ready"
            ),
            stderr="launch diagnostics\n",
            exit_code=1,
        )
    )

    outcome = run_daemon_wait_ready_operation(
        minimal_project(tmp_path), make_runner=make_runner
    )

    assert isinstance(outcome, Failure)
    assert outcome.error.category == "live"
    assert outcome.error.code == "engine_session_not_running"
    assert outcome.error.message == "engine did not become ready"
    assert outcome.child_stderr == "launch diagnostics\n"
    assert fake.calls == [("daemon-wait-ready", {"timeout": 25.0})]


@pytest.mark.parametrize("timeout", [0.0, 51.0, float("inf"), float("nan")])
def test_returning_wait_ready_keeps_the_registered_timeout_constraints(
    tmp_path, timeout
):
    with pytest.raises(ValidationError):
        run_daemon_wait_ready_operation(minimal_project(tmp_path), timeout=timeout)


def test_wait_ready_reports_the_established_session_as_json(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch, RunResult(stdout=sentinel(READY), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        ["daemon", "wait-ready", "--project", str(minimal_project(tmp_path)), "--json"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data == {"pid": 4242, "launched": True}
    # Routed through the LIVE seam, carrying the default bound.
    assert fake.calls == [("daemon-wait-ready", {"timeout": 25.0})]


def test_wait_ready_passes_the_caller_bound_through(monkeypatch, tmp_path):
    fake = inject_live_runner(
        monkeypatch, RunResult(stdout=sentinel(READY), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        [
            "daemon",
            "wait-ready",
            "--timeout",
            "10",
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert fake.calls == [("daemon-wait-ready", {"timeout": 10.0})]


def test_wait_ready_human_output_names_the_launch_state(monkeypatch, tmp_path):
    inject_live_runner(
        monkeypatch, RunResult(stdout=sentinel(READY), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["daemon", "wait-ready", "--project", str(minimal_project(tmp_path))]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "engine session ready (launched now; daemon pid 4242)" in result.stdout


def test_wait_ready_human_output_reports_an_already_serving_session(
    monkeypatch, tmp_path
):
    inject_live_runner(
        monkeypatch,
        RunResult(
            stdout=sentinel({"pid": 4242, "launched": False}), stderr="", exit_code=0
        ),
    )

    result = CliRunner().invoke(
        app, ["daemon", "wait-ready", "--project", str(minimal_project(tmp_path))]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "already serving" in result.stdout


def test_wait_ready_with_no_daemon_reports_daemon_not_running(monkeypatch, tmp_path):
    # No fake: the real DaemonRunner + discovery run against an empty runtime dir.
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    result = CliRunner().invoke(
        app,
        ["daemon", "wait-ready", "--project", str(minimal_project(tmp_path)), "--json"],
    )

    assert result.exit_code == EXIT_LIVE, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "daemon_not_running"
    assert "gda daemon start" in error["message"]


def test_wait_ready_refuses_an_out_of_range_bound_on_argv(monkeypatch, tmp_path):
    # The params model owns the (0, 50] bound (ADR-0015): the argv path
    # translates its refusal into the Click usage error. 50 caps the wait under
    # the live channel's 60s client-side round-trip bound.
    project = str(minimal_project(tmp_path))
    for bad in ("0", "60", "inf", "nan"):
        result = CliRunner().invoke(
            app, ["daemon", "wait-ready", "--timeout", bad, "--project", project]
        )
        assert result.exit_code == 2, f"--timeout {bad}: {result.stdout}"


def test_wait_ready_refuses_an_out_of_range_bound_on_params_json(monkeypatch, tmp_path):
    # The same rule on the structured path, as the structured refusal.
    result = CliRunner().invoke(
        app,
        [
            "daemon",
            "wait-ready",
            "--params-json",
            json.dumps({"timeout": 60}),
            "--project",
            str(minimal_project(tmp_path)),
            "--json",
        ],
    )

    assert_operation_error(result, "invalid_params")
