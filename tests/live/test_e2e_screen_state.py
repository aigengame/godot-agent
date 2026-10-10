"""Rendered pixels and owned recovery through the public CLI."""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.screen_support import (
    assert_capture_receipt,
    assert_screen_pixels,
    write_screen_project,
)
from tests.support import GODOT, Gda, ObservedWindowsProcess

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.usefixtures("windowed_host"),
    pytest.mark.xdist_group("windowed"),
]


def test_screen_captures_known_pixels_and_receipts_for_every_frame(
    tmp_path, daemon_runtime_dir
):
    run = Gda(write_screen_project(tmp_path), json_output=True)
    try:
        run.json("daemon", "start", "--windowed")
        first = run.json("screen", "capture", "--output", str(tmp_path / "first.png"))
        session = run.json("daemon", "status")["session_id"]
        assert_screen_pixels(first)
        assert_capture_receipt(first, session)
        frames = run.json(
            "screen",
            "frames",
            "--frames",
            "3",
            "--settle-frames",
            "2",
            "--output-dir",
            str(tmp_path / "frames"),
        )
        assert frames["count"] == 3 and frames["settle_frames"] == 2
        for frame in frames["frames"]:
            assert_screen_pixels(frame)
            assert_capture_receipt(frame, session)
        receipts = [f["receipt"] for f in frames["frames"]]
        assert [r["engine_frame"] for r in receipts] == list(
            range(receipts[0]["engine_frame"], receipts[0]["engine_frame"] + 3)
        )
        assert [r["render_frame"] for r in receipts] == sorted(
            r["render_frame"] for r in receipts
        )
        summary_dir = tmp_path / "summary"
        summary = run.json(
            "screen",
            "frames",
            "--frames",
            "3",
            "--summary",
            "--output-dir",
            str(summary_dir),
        )["summary"]
        for index, key in ((0, "first_receipt"), (2, "last_receipt")):
            assert_capture_receipt(
                {
                    "path": str(summary_dir / f"frame_{index:04d}.png"),
                    "receipt": summary[key],
                },
                session,
            )
    finally:
        run("daemon", "stop")


@pytest.mark.skipif(
    sys.platform != "win32", reason="Windows capture deadline and owned retirement"
)
@pytest.mark.parametrize("failure", ["timeout", "disconnect"])
def test_capture_failure_retires_only_its_session_and_keeps_an_unrelated_window(
    tmp_path, daemon_runtime_dir, failure
):
    project = tmp_path / "project"
    project.mkdir()
    write_screen_project(project)
    scene = (
        (project / "main.tscn")
        .read_text(encoding="utf-8")
        .replace(
            "[gd_scene format=3]",
            '[gd_scene load_steps=2 format=3]\n[ext_resource type="Script" path="res://main.gd" id="1"]',
        )
        .replace(
            '[node name="Main" type="Node2D"]',
            '[node name="Main" type="Node2D"]\nscript = ExtResource("1")',
        )
    )
    (project / "main.tscn").write_text(scene, encoding="utf-8")
    (project / "main.gd").write_text(
        """extends Node2D
var failure := ""
var probe: int:
    get:
        if failure == "timeout":
            while true:
                OS.delay_msec(20)
        elif failure == "disconnect":
            get_tree().quit()
        return 0
func _ready():
    Engine.max_fps = 30
    var file = FileAccess.open("res://engine-pid.txt", FileAccess.WRITE)
    file.store_string(str(OS.get_process_id()))
    file.close()
""",
        encoding="utf-8",
    )
    other = tmp_path / "unrelated"
    other.mkdir()
    write_screen_project(other)
    binary = Path(GODOT).with_name(Path(GODOT).name.replace("_console.exe", ".exe"))
    assert binary.is_file(), binary
    outsider = subprocess.Popen(
        [str(binary), "--path", str(other)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    run = Gda(project, json_output=True)
    engine = None
    try:
        run.json("daemon", "start", "--windowed")
        run.json("daemon", "wait-ready")
        before = run.json("daemon", "status")
        engine = ObservedWindowsProcess(
            int((project / "engine-pid.txt").read_text(encoding="utf-8"))
        )
        run.json(
            "game",
            "set",
            "/root/Main",
            "--property",
            "failure",
            "--value",
            failure,
        )
        out = project / "failed.png"
        start = time.monotonic()
        failed = run(
            "screen",
            "capture",
            "--output",
            str(out),
            "--await-node",
            "/root/Main",
            "--await-property",
            "probe",
            "--await-value",
            "1",
            "--await-frames",
            "5",
        )
        elapsed = time.monotonic() - start
        assert failed.returncode == 6, failed.stdout + failed.stderr
        expected = "live_timeout" if failure == "timeout" else "engine_disconnected"
        assert json.loads(failed.stdout)["error"]["code"] == expected
        assert not out.exists()
        if failure == "timeout":
            assert 29 <= elapsed < 45, elapsed
        else:
            assert elapsed < 30, elapsed
        assert run.json("daemon", "status")["session_id"] == before["session_id"]
        recovered = run.json(
            "screen", "capture", "--output", str(project / "recovered.png")
        )
        engine.exited()
        after = run.json("daemon", "status")
        assert after["pid"] == before["pid"]
        assert after["session_id"] != before["session_id"]
        assert_screen_pixels(recovered)
        assert_capture_receipt(recovered, after["session_id"])
        assert outsider.poll() is None
        run.json("daemon", "stop")
        assert outsider.poll() is None
    finally:
        run("daemon", "stop")
        if engine is not None:
            engine.close()
        outsider.terminate()
        outsider.wait(timeout=5)
