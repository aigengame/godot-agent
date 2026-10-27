"""The behaviours that the two daemon-served log operations share (#1212).

``diag errors`` and ``logger tail`` read the Session log that the daemon launched
the Engine session with (ADR-0022, ADR-0026). The daemon serves both itself, not
through the harness. Each behaviour is one test over both operations, in process
and with no engine.
"""

import socket
from typing import cast

import pytest

from gda.core.engine.sentinel import parse_result
from gda.daemon.discovery import daemon_paths
from gda.daemon.host import host_platform
from gda.daemon.server import DIAG_ERRORS_OP, LOGGER_TAIL_OP, DaemonServer
from tests.support import FakeHarnessListener, runnable_project, server_with_session

# Each daemon-served log operation, and the result key that holds what it read.
LOG_OPS = {DIAG_ERRORS_OP: "errors", LOGGER_TAIL_OP: "records"}


def _serve(server: DaemonServer, op: str) -> dict:
    reply = server._handle({"op": op, "params": {}})
    assert reply is not None
    return parse_result(reply["stdout"])


@pytest.mark.parametrize(("op", "key"), LOG_OPS.items())
def test_a_log_op_reads_the_log_after_the_session_process_died(tmp_path, op, key):
    # A crash stays diagnosable: the daemon reads the remembered log file after
    # the session process has exited.
    log_file = tmp_path / "session.log"
    log_file.write_text(
        "ERROR: crashed\n   at: _ready (res://main.gd:3)\n", encoding="utf-8"
    )
    server = server_with_session(tmp_path, log_file, alive=False)

    assert _serve(server, op)[key][0]["message"] == "crashed"


@pytest.mark.parametrize(("op", "key"), LOG_OPS.items())
def test_a_log_op_reads_an_empty_log_as_an_empty_result(tmp_path, op, key):
    log_file = tmp_path / "session.log"
    log_file.write_text("", encoding="utf-8")
    server = server_with_session(tmp_path, log_file)

    assert _serve(server, op)[key] == []


@pytest.mark.parametrize("op", LOG_OPS)
def test_a_log_op_with_no_session_launches_none(tmp_path, op):
    # ADR-0022: a log operation observes a session that is already launched. It
    # never launches one, because a launch runs project code (ADR-0009).
    def _must_not_launch(*args, **kwargs):
        pytest.fail(f"{op} launched an Engine session")

    server = DaemonServer(
        daemon_paths(runnable_project(tmp_path), platform=host_platform()),
        godot="godot",
        launch=_must_not_launch,
        platform=host_platform(),
    )
    # A serving daemon holds its harness listener. Without one, a launch stops
    # before it calls the launch function.
    server._harness_listener = cast(socket.socket, FakeHarnessListener())

    assert _serve(server, op)["error"]["code"] == "engine_session_not_running"
    assert server._session is None


@pytest.mark.parametrize("op", LOG_OPS)
def test_a_log_op_with_a_missing_log_file_is_live_log_unavailable(tmp_path, op):
    # The session is remembered, but its log file is gone.
    server = server_with_session(tmp_path, tmp_path / "missing.log", alive=False)

    assert _serve(server, op)["error"]["code"] == "live_log_unavailable"
