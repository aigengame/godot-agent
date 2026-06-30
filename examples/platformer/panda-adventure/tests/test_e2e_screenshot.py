"""Integration seam (c) — windowed viewport screenshot (#329 "log/screenshot").

The screenshot half of the e2e gate, modeled on gda's own ``test_e2e_screen.py``:
a real ``gda daemon start --windowed`` boots a WINDOWED engine session showing the
data-driven Block, ``gda screen capture`` writes a real PNG of the running
viewport, and we assert it is a decodable image (PNG magic + non-zero IHDR dims) —
no image-decode dependency. The headless logger/tree/get gate
(``test_e2e_boot.py``) stays separate so Linux CI keeps that coverage with no
display.

Isolation matches ``test_e2e_boot.py`` (a throwaway COPY; ``gda daemon start``
mutates the project). posix-only — the live stack uses ``AF_UNIX`` (ADR-0021); a
windowed session needs a DisplayServer, so this skips visibly on headless Linux
(``-rs``) and runs directly on macOS (Aqua).
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys

import pytest

from gda.binary import resolve_godot_binary

import build_config

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")

# Same-environment gda resolution (ADR-0011): the module in this interpreter.
GDA_CMD = [sys.executable, "-m", "gda"]
GODOT = resolve_godot_binary()
GAME_DIR = build_config.GAME_DIR

# The PNG magic the written capture must start with — proof it is a real,
# decodable image (not an empty/placeholder buffer).
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

_COPY_IGNORE = shutil.ignore_patterns(
    "tests", ".godot", "build", "generated", "__pycache__"
)

# A WINDOWED session needs a real DisplayServer. macOS always has one (Aqua);
# headless Linux CI does not, so skip there unless run under a virtual framebuffer
# (xvfb-run sets DISPLAY) — exactly how gda's own screen e2e behaves.
_needs_display = pytest.mark.skipif(
    sys.platform.startswith("linux") and not os.environ.get("DISPLAY"),
    reason="windowed capture needs a DisplayServer; headless Linux has none — run "
    "under xvfb-run, which sets DISPLAY",
)


def _make_project_copy(dst):
    """Copy the committed game into a throwaway dir and build its config there."""
    shutil.copytree(GAME_DIR, dst, ignore=_COPY_IGNORE)
    build_config.build(
        json_path=dst / "data" / "json" / "boot_config.json",
        schema_path=dst / "data" / "schema" / "boot_config.schema.json",
        out_path=dst / "data" / "generated" / "boot_config.tres",
    )
    return dst


@pytest.mark.e2e
@_needs_display
def test_windowed_daemon_captures_the_running_viewport(tmp_path, daemon_runtime_dir):
    project = _make_project_copy(tmp_path / "game")
    env = {**os.environ}
    out = tmp_path / "shot.png"

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                *GDA_CMD,
                *args,
                "--project",
                str(project),
                "--godot",
                str(GODOT),
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )

    try:
        started = run("daemon", "start", "--windowed")
        assert started.returncode == 0, started.stdout + started.stderr
        assert json.loads(started.stdout)["windowed"] is True

        # `screen capture` writes a real PNG of the running game's viewport.
        cap = run("screen", "capture", "--output", str(out))
        assert cap.returncode == 0, cap.stdout + cap.stderr
        doc = json.loads(cap.stdout)
        assert doc["format"] == "png"
        assert doc["width"] > 0 and doc["height"] > 0

        # The written file is a real PNG with non-zero IHDR dimensions, read
        # straight from bytes 16:24 (big-endian) without an image library.
        assert out.exists()
        data = out.read_bytes()
        assert data.startswith(PNG_MAGIC), data[:16]
        assert doc["bytes"] == len(data) > 0
        width, height = struct.unpack(">II", data[16:24])
        assert width > 0 and height > 0
        assert (width, height) == (doc["width"], doc["height"])
    finally:
        run("daemon", "stop")
