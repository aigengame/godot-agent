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
import shutil
import subprocess
import sys

import pytest

from gda.binary import resolve_godot_binary

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

# A WINDOWED engine session needs a real DisplayServer. macOS always has one (Aqua);
# headless Linux CI does not — the release/scheduled e2e runners are headless, where
# launching a windowed session fails with `engine_session_not_running`. So the
# windowed-capture tests skip there unless run under a virtual framebuffer
# (`xvfb-run`, which sets DISPLAY); the headless-guard and no-daemon screen tests
# below still run. The check is forward-compatible: wire Xvfb into CI and DISPLAY is
# set, so these run rather than skip. (PR #248 follow-up — the release-gate fix that
# unblocked PyPI publishing; the macOS run already exercises the real windowed path.)
_needs_display = pytest.mark.skipif(
    sys.platform.startswith("linux") and not os.environ.get("DISPLAY"),
    reason="windowed capture needs a DisplayServer; headless Linux has none — run "
    "under xvfb-run, which sets DISPLAY",
)


def _scaffold(tmp_path):
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")


def _runner(gda, tmp_path):
    env = {**os.environ}

    def run(*args):
        return subprocess.run(
            [gda, *args, "--project", str(tmp_path), "--godot", str(GODOT), "--json"],
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
    gda = shutil.which("gda")
    assert gda, "the `gda` console script is not on PATH"
    _scaffold(tmp_path)
    run = _runner(gda, tmp_path)
    out = tmp_path / "shot.png"

    try:
        started = run("daemon", "start", "--windowed")
        assert started.returncode == 0, started.stdout + started.stderr
        assert json.loads(started.stdout)["windowed"] is True

        cap = run("screen", "capture", "--output", str(out))
        assert cap.returncode == 0, cap.stdout + cap.stderr
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
    gda = shutil.which("gda")
    assert gda, "the `gda` console script is not on PATH"
    _scaffold(tmp_path)
    run = _runner(gda, tmp_path)
    out = tmp_path / "shot.png"

    try:
        assert run("daemon", "start", "--windowed").returncode == 0
        cap = run("screen", "capture", "--inline", "--output", str(out))
        assert cap.returncode == 0, cap.stdout + cap.stderr
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
    gda = shutil.which("gda")
    assert gda, "the `gda` console script is not on PATH"
    _scaffold(tmp_path)
    run = _runner(gda, tmp_path)
    out_dir = tmp_path / "frames"

    try:
        assert run("daemon", "start", "--windowed").returncode == 0
        frames = run("screen", "frames", "--frames", "3", "--output-dir", str(out_dir))
        assert frames.returncode == 0, frames.stdout + frames.stderr
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
def test_headless_session_reports_live_display_unavailable(tmp_path, daemon_runtime_dir):
    # A default (HEADLESS) daemon session has the dummy DisplayServer; a `screen
    # capture` there is refused with the typed live_display_unavailable (the
    # self-revealing remediation: start --windowed). No file is written.
    gda = shutil.which("gda")
    assert gda, "the `gda` console script is not on PATH"
    _scaffold(tmp_path)
    run = _runner(gda, tmp_path)
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
    gda = shutil.which("gda")
    assert gda, "the `gda` console script is not on PATH"
    _scaffold(tmp_path)
    run = _runner(gda, tmp_path)

    cap = run("screen", "capture", "--output", str(tmp_path / "shot.png"))

    assert cap.returncode == 6, cap.stdout + cap.stderr  # EXIT_LIVE
    error = json.loads(cap.stdout)["error"]
    assert error["code"] == "daemon_not_running"
    assert "gda daemon start" in error["message"]
