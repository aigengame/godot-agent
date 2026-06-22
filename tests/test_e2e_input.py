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
import shutil
import subprocess

import pytest

from gda.binary import resolve_godot_binary

from .conftest import project_godot

GODOT = resolve_godot_binary()

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
    '[gd_scene load_steps=2 format=3]\n\n'
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
    '[gd_scene load_steps=2 format=3]\n\n'
    '[ext_resource type="Script" path="res://player.gd" id="1"]\n\n'
    '[node name="Main" type="Node2D"]\n\n'
    '[node name="Player" type="Node2D" parent="."]\n'
    'script = ExtResource("1")\n'
)

# A Player that polls a `move_right` input action each frame: while the action is
# pressed it advances, so an injected `input action move_right` (a press held until
# released) moves the node. The action is registered in project.godot's input map.
ACTION_PLAYER_GD = (
    "extends Node2D\n"
    "func _process(_delta: float) -> void:\n"
    "\tif Input.is_action_pressed(\"move_right\"):\n"
    "\t\tposition.x += 1.0\n"
)
ACTION_MAIN_TSCN = (
    '[gd_scene load_steps=2 format=3]\n\n'
    '[ext_resource type="Script" path="res://player.gd" id="1"]\n\n'
    '[node name="Main" type="Node2D"]\n\n'
    '[node name="Player" type="Node2D" parent="."]\n'
    'script = ExtResource("1")\n'
)

PROJECT_GODOT = project_godot(extra='run/main_scene="res://main.tscn"')

# A project.godot whose [input] section declares `move_right` so the running
# InputMap has the action `input action move_right` drives (InputMap.has_action).
ACTION_PROJECT_GODOT = project_godot(
    extra=(
        'run/main_scene="res://main.tscn"\n\n'
        "[input]\n\n"
        'move_right={\n'
        '"deadzone": 0.5,\n'
        '"events": []\n'
        "}\n"
    )
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")


@pytest.mark.e2e
def test_daemon_serves_input_key_observed_via_game_get(tmp_path, daemon_runtime_dir):
    # The #221 DoD: a real daemon -> engine session -> `input key Right` pushes a key
    # event into the running game, whose `_input` moves the Player, observed via
    # `game get` — end-to-end through the real harness over UDS (ADR-0020).
    gda = shutil.which("gda")
    assert gda, "the `gda` console script is not on PATH"
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(KEY_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(KEY_PLAYER_GD, encoding="utf-8")

    env = {**os.environ}

    def run(*args):
        return subprocess.run(
            [gda, *args, "--project", str(tmp_path), "--godot", str(GODOT), "--json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=90,
        )

    try:
        assert run("daemon", "start").returncode == 0

        # Baseline: the Player starts at x == 0.
        before = run("game", "get", "/root/Main/Player", "--property", "position")
        assert before.returncode == 0, before.stdout + before.stderr
        before_x = next(
            p for p in json.loads(before.stdout)["properties"] if p["name"] == "position"
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
def test_daemon_serves_input_mouse_click_observed_via_game_get(tmp_path, daemon_runtime_dir):
    # The mouse leg of the #221 DoD: a real daemon -> engine session ->
    # `input mouse-click <x> <y>` (post-flatten two-token name) pushes an
    # InputEventMouseButton through the real `push_input` viewport path into the
    # running game's `_input`, which snaps the Player to the click position —
    # observed via `game get` (ADR-0020).
    gda = shutil.which("gda")
    assert gda, "the `gda` console script is not on PATH"
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MOUSE_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(MOUSE_PLAYER_GD, encoding="utf-8")

    env = {**os.environ}

    def run(*args):
        return subprocess.run(
            [gda, *args, "--project", str(tmp_path), "--godot", str(GODOT), "--json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=90,
        )

    try:
        assert run("daemon", "start").returncode == 0

        # Baseline: the Player starts at the origin.
        before = run("game", "get", "/root/Main/Player", "--property", "position")
        assert before.returncode == 0, before.stdout + before.stderr
        before_pos = next(
            p for p in json.loads(before.stdout)["properties"] if p["name"] == "position"
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
def test_daemon_serves_input_action_observed_via_game_get(tmp_path, daemon_runtime_dir):
    # `input action move_right` presses an action the running InputMap declares; the
    # Player polls it each frame and advances. The press is held across frames until
    # released, so position.x increases — observed via game get.
    gda = shutil.which("gda")
    assert gda, "the `gda` console script is not on PATH"
    (tmp_path / "project.godot").write_text(ACTION_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(ACTION_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(ACTION_PLAYER_GD, encoding="utf-8")

    env = {**os.environ}

    def run(*args):
        return subprocess.run(
            [gda, *args, "--project", str(tmp_path), "--godot", str(GODOT), "--json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=90,
        )

    try:
        assert run("daemon", "start").returncode == 0

        before = run("game", "get", "/root/Main/Player", "--property", "position")
        assert before.returncode == 0, before.stdout + before.stderr
        before_x = next(
            p for p in json.loads(before.stdout)["properties"] if p["name"] == "position"
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
def test_daemon_serves_input_sequence_across_frames(tmp_path, daemon_runtime_dir):
    # `input sequence` applies multiple key events across frames via the time-windowed
    # multi-frame base (#223), returned as ONE blocking result. Three Right presses at
    # frames 0/1/2 each move the Player by 10, so position.x advances by 30 over the
    # window — observed via game get.
    gda = shutil.which("gda")
    assert gda, "the `gda` console script is not on PATH"
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(KEY_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(KEY_PLAYER_GD, encoding="utf-8")

    env = {**os.environ}

    def run(*args):
        return subprocess.run(
            [gda, *args, "--project", str(tmp_path), "--godot", str(GODOT), "--json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=90,
        )

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
            p for p in json.loads(before.stdout)["properties"] if p["name"] == "position"
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
def test_input_action_unknown_action_reports_live_unknown_action(tmp_path, daemon_runtime_dir):
    # An action absent from the running InputMap is the typed harness op-error,
    # relayed through the daemon (exit-0 sentinel) and mapped by classify_live.
    gda = shutil.which("gda")
    assert gda, "the `gda` console script is not on PATH"
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(KEY_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(KEY_PLAYER_GD, encoding="utf-8")

    env = {**os.environ}

    def run(*args):
        return subprocess.run(
            [gda, *args, "--project", str(tmp_path), "--godot", str(GODOT), "--json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=90,
        )

    from gda.exit_codes import EXIT_LIVE

    try:
        assert run("daemon", "start").returncode == 0

        missing = run("input", "action", "no_such_action")
        assert missing.returncode == EXIT_LIVE, missing.stdout + missing.stderr
        assert json.loads(missing.stdout)["error"]["code"] == "live_unknown_action"
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_input_key_without_a_daemon_reports_daemon_not_running(tmp_path):
    # The attach-or-fail path through the real DaemonRunner + discovery, no daemon.
    gda = shutil.which("gda")
    assert gda, "the `gda` console script is not on PATH"
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")

    from gda.exit_codes import EXIT_LIVE

    env = {**os.environ, "XDG_RUNTIME_DIR": str(tmp_path / "run")}
    proc = subprocess.run(
        [gda, "input", "key", "Right", "--project", str(tmp_path), "--json"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert proc.returncode == EXIT_LIVE, proc.stdout + proc.stderr
    error = json.loads(proc.stdout)["error"]
    assert error["code"] == "daemon_not_running"
    assert "gda daemon start" in error["message"]
