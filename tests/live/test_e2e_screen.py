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

    xvfb-run -a uv run pytest tests/live/test_e2e_screen.py -m e2e

macOS has a real display, so it runs directly. Run the e2e tier SERIALLY (a shared
windowed session is heavier than a headless one) and NOT under a fresh empty HOME
(Godot first-run). The `daemon_runtime_dir` fixture keeps the daemon's UDS path
within the `sun_path` limit.
"""

import json
import os

import pytest

from tests.support import Gda, assert_windowed_ok

from tests.conftest import LIVE_PROJECT_GODOT, project_godot

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

pytestmark = [
    pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX"),
    # The windowed captures share the host display: one worker under xdist's
    # `--dist loadgroup`, so two windowed sessions never compete for it (#818).
    pytest.mark.xdist_group("windowed"),
]

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
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")


@pytest.mark.e2e
@_needs_display
def test_windowed_daemon_captures_a_single_viewport_frame(tmp_path, daemon_runtime_dir):
    # `daemon start --windowed` -> a WINDOWED engine session -> `screen capture`
    # writes a real PNG of the running viewport (magic + dims > 0).
    _scaffold(tmp_path)
    run = Gda(tmp_path, json_output=True, timeout=120)
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
        # The evidence receipt (#660): the real harness binds the image to the
        # session, the launched scene (uid-less: gda-authored, ADR-0036), the
        # engine frame, and the exact bytes on disk.
        import hashlib

        receipt = doc["receipt"]
        assert receipt["scene_path"] == "res://main.tscn"
        assert receipt["scene_uid"] is None
        assert receipt["engine_frame"] >= 0
        assert receipt["observed"] is None
        assert receipt["sha256"] == hashlib.sha256(data).hexdigest()
        # The same identity is readable on `daemon status` (the correlation the
        # issue requires), and stays stable across captures in one session.
        status = json.loads(run("daemon", "status").stdout)
        assert status["session_id"] == receipt["session_id"]
        assert len(receipt["session_id"]) == 16
        again = assert_windowed_ok(
            run("screen", "capture", "--output", str(tmp_path / "shot2.png"))
        )
        assert (
            json.loads(again.stdout)["receipt"]["session_id"] == receipt["session_id"]
        )
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
@_needs_display
def test_windowed_daemon_inline_embeds_the_base64(tmp_path, daemon_runtime_dir):
    # `screen capture --inline` additionally embeds the base64 PNG in the reply.
    _scaffold(tmp_path)
    run = Gda(tmp_path, json_output=True, timeout=120)
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
@pytest.mark.parametrize(
    "header",
    [
        '[gd_scene format=3 uid="uid://c4qn8xbhw6kmv"]',
        # Whitespace around `=` is a legal, engine-preserved header form the
        # parse must accept too (#746 review Spec 2).
        '[gd_scene format=3 uid = "uid://c4qn8xbhw6kmv"]',
    ],
    ids=["plain", "spaced-equals"],
)
def test_capture_receipt_reports_the_scene_uid_the_project_provides(
    tmp_path, daemon_runtime_dir, header
):
    # The uid arm of the receipt (#660, ADR-0036 read-uid asymmetry): a scene
    # whose FILE HEADER carries a uid (as every editor-authored scene does)
    # reports it — read from the header itself, no `.godot/` cache needed. The
    # uid-less arm is the single-frame test above.
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(
        f'{header}\n\n[node name="Main" type="Node2D"]\n',
        encoding="utf-8",
    )
    run = Gda(tmp_path, json_output=True, timeout=120)
    out = tmp_path / "shot.png"

    try:
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        cap = assert_windowed_ok(run("screen", "capture", "--output", str(out)))
        receipt = json.loads(cap.stdout)["receipt"]
        assert receipt["scene_path"] == "res://main.tscn"
        assert receipt["scene_uid"] == "uid://c4qn8xbhw6kmv"
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
@_needs_display
def test_capture_receipt_names_the_launched_scene_after_a_scene_switch(
    tmp_path, daemon_runtime_dir
):
    # #660's authoritative semantics (#746 review Spec 1): the receipt's scene
    # fields are the LAUNCHED scene — a session launch fact — so a game that
    # switches scenes mid-session still receipts under the scene it launched.
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.gd").write_text(
        "extends Node2D\n"
        "var _frames := 0\n"
        "func _process(_delta: float) -> void:\n"
        "\t_frames += 1\n"
        "\tif _frames == 5:\n"
        '\t\tget_tree().change_scene_to_file("res://other.tscn")\n',
        encoding="utf-8",
    )
    (tmp_path / "main.tscn").write_text(
        "[gd_scene load_steps=2 format=3]\n\n"
        '[ext_resource type="Script" path="res://main.gd" id="1"]\n\n'
        '[node name="Main" type="Node2D"]\n'
        'script = ExtResource("1")\n',
        encoding="utf-8",
    )
    (tmp_path / "other.tscn").write_text(
        '[gd_scene format=3]\n\n[node name="Other" type="Node2D"]\n',
        encoding="utf-8",
    )
    run = Gda(tmp_path, json_output=True, timeout=120)
    out = tmp_path / "shot.png"

    try:
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        # Establish the session, then give the game time to switch scenes.
        ready = run("daemon", "wait-ready")
        assert ready.returncode == 0, ready.stdout + ready.stderr
        tree = run("game", "tree")  # a round trip AFTER the switch frame
        assert '"Other"' in tree.stdout, tree.stdout
        cap = assert_windowed_ok(run("screen", "capture", "--output", str(out)))
        receipt = json.loads(cap.stdout)["receipt"]
        # The game now presents res://other.tscn; the receipt still names the
        # launched scene — the session identity the issue binds evidence to.
        assert receipt["scene_path"] == "res://main.tscn"
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
@_needs_display
def test_windowed_daemon_captures_a_frame_window(tmp_path, daemon_runtime_dir):
    # `screen frames --frames 3`: the time-windowed multi-frame base (#223) collects
    # 3 viewport frames over the engine session and returns them in one blocking
    # call; the CLI writes one PNG per frame (path-only).
    _scaffold(tmp_path)
    run = Gda(tmp_path, json_output=True, timeout=120)
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
@_needs_display
def test_ninety_frame_capture_completes_with_a_structured_envelope(
    tmp_path, daemon_runtime_dir
):
    # #665 AC1/AC3 (GDA-DF-021): a capture at the dogfooding failure scale must
    # END in a structured completion result (or the registered live_timeout —
    # never silence). PROVEN by reproduction: gda's own stack loses nothing —
    # the exact release under test (gda 0.8.0, harness v6) and the current head
    # both complete 90 frames x 3.6 MB (≈327 MB of PNG bytes, ≈436 MB
    # base64-expanded in the single IPC reply) with the full envelope on real
    # Godot 4.6.3; the original observation (all PNGs present, no final JSON)
    # itself shows the reply reached the CLI, which writes the files from it.
    # The residual loss's leading BOUNDED HYPOTHESIS — not reproduced (the
    # original caller's automation was not re-run) — is a caller-side
    # output-handling limit, suggested by the failure boundary tracking the
    # result line's size (~226 B/frame entry: 30/36/48 ≤ ~11 KB good, 90 ≈
    # 20 KB lost); those observations vary count and line length together, so
    # they establish correlation, not the specific cap. The --summary envelope
    # below stays well under any such limit either way.
    _scaffold(tmp_path)
    run = Gda(tmp_path, json_output=True, timeout=120)
    out_dir = tmp_path / "frames"

    try:
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        full = assert_windowed_ok(
            run("screen", "frames", "--frames", "90", "--output-dir", str(out_dir))
        )
        doc = json.loads(full.stdout)
        assert doc["count"] == 90
        assert len(doc["frames"]) == 90
        assert len(list(out_dir.glob("frame_*.png"))) == 90

        # The compact form at the same scale: every frame still written, and the
        # completion envelope no longer grows with the frame count.
        summary_dir = tmp_path / "frames-summary"
        compact = assert_windowed_ok(
            run(
                "screen",
                "frames",
                "--frames",
                "90",
                "--summary",
                "--output-dir",
                str(summary_dir),
            )
        )
        summary_doc = json.loads(compact.stdout)
        assert summary_doc["count"] == 90
        assert summary_doc["frames"] is None
        aggregate = summary_doc["summary"]
        assert aggregate["pattern"] == "frame_%04d.png"
        assert aggregate["width"] > 0 and aggregate["height"] > 0
        written = sorted(summary_dir.glob("frame_*.png"))
        assert len(written) == 90
        assert aggregate["total_bytes"] == sum(f.stat().st_size for f in written)
        # The compact envelope is bounded: an order of magnitude under the
        # per-frame form's line at the same count.
        assert len(compact.stdout) < len(full.stdout) / 10
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
    run = Gda(tmp_path, json_output=True, timeout=120)
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
    run = Gda(tmp_path, json_output=True, timeout=120)

    cap = run("screen", "capture", "--output", str(tmp_path / "shot.png"))

    assert cap.returncode == 6, cap.stdout + cap.stderr  # EXIT_LIVE
    error = json.loads(cap.stdout)["error"]
    assert error["code"] == "daemon_not_running"
    assert "gda daemon start" in error["message"]


# --- the --await-* predicate capture (#661) ------------------------------------

# A scene with transient states too short for separate input + capture round
# trips (GDA-DF-023): `phase` cycles 0..7 once per process frame (any value
# holds for exactly ONE frame, recurring every 8) and the rect is RED on the
# `phase == 5` frame alone, so the written PNG proves WHICH frame's
# presentation was captured (#743 review, Spec 3). `flash` runs 4->0 only
# after a key press (an input-triggered ~4-frame transient). The `key_down` /
# `btn_down` / `act_down` flags expose held input state to `game get` (the
# release-drain proofs, ARC-743-001), and `probe` counts its own getter runs
# (the metadata-only-resolution proof, ARC-743-002).
PREDICATE_GD = (
    "extends Node2D\n"
    "var tick := 0\n"
    "var phase := 0\n"
    "var flash := 0\n"
    "var key_down := false\n"
    "var btn_down := false\n"
    "var act_down := false\n"
    "var probe_reads := 0\n"
    "var hit := false\n"
    "var probe: int:\n"
    "\tget:\n"
    "\t\tprobe_reads += 1\n"
    "\t\treturn phase\n"
    "func _process(_delta: float) -> void:\n"
    "\ttick += 1\n"
    "\tphase = tick % 8\n"
    "\tif flash > 0:\n"
    "\t\tflash -= 1\n"
    '\tact_down = Input.is_action_pressed("qa_probe")\n'
    "\tvar rect: ColorRect = $Rect\n"
    "\trect.color = Color(1, 0, 0, 1) if phase == 5 else Color(0.2, 0.6, 0.9, 1)\n"
    "func _input(event: InputEvent) -> void:\n"
    "\tif event is InputEventKey:\n"
    "\t\tkey_down = event.pressed\n"
    "\t\tif event.pressed:\n"
    "\t\t\tflash = 4\n"
    "\t\t\thit = true\n"
    "\t\t\tvar marker: ColorRect = $Marker\n"
    "\t\t\tmarker.color = Color(0, 1, 0, 1)\n"
    "\tif event is InputEventMouseButton:\n"
    "\t\tbtn_down = event.pressed\n"
)
PREDICATE_TSCN = (
    "[gd_scene load_steps=2 format=3]\n\n"
    '[ext_resource type="Script" path="res://main.gd" id="1"]\n\n'
    '[node name="Main" type="Node2D"]\n'
    'script = ExtResource("1")\n\n'
    '[node name="Rect" type="ColorRect" parent="."]\n'
    "offset_right = 200.0\n"
    "offset_bottom = 150.0\n"
    "color = Color(0.2, 0.6, 0.9, 1)\n\n"
    '[node name="Marker" type="ColorRect" parent="."]\n'
    "offset_left = 250.0\n"
    "offset_right = 320.0\n"
    "offset_bottom = 150.0\n"
    "color = Color(0.2, 0.6, 0.9, 1)\n"
)
PREDICATE_PROJECT = project_godot(
    extra=(
        'run/main_scene="res://main.tscn"\n\n'
        "[input]\n\n"
        'qa_probe={\n"deadzone": 0.5,\n"events": []\n}\n'
    )
)


def _predicate_scaffold(tmp_path):
    (tmp_path / "project.godot").write_text(PREDICATE_PROJECT, encoding="utf-8")
    (tmp_path / "main.gd").write_text(PREDICATE_GD, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(PREDICATE_TSCN, encoding="utf-8")


def _png_pixel(path, px, py):
    """Decode one pixel of an 8-bit RGB/RGBA PNG (all five row filters)."""
    import struct
    import zlib

    data = path.read_bytes()
    assert data[:8] == PNG_MAGIC
    pos = 8
    meta = None
    idat = b""
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        tag = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            w, h, depth, color = struct.unpack(">IIBB", chunk[:10])
            assert depth == 8 and color in (2, 6), (depth, color)
            meta = (w, h, 3 if color == 2 else 4)
        elif tag == b"IDAT":
            idat += chunk
    assert meta is not None, "PNG carries no IHDR"
    w, h, ch = meta
    raw = zlib.decompress(idat)
    stride = w * ch
    prev = bytearray(stride)
    at = 0
    for row in range(h):
        f = raw[at]
        line = bytearray(raw[at + 1 : at + 1 + stride])
        at += 1 + stride
        for i in range(stride):
            a = line[i - ch] if i >= ch else 0
            b = prev[i]
            c = prev[i - ch] if i >= ch else 0
            if f == 1:
                line[i] = (line[i] + a) & 0xFF
            elif f == 2:
                line[i] = (line[i] + b) & 0xFF
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 0xFF
            elif f == 4:
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        if row == py:
            return tuple(line[px * ch : px * ch + 3])
        prev = line
    raise AssertionError("pixel row out of range")


def _assert_red(path):
    r, g, b = _png_pixel(path, 50, 50)
    assert r > 200 and b < 80, (r, g, b, str(path))


def _game_get(run, prop):
    got = run("game", "get", "/root/Main", "--property", prop)
    assert got.returncode == 0, got.stdout + got.stderr
    return json.loads(got.stdout)["properties"][0]["value"]


def _await_capture(run, out, prop, value, *extra):
    return run(
        "screen",
        "capture",
        "--output",
        str(out),
        "--await-node",
        "/root/Main",
        "--await-property",
        prop,
        "--await-value",
        value,
        *extra,
    )


@pytest.mark.e2e
@_needs_display
def test_await_predicate_captures_the_matched_frames_pixels_repeatedly(
    tmp_path, daemon_runtime_dir
):
    # AC1 + AC4 (#661) + #743 Spec 3: `phase == 5` holds for exactly one process
    # frame per 8-frame cycle and the rect is RED on that frame alone; the
    # decoded PNG must show the MATCHED frame's presentation — not the frame
    # before it — on REPEATED captures in one session.
    _predicate_scaffold(tmp_path)
    run = Gda(tmp_path, json_output=True, timeout=120)

    try:
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        for attempt in range(3):
            out = tmp_path / f"shot{attempt}.png"
            cap = assert_windowed_ok(_await_capture(run, out, "phase", "5"))
            doc = json.loads(cap.stdout)
            assert doc["predicate"]["observed"] == 5, doc
            assert doc["predicate"]["frames_waited"] < 60
            assert doc["predicate"]["engine_frame"] > 0
            # The receipt echoes the predicate evidence at the SAME frame (#660):
            # the real harness stamps both in one tick, and the CLI's receipt
            # gate has already verified the agreement before writing the file.
            assert doc["receipt"]["observed"] == 5
            assert doc["receipt"]["engine_frame"] == doc["predicate"]["engine_frame"]
            _assert_red(out)
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
    run = Gda(tmp_path, json_output=True, timeout=120)
    out = tmp_path / "never.png"

    try:
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        cap = _await_capture(run, out, "phase", "99", "--await-frames", "20")
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
    # The atomic input-and-capture form (#661, GDA-DF-023): the key press and
    # the predicate ride ONE window, so the ~4-frame `flash` transient the
    # press triggers cannot be missed by a second CLI round trip; the declared
    # release fires before the reply, so no key is left held.
    _predicate_scaffold(tmp_path)
    run = Gda(tmp_path, json_output=True, timeout=120)
    out = tmp_path / "flash.png"

    try:
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        cap = assert_windowed_ok(
            _await_capture(
                run,
                out,
                "flash",
                "1",
                "--await-events",
                '[{"type": "key", "key": "Right", "frame": 0},'
                ' {"type": "key", "key": "Right", "released": true, "frame": 3}]',
            )
        )
        doc = json.loads(cap.stdout)
        assert doc["predicate"]["observed"] == 1, doc
        assert doc["predicate"]["frames_waited"] >= 1
        assert out.read_bytes().startswith(PNG_MAGIC)
        assert _game_get(run, "key_down") is False
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
@_needs_display
def test_early_match_still_fires_every_scheduled_release(tmp_path, daemon_runtime_dir):
    # #743 review ARC-743-001: the predicate matches BEFORE the scheduled
    # release, yet the reply must wait for every accepted event — a key, a
    # mouse-button phase, and an action are each verified released afterwards,
    # so no input state leaks into later live operations.
    _predicate_scaffold(tmp_path)
    run = Gda(tmp_path, json_output=True, timeout=120)

    cases = [
        (
            "key_down",
            '[{"type": "key", "key": "Right", "frame": 0},'
            ' {"type": "key", "key": "Right", "released": true, "frame": 5}]',
        ),
        (
            "btn_down",
            '[{"type": "mouse_button", "x": 60, "y": 60, "pressed": true, "frame": 0},'
            ' {"type": "mouse_button", "x": 60, "y": 60, "release": true, "frame": 5}]',
        ),
        (
            "act_down",
            '[{"type": "action", "action": "qa_probe", "frame": 0},'
            ' {"type": "action", "action": "qa_probe", "release": true, "frame": 5}]',
        ),
    ]
    try:
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        for index, (flag, events) in enumerate(cases):
            out = tmp_path / f"held{index}.png"
            cap = assert_windowed_ok(
                _await_capture(run, out, flag, "true", "--await-events", events)
            )
            doc = json.loads(cap.stdout)
            # Matched while held (well before the frame-5 release)...
            assert doc["predicate"]["observed"] is True, doc
            assert doc["predicate"]["frames_waited"] < 5
            # ...yet the release still fired before the reply.
            assert _game_get(run, flag) is False, flag
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
@_needs_display
def test_unmet_predicate_error_path_still_fires_every_event(
    tmp_path, daemon_runtime_dir
):
    # #743 review ARC-743-001, the ERROR path: the window ends in
    # live_predicate_unmet, but the declared press/release pair still ran — no
    # held key survives the failure. The release sits BEYOND the ceiling
    # (offset 12 > frames 10): an out-of-window offset is accepted (exact
    # schema/model parity, #743 second re-review) and still fires during the
    # drain, so the reply arrives only after it.
    _predicate_scaffold(tmp_path)
    run = Gda(tmp_path, json_output=True, timeout=120)
    out = tmp_path / "never.png"

    try:
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        cap = _await_capture(
            run,
            out,
            "phase",
            "99",
            "--await-frames",
            "10",
            "--await-events",
            '[{"type": "key", "key": "Right", "frame": 0},'
            ' {"type": "key", "key": "Right", "released": true, "frame": 12}]',
        )
        assert cap.returncode != 0
        assert json.loads(cap.stdout)["error"]["code"] == "live_predicate_unmet"
        assert not out.exists()
        assert _game_get(run, "key_down") is False
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
@_needs_display
def test_predicate_resolution_never_reads_the_property(tmp_path, daemon_runtime_dir):
    # #743 review ARC-743-002: resolving the property up front is metadata-only,
    # so a scripted getter runs EXACTLY once per sampled frame — frames_waited+1
    # times in total, no pre-read, no re-read at capture.
    _predicate_scaffold(tmp_path)
    run = Gda(tmp_path, json_output=True, timeout=120)
    out = tmp_path / "probe.png"

    try:
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        cap = assert_windowed_ok(_await_capture(run, out, "probe", "5"))
        doc = json.loads(cap.stdout)
        waited = doc["predicate"]["frames_waited"]
        assert _game_get(run, "probe_reads") == waited + 1
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
@_needs_display
def test_input_written_state_is_captured_with_its_own_presentation(
    tmp_path, daemon_runtime_dir
):
    # #743 re-review ARC-743-004 / Spec 1, the same-callback counterexample:
    # one _input callback writes BOTH the property (`hit`) and the visual (the
    # Marker rect turns green). Evaluate-before-inject means the state an event
    # writes is observed one boundary LATER, together with its own
    # presentation — so the decoded pixels show the matched visual.
    _predicate_scaffold(tmp_path)
    run = Gda(tmp_path, json_output=True, timeout=120)

    try:
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        out = tmp_path / "marker.png"
        cap = assert_windowed_ok(
            _await_capture(
                run,
                out,
                "hit",
                "true",
                "--await-events",
                '[{"type": "key", "key": "Right", "frame": 0},'
                ' {"type": "key", "key": "Right", "released": true, "frame": 2}]',
            )
        )
        doc = json.loads(cap.stdout)
        assert doc["predicate"]["observed"] is True, doc
        r, g, b = _png_pixel(out, 260, 50)
        assert g > 200 and r < 80, (r, g, b)
        assert _game_get(run, "key_down") is False
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
@_needs_display
def test_late_event_failure_is_the_reply_and_writes_no_file(
    tmp_path, daemon_runtime_dir
):
    # #743 re-review ARC-743-001 / Spec 2: the predicate matches early, then a
    # scheduled event FAILS — the reply is that typed failure, no file is
    # written, and the later declared release still drains (no held action).
    _predicate_scaffold(tmp_path)
    run = Gda(tmp_path, json_output=True, timeout=120)
    out = tmp_path / "late.png"

    try:
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        cap = _await_capture(
            run,
            out,
            "act_down",
            "true",
            "--await-events",
            '[{"type": "action", "action": "qa_probe", "frame": 0},'
            ' {"type": "action", "action": "no_such_action", "frame": 5},'
            ' {"type": "action", "action": "qa_probe", "release": true, "frame": 6}]',
        )
        assert cap.returncode != 0
        doc = json.loads(cap.stdout)
        assert doc["error"]["code"] == "live_unknown_action"
        assert not out.exists()
        assert _game_get(run, "act_down") is False
    finally:
        run("daemon", "stop")


# --- --settle-frames and the render frame (#847) --------------------------------

# The GDA-DF-065 shape, as a windowed fixture: a TabBar switch gives the body
# page a different minimum size per tab, so the VBoxContainer re-sorts and lays
# out every header sibling again - a title swatch, a title Label, a close Button
# and a close swatch, none of which CHANGES. The swatches are solid Controls, so
# one unchanged Control's pixels can be asserted exactly. `tab_x` / `tab_y` carry
# the live tab-rect centres, so the click targets a tab without hard-coded
# coordinates.
TABBAR_GD = (
    "extends Control\n"
    "var tab := 0\n"
    "var switches := 0\n"
    "var tab_x := [0.0, 0.0, 0.0]\n"
    "var tab_y := 0.0\n"
    "const PAGE_COLORS := [Color(0.9, 0.3, 0.2, 1), Color(0.3, 0.5, 0.9, 1),"
    " Color(0.9, 0.8, 0.2, 1)]\n"
    "func _ready() -> void:\n"
    "\tvar tabs: TabBar = $Root/Tabs\n"
    '\ttabs.add_tab("ALPHA")\n'
    '\ttabs.add_tab("BRAVO")\n'
    '\ttabs.add_tab("CHARLIE")\n'
    "\ttabs.tab_changed.connect(_on_tab_changed)\n"
    "func _process(_delta: float) -> void:\n"
    "\tvar tabs: TabBar = $Root/Tabs\n"
    "\tif tabs.get_tab_count() > 2:\n"
    "\t\ttab_y = tabs.global_position.y + tabs.size.y * 0.5\n"
    "\t\tfor i in 3:\n"
    "\t\t\tvar r := tabs.get_tab_rect(i)\n"
    "\t\t\ttab_x[i] = tabs.global_position.x + r.position.x + r.size.x * 0.5\n"
    "func _on_tab_changed(which: int) -> void:\n"
    "\ttab = which\n"
    "\tswitches += 1\n"
    "\tvar page: ColorRect = $Root/Body/Page\n"
    "\tpage.custom_minimum_size = Vector2(240 + which * 160, 120 + which * 120)\n"
    "\tpage.color = PAGE_COLORS[which]\n"
)
TABBAR_TSCN = (
    "[gd_scene load_steps=2 format=3]\n\n"
    '[ext_resource type="Script" path="res://main.gd" id="1"]\n\n'
    '[node name="Main" type="Control"]\n'
    "anchor_right = 1.0\nanchor_bottom = 1.0\n"
    'script = ExtResource("1")\n\n'
    '[node name="BG" type="ColorRect" parent="."]\n'
    "anchor_right = 1.0\nanchor_bottom = 1.0\n"
    "color = Color(0.05, 0.07, 0.12, 1)\n\n"
    '[node name="Root" type="VBoxContainer" parent="."]\n'
    "anchor_right = 1.0\nanchor_bottom = 1.0\nalignment = 1\n\n"
    '[node name="Header" type="HBoxContainer" parent="Root"]\n\n'
    '[node name="TitleSwatch" type="ColorRect" parent="Root/Header"]\n'
    "custom_minimum_size = Vector2(160, 48)\n"
    "color = Color(0.2, 0.9, 0.3, 1)\n\n"
    '[node name="Title" type="Label" parent="Root/Header"]\n'
    'text = "KUNG FU"\n\n'
    '[node name="Close" type="Button" parent="Root/Header"]\n'
    'text = "CLOSE"\n\n'
    '[node name="CloseSwatch" type="ColorRect" parent="Root/Header"]\n'
    "custom_minimum_size = Vector2(90, 48)\n"
    "color = Color(0.95, 0.35, 0.85, 1)\n\n"
    '[node name="Tabs" type="TabBar" parent="Root"]\n\n'
    '[node name="Body" type="PanelContainer" parent="Root"]\n\n'
    '[node name="Page" type="ColorRect" parent="Root/Body"]\n'
    "custom_minimum_size = Vector2(240, 120)\n"
    "color = Color(0.9, 0.3, 0.2, 1)\n"
)
TABBAR_PROJECT = project_godot(
    extra=(
        'run/main_scene="res://main.tscn"\n\n'
        "[display]\n\n"
        "window/size/viewport_width=1440\n"
        "window/size/viewport_height=900\n"
    )
)
# The declared fill of each solid header Control, as bytes: Godot writes the
# ColorRect's channels straight into the 8-bit PNG (0.2 -> 51, 0.9 -> 229).
SWATCH_RGB = {"TitleSwatch": (51, 229, 77), "CloseSwatch": (242, 89, 217)}
BACKGROUND_RGB = (13, 18, 31)


def _tabbar_scaffold(tmp_path):
    (tmp_path / "project.godot").write_text(TABBAR_PROJECT, encoding="utf-8")
    (tmp_path / "main.gd").write_text(TABBAR_GD, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(TABBAR_TSCN, encoding="utf-8")


def _rect_centre(run, path):
    got = run("game", "rect", path)
    assert got.returncode == 0, got.stdout + got.stderr
    doc = json.loads(got.stdout)
    return (
        int(doc["position"][0] + doc["size"][0] / 2),
        int(doc["position"][1] + doc["size"][1] / 2),
    )


def _assert_close(actual, expected, label):
    assert all(abs(a - e) <= 3 for a, e in zip(actual, expected)), (
        f"{label}: {actual} is not {expected}"
    )


@pytest.mark.e2e
@_needs_display
def test_a_capture_after_a_tab_switch_shows_the_unchanged_controls(
    tmp_path, daemon_runtime_dir
):
    # #847 AC2, the GDA-DF-065 shape: a TabBar switch re-lays-out the header's
    # siblings, and an IMMEDIATE capture must still show them. The assertion is
    # one unchanged Control's pixels - the title swatch keeps its declared fill
    # at the rect `game rect` reports, and is not the background colour the
    # dogfooding report saw in its place. The close swatch rides along as the
    # second Control the report named.
    _tabbar_scaffold(tmp_path)
    run = Gda(tmp_path, json_output=True, timeout=120)

    try:
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        ready = run("daemon", "wait-ready")
        assert ready.returncode == 0, ready.stdout + ready.stderr
        before = _rect_centre(run, "/root/Main/Root/Header/TitleSwatch")
        centres = json.loads(
            run("game", "get", "/root/Main", "--property", "tab_x").stdout
        )["properties"][0]["value"]
        row = json.loads(
            run("game", "get", "/root/Main", "--property", "tab_y").stdout
        )["properties"][0]["value"]

        clicked = run("input", "mouse-click", str(int(centres[2])), str(int(row)))
        assert clicked.returncode == 0, clicked.stdout + clicked.stderr
        out = tmp_path / "after-switch.png"
        cap = assert_windowed_ok(run("screen", "capture", "--output", str(out)))

        switched = json.loads(
            run("game", "get", "/root/Main", "--property", "switches").stdout
        )["properties"][0]["value"]
        assert switched == 1, "the click did not reach the TabBar"
        # The header MOVED (the body page grew), so this is the re-laid-out case
        # the report describes, not a static screen.
        after = _rect_centre(run, "/root/Main/Root/Header/TitleSwatch")
        assert after != before, (before, after)
        for name, rgb in SWATCH_RGB.items():
            x, y = _rect_centre(run, f"/root/Main/Root/Header/{name}")
            pixel = _png_pixel(out, x, y)
            _assert_close(pixel, rgb, name)
            assert pixel != BACKGROUND_RGB
        # And the receipt says which drawn frame those pixels are (#847).
        receipt = json.loads(cap.stdout)["receipt"]
        assert receipt["render_frame"] >= 0
        assert json.loads(cap.stdout)["settle_frames"] == 0
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
@_needs_display
def test_settle_frames_moves_the_gated_capture_by_the_declared_frames(
    tmp_path, daemon_runtime_dir
):
    # #847 AC3 on the real engine, in PIXELS. `phase` cycles 0..7 once per
    # process frame and the rect is RED on the `phase == 5` frame alone, so the
    # image says which frame was read: settle 0 captures the matched frame (red),
    # settle 4 captures four frames later (phase 1, not red), and settle 8 lands
    # a whole cycle on (red again). The predicate report keeps naming the frame
    # it was observed at, while the receipt names the read boundary.
    _predicate_scaffold(tmp_path)
    run = Gda(tmp_path, json_output=True, timeout=120)

    try:
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        for settle, red in ((0, True), (4, False), (8, True)):
            out = tmp_path / f"settle{settle}.png"
            cap = assert_windowed_ok(
                _await_capture(run, out, "phase", "5", "--settle-frames", str(settle))
            )
            doc = json.loads(cap.stdout)
            assert doc["settle_frames"] == settle, doc
            # The predicate evidence is unchanged by the settle.
            assert doc["predicate"]["observed"] == 5, doc
            assert doc["predicate"]["frames_waited"] < 60
            # ...and the read boundary is exactly that frame plus the settle.
            assert (
                doc["receipt"]["engine_frame"]
                == doc["predicate"]["engine_frame"] + settle
            ), doc
            r, g, b = _png_pixel(out, 50, 50)
            assert (r > 200 and b < 80) is red, (settle, r, g, b)
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
@_needs_display
def test_the_receipt_render_frame_tracks_the_frames_the_engine_drew(
    tmp_path, daemon_runtime_dir
):
    # #847 AC4 on the real engine: the receipt carries the drawn-frame counter
    # beside the process-frame one. A running game draws between two captures,
    # so the counter advances; it never runs backwards inside one session, and
    # it is a different quantity from the boundary `engine_frame` names.
    _predicate_scaffold(tmp_path)
    run = Gda(tmp_path, json_output=True, timeout=120)

    try:
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        receipts = []
        for n in range(3):
            cap = assert_windowed_ok(
                run("screen", "capture", "--output", str(tmp_path / f"r{n}.png"))
            )
            receipts.append(json.loads(cap.stdout)["receipt"])
        frames = [r["render_frame"] for r in receipts]
        assert frames == sorted(frames), frames
        assert frames[-1] > frames[0], frames
        # Three round trips over a running game are three different drawn
        # frames. (Different drawn frames need NOT be different bytes: this
        # fixture's visual repeats on an 8-frame cycle, so the hashes may
        # legitimately collide - the implication runs the other way, same
        # render_frame means the same drawn frame.)
        assert len(set(frames)) == 3, frames
        # The drawn counter can never overtake the process counter: the engine
        # draws at most once per process frame, and sometimes not at all.
        assert all(r["engine_frame"] >= r["render_frame"] for r in receipts)
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
@_needs_display
def test_screen_frames_settles_once_before_the_first_frame(
    tmp_path, daemon_runtime_dir
):
    # #847 on `screen frames`: the settle runs ONCE before the first frame, so
    # the sequence still carries exactly `--frames` frames - the settle is not
    # spent out of the frame budget and is not captured.
    _scaffold(tmp_path)
    run = Gda(tmp_path, json_output=True, timeout=120)

    try:
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        for settle in (0, 12):
            out_dir = tmp_path / f"frames{settle}"
            frames = assert_windowed_ok(
                run(
                    "screen",
                    "frames",
                    "--frames",
                    "3",
                    "--settle-frames",
                    str(settle),
                    "--output-dir",
                    str(out_dir),
                )
            )
            doc = json.loads(frames.stdout)
            assert doc["settle_frames"] == settle, doc
            assert doc["count"] == 3
            assert len(doc["frames"]) == 3
            assert len(list(out_dir.glob("frame_*.png"))) == 3
            for frame in doc["frames"]:
                assert open(frame["path"], "rb").read().startswith(PNG_MAGIC)
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_a_settled_capture_on_a_headless_session_is_still_refused(
    tmp_path, daemon_runtime_dir
):
    # The display guard runs BEFORE the settle window opens, so a headless
    # session refuses at once with the same typed code instead of spending the
    # settle frames first and refusing afterwards.
    _scaffold(tmp_path)
    run = Gda(tmp_path, json_output=True, timeout=120)
    out = tmp_path / "shot.png"

    try:
        assert run("daemon", "start").returncode == 0  # no --windowed
        cap = run("screen", "capture", "--settle-frames", "30", "--output", str(out))
        assert cap.returncode == 6, cap.stdout + cap.stderr  # EXIT_LIVE
        assert json.loads(cap.stdout)["error"]["code"] == "live_display_unavailable"
        assert not out.exists()
    finally:
        run("daemon", "stop")


# The settle a PLAIN capture and a PLAIN frames window really run is not
# observable from the reply alone — the harness could report a count it never
# spent. These two tests bracket the operation with the engine's own clock, so a
# harness that skips the wait moves the clock by a round trip instead of by the
# settle (#847 review P2-2). The bracket is self-calibrating: each test first
# measures what a round trip costs in the SAME session and asserts that the
# margin it relies on is real.
SETTLE_E2E_FRAMES = 90


@pytest.mark.e2e
@_needs_display
def test_a_plain_settled_capture_reads_a_later_boundary(tmp_path, daemon_runtime_dir):
    # The observable for a plain `screen capture --settle-frames N`: the read
    # boundary the receipt names moved at least N process frames past the
    # previous capture's, which no round trip alone can do here.
    _predicate_scaffold(tmp_path)
    run = Gda(tmp_path, json_output=True, timeout=120)

    def capture(name, *extra):
        got = assert_windowed_ok(
            run("screen", "capture", "--output", str(tmp_path / name), *extra)
        )
        return json.loads(got.stdout)

    try:
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        first = capture("p0.png")
        second = capture("p1.png")
        settled = capture("p2.png", "--settle-frames", str(SETTLE_E2E_FRAMES))

        round_trip = (
            second["receipt"]["engine_frame"] - first["receipt"]["engine_frame"]
        )
        settled_gap = (
            settled["receipt"]["engine_frame"] - second["receipt"]["engine_frame"]
        )
        # Calibration: the margin this test relies on exists in this session.
        assert 0 < round_trip < SETTLE_E2E_FRAMES, round_trip
        # The claim: the settled read is at least the declared frames later.
        assert settled_gap >= SETTLE_E2E_FRAMES, (settled_gap, round_trip)
        assert first["settle_frames"] == second["settle_frames"] == 0
        assert settled["settle_frames"] == SETTLE_E2E_FRAMES
        # The drawn counter moved with it: this session draws on every process
        # frame (asserted over the unsettled gap first), so it must over the
        # settled one too.
        assert (
            second["receipt"]["render_frame"] - first["receipt"]["render_frame"]
            == round_trip
        ), "the session did not draw on every process frame"
        assert (
            settled["receipt"]["render_frame"] - second["receipt"]["render_frame"]
            == settled_gap
        )
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
@_needs_display
def test_screen_frames_spends_its_settle_on_the_engines_clock(
    tmp_path, daemon_runtime_dir
):
    # `screen frames` carries no receipt, so the bracket is the game's own
    # per-process-frame counter read either side of the window.
    _predicate_scaffold(tmp_path)
    run = Gda(tmp_path, json_output=True, timeout=120)

    def tick():
        return _game_get(run, "tick")

    def window(name, *extra):
        got = assert_windowed_ok(
            run(
                "screen",
                "frames",
                "--frames",
                "2",
                "--output-dir",
                str(tmp_path / name),
                *extra,
            )
        )
        return json.loads(got.stdout)

    try:
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        before = tick()
        plain = window("w0")
        base = tick() - before

        before = tick()
        settled = window("w1", "--settle-frames", str(SETTLE_E2E_FRAMES))
        spent = tick() - before

        assert plain["settle_frames"] == 0
        assert settled["settle_frames"] == SETTLE_E2E_FRAMES
        # Calibration, then the claim: the settled window ran the extra frames.
        assert 0 < base < SETTLE_E2E_FRAMES, base
        assert spent >= SETTLE_E2E_FRAMES + 2, (spent, base)
        # Both windows still captured exactly the frames that were asked for.
        assert plain["count"] == settled["count"] == 2
    finally:
        run("daemon", "stop")
