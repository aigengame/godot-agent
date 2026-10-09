"""The real TCP harness framing seam, including main-loop progress (#1118)."""

import json
import os
import socket
import struct
import subprocess
import time
from pathlib import Path

import pytest

from gda.daemon.protocol import read_frame, write_message
from tests.conftest import SCRIPTED_MAIN_TSCN, project_godot
from tests.support import GODOT, Gda

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.name != "nt", reason="Windows TCP harness"),
]


def _ticks(path):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            return int(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            time.sleep(0.01)
    raise AssertionError("the real game did not publish a tick")


def test_fragmented_input_large_utf8_reply_and_disconnect_keep_game_ticking(tmp_path):
    (tmp_path / "project.godot").write_text(
        project_godot(extra='run/main_scene="res://main.tscn"'), encoding="utf-8"
    )
    (tmp_path / "main.tscn").write_text(SCRIPTED_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "main.gd").write_text(
        'extends Node2D\n@export var text: String = "测试".repeat(300000)\n'
        "func _process(_delta):\n"
        '\tvar file = FileAccess.open("res://ticks", FileAccess.WRITE)\n'
        "\tfile.store_string(str(Engine.get_process_frames()))\n",
        encoding="utf-8",
    )
    Gda(tmp_path).json("daemon", "install")
    # Use the real GUI executable in headless mode, with no console-wrapper child.
    binary = Path(GODOT).with_name(Path(GODOT).name.replace("_console.exe", ".exe"))
    assert binary.is_file(), binary
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(10)
        proc = subprocess.Popen(
            [
                str(binary),
                "--headless",
                "--path",
                str(tmp_path),
                "--",
                "gda-daemon",
                f"tcp://127.0.0.1:{listener.getsockname()[1]}",
                "original-token",
                "",
                "stream-session",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            with listener.accept()[0] as peer:
                deadline = time.monotonic() + 10
                assert read_frame(peer, deadline) == b"original-token"
                verification = read_frame(peer, deadline)
                assert verification is not None
                assert json.loads(verification)["scene_ok"] is True
                body = json.dumps(
                    {
                        "op": "game-get",
                        "params": {"node": "/root/Main", "property": "text"},
                    }
                ).encode()
                header = struct.pack(">I", len(body))
                peer.sendall(header[:2])
                before = _ticks(tmp_path / "ticks")
                time.sleep(0.15)
                assert _ticks(tmp_path / "ticks") > before
                peer.sendall(header[2:] + body[: len(body) // 2])
                before = _ticks(tmp_path / "ticks")
                time.sleep(0.15)
                assert _ticks(tmp_path / "ticks") > before
                peer.sendall(body[len(body) // 2 :])
                payload = read_frame(peer, time.monotonic() + 10)
                assert payload is not None
                reply = payload.decode("utf-8")
                assert "测试" * 300000 in reply
                assert reply.endswith("<<<GDA:END>>>")
                # Close while another large response is being produced.
                write_message(
                    peer,
                    {
                        "op": "game-get",
                        "params": {"node": "/root/Main", "property": "text"},
                    },
                )
            before = _ticks(tmp_path / "ticks")
            time.sleep(0.2)
            assert _ticks(tmp_path / "ticks") > before
        finally:
            proc.terminate()
            proc.wait(timeout=5)
