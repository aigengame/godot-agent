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
from gda.commands.daemon import DaemonStatusResult, DaemonWaitReadyResult
from gda.exit_codes import EXIT_LIVE
from gda.runner import RunResult
from tests.support import (
    assert_operation_error,
    inject_live_runner,
    minimal_project,
    sentinel,
)


READY = {
    "pid": 4242,
    "launched": True,
    "startup_diagnostics": [],
    "clean_start": True,
}

# What a broken scene's readiness boundary reports (#848): the session SERVES —
# a root script that failed to compile leaves a script-less root behind, which
# is exactly when the live reads are wanted — so the disclosure rides success.
DEGRADED = {
    "pid": 4242,
    "launched": True,
    "startup_diagnostics": [
        {
            "kind": "parse_error",
            "message": "Parse Error: bad",
            "path": "res://main.gd",
            "line": 5,
        }
    ],
    "clean_start": False,
}


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
    assert data == {
        "pid": 4242,
        "launched": True,
        "startup_diagnostics": [],
        "clean_start": True,
    }
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
            stdout=sentinel({**READY, "launched": False}), stderr="", exit_code=0
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


def test_wait_ready_discloses_a_degraded_start_as_json(monkeypatch, tmp_path):
    # GDA-DF-047: readiness said "ready" while the scene's root script had failed
    # to parse, and the blank frame that followed was captured as evidence. The
    # verdict now names it — success, `clean_start: false`, and the recognized
    # diagnostic naming the script and its line.
    inject_live_runner(
        monkeypatch, RunResult(stdout=sentinel(DEGRADED), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        ["daemon", "wait-ready", "--project", str(minimal_project(tmp_path)), "--json"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["launched"] is True
    assert data["clean_start"] is False
    assert data["startup_diagnostics"] == DEGRADED["startup_diagnostics"]


def test_wait_ready_human_output_names_a_degraded_start(monkeypatch, tmp_path):
    inject_live_runner(
        monkeypatch, RunResult(stdout=sentinel(DEGRADED), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["daemon", "wait-ready", "--project", str(minimal_project(tmp_path))]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "startup not clean" in result.stdout
    assert "parse_error: res://main.gd:5: Parse Error: bad" in result.stdout


def test_wait_ready_human_output_says_nothing_extra_on_a_clean_start(
    monkeypatch, tmp_path
):
    # A clean start adds no line: the readiness sentence already says everything,
    # and a per-run "0 errors" would train the reader to skip the line that matters.
    inject_live_runner(
        monkeypatch, RunResult(stdout=sentinel(READY), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["daemon", "wait-ready", "--project", str(minimal_project(tmp_path))]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert (
        result.stdout.strip() == "engine session ready (launched now; daemon pid 4242)"
    )


# The third state (third review of PR #940): the launch could not read the log
# up to the handshake — no session log, or a read failure. Both keys are null,
# never a clean start for a log nobody saw (ADR-0022 keeps unavailable apart
# from empty); the session still serves.
UNREAD = {
    "pid": 4242,
    "launched": True,
    "startup_diagnostics": None,
    "clean_start": None,
}


def test_wait_ready_passes_a_null_verdict_through_as_success(monkeypatch, tmp_path):
    inject_live_runner(
        monkeypatch, RunResult(stdout=sentinel(UNREAD), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        ["daemon", "wait-ready", "--project", str(minimal_project(tmp_path)), "--json"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["launched"] is True
    assert data["startup_diagnostics"] is None
    assert data["clean_start"] is None


def test_wait_ready_human_output_names_an_unavailable_verdict(monkeypatch, tmp_path):
    # Silence would read as a clean start, so the null verdict is one line.
    inject_live_runner(
        monkeypatch, RunResult(stdout=sentinel(UNREAD), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["daemon", "wait-ready", "--project", str(minimal_project(tmp_path))]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert result.stdout.splitlines() == [
        "engine session ready (launched now; daemon pid 4242)",
        "  startup verdict unavailable: the session log up to the handshake was "
        "not read (run `gda diag errors`)",
    ]


# The pair is ONE fact (fourth review of PR #940): both null, or a list and
# exactly "that list is empty". A reply that says otherwise is a drifted daemon,
# and on `wait-ready` it fails OUTPUT validation the way a missing key does —
# never a success carrying half a verdict.
CONTRADICTIONS = [
    (None, True),
    ([], None),
    ([], False),
    (DEGRADED["startup_diagnostics"], True),
]


@pytest.mark.parametrize("diagnostics,clean", CONTRADICTIONS)
def test_wait_ready_rejects_a_contradictory_verdict_pair(
    monkeypatch, tmp_path, diagnostics, clean
):
    reply = {**READY, "startup_diagnostics": diagnostics, "clean_start": clean}
    inject_live_runner(
        monkeypatch, RunResult(stdout=sentinel(reply), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app,
        ["daemon", "wait-ready", "--project", str(minimal_project(tmp_path)), "--json"],
    )

    assert result.exit_code != 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "contract_violation"


@pytest.mark.parametrize("model", [DaemonWaitReadyResult, DaemonStatusResult])
@pytest.mark.parametrize("diagnostics,clean", CONTRADICTIONS)
def test_both_result_models_own_the_one_verdict_rule(model, diagnostics, clean):
    # The rule lives on the published values, not in the daemon that computed
    # them: a second deployment (the reachable CLI/daemon skew) is exactly where
    # "the daemon derives the boolean in one place" stops being evidence.
    base = {
        "pid": 4242,
        "launched": True,
        "running": True,
        "socket_path": "/tmp/x.sock",
        "session_id": None,
    }
    fields = {k: v for k, v in base.items() if k in model.model_fields}
    with pytest.raises(ValidationError):
        model(**fields, startup_diagnostics=diagnostics, clean_start=clean)
    for good_diagnostics, good_clean in ((None, None), ([], True)):
        model(**fields, startup_diagnostics=good_diagnostics, clean_start=good_clean)


def test_wait_ready_schema_publishes_the_startup_verdict():
    result = CliRunner().invoke(app, ["daemon", "wait-ready", "--schema"])
    assert result.exit_code == 0, result.stdout
    output = json.loads(result.stdout)["output"]
    assert {"startup_diagnostics", "clean_start"} <= set(output["required"])
