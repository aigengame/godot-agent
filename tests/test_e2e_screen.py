"""S (e2e): `gda screen` live viewport capture through the real gda-daemon loop (#222).

The Step-6 proof for screen: a real `gda daemon start --windowed` (real detached
daemon, real harness install, a WINDOWED engine session — no `--headless`) ->
`gda screen capture` writes a real PNG of the RUNNING game's viewport, and
`gda screen frames --frames 3` writes a 3-frame sequence collected by the harness's
time-windowed multi-frame base. The headless-session guard is proven by starting
the daemon WITHOUT `--windowed` and asserting the typed `live_display_unavailable`;
the no-daemon path asserts `daemon_not_running`.

CI / headless hosts: a windowed session needs a real DisplayServer. On Linux CI
(no physical display) run this module under a virtual framebuffer, e.g.::

    xvfb-run -a uv run pytest tests/test_e2e_screen.py -m e2e

macOS has a real display, so it runs directly. Run the e2e tier SERIALLY (a shared
windowed session is heavier than a headless one) and NOT under a fresh empty HOME
(Godot first-run). The `daemon_runtime_dir` fixture keeps the daemon's UDS path
within the `sun_path` limit.
"""

import json
import os
import subprocess

import pytest

from gda.binary import resolve_godot_binary
from tests.support import GDA_CMD, assert_windowed_ok

from .conftest import project_godot

GODOT = resolve_godot_binary()

# The PNG magic the written capture must start with — the proof it is a real,
# decodable image (not an empty/placeholder buffer).
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# A main scene with a visible ColorRect so the windowed viewport renders non-empty
# content; the capture asserts dims > 0, the frames test asserts each file decodes.
# File logging stays disabled via project_godot (#180).
MAIN_TSCN = (
    "[gd_scene format=3]\n\n"
    '[node name="Main" type="Node2D"]\n\n'
    '[node name="Rect" type="ColorRect" parent="."]\n'
    "offset_right = 200.0\n"
    "offset_bottom = 150.0\n"
    "color = Color(0.2, 0.6, 0.9, 1)\n"
)
PROJECT_GODOT = project_godot(extra='run/main_scene="res://main.tscn"')

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")

# A WINDOWED engine session needs a usable host DisplayServer. This is NOT a
# "macOS always has one" assumption: headless macOS (SSH / CI / sandbox) has no
# on-console window-server session even though `launchctl managername` reports
# "Aqua", and a windowed Godot aborts in AppKit registration there — so the gate is
# the shared `gda.display.windowed_unavailable()` helper (#345), which probes
# CGSessionCopyCurrentDictionary on macOS and $DISPLAY/$WAYLAND_DISPLAY on Linux,
# skipping BEFORE spawning (and crashing) Godot. The headless-guard and no-daemon
# screen tests below still run. Forward-compatible: wire Xvfb into CI (DISPLAY set)
# and these run rather than skip.
# A fixture, not a skipif: the reaction differs by verdict (#667). A host that
# CANNOT show a window skips; a run that is merely CONFINED fails loudly, because
# skipping there greens the suite with the rendered acceptance unexecuted. The
# policy has one owner — `tests.support.require_windowed_host` — shared with the
# post-start race path and the daemon suite.
_needs_display = pytest.mark.usefixtures("windowed_host")


def _scaffold(tmp_path):
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")


def _runner(gda, tmp_path):
    env = {**os.environ}

    def run(*args):
        return subprocess.run(
            [*gda, *args, "--project", str(tmp_path), "--godot", str(GODOT), "--json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )

    return run


@pytest.mark.e2e
@_needs_display
def test_windowed_daemon_captures_a_single_viewport_frame(tmp_path, daemon_runtime_dir):
    # `daemon start --windowed` -> a WINDOWED engine session -> `screen capture`
    # writes a real PNG of the running viewport (magic + dims > 0).
    _scaffold(tmp_path)
    run = _runner(GDA_CMD, tmp_path)
    out = tmp_path / "shot.png"

    try:
        # A refusal on the start / first-live-op / capture branches is routed through
        # the shared display policy before the ordinary assertion: a capability
        # verdict skips (as the game's tiers do), a permission verdict fails loudly.
        started = assert_windowed_ok(run("daemon", "start", "--windowed"))
        assert json.loads(started.stdout)["windowed"] is True

        cap = assert_windowed_ok(run("screen", "capture", "--output", str(out)))
        doc = json.loads(cap.stdout)
        assert doc["path"] == str(out)
        assert doc["width"] > 0 and doc["height"] > 0
        assert doc["format"] == "png"
        # The written file is a real PNG (the magic the spec requires) with bytes.
        assert out.exists()
        data = out.read_bytes()
        assert data.startswith(PNG_MAGIC)
        assert doc["bytes"] == len(data) > 0
        # No --inline -> no base64 embedded (the default small reply).
        assert doc.get("inline") is None
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
@_needs_display
def test_windowed_daemon_inline_embeds_the_base64(tmp_path, daemon_runtime_dir):
    # `screen capture --inline` additionally embeds the base64 PNG in the reply.
    _scaffold(tmp_path)
    run = _runner(GDA_CMD, tmp_path)
    out = tmp_path / "shot.png"

    try:
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        cap = assert_windowed_ok(
            run("screen", "capture", "--inline", "--output", str(out))
        )
        doc = json.loads(cap.stdout)
        import base64

        assert base64.b64decode(doc["inline"]).startswith(PNG_MAGIC)
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
@_needs_display
def test_windowed_daemon_captures_a_frame_window(tmp_path, daemon_runtime_dir):
    # `screen frames --frames 3`: the time-windowed multi-frame base (#223) collects
    # 3 viewport frames over the engine session and returns them in one blocking
    # call; the CLI writes one PNG per frame (path-only).
    _scaffold(tmp_path)
    run = _runner(GDA_CMD, tmp_path)
    out_dir = tmp_path / "frames"

    try:
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        frames = assert_windowed_ok(
            run("screen", "frames", "--frames", "3", "--output-dir", str(out_dir))
        )
        doc = json.loads(frames.stdout)
        assert doc["count"] == 3
        assert len(doc["frames"]) == 3
        for frame in doc["frames"]:
            assert frame["width"] > 0 and frame["height"] > 0
            assert frame["format"] == "png"
            path = frame["path"]
            assert path.startswith(str(out_dir))
            data = open(path, "rb").read()
            assert data.startswith(PNG_MAGIC)
            assert frame["bytes"] == len(data) > 0
            assert "inline" not in frame  # path-only sequence
        # Distinct files, one per frame.
        assert len({f["path"] for f in doc["frames"]}) == 3
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_headless_session_reports_live_display_unavailable(
    tmp_path, daemon_runtime_dir
):
    # A default (HEADLESS) daemon session has the dummy DisplayServer; a `screen
    # capture` there is refused with the typed live_display_unavailable (the
    # self-revealing remediation: start --windowed). No file is written.
    _scaffold(tmp_path)
    run = _runner(GDA_CMD, tmp_path)
    out = tmp_path / "shot.png"

    try:
        # NOTE: no --windowed -> the session is launched --headless (the default).
        assert run("daemon", "start").returncode == 0
        cap = run("screen", "capture", "--output", str(out))
        assert cap.returncode == 6, cap.stdout + cap.stderr  # EXIT_LIVE
        error = json.loads(cap.stdout)["error"]
        assert error["code"] == "live_display_unavailable"
        assert error["category"] == "live"
        assert not out.exists()  # a refused capture writes nothing
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_screen_capture_with_no_daemon_reports_daemon_not_running(
    tmp_path, daemon_runtime_dir
):
    # No daemon started: `screen capture` is the attach-or-fail daemon_not_running
    # (ADR-0017), the same typed error every live op reports with no daemon.
    _scaffold(tmp_path)
    run = _runner(GDA_CMD, tmp_path)

    cap = run("screen", "capture", "--output", str(tmp_path / "shot.png"))

    assert cap.returncode == 6, cap.stdout + cap.stderr  # EXIT_LIVE
    error = json.loads(cap.stdout)["error"]
    assert error["code"] == "daemon_not_running"
    assert "gda daemon start" in error["message"]


# --- the --await-* predicate capture (#661) ------------------------------------

# A scene with two transient states, each too short for separate input + capture
# round trips (GDA-DF-023): `phase` cycles 0..7 once per process frame (any given
# value holds for exactly ONE frame, recurring every 8), and `flash` runs 4->0
# only after a key press (a ~4-frame input-triggered transient).
PREDICATE_GD = (
    "extends Node2D\n"
    "var tick := 0\n"
    "var phase := 0\n"
    "var flash := 0\n"
    "func _process(_delta: float) -> void:\n"
    "\ttick += 1\n"
    "\tphase = tick % 8\n"
    "\tif flash > 0:\n"
    "\t\tflash -= 1\n"
    "func _input(event: InputEvent) -> void:\n"
    "\tif event is InputEventKey and event.pressed:\n"
    "\t\tflash = 4\n"
)
PREDICATE_TSCN = (
    "[gd_scene load_steps=2 format=3]\n\n"
    '[ext_resource type="Script" path="res://main.gd" id="1"]\n\n'
    '[node name="Main" type="Node2D"]\n'
    'script = ExtResource("1")\n\n'
    '[node name="Rect" type="ColorRect" parent="."]\n'
    "offset_right = 200.0\n"
    "offset_bottom = 150.0\n"
    "color = Color(0.9, 0.4, 0.2, 1)\n"
)


def _predicate_scaffold(tmp_path):
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.gd").write_text(PREDICATE_GD, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(PREDICATE_TSCN, encoding="utf-8")


@pytest.mark.e2e
@_needs_display
def test_await_predicate_captures_a_one_frame_transient_repeatedly(
    tmp_path, daemon_runtime_dir
):
    # AC1 + AC4 (#661): a declared transient state — `phase == 5` holds for
    # exactly one process frame per 8-frame cycle — is captured deterministically,
    # with no game-side freeze fixture, on REPEATED runs in one session.
    _predicate_scaffold(tmp_path)
    run = _runner(GDA_CMD, tmp_path)

    try:
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        for attempt in range(3):
            out = tmp_path / f"shot{attempt}.png"
            cap = assert_windowed_ok(
                run(
                    "screen",
                    "capture",
                    "--output",
                    str(out),
                    "--await-node",
                    "/root/Main",
                    "--await-property",
                    "phase",
                    "--await-value",
                    "5",
                )
            )
            doc = json.loads(cap.stdout)
            assert doc["predicate"]["observed"] == 5, doc
            assert doc["predicate"]["frames_waited"] < 60
            assert doc["predicate"]["engine_frame"] > 0
            assert out.read_bytes().startswith(PNG_MAGIC)
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
@_needs_display
def test_await_predicate_that_never_holds_is_the_typed_error(
    tmp_path, daemon_runtime_dir
):
    # AC2 (#661): a predicate that never holds fails with live_predicate_unmet
    # after the declared frame bound — in ~a third of a second, not a timeout —
    # and writes no file.
    _predicate_scaffold(tmp_path)
    run = _runner(GDA_CMD, tmp_path)
    out = tmp_path / "never.png"

    try:
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        cap = run(
            "screen",
            "capture",
            "--output",
            str(out),
            "--await-node",
            "/root/Main",
            "--await-property",
            "phase",
            "--await-value",
            "99",
            "--await-frames",
            "20",
        )
        assert cap.returncode != 0
        doc = json.loads(cap.stdout)
        assert doc["error"]["code"] == "live_predicate_unmet"
        assert "did not hold within 20 frames" in doc["error"]["message"]
        assert "last observed" in doc["error"]["message"]
        assert not out.exists()
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
@_needs_display
def test_await_events_capture_an_input_triggered_transient(
    tmp_path, daemon_runtime_dir
):
    # The atomic input-and-capture form (#661, GDA-DF-023): the key press and the
    # predicate ride ONE window, so the ~4-frame `flash` transient the press
    # triggers cannot be missed by a second CLI round trip. `flash == 1` holds
    # for exactly one frame after the injected press.
    _predicate_scaffold(tmp_path)
    run = _runner(GDA_CMD, tmp_path)
    out = tmp_path / "flash.png"

    try:
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        cap = assert_windowed_ok(
            run(
                "screen",
                "capture",
                "--output",
                str(out),
                "--await-node",
                "/root/Main",
                "--await-property",
                "flash",
                "--await-value",
                "1",
                "--await-events",
                '[{"type": "key", "key": "Right", "frame": 0}]',
            )
        )
        doc = json.loads(cap.stdout)
        assert doc["predicate"]["observed"] == 1, doc
        assert doc["predicate"]["frames_waited"] >= 1
        assert out.read_bytes().startswith(PNG_MAGIC)
    finally:
        run("daemon", "stop")
