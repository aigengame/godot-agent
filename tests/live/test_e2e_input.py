"""S (e2e): `gda input` live input simulation through the real gda-daemon loop (#221).

The Step-6 proof for input: a real `gda daemon start` (real detached daemon, real
harness install, live-version gate) -> a real engine session it launches on demand
-> `gda input key/action/sequence ...` pushes input into the RUNNING game, whose
`_input` / action polling turns it into a node-state change, observed via
`gda game get` (#220). This is the #221 DoD: inject input, then observe the effect.

Run e2e SERIALLY (a sibling worktree may drive Godot concurrently); not a fresh
empty HOME (Godot first-run). The `daemon_runtime_dir` fixture keeps the daemon's
UDS path within the OS `sun_path` limit. File logging stays disabled via
project_godot (#180).
"""

import json
import os

import pytest

from tests.support import Gda, assert_windowed_ok

from tests.conftest import LIVE_PROJECT_GODOT, project_godot

# A Player whose `_input` moves it right on KEY_RIGHT — so an injected key event
# rides the game's real input flow into `_input` and mutates `position.x`, observed
# via `game get`. The move is a fixed step so the assertion is exact.
KEY_PLAYER_GD = (
    "extends Node2D\n"
    "func _input(event: InputEvent) -> void:\n"
    "\tif event is InputEventKey and event.pressed:\n"
    "\t\tif event.keycode == KEY_RIGHT:\n"
    "\t\t\tposition.x += 10.0\n"
)
KEY_MAIN_TSCN = (
    "[gd_scene load_steps=2 format=3]\n\n"
    '[ext_resource type="Script" path="res://player.gd" id="1"]\n\n'
    '[node name="Main" type="Node2D"]\n\n'
    '[node name="Player" type="Node2D" parent="."]\n'
    'script = ExtResource("1")\n'
)

# A Player whose `_input` reacts to a LEFT mouse button press by snapping its
# position to the click coordinates — so an injected `input mouse-click <x> <y>`
# rides the real `push_input(InputEventMouseButton)` viewport path into `_input`
# and sets `position`, observed via `game get`. The click position is exact so the
# assertion is exact.
MOUSE_PLAYER_GD = (
    "extends Node2D\n"
    "func _input(event: InputEvent) -> void:\n"
    "\tif event is InputEventMouseButton and event.pressed:\n"
    "\t\tif event.button_index == MOUSE_BUTTON_LEFT:\n"
    "\t\t\tposition = event.position\n"
)
MOUSE_MAIN_TSCN = (
    "[gd_scene load_steps=2 format=3]\n\n"
    '[ext_resource type="Script" path="res://player.gd" id="1"]\n\n'
    '[node name="Main" type="Node2D"]\n\n'
    '[node name="Player" type="Node2D" parent="."]\n'
    'script = ExtResource("1")\n'
)

DRAG_PLAYER_GD = (
    "extends Node2D\n"
    "@export var dragging: bool = false\n"
    "@export var release_seen: bool = false\n"
    "@export var motion_with_left_mask: bool = false\n"
    "func _input(event: InputEvent) -> void:\n"
    "\tif event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:\n"
    "\t\tif event.pressed:\n"
    "\t\t\tdragging = true\n"
    "\t\t\trelease_seen = false\n"
    "\t\t\tposition = event.position\n"
    "\t\telse:\n"
    "\t\t\tdragging = false\n"
    "\t\t\trelease_seen = true\n"
    "\telif event is InputEventMouseMotion and dragging:\n"
    "\t\tif event.button_mask & MOUSE_BUTTON_MASK_LEFT != 0:\n"
    "\t\t\tmotion_with_left_mask = true\n"
    "\t\t\tposition = event.position\n"
)
DRAG_MAIN_TSCN = MOUSE_MAIN_TSCN

TRACKED_MOUSE_PLAYER_GD = (
    "extends Node2D\n"
    '@export var last_event_type: String = ""\n'
    "@export var last_event_position: Vector2 = Vector2(-1, -1)\n"
    "@export var last_event_relative: Vector2 = Vector2(-1, -1)\n"
    "@export var last_global_mouse_position: Vector2 = Vector2(-1, -1)\n"
    "@export var last_viewport_mouse_position: Vector2 = Vector2(-1, -1)\n"
    "func _input(event: InputEvent) -> void:\n"
    "\tif event is InputEventMouseButton and event.pressed:\n"
    '\t\t_capture_mouse("click", event.position, Vector2.ZERO)\n'
    "\telif event is InputEventMouseMotion:\n"
    '\t\t_capture_mouse("move", event.position, event.relative)\n'
    "func _capture_mouse(kind: String, event_position: Vector2, event_relative: Vector2) -> void:\n"
    "\tlast_event_type = kind\n"
    "\tlast_event_position = event_position\n"
    "\tlast_event_relative = event_relative\n"
    "\tlast_global_mouse_position = get_global_mouse_position()\n"
    "\tlast_viewport_mouse_position = get_viewport().get_mouse_position()\n"
)
TRACKED_MOUSE_MAIN_TSCN = MOUSE_MAIN_TSCN

# A Player that polls a `move_right` input action each frame: while the action is
# pressed it advances, so an injected `input action move_right` (a press held until
# released) moves the node. The action is registered in project.godot's input map.
ACTION_PLAYER_GD = (
    "extends Node2D\n"
    "func _process(_delta: float) -> void:\n"
    '\tif Input.is_action_pressed("move_right"):\n'
    "\t\tposition.x += 1.0\n"
)
ACTION_MAIN_TSCN = (
    "[gd_scene load_steps=2 format=3]\n\n"
    '[ext_resource type="Script" path="res://player.gd" id="1"]\n\n'
    '[node name="Main" type="Node2D"]\n\n'
    '[node name="Player" type="Node2D" parent="."]\n'
    'script = ExtResource("1")\n'
)

PHYSICS_ACTION_PLAYER_GD = (
    "extends Node2D\n"
    "const SPEED := 120.0\n"
    "func _physics_process(delta: float) -> void:\n"
    '\tif Input.is_action_pressed("move_right"):\n'
    "\t\tposition.x += SPEED * delta\n"
)


# A project.godot whose [input] section declares `move_right` so the running
# InputMap has the action `input action move_right` drives (InputMap.has_action).
ACTION_PROJECT_GODOT = project_godot(
    extra=(
        'run/main_scene="res://main.tscn"\n\n'
        "[input]\n\n"
        "move_right={\n"
        '"deadzone": 0.5,\n'
        '"events": []\n'
        "}\n"
    )
)

PHYSICS_ACTION_PROJECT_GODOT = project_godot(
    extra=(
        'run/main_scene="res://main.tscn"\n\n'
        "[physics]\n\n"
        "common/physics_ticks_per_second=60\n\n"
        "[input]\n\n"
        "move_right={\n"
        '"deadzone": 0.5,\n'
        '"events": []\n'
        "}\n"
    )
)

# A standard enabled Button plus counters for its activation signals (#652,
# #647). A default Button emits `pressed` only on the RELEASE of a complete
# click, so the counters expose whether an injected "click" performed the whole
# gesture or left the button held down (GDA-DF-004). `motion_seen` records the
# gesture's initial mouse move riding `_input`.
BUTTON_UI_GD = (
    "extends Control\n"
    "@export var pressed_count: int = 0\n"
    "@export var down_count: int = 0\n"
    "@export var up_count: int = 0\n"
    "@export var motion_seen: bool = false\n"
    "func _ready() -> void:\n"
    "\t$Btn.pressed.connect(func() -> void: pressed_count += 1)\n"
    "\t$Btn.button_down.connect(func() -> void: down_count += 1)\n"
    "\t$Btn.button_up.connect(func() -> void: up_count += 1)\n"
    "func _input(event: InputEvent) -> void:\n"
    "\tif event is InputEventMouseMotion:\n"
    "\t\tmotion_seen = true\n"
)
BUTTON_MAIN_TSCN = (
    "[gd_scene load_steps=2 format=3]\n\n"
    '[ext_resource type="Script" path="res://ui.gd" id="1"]\n\n'
    '[node name="Main" type="Control"]\n'
    "anchor_right = 1.0\n"
    "anchor_bottom = 1.0\n"
    'script = ExtResource("1")\n\n'
    '[node name="Btn" type="Button" parent="."]\n'
    "offset_right = 100.0\n"
    "offset_bottom = 40.0\n"
    'text = "Go"\n'
)

# A focus-driven UI (#652, GDA-DF-034): three Buttons in a VBoxContainer, the
# first focused at startup. One `ui_down` activation (the Down key) must move
# focus exactly ONE button; the focus neighbors come from the container layout.
FOCUS_UI_GD = "extends VBoxContainer\nfunc _ready() -> void:\n\t$A.grab_focus()\n"
FOCUS_MAIN_TSCN = (
    "[gd_scene load_steps=2 format=3]\n\n"
    '[ext_resource type="Script" path="res://ui.gd" id="1"]\n\n'
    '[node name="Main" type="VBoxContainer"]\n'
    "offset_right = 120.0\n"
    "offset_bottom = 120.0\n"
    'script = ExtResource("1")\n\n'
    '[node name="A" type="Button" parent="."]\n'
    'text = "A"\n\n'
    '[node name="B" type="Button" parent="."]\n'
    'text = "B"\n\n'
    '[node name="C" type="Button" parent="."]\n'
    'text = "C"\n'
)

# An action-edge observer (#652): counts each press edge and each release edge
# of `move_right`, so one tap must produce exactly one of each.
TAP_ACTION_PLAYER_GD = (
    "extends Node2D\n"
    "@export var pressed_edges: int = 0\n"
    "@export var released_edges: int = 0\n"
    "func _process(_delta: float) -> void:\n"
    '\tif Input.is_action_just_pressed("move_right"):\n'
    "\t\tpressed_edges += 1\n"
    '\tif Input.is_action_just_released("move_right"):\n'
    "\t\treleased_edges += 1\n"
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")


@pytest.mark.e2e
def test_daemon_serves_input_key_observed_via_game_get(tmp_path, daemon_runtime_dir):
    # The #221 DoD: a real daemon -> engine session -> `input key Right` pushes a key
    # event into the running game, whose `_input` moves the Player, observed via
    # `game get` — end-to-end through the real harness over UDS (ADR-0020).
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(KEY_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(KEY_PLAYER_GD, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

    try:
        assert run("daemon", "start").returncode == 0

        # Baseline: the Player starts at x == 0.
        before = run("game", "get", "/root/Main/Player", "--property", "position")
        assert before.returncode == 0, before.stdout + before.stderr
        before_x = next(
            p
            for p in json.loads(before.stdout)["properties"]
            if p["name"] == "position"
        )["value"][0]

        # Inject a Right key press; the game's _input advances position.x by 10.
        injected = run("input", "key", "Right")
        assert injected.returncode == 0, injected.stdout + injected.stderr
        key_doc = json.loads(injected.stdout)
        assert key_doc["kind"] == "key"
        assert key_doc["key"] == "Right"
        assert key_doc["pressed"] is True

        # Observe the effect via game get (single writer, frame-coherent, ADR-0020).
        after = run("game", "get", "/root/Main/Player", "--property", "position")
        assert after.returncode == 0, after.stdout + after.stderr
        after_x = next(
            p for p in json.loads(after.stdout)["properties"] if p["name"] == "position"
        )["value"][0]
        assert after_x == before_x + 10.0
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_serves_input_mouse_click_observed_via_game_get(
    tmp_path, daemon_runtime_dir
):
    # The mouse leg of the #221 DoD: a real daemon -> engine session ->
    # `input mouse-click <x> <y>` (post-flatten two-token name) pushes an
    # InputEventMouseButton through the real `push_input` viewport path into the
    # running game's `_input`, which snaps the Player to the click position —
    # observed via `game get` (ADR-0020).
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MOUSE_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(MOUSE_PLAYER_GD, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

    try:
        assert run("daemon", "start").returncode == 0

        # Baseline: the Player starts at the origin.
        before = run("game", "get", "/root/Main/Player", "--property", "position")
        assert before.returncode == 0, before.stdout + before.stderr
        before_pos = next(
            p
            for p in json.loads(before.stdout)["properties"]
            if p["name"] == "position"
        )["value"]
        assert before_pos == [0.0, 0.0]

        # Inject a LEFT click at (123, 45); the game's _input snaps position there.
        injected = run("input", "mouse-click", "123", "45")
        assert injected.returncode == 0, injected.stdout + injected.stderr
        click_doc = json.loads(injected.stdout)
        assert click_doc["kind"] == "mouse_click"
        assert click_doc["position"] == [123.0, 45.0]
        assert click_doc["button"] == "left"

        # Observe the effect via game get (single writer, frame-coherent, ADR-0020).
        after = run("game", "get", "/root/Main/Player", "--property", "position")
        assert after.returncode == 0, after.stdout + after.stderr
        after_pos = next(
            p for p in json.loads(after.stdout)["properties"] if p["name"] == "position"
        )["value"]
        assert after_pos == [123.0, 45.0]
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_mouse_input_reports_event_position_when_tracked_mouse_position_is_stale(
    tmp_path, daemon_runtime_dir
):
    # #462: in the default daemon session, Godot accepts the injected event position
    # but does not expose a reliable seam for updating the engine-tracked mouse
    # position. Pin that limitation so the documented workaround remains true.
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(TRACKED_MOUSE_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(TRACKED_MOUSE_PLAYER_GD, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

    def player_property(name: str):
        got = run("game", "get", "/root/Main/Player", "--property", name)
        assert got.returncode == 0, got.stdout + got.stderr
        return json.loads(got.stdout)["properties"][0]["value"]

    def assert_event_position_with_stale_tracked_mouse(
        kind: str, expected: list[float], relative: list[float]
    ) -> None:
        assert player_property("last_event_type") == kind
        assert player_property("last_event_position") == expected
        assert player_property("last_event_relative") == relative
        assert player_property("last_global_mouse_position") == [0.0, 0.0]
        assert player_property("last_viewport_mouse_position") == [0.0, 0.0]

    try:
        assert run("daemon", "start").returncode == 0

        click = run("input", "mouse-click", "123", "45")
        assert click.returncode == 0, click.stdout + click.stderr
        assert_event_position_with_stale_tracked_mouse(
            "click", [123.0, 45.0], [0.0, 0.0]
        )

        move = run("input", "mouse-move", "50", "60")
        assert move.returncode == 0, move.stdout + move.stderr
        assert_event_position_with_stale_tracked_mouse(
            "move", [50.0, 60.0], [-73.0, 15.0]
        )

        events = json.dumps([{"type": "mouse_move", "x": 77, "y": 88, "frame": 0}])
        seq = run("input", "sequence", "--events", events)
        assert seq.returncode == 0, seq.stdout + seq.stderr
        assert_event_position_with_stale_tracked_mouse(
            "move", [77.0, 88.0], [27.0, 28.0]
        )
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_input_sequence_drags_mouse_with_held_button_mask(tmp_path, daemon_runtime_dir):
    # #461: a press -> move(s) -> release gesture stays inside one `input sequence`
    # RPC. The game reads event.position and event.button_mask, not tracked mouse
    # position, because #462 documents the tracked-position limitation.
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(DRAG_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(DRAG_PLAYER_GD, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

    def player_property(name: str):
        got = run("game", "get", "/root/Main/Player", "--property", name)
        assert got.returncode == 0, got.stdout + got.stderr
        return json.loads(got.stdout)["properties"][0]["value"]

    events = json.dumps(
        [
            {"type": "mouse_button", "x": 10, "y": 10, "pressed": True, "frame": 0},
            {"type": "mouse_move", "x": 40, "y": 20, "frame": 1},
            {"type": "mouse_move", "x": 70, "y": 50, "frame": 2},
            {"type": "mouse_button", "x": 70, "y": 50, "release": True, "frame": 3},
        ]
    )

    try:
        assert run("daemon", "start").returncode == 0

        seq = run("input", "sequence", "--events", events)
        assert seq.returncode == 0, seq.stdout + seq.stderr
        seq_doc = json.loads(seq.stdout)
        assert seq_doc["kind"] == "sequence"
        assert seq_doc["events"] == 4
        assert seq_doc["frames"] == 4

        assert player_property("position") == [70.0, 50.0]
        assert player_property("motion_with_left_mask") is True
        assert player_property("dragging") is False
        assert player_property("release_seen") is True
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_serves_input_action_observed_via_game_get(tmp_path, daemon_runtime_dir):
    # `input action move_right` presses an action the running InputMap declares; the
    # Player polls it each frame and advances. The press is held across frames until
    # released, so position.x increases — observed via game get.
    (tmp_path / "project.godot").write_text(ACTION_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(ACTION_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(ACTION_PLAYER_GD, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

    try:
        assert run("daemon", "start").returncode == 0

        before = run("game", "get", "/root/Main/Player", "--property", "position")
        assert before.returncode == 0, before.stdout + before.stderr
        before_x = next(
            p
            for p in json.loads(before.stdout)["properties"]
            if p["name"] == "position"
        )["value"][0]

        # Press the action; the Player polls is_action_pressed each frame and moves.
        pressed = run("input", "action", "move_right")
        assert pressed.returncode == 0, pressed.stdout + pressed.stderr
        assert json.loads(pressed.stdout)["action"] == "move_right"
        assert json.loads(pressed.stdout)["pressed"] is True

        # The action stays pressed across subsequent live ops within the session, so
        # by the time we read back the Player has advanced.
        after = run("game", "get", "/root/Main/Player", "--property", "position")
        assert after.returncode == 0, after.stdout + after.stderr
        after_x = next(
            p for p in json.loads(after.stdout)["properties"] if p["name"] == "position"
        )["value"][0]
        assert after_x > before_x

        # Release the action so it no longer fires.
        released = run("input", "action", "move_right", "--release")
        assert released.returncode == 0, released.stdout + released.stderr
        assert json.loads(released.stdout)["pressed"] is False
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_add_input_action_makes_the_action_immediately_driveable(
    tmp_path, daemon_runtime_dir
):
    # Issue #380's acceptance criterion: an action registered HEADLESSLY by
    # `gda project add-input-action` is immediately driveable by `gda input action`
    # in a live session. The fixture project declares NO [input] section — the
    # action exists only because add-input-action persisted it. Ordering matters:
    # the InputMap loads from project.godot at engine launch, so the headless add
    # runs BEFORE `daemon start`.
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(ACTION_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(ACTION_PLAYER_GD, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

    # Register the action headlessly FIRST — before any engine session exists.
    added = run("project", "add-input-action", "move_right", "--key", "Right")
    assert added.returncode == 0, added.stdout + added.stderr
    assert json.loads(added.stdout)["name"] == "move_right"

    try:
        assert run("daemon", "start").returncode == 0

        before = run("game", "get", "/root/Main/Player", "--property", "position")
        assert before.returncode == 0, before.stdout + before.stderr
        before_x = next(
            p
            for p in json.loads(before.stdout)["properties"]
            if p["name"] == "position"
        )["value"][0]

        # The freshly-registered action is in the running InputMap: pressing it
        # moves the Player (which polls is_action_pressed each frame).
        pressed = run("input", "action", "move_right")
        assert pressed.returncode == 0, pressed.stdout + pressed.stderr
        assert json.loads(pressed.stdout)["pressed"] is True

        after = run("game", "get", "/root/Main/Player", "--property", "position")
        assert after.returncode == 0, after.stdout + after.stderr
        after_x = next(
            p for p in json.loads(after.stdout)["properties"] if p["name"] == "position"
        )["value"][0]
        assert after_x > before_x

        released = run("input", "action", "move_right", "--release")
        assert released.returncode == 0, released.stdout + released.stderr
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_daemon_serves_input_sequence_across_frames(tmp_path, daemon_runtime_dir):
    # `input sequence` applies multiple key events across frames via the time-windowed
    # multi-frame base (#223), returned as ONE blocking result. Three Right presses at
    # frames 0/1/2 each move the Player by 10, so position.x advances by 30 over the
    # window — observed via game get.
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(KEY_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(KEY_PLAYER_GD, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

    events = json.dumps(
        [
            {"type": "key", "key": "Right", "frame": 0},
            {"type": "key", "key": "Right", "frame": 1},
            {"type": "key", "key": "Right", "frame": 2},
        ]
    )

    try:
        assert run("daemon", "start").returncode == 0

        before = run("game", "get", "/root/Main/Player", "--property", "position")
        assert before.returncode == 0, before.stdout + before.stderr
        before_x = next(
            p
            for p in json.loads(before.stdout)["properties"]
            if p["name"] == "position"
        )["value"][0]

        # The whole sequence returns as one blocking result: 3 events over 3 frames.
        seq = run("input", "sequence", "--events", events)
        assert seq.returncode == 0, seq.stdout + seq.stderr
        seq_doc = json.loads(seq.stdout)
        assert seq_doc["kind"] == "sequence"
        assert seq_doc["events"] == 3
        assert seq_doc["frames"] == 3

        after = run("game", "get", "/root/Main/Player", "--property", "position")
        assert after.returncode == 0, after.stdout + after.stderr
        after_x = next(
            p for p in json.loads(after.stdout)["properties"] if p["name"] == "position"
        )["value"][0]
        # Each of the 3 Right presses advances position.x by 10.
        assert after_x == before_x + 30.0
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_input_sequence_physics_frame_hold_matches_predicted_displacement(
    tmp_path, daemon_runtime_dir
):
    # #391: `physics_frame` offsets are driven by Godot's physics clock, not the
    # harness/process clock. Holding `move_right` for N physics frames should move a
    # player that integrates in _physics_process by speed * (N / physics_fps), without
    # first measuring an idle/process-to-physics ratio.
    (tmp_path / "project.godot").write_text(
        PHYSICS_ACTION_PROJECT_GODOT, encoding="utf-8"
    )
    (tmp_path / "main.tscn").write_text(ACTION_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(PHYSICS_ACTION_PLAYER_GD, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

    hold_frames = 12
    physics_fps = 60
    speed = 120.0
    expected_delta = speed * (hold_frames / physics_fps)
    tolerance = 0.1
    events = json.dumps(
        [
            {
                "type": "action",
                "action": "move_right",
                "physics_frame": 0,
            },
            {
                "type": "action",
                "action": "move_right",
                "release": True,
                "physics_frame": hold_frames,
            },
        ]
    )

    try:
        assert run("daemon", "start").returncode == 0

        before = run("game", "get", "/root/Main/Player", "--property", "position")
        assert before.returncode == 0, before.stdout + before.stderr
        before_x = next(
            p
            for p in json.loads(before.stdout)["properties"]
            if p["name"] == "position"
        )["value"][0]

        seq = run("input", "sequence", "--events", events)
        assert seq.returncode == 0, seq.stdout + seq.stderr
        seq_doc = json.loads(seq.stdout)
        assert seq_doc["clock"] == "physics"
        assert seq_doc["events"] == 2
        # Includes the release tick: press at 0, release at N => N physics frames held.
        assert seq_doc["frames"] == hold_frames + 1

        after = run("game", "get", "/root/Main/Player", "--property", "position")
        assert after.returncode == 0, after.stdout + after.stderr
        after_x = next(
            p for p in json.loads(after.stdout)["properties"] if p["name"] == "position"
        )["value"][0]

        actual_delta = after_x - before_x
        assert abs(actual_delta - expected_delta) <= tolerance, (
            f"expected {expected_delta} +/- {tolerance}, got {actual_delta}"
        )
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_input_action_unknown_action_reports_live_unknown_action(
    tmp_path, daemon_runtime_dir
):
    # An action absent from the running InputMap is the typed harness op-error,
    # relayed through the daemon (exit-0 sentinel) and mapped by classify_live.
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(KEY_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(KEY_PLAYER_GD, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

    from gda.exit_codes import EXIT_LIVE

    try:
        assert run("daemon", "start").returncode == 0

        missing = run("input", "action", "no_such_action")
        assert missing.returncode == EXIT_LIVE, missing.stdout + missing.stderr
        assert json.loads(missing.stdout)["error"]["code"] == "live_unknown_action"
    finally:
        run("daemon", "stop")


def _button_project(tmp_path):
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(BUTTON_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "ui.gd").write_text(BUTTON_UI_GD, encoding="utf-8")


def _property_value(gda, node, name):
    """One property's projected value, read live off the running game."""
    got = gda("game", "get", node, "--property", name)
    assert got.returncode == 0, got.stdout + got.stderr
    return next(p for p in json.loads(got.stdout)["properties"] if p["name"] == name)[
        "value"
    ]


@pytest.mark.e2e
def test_mouse_click_performs_the_complete_activation_gesture(
    tmp_path, daemon_runtime_dir
):
    # The #652 DoD (GDA-DF-004): `input mouse-click` on a standard enabled
    # Button emits `pressed` — the whole move/press/release gesture, not a bare
    # press that leaves the button held down forever. Repeated clicks keep
    # activating, because each gesture releases what it pressed.
    _button_project(tmp_path)
    gda = Gda(tmp_path, json_output=True)

    try:
        assert gda("daemon", "start").returncode == 0

        first = gda("input", "mouse-click", "50", "20")
        assert first.returncode == 0, first.stdout + first.stderr
        doc = json.loads(first.stdout)
        # The structured gesture evidence: the three phases at their frames, each
        # naming the route it took into the game (#838).
        assert doc["phases"] == [
            {"frame": 0, "phase": "move", "injection_route": "viewport_event"},
            {"frame": 1, "phase": "press", "injection_route": "viewport_event"},
            {"frame": 2, "phase": "release", "injection_route": "viewport_event"},
        ]

        # The Button observed the COMPLETE activation: down, up, and `pressed`.
        assert _property_value(gda, "/root/Main", "pressed_count") == 1
        assert _property_value(gda, "/root/Main", "down_count") == 1
        assert _property_value(gda, "/root/Main", "up_count") == 1
        # The gesture included the initial move (GDA-DF-004's "initial move").
        assert _property_value(gda, "/root/Main", "motion_seen") is True

        second = gda("input", "mouse-click", "50", "20")
        assert second.returncode == 0, second.stdout + second.stderr
        assert _property_value(gda, "/root/Main", "pressed_count") == 2
        assert _property_value(gda, "/root/Main", "up_count") == 2
    finally:
        gda("daemon", "stop")


@pytest.mark.e2e
def test_two_clicks_leave_diag_errors_empty(tmp_path, daemon_runtime_dir):
    # The #647 defect mechanism, pinned where every environment can run it: two
    # successful clicks in a (headless) session, then `diag errors` must be
    # EMPTY — not merely free of one known message — so a consumer can use an
    # empty result as clean runtime evidence after a multi-click playtest.
    _button_project(tmp_path)
    gda = Gda(tmp_path, json_output=True)

    try:
        assert gda("daemon", "start").returncode == 0

        assert gda("input", "mouse-click", "50", "20").returncode == 0
        assert gda("input", "mouse-click", "50", "20").returncode == 0

        diag = gda("diag", "errors")
        assert diag.returncode == 0, diag.stdout + diag.stderr
        assert json.loads(diag.stdout)["errors"] == []
    finally:
        gda("daemon", "stop")


@pytest.mark.e2e
@pytest.mark.usefixtures("windowed_host")
@pytest.mark.xdist_group("windowed")  # shares the host display (#818)
def test_two_windowed_clicks_leave_diag_errors_empty(tmp_path, daemon_runtime_dir):
    # The exact #647 reproduction: a WINDOWED daemon session, two successful
    # clicks, an empty `diag errors`. The windowed path also carries the
    # OS-driven mouse enter/exit branch of the harness's signal mirror, which
    # the headless twin cannot exercise. Gated on a real display
    # (tests.support.require_windowed_host); a capability refusal skips, a
    # confined run fails loudly (#345/#667).
    _button_project(tmp_path)
    gda = Gda(tmp_path, json_output=True)

    try:
        assert_windowed_ok(gda("daemon", "start", "--windowed"))

        assert_windowed_ok(gda("input", "mouse-click", "50", "20"))
        assert_windowed_ok(gda("input", "mouse-click", "50", "20"))

        diag = assert_windowed_ok(gda("diag", "errors"))
        assert json.loads(diag.stdout)["errors"] == []
    finally:
        gda("daemon", "stop")


@pytest.mark.e2e
def test_sequence_mouse_click_event_activates_a_button(tmp_path, daemon_runtime_dir):
    # A sequence `mouse_click` event is a WHOLE click at one clock offset
    # (#652): the harness pushes the press and the release on the same frame,
    # which fully activates a default Button.
    _button_project(tmp_path)
    gda = Gda(tmp_path, json_output=True)

    try:
        assert gda("daemon", "start").returncode == 0

        injected = gda(
            "input",
            "sequence",
            "--events",
            '[{"type": "mouse_click", "x": 50, "y": 20}]',
        )
        assert injected.returncode == 0, injected.stdout + injected.stderr

        assert _property_value(gda, "/root/Main", "pressed_count") == 1
        assert _property_value(gda, "/root/Main", "up_count") == 1
    finally:
        gda("daemon", "stop")


@pytest.mark.e2e
def test_tap_advances_a_focus_driven_ui_exactly_once_repeatably(
    tmp_path, daemon_runtime_dir
):
    # The #652 tap DoD (GDA-DF-034): one key tap advances a focus-driven UI
    # exactly ONE step, and does so repeatably — the press and the release land
    # on separate process frames, and only the press navigates.
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(FOCUS_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "ui.gd").write_text(FOCUS_UI_GD, encoding="utf-8")
    gda = Gda(tmp_path, json_output=True)

    try:
        assert gda("daemon", "start").returncode == 0

        first = gda("input", "tap", "--key", "Down")
        assert first.returncode == 0, first.stdout + first.stderr
        doc = json.loads(first.stdout)
        assert doc["phases"] == [
            {"frame": 0, "phase": "press", "injection_route": "viewport_event"},
            {"frame": 2, "phase": "release", "injection_route": "viewport_event"},
        ]
        # Exactly one step: A -> B, evidenced by the op's own focus read-back.
        assert doc["focus_before"] == "/root/Main/A", doc
        assert doc["focus_after"] == "/root/Main/B", doc

        second = gda("input", "tap", "--key", "Down")
        assert second.returncode == 0, second.stdout + second.stderr
        doc = json.loads(second.stdout)
        # Repeatably: the next tap advances exactly one more step, B -> C.
        assert doc["focus_before"] == "/root/Main/B", doc
        assert doc["focus_after"] == "/root/Main/C", doc
    finally:
        gda("daemon", "stop")


@pytest.mark.e2e
def test_tap_action_produces_exactly_one_press_and_release_edge(
    tmp_path, daemon_runtime_dir
):
    # The action leg of the tap (#652): one tap of an InputMap action produces
    # exactly one press edge and one release edge, observed by the game's own
    # is_action_just_pressed / is_action_just_released polling.
    (tmp_path / "project.godot").write_text(ACTION_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(ACTION_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(TAP_ACTION_PLAYER_GD, encoding="utf-8")
    gda = Gda(tmp_path, json_output=True)

    try:
        assert gda("daemon", "start").returncode == 0

        first = gda("input", "tap", "--action", "move_right")
        assert first.returncode == 0, first.stdout + first.stderr
        doc = json.loads(first.stdout)
        assert doc["action"] == "move_right"
        assert doc["key"] is None

        node = "/root/Main/Player"
        assert _property_value(gda, node, "pressed_edges") == 1
        assert _property_value(gda, node, "released_edges") == 1

        second = gda("input", "tap", "--action", "move_right")
        assert second.returncode == 0, second.stdout + second.stderr
        assert _property_value(gda, node, "pressed_edges") == 2
        assert _property_value(gda, node, "released_edges") == 2
    finally:
        gda("daemon", "stop")


@pytest.mark.e2e
def test_input_results_name_the_injection_route_against_a_live_session(
    tmp_path, daemon_runtime_dir
):
    # The #838 live regression: against a REAL engine session, each injected form
    # reports the route it actually took — a key event pushed through the root
    # viewport, an action driven as polled state, and a tap holding an action
    # reporting that route on every phase. The routes are what the two dogfooding
    # rounds could not see (GDA-DF-048, GDA-DF-075), so they are asserted where the
    # daemon, the harness and the engine are all real.
    (tmp_path / "project.godot").write_text(ACTION_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(ACTION_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(TAP_ACTION_PLAYER_GD, encoding="utf-8")
    gda = Gda(tmp_path, json_output=True)

    try:
        assert gda("daemon", "start").returncode == 0

        key = gda("input", "key", "Right")
        assert key.returncode == 0, key.stdout + key.stderr
        assert json.loads(key.stdout)["injection_route"] == "viewport_event"

        action = gda("input", "action", "move_right")
        assert action.returncode == 0, action.stdout + action.stderr
        assert json.loads(action.stdout)["injection_route"] == "action_state"
        released = gda("input", "action", "move_right", "--release")
        assert released.returncode == 0, released.stdout + released.stderr

        tap = gda("input", "tap", "--action", "move_right")
        assert tap.returncode == 0, tap.stdout + tap.stderr
        tap_doc = json.loads(tap.stdout)
        assert [phase["injection_route"] for phase in tap_doc["phases"]] == [
            "action_state",
            "action_state",
        ]
        # The tap really did drive the action it named the route for: the game's
        # own polling saw its edges. Two of each by now — the standalone press and
        # release above are the first pair, the tap is the second.
        node = "/root/Main/Player"
        assert _property_value(gda, node, "pressed_edges") == 2
        assert _property_value(gda, node, "released_edges") == 2

        sequence = gda(
            "input",
            "sequence",
            "--events",
            json.dumps(
                [
                    {"type": "action", "action": "move_right", "frame": 0},
                    {"type": "key", "key": "Right", "frame": 1},
                ]
            ),
        )
        assert sequence.returncode == 0, sequence.stdout + sequence.stderr
        assert json.loads(sequence.stdout)["phases"] == [
            {"frame": 0, "phase": "press", "injection_route": "action_state"},
            {"frame": 1, "phase": "press", "injection_route": "viewport_event"},
        ]
    finally:
        gda("daemon", "stop")


@pytest.mark.e2e
def test_input_key_without_a_daemon_reports_daemon_not_running(tmp_path):
    # The attach-or-fail path through the real DaemonRunner + discovery, no daemon.
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")

    from gda.exit_codes import EXIT_LIVE

    proc = Gda(tmp_path, godot=None)(
        "input",
        "key",
        "Right",
        "--json",
        extra_env={"XDG_RUNTIME_DIR": str(tmp_path / "run")},
    )

    assert proc.returncode == EXIT_LIVE, proc.stdout + proc.stderr
    error = json.loads(proc.stdout)["error"]
    assert error["code"] == "daemon_not_running"
    assert "gda daemon start" in error["message"]
