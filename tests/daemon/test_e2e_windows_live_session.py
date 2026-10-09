"""The bounded first Windows Live session through the public CLI (#1118)."""

import os
import json
import socket
import time
import subprocess
import sys
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.support import GODOT, Gda, ObservedWindowsProcess, runnable_project
from tests.conftest import SCRIPTED_MAIN_TSCN, project_godot
from gda.daemon.protocol import write_frame


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.name != "nt", reason="Windows owned headless session"),
]


def _project(directory):
    project = runnable_project(directory)
    (project / "project.godot").write_text(
        project_godot(extra='run/main_scene="res://main.tscn"'), encoding="utf-8"
    )
    return project


def test_windows_reaches_the_requested_scene_and_keeps_one_session(
    tmp_path,
    daemon_runtime_dir,
):
    project = _project(tmp_path / "project")
    (project / "chosen.tscn").write_text(
        '[gd_scene format=3]\n\n[node name="Chosen" type="Node2D"]\n'
        "position = Vector2(11, 23)\n",
        encoding="utf-8",
    )
    run = Gda(project, json_output=True)
    try:
        run.json("daemon", "start", "--scene", "res://chosen.tscn")
        assert run.json("daemon", "wait-ready", "--timeout", "10")["launched"] is True
        session = run.json("daemon", "status")["session_id"]
        assert isinstance(session, str) and len(session) == 16
        assert run.json("game", "tree")["root"]["name"] == "Chosen"
        value = run.json("game", "get", "/root/Chosen", "--property", "position")
        position = next(
            item for item in value["properties"] if item["name"] == "position"
        )
        assert position["value"] == [11.0, 23.0]
        assert run.json("daemon", "wait-ready")["launched"] is False
        assert run.json("daemon", "status")["session_id"] == session
        assert run.json("daemon", "stop")["stopped"] is True
    finally:
        run("daemon", "stop")


def _read_pids(path):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            time.sleep(0.01)
    raise AssertionError("the fixture did not publish its owned processes")


@pytest.mark.parametrize("binary_kind", ["console", "gui"])
@pytest.mark.parametrize(
    "retirement", ["stop", "daemon-crash", "replacement", "leader-exit", "timeout"]
)
def test_owned_tree_retires_without_touching_an_unrelated_process(
    tmp_path, daemon_runtime_dir, binary_kind, retirement
):
    project = _project(tmp_path / "project")
    (project / "main.tscn").write_text(SCRIPTED_MAIN_TSCN, encoding="utf-8")
    child_file = project / "child.json"
    child_code = (
        "import os,time; from pathlib import Path; "
        f"Path({str(child_file)!r}).write_text(str(os.getpid())); time.sleep(60)"
    )
    (project / "main.gd").write_text(
        "extends Node2D\nfunc _ready():\n"
        f'\tOS.create_process({json.dumps(sys.executable)}, ["-c", {json.dumps(child_code)}])\n'
        '\tvar file = FileAccess.open("res://engine.json", FileAccess.WRITE)\n'
        "\tfile.store_string(str(OS.get_process_id()))\n\tfile.close()\n"
        + ("\twhile true:\n\t\tOS.delay_msec(20)\n" if retirement == "timeout" else ""),
        encoding="utf-8",
    )
    binary = (
        GODOT
        if binary_kind == "console"
        else str(GODOT).replace("_console.exe", ".exe")
    )
    run = Gda(project, godot=binary, json_output=True)
    outsider = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    observed = []
    try:
        run.json("daemon", "start")
        started_at = time.monotonic()
        with ThreadPoolExecutor(max_workers=1) as pool:
            readiness = pool.submit(
                run,
                "daemon",
                "wait-ready",
                "--timeout",
                "2" if retirement == "timeout" else "10",
            )
            engine = ObservedWindowsProcess(_read_pids(project / "engine.json"))
            child = ObservedWindowsProcess(_read_pids(child_file))
            observed += [engine, child]
            ready = readiness.result(timeout=15)
        if retirement == "timeout":
            assert time.monotonic() - started_at < 4
            assert ready.returncode == 6, ready.stdout + ready.stderr
            assert "engine_session_not_running" in ready.stdout
        else:
            assert ready.returncode == 0, ready.stdout + ready.stderr
            if retirement == "daemon-crash":
                owner = ObservedWindowsProcess(run.json("daemon", "status")["pid"])
                observed.append(owner)
                owner.terminate()
                owner.exited()
            elif retirement in {"replacement", "leader-exit"}:
                identity = run.json("daemon", "status")["session_id"]
                engine.terminate()
                engine.exited()
                if retirement == "replacement":
                    # Observe the dropped channel even if a console leader waits
                    # for descendants, then replace through public wait-ready.
                    run("game", "tree")
                    run.json("daemon", "wait-ready", "--timeout", "10")
                    assert run.json("daemon", "status")["session_id"] != identity
                else:
                    run.json("daemon", "stop")
            else:
                run.json("daemon", "stop")
        engine.exited()
        child.exited()
        assert outsider.poll() is None
    finally:
        run("daemon", "stop")
        for process in observed:
            process.close()
        outsider.terminate()
        outsider.wait(timeout=5)


def test_wrong_harness_peer_does_not_consume_the_launch(tmp_path, daemon_runtime_dir):
    project = _project(tmp_path / "project")
    (project / "main.tscn").write_text(
        '[gd_scene format=3]\n\n[node name="Main" type="Node"]\n', encoding="utf-8"
    )
    run = Gda(project, json_output=True)
    try:
        run.json("daemon", "start")
        metadata = json.loads(
            next(daemon_runtime_dir.rglob("*.json")).read_text(encoding="utf-8")
        )
        with socket.create_connection(("127.0.0.1", metadata["harness_port"])) as peer:
            write_frame(peer, b"wrong-token")
            before = time.monotonic()
            assert run.json("daemon", "wait-ready", "--timeout", "6")["launched"]
            assert time.monotonic() - before < 7
        assert run.json("game", "tree")["root"]["name"] == "Main"
    finally:
        run("daemon", "stop")


@pytest.mark.parametrize(
    "failure,winerrors", [("invalid-image", (193, 216)), ("denied-directory", (5,))]
)
def test_actual_engine_spawn_error_is_reported_before_handshake_timeout(
    tmp_path, daemon_runtime_dir, failure, winerrors
):
    project = _project(tmp_path / "project")
    binary = tmp_path / Path(GODOT).name
    assert binary.name.endswith("_console.exe"), (
        "this fixture needs the console distribution"
    )
    shutil.copyfile(GODOT, binary)
    # The GUI sibling is read-only in this fixture; overwrite only the copied wrapper.
    gui = Path(GODOT).with_name(Path(GODOT).name.replace("_console.exe", ".exe"))
    os.link(gui, binary.with_name(gui.name))
    run = Gda(project, godot=binary, json_output=True)
    try:
        run.json("daemon", "start")  # version check observes a valid engine
        binary.unlink()
        if failure == "invalid-image":
            binary.write_bytes(b"MZ" + bytes(62))
        else:
            binary.mkdir()
        before = time.monotonic()
        failed = run("daemon", "wait-ready", "--timeout", "6")
        assert failed.returncode == 6, failed.stdout + failed.stderr
        error = json.loads(failed.stdout)
        assert error["error"]["category"] == "live"
        assert error["error"]["code"] == "engine_session_not_running"
        assert time.monotonic() - before < 3
        assert any(
            f"WinError {code}" in error["error"]["diagnostics"] for code in winerrors
        )
        assert "harness did not connect within" not in error["error"]["diagnostics"]
    finally:
        run("daemon", "stop")


def test_headless_screen_capture_remains_explicitly_refused(
    tmp_path, daemon_runtime_dir
):
    project = _project(tmp_path / "project")
    (project / "main.tscn").write_text(
        '[gd_scene format=3]\n\n[node name="Main" type="Node2D"]\n', encoding="utf-8"
    )
    run = Gda(project, json_output=True)
    try:
        run.json("daemon", "start")
        output = project / "pending.png"
        refused = run("screen", "capture", "--output", str(output))
        assert refused.returncode == 6, refused.stdout + refused.stderr
        assert json.loads(refused.stdout)["error"]["code"] == "live_display_unavailable"
        assert not output.exists()
    finally:
        run("daemon", "stop")
