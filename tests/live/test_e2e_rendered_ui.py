"""Actual rendered UI effects through the public CLI, not injection echoes."""

import json
import os
import time

import pytest

from tests.rendered_ui_support import (
    BUTTON_A,
    BUTTON_B,
    GREEN,
    OUTSIDE,
    YELLOW,
    assert_ui_pixels,
    write_rendered_ui_project,
)
from gda.exit_codes import EXIT_LIVE
from tests.support import Gda, ObservedWindowsProcess

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.usefixtures("windowed_host"),
    pytest.mark.xdist_group("windowed"),
]


@pytest.fixture
def rendered_ui(tmp_path, daemon_runtime_dir):
    run = Gda(write_rendered_ui_project(tmp_path), json_output=True)
    try:
        run.json("daemon", "start", "--windowed")
        run.json("daemon", "wait-ready")
        session = run.json("daemon", "status")["session_id"]
        # Keep the full startup log visible; interaction must add no diagnostics.
        startup = run.json("diag", "errors")["errors"]
        run.json("input", "mouse-move", *map(str, OUTSIDE))
        yield run, session, startup
    finally:
        run("daemon", "stop")


def ui_snapshot(run):
    return run.json("game", "get", "/root/Main", "--property", "snapshot")[
        "properties"
    ][0]["value"]


def capture_ui(run, output):
    return run.json(
        "screen", "capture", "--output", str(output), "--settle-frames", "2"
    )


def test_pointer_movement_and_complete_click_change_the_rendered_ui(
    tmp_path, rendered_ui
):
    run, session, startup = rendered_ui

    def observed():
        return ui_snapshot(run)

    def captured(name):
        return capture_ui(run, tmp_path / name)

    initial = observed()
    assert initial["focus"] == "/root/Main/A"
    assert initial["a_pressed"] == 0 and initial["b_pressed"] == 0
    assert initial["a_rect"] == {"position": [20.0, 20.0], "size": [120.0, 40.0]}
    assert initial["b_rect"] == {"position": [20.0, 100.0], "size": [120.0, 40.0]}
    assert_ui_pixels(captured("before.png"), session)
    moved = run.json("input", "mouse-move", *map(str, BUTTON_A))
    assert moved["injection_route"] == "viewport_event"
    state = observed()
    assert state["mouse_at"] == [70.0, 40.0] and state["hover_a"] is True
    assert_ui_pixels(captured("hover.png"), session, hover=GREEN)
    clicked = run.json("input", "mouse-click", *map(str, BUTTON_A))
    assert clicked["phases"] == [
        {"frame": 0, "phase": "move", "injection_route": "viewport_event"},
        {"frame": 1, "phase": "press", "injection_route": "viewport_event"},
        {"frame": 2, "phase": "release", "injection_route": "viewport_event"},
    ]
    assert clicked["focus_before"] == clicked["focus_after"] == "/root/Main/A"
    activated = observed()
    assert [activated[k] for k in ("a_pressed", "a_down", "a_up")] == [1, 1, 1]
    assert activated["b_pressed"] == 0 and activated["polled"] is False
    assert_ui_pixels(captured("clicked.png"), session, a=GREEN, hover=GREEN)
    changed = run.json("input", "mouse-click", *map(str, BUTTON_B))
    assert changed["focus_before"] == "/root/Main/A"
    assert changed["focus_after"] == "/root/Main/B"
    assert ui_snapshot(run)["b_pressed"] == 1
    assert_ui_pixels(
        captured("pointer-focus.png"), session, a=GREEN, b=GREEN, focus=GREEN
    )
    run.json("input", "mouse-click", *map(str, BUTTON_A))
    repeated = observed()
    assert [repeated[k] for k in ("a_pressed", "a_down", "a_up")] == [2, 2, 2]
    assert repeated["focus"] == "/root/Main/A"
    assert_ui_pixels(captured("repeated.png"), session, b=GREEN, hover=GREEN)
    assert run.json("diag", "errors")["errors"] == startup


def test_action_state_changes_pixels_without_activation_but_action_events_activate(
    tmp_path, rendered_ui
):
    run, session, startup = rendered_ui
    pressed = run.json("input", "action", "ui_accept")
    assert pressed["injection_route"] == "action_state"
    held = ui_snapshot(run)
    assert held["polled"] is True and held["polled_frames"] > 0
    assert held["a_pressed"] == held["a_down"] == 0
    assert_ui_pixels(
        capture_ui(run, tmp_path / "state-held.png"), session, state=YELLOW
    )
    run.json("input", "action", "ui_accept", "--release")
    tapped_state = run.json("input", "tap", "--action", "ui_accept")
    assert [p["injection_route"] for p in tapped_state["phases"]] == [
        "action_state"
    ] * 2
    baseline = ui_snapshot(run)
    assert (
        baseline["polled"] is False
        and baseline["polled_frames"] > held["polled_frames"]
    )
    assert baseline["a_pressed"] == baseline["a_down"] == 0
    assert_ui_pixels(capture_ui(run, tmp_path / "state-released.png"), session)

    event = run.json("input", "action", "ui_accept", "--as-event")
    assert event["injection_route"] == "viewport_event"
    assert ui_snapshot(run)["a_pressed"] == 0
    run.json("input", "action", "ui_accept", "--as-event", "--release")
    assert ui_snapshot(run)["a_pressed"] == 1
    assert_ui_pixels(capture_ui(run, tmp_path / "event-paired.png"), session, a=GREEN)
    event_tap = run.json("input", "tap", "--action", "ui_accept", "--as-event")
    assert event_tap["phases"] == [
        {"frame": 0, "phase": "press", "injection_route": "viewport_event"},
        {"frame": 2, "phase": "release", "injection_route": "viewport_event"},
    ]
    assert ui_snapshot(run)["a_pressed"] == 2
    assert_ui_pixels(capture_ui(run, tmp_path / "event-tapped.png"), session)
    run.json(
        "input",
        "sequence",
        "--events",
        json.dumps(
            [
                {"type": "action", "action": "ui_accept", "as_event": True, "frame": 0},
                {
                    "type": "action",
                    "action": "ui_accept",
                    "as_event": True,
                    "release": True,
                    "frame": 3,
                },
            ]
        ),
    )
    final = ui_snapshot(run)
    assert [final[k] for k in ("a_pressed", "a_down", "a_up")] == [3, 3, 3]
    assert final["b_pressed"] == 0 and final["polled"] is False
    assert final["polled_frames"] == baseline["polled_frames"]
    assert_ui_pixels(
        capture_ui(run, tmp_path / "event-sequenced.png"), session, a=GREEN
    )
    assert run.json("diag", "errors")["errors"] == startup


@pytest.mark.skipif(os.name != "nt", reason="Windows rendered input owned replacement")
def test_rendered_input_deadline_retires_the_engine_and_resets_ui(
    tmp_path, rendered_ui
):
    run, session, _startup = rendered_ui
    before = run.json("daemon", "status")
    engine = ObservedWindowsProcess(
        int((tmp_path / "engine-pid.txt").read_text(encoding="utf-8"))
    )
    try:
        run.json("input", "tap", "--key", "Space")
        assert ui_snapshot(run)["a_pressed"] == 1
        run.json(
            "game", "set", "/root/Main", "--property", "block_input", "--value", "true"
        )
        started = time.monotonic()
        timed_out = run(
            "input",
            "sequence",
            "--events",
            '[{"type":"key","key":"Space","frame":0},{"type":"key","key":"Space","released":true,"frame":2}]',
        )
        elapsed = time.monotonic() - started
        assert timed_out.returncode == EXIT_LIVE, timed_out.stdout + timed_out.stderr
        error = json.loads(timed_out.stdout)["error"]
        assert (error["category"], error["code"]) == ("live", "live_timeout")
        assert "within 30s" in error["message"] and 29 <= elapsed < 45
        assert run.json("daemon", "status")["session_id"] == session
        assert run.json("daemon", "wait-ready")["launched"] is True
        engine.exited()
        after = run.json("daemon", "status")
        assert after["pid"] == before["pid"] and after["session_id"] != session
        fresh = ui_snapshot(run)
        assert fresh["a_pressed"] == fresh["b_pressed"] == 0
        assert fresh["focus"] == "/root/Main/A" and fresh["polled"] is False
        run.json("input", "mouse-move", *map(str, OUTSIDE))
        assert_ui_pixels(capture_ui(run, tmp_path / "fresh.png"), after["session_id"])
        run.json("input", "tap", "--key", "Space")
        assert ui_snapshot(run)["a_pressed"] == 1
        assert_ui_pixels(
            capture_ui(run, tmp_path / "recovered.png"), after["session_id"], a=GREEN
        )
    finally:
        engine.close()


def test_keys_move_focus_and_activate_once_per_complete_gesture(tmp_path, rendered_ui):
    run, session, startup = rendered_ui
    assert ui_snapshot(run)["focus"] == "/root/Main/A"
    navigated = run.json("input", "tap", "--key", "Down")
    assert navigated["focus_before"] == "/root/Main/A"
    assert navigated["focus_after"] == "/root/Main/B"
    assert_ui_pixels(capture_ui(run, tmp_path / "focused.png"), session, focus=GREEN)

    pressed = run.json("input", "key", "Space")
    assert pressed["injection_route"] == "viewport_event"
    held = ui_snapshot(run)
    assert held["b_down"] == 1 and held["b_pressed"] == 0
    assert held["polled"] is False
    released = run.json("input", "key", "Space", "--released")
    assert released["injection_route"] == "viewport_event"
    assert [ui_snapshot(run)[k] for k in ("b_pressed", "b_down", "b_up")] == [1, 1, 1]
    assert_ui_pixels(
        capture_ui(run, tmp_path / "paired.png"), session, b=GREEN, focus=GREEN
    )

    tapped = run.json("input", "tap", "--key", "Space", "--hold-frames", "2")
    assert tapped["phases"] == [
        {"frame": 0, "phase": "press", "injection_route": "viewport_event"},
        {"frame": 2, "phase": "release", "injection_route": "viewport_event"},
    ]
    assert tapped["focus_before"] == tapped["focus_after"] == "/root/Main/B"
    assert ui_snapshot(run)["b_pressed"] == 2
    assert_ui_pixels(capture_ui(run, tmp_path / "tapped.png"), session, focus=GREEN)

    sequenced = run.json(
        "input",
        "sequence",
        "--events",
        json.dumps(
            [
                {"type": "key", "key": "Space", "frame": 0},
                {"type": "key", "key": "Space", "released": True, "frame": 2},
            ]
        ),
    )
    assert [p["injection_route"] for p in sequenced["phases"]] == ["viewport_event"] * 2
    final = ui_snapshot(run)
    assert [final[k] for k in ("b_pressed", "b_down", "b_up")] == [3, 3, 3]
    assert final["a_pressed"] == 0 and final["polled_frames"] == 0
    assert_ui_pixels(
        capture_ui(run, tmp_path / "sequenced.png"), session, b=GREEN, focus=GREEN
    )
    assert run.json("diag", "errors")["errors"] == startup
