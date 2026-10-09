"""Actual rendered UI effects through the public CLI, not injection echoes."""

import pytest

from tests.rendered_ui_support import (
    BUTTON_A,
    GREEN,
    OUTSIDE,
    assert_ui_pixels,
    write_rendered_ui_project,
)
from tests.support import Gda

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.usefixtures("windowed_host"),
    pytest.mark.xdist_group("windowed"),
]


def test_pointer_movement_and_complete_click_change_the_rendered_ui(
    tmp_path, daemon_runtime_dir
):
    run = Gda(write_rendered_ui_project(tmp_path), json_output=True)

    def observed():
        return run.json("game", "get", "/root/Main", "--property", "snapshot")[
            "properties"
        ][0]["value"]

    def captured(name):
        return run.json(
            "screen",
            "capture",
            "--output",
            str(tmp_path / name),
            "--settle-frames",
            "2",
        )

    try:
        run.json("daemon", "start", "--windowed")
        run.json("daemon", "wait-ready")
        session = run.json("daemon", "status")["session_id"]
        run.json("input", "mouse-move", *map(str, OUTSIDE))
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
        assert run.json("diag", "errors")["errors"] == []
    finally:
        run("daemon", "stop")
