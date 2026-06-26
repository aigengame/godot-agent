"""Daemon-side `logger-tail` serving from the daemon-owned Session log (#281).

In-process, engine-free. Like ``diag``, ``logger-tail`` is a daemon-served live op
(ADR-0022, ADR-0026): the daemon serves it by reading the ``--log-file`` it
launched the engine with — NOT by relaying to the harness, and even after the
session process has died (so a crash stays diagnosable). These tests exercise the
daemon's ``_handle`` read path for the structured + raw channels against a temp
log file, plus the same no-session / missing-file typed errors ``diag`` returns.
"""

import os

import pytest

from gda.daemon.discovery import daemon_paths
from gda.daemon.server import DaemonServer
from gda.daemon.session import EngineSession
from gda.parser import parse_result

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")


class _FakeProc:
    def __init__(self, returncode=None):
        self.returncode = returncode

    def poll(self):
        return self.returncode


def _project(tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return tmp_path


def _server_with_session(tmp_path, log_file, alive=True):
    server = DaemonServer(daemon_paths(_project(tmp_path)), godot="godot")
    server._session = EngineSession(
        _FakeProc(None if alive else 0), conn=None, log_file=log_file
    )
    return server


def test_logger_tail_reads_structured_records_from_the_log(tmp_path):
    log_file = tmp_path / "session.log"
    log_file.write_text(
        "print output\nERROR: boom\n   at: _ready (res://main.gd:9)\n", encoding="utf-8"
    )
    server = _server_with_session(tmp_path, log_file)

    reply = server._handle({"op": "logger-tail", "params": {}})
    payload = parse_result(reply["stdout"])

    records = payload["records"]
    assert records[0]["level"] == "info"
    assert records[0]["message"] == "print output"
    err = next(r for r in records if r["level"] == "error")
    assert err["message"] == "boom"
    assert err["origin"] == "engine"
    assert err["source"] == {"function": "_ready", "file": "res://main.gd", "line": 9}


def test_logger_tail_raw_returns_verbatim_info_records(tmp_path):
    # --raw skips classification: every line is a verbatim `info` record (still
    # LogRecord[]), so even an `ERROR:` header stays an unclassified info line.
    log_file = tmp_path / "session.log"
    log_file.write_text("known line\nERROR: boom\n", encoding="utf-8")
    server = _server_with_session(tmp_path, log_file)

    reply = server._handle({"op": "logger-tail", "params": {"raw": True}})
    payload = parse_result(reply["stdout"])

    messages = [r["message"] for r in payload["records"]]
    assert messages == ["known line", "ERROR: boom"]
    assert all(r["level"] == "info" and r["source"] is None for r in payload["records"])


def test_logger_tail_level_filters_by_minimum_severity(tmp_path):
    log_file = tmp_path / "session.log"
    log_file.write_text(
        "plain output\nWARNING: heads up\n   at: f (res://a.gd:1)\n"
        "ERROR: boom\n   at: g (res://b.gd:2)\n",
        encoding="utf-8",
    )
    server = _server_with_session(tmp_path, log_file)

    reply = server._handle({"op": "logger-tail", "params": {"level": "warning"}})
    payload = parse_result(reply["stdout"])

    levels = {r["level"] for r in payload["records"]}
    assert "info" not in levels  # the plain output line is filtered out
    assert levels == {"warning", "error"}


def test_logger_tail_limit_tails_the_most_recent_n(tmp_path):
    log_file = tmp_path / "session.log"
    log_file.write_text("one\ntwo\nthree\n", encoding="utf-8")
    server = _server_with_session(tmp_path, log_file)

    reply = server._handle({"op": "logger-tail", "params": {"limit": 1}})
    payload = parse_result(reply["stdout"])

    assert len(payload["records"]) == 1
    assert payload["records"][0]["message"] == "three"


def test_logger_tail_serves_even_when_the_session_process_has_died(tmp_path):
    # A crash is diagnosable: the daemon serves logger-tail from the remembered log
    # file even after the session process has exited (ADR-0022 rationale).
    log_file = tmp_path / "session.log"
    log_file.write_text(
        "ERROR: crashed\n   at: _ready (res://main.gd:3)\n", encoding="utf-8"
    )
    server = _server_with_session(tmp_path, log_file, alive=False)

    reply = server._handle({"op": "logger-tail", "params": {}})
    payload = parse_result(reply["stdout"])

    crashed = next(r for r in payload["records"] if "crashed" in r["message"])
    assert crashed["level"] == "error"


def test_logger_tail_empty_log_is_an_empty_result_not_an_error(tmp_path):
    log_file = tmp_path / "session.log"
    log_file.write_text("", encoding="utf-8")
    server = _server_with_session(tmp_path, log_file)

    reply = server._handle({"op": "logger-tail", "params": {}})
    payload = parse_result(reply["stdout"])

    assert payload["records"] == []


def test_logger_tail_with_no_session_is_engine_session_not_running(tmp_path):
    # ADR-0022: a daemon-served log op observes an already-launched session; it does
    # NOT launch one. With none launched this lifetime it is a structured error.
    server = DaemonServer(daemon_paths(_project(tmp_path)), godot="godot")

    reply = server._handle({"op": "logger-tail", "params": {}})

    assert (
        parse_result(reply["stdout"])["error"]["code"] == "engine_session_not_running"
    )
    assert server._session is None


def test_logger_tail_with_a_remembered_session_but_missing_file_is_live_log_unavailable(
    tmp_path,
):
    log_file = tmp_path / "missing.log"  # never created
    server = _server_with_session(tmp_path, log_file, alive=False)

    reply = server._handle({"op": "logger-tail", "params": {}})

    assert parse_result(reply["stdout"])["error"]["code"] == "live_log_unavailable"
