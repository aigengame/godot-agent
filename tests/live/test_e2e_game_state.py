"""Headless game state through the real public CLI on every platform (#1119)."""

import json
import sys

import pytest

from gda.exit_codes import EXIT_LIVE
from tests.conftest import engine_pid_writer_gd, read_engine_pid
from tests.game_support import write_game_state_project
from tests.support import Gda, ObservedWindowsProcess


pytestmark = pytest.mark.e2e


def test_game_state_reads_follow_writes_while_paused_and_reset_after_relaunch(
    tmp_path, daemon_runtime_dir
):
    run = Gda(write_game_state_project(tmp_path), json_output=True)
    try:
        run.json("daemon", "start")
        run.json("daemon", "wait-ready")
        session = run.json("daemon", "status")["session_id"]

        paused = run.json(
            "game", "set", "/root/Main", "--property", "paused", "--value", "true"
        )
        assert paused["verified"] is True
        first = run.json("game", "call", "/root/Main", "--method", "state")["value"]
        assert first["paused"] is True
        changed = run.json(
            "game", "set", "/root/Main", "--property", "count", "--value", "41"
        )
        assert (changed["value"], changed["verified"]) == (41, True)
        got = run.json("game", "get", "/root/Main", "--property", "count")
        assert got["properties"][0]["value"] == 41
        second = run.json("game", "call", "/root/Main", "--method", "state")["value"]
        assert second == {**first, "count": 41}
        assert second["payload"] == {"items": [1, 1.25], "at": [5.0, 7.0]}
        assert type(second["payload"]["items"][0]) is int
        assert type(second["payload"]["items"][1]) is float

        assert run.json("game", "tree")["root"]["name"] == "Main"
        found = run.json("game", "find", "--type", "Control")
        assert found["count"] == 1
        assert found["matches"][0]["path"] == "/root/Main/Panel"
        rect = run.json("game", "rect", "/root/Main/Panel")
        assert rect["position"] == [20.0, 30.0]
        assert rect["size"] == [100.0, 50.0]
        assert rect["local_position"] == [20.0, 30.0]
        assert rect["minimum_size"] == [0.0, 0.0]
        assert rect["combined_minimum_size"] == [40.0, 25.0]
        assert run.json("daemon", "status")["session_id"] == session

        run.json(
            "game", "set", "/root/Main", "--property", "paused", "--value", "false"
        )
        resumed = run.json("game", "call", "/root/Main", "--method", "state")["value"]
        assert resumed["paused"] is False
        assert resumed["ticks"] > second["ticks"]
        assert run.json("daemon", "stop")["stopped"] is True
        run.json("daemon", "start")
        run.json("daemon", "wait-ready")
        assert run.json("daemon", "status")["session_id"] != session
        fresh = run.json("game", "call", "/root/Main", "--method", "state")["value"]
        assert fresh["count"] == 3
        assert fresh["paused"] is False
    finally:
        run("daemon", "stop")


@pytest.mark.skipif(
    sys.platform != "win32", reason="Windows Engine-session replacement"
)
def test_game_state_resets_when_the_same_daemon_replaces_its_engine(
    tmp_path, daemon_runtime_dir
):
    project = write_game_state_project(tmp_path)
    script = project / "main.gd"
    script.write_text(
        script.read_text(encoding="utf-8")
        + "\nfunc _ready() -> void:\n"
        + engine_pid_writer_gd(),
        encoding="utf-8",
    )
    run = Gda(project, json_output=True)
    engine = None
    try:
        run.json("daemon", "start")
        run.json("daemon", "wait-ready")
        before = run.json("daemon", "status")
        engine = ObservedWindowsProcess(read_engine_pid(project))
        changed = run.json(
            "game", "set", "/root/Main", "--property", "count", "--value", "41"
        )
        assert changed["verified"] is True
        engine.terminate()
        engine.exited()
        # Observe the retired connection before asking for a replacement.
        run("game", "tree")
        run.json("daemon", "wait-ready")
        after = run.json("daemon", "status")
        assert after["pid"] == before["pid"]
        assert after["session_id"] != before["session_id"]
        fresh = run.json("game", "call", "/root/Main", "--method", "state")["value"]
        assert fresh["count"] == 3
        assert fresh["paused"] is False
    finally:
        run("daemon", "stop")
        if engine is not None:
            engine.close()


@pytest.mark.parametrize(
    ("arguments", "expected_code"),
    [
        (("get", "/root/Missing"), "live_node_not_found"),
        (("rect", "/root/Main"), "live_not_control"),
        (
            ("set", "/root/Main", "--property", "absent", "--value", "1"),
            "live_unknown_property",
        ),
        (("call", "/root/Main", "--method", "secret"), "live_method_not_allowlisted"),
        (
            ("call", "/root/Main", "--method", "echo_float", "--args", "[]"),
            "live_invalid_call_args",
        ),
    ],
)
def test_game_state_refusals_preserve_the_ready_session(
    tmp_path, daemon_runtime_dir, arguments, expected_code
):
    run = Gda(write_game_state_project(tmp_path), json_output=True)
    try:
        run.json("daemon", "start")
        run.json("daemon", "wait-ready")
        session = run.json("daemon", "status")["session_id"]
        refused = run("game", *arguments)
        assert refused.returncode == EXIT_LIVE, refused.stdout + refused.stderr
        error = json.loads(refused.stdout)["error"]
        assert (error["category"], error["code"]) == ("live", expected_code)
        assert run.json("daemon", "status")["session_id"] == session
        assert (
            run.json("game", "call", "/root/Main", "--method", "state")["value"][
                "count"
            ]
            == 3
        )
    finally:
        run("daemon", "stop")
