"""Observe headless input while paused and replace a timed-out Engine session."""

import json
import os
import time

import pytest

from gda.exit_codes import EXIT_LIVE
from tests.input_support import write_input_observer_project
from tests.support import Gda, ObservedWindowsProcess


pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("clock", ["frame", "physics_frame"])
def test_paused_input_observes_both_routes_and_preserves_frame_order(
    tmp_path, daemon_runtime_dir, clock
):
    run = Gda(write_input_observer_project(tmp_path), json_output=True)

    def observed():
        return run.json("game", "get", "/root/Main", "--property", "snapshot")[
            "properties"
        ][0]["value"]

    try:
        run.json("daemon", "start")
        run.json("daemon", "wait-ready")
        session = run.json("daemon", "status")["session_id"]
        assert (
            run.json(
                "game", "set", "/root/Main", "--property", "paused", "--value", "true"
            )["verified"]
            is True
        )
        baseline = observed()
        assert baseline["paused"] is True
        assert observed()["ticker"] == baseline["ticker"]

        pressed = run.json("input", "action", "move_right", "--strength", "0.25")
        assert pressed["injection_route"] == "action_state"
        state = observed()
        assert state["state"] is True and state["polled"] > baseline["polled"]
        assert [state[k] for k in ("input", "gui", "unhandled")] == [0, 0, 0]
        run.json("input", "action", "move_right", "--release")
        released = observed()
        assert released["state"] is False

        key = run.json("input", "key", "X")
        assert key["injection_route"] == "viewport_event"
        run.json("input", "key", "X", "--released")
        event = observed()
        assert [event[k] for k in ("input", "gui", "unhandled")] == [1, 1, 1]
        assert [
            event[k] for k in ("input_release", "gui_release", "unhandled_release")
        ] == [1, 1, 1]
        assert event["state"] is False and event["polled"] == released["polled"]

        moved = run.json("input", "mouse-move", "20", "25")
        assert moved["injection_route"] == "viewport_event"
        assert observed()["at"] == [20.0, 25.0]
        click = run.json("input", "mouse-click", "22", "27")
        assert click["phases"] == [
            {"frame": 0, "phase": "move", "injection_route": "viewport_event"},
            {"frame": 1, "phase": "press", "injection_route": "viewport_event"},
            {"frame": 2, "phase": "release", "injection_route": "viewport_event"},
        ]
        mouse = observed()
        assert mouse["mouse"] == ["move", "move", "press", "release"]
        assert mouse["at"] == [22.0, 27.0]

        tap = run.json(
            "input",
            "tap",
            "--action",
            "move_right",
            "--hold-frames",
            "2",
            "--settle-frames",
            "2",
        )
        assert tap["frames"] == 5
        assert tap["phases"] == [
            {"frame": 0, "phase": "press", "injection_route": "action_state"},
            {"frame": 2, "phase": "release", "injection_route": "action_state"},
        ]
        tapped = observed()
        assert (tapped["pressed"], tapped["released"]) == (
            released["pressed"] + 1,
            released["released"] + 1,
        )
        assert tapped["input"] == event["input"]

        events = [
            {"type": "action", "action": "move_right", clock: 0},
            {"type": "action", "action": "move_right", "as_event": True, clock: 1},
            {
                "type": "action",
                "action": "move_right",
                "as_event": True,
                "release": True,
                clock: 2,
            },
            {"type": "action", "action": "move_right", "release": True, clock: 3},
        ]
        sequence = run.json("input", "sequence", "--events", json.dumps(events))
        assert sequence["clock"] == ("process" if clock == "frame" else "physics")
        assert sequence["frames"] == 4
        assert sequence["phases"] == [
            {"frame": 0, "phase": "press", "injection_route": "action_state"},
            {"frame": 1, "phase": "press", "injection_route": "viewport_event"},
            {"frame": 2, "phase": "release", "injection_route": "viewport_event"},
            {"frame": 3, "phase": "release", "injection_route": "action_state"},
        ]
        final = observed()
        assert final["state"] is False and final["polled"] > tapped["polled"]
        assert [final[k] for k in ("input", "gui", "unhandled")] == [2, 2, 2]
        assert [
            final[k] for k in ("input_release", "gui_release", "unhandled_release")
        ] == [2, 2, 2]
        assert final["ticker"] == baseline["ticker"]
        assert run.json("daemon", "status")["session_id"] == session
        run.json(
            "game", "set", "/root/Main", "--property", "paused", "--value", "false"
        )
        assert observed()["ticker"] > final["ticker"]
    finally:
        run("daemon", "stop")


@pytest.mark.skipif(
    os.name != "nt", reason="Windows input deadline and owned replacement"
)
def test_input_sequence_timeout_retires_the_stale_engine_before_replacement(
    tmp_path, daemon_runtime_dir
):
    run = Gda(write_input_observer_project(tmp_path), json_output=True)
    engine = None
    try:
        run.json("daemon", "start")
        run.json("daemon", "wait-ready")
        before = run.json("daemon", "status")
        engine = ObservedWindowsProcess(
            int((tmp_path / "engine-pid.txt").read_text(encoding="utf-8"))
        )
        run.json("input", "action", "move_right")
        held = run.json("game", "get", "/root/Main", "--property", "snapshot")[
            "properties"
        ][0]["value"]
        assert held["state"] is True
        run.json(
            "game", "set", "/root/Main", "--property", "block_input", "--value", "true"
        )
        started = time.monotonic()
        timed_out = run(
            "input",
            "sequence",
            "--events",
            '[{"type":"key","key":"X","frame":0},{"type":"key","key":"X","released":true,"frame":2}]',
        )
        elapsed = time.monotonic() - started
        assert timed_out.returncode == EXIT_LIVE, timed_out.stdout + timed_out.stderr
        error = json.loads(timed_out.stdout)["error"]
        assert (error["category"], error["code"]) == ("live", "live_timeout")
        assert "within 30s" in error["message"]
        assert 29 <= elapsed < 45, elapsed
        assert run.json("daemon", "status")["session_id"] == before["session_id"]
        assert run.json("daemon", "wait-ready")["launched"] is True
        engine.exited()
        after = run.json("daemon", "status")
        assert after["pid"] == before["pid"]
        assert after["session_id"] != before["session_id"]
        fresh = run.json("game", "get", "/root/Main", "--property", "snapshot")[
            "properties"
        ][0]["value"]
        assert fresh["block_input"] is False
        assert fresh["input"] == 0
        assert fresh["state"] is False
        run.json("input", "key", "X")
        observed = run.json("game", "get", "/root/Main", "--property", "snapshot")[
            "properties"
        ][0]["value"]
        assert observed["input"] == 1
        assert observed["state"] is False
    finally:
        run("daemon", "stop")
        if engine is not None:
            engine.close()
