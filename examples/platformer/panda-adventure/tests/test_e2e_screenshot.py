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
windowed session needs a usable window server, so this skips — **before spawning
Godot** — where there is none (headless Linux without ``$DISPLAY``; macOS without
an active window-server session) and runs for real on a genuine desktop.
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
from gda.display import windowed_unavailable_reason

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

# Daemon error codes that mean "this environment cannot show a window" (the windowed
# start was refused pre-launch, or the live session has no display) — a skip signal,
# not a test failure. `live_windowed_unavailable` is the typed pre-launch refusal gda
# now returns for `daemon start --windowed` on a display-less host (#345), replacing
# the generic `engine_session_not_running` this used to key on.
_NO_DISPLAY_CODES = {"live_windowed_unavailable", "live_display_unavailable"}


def _error_code(stdout: str) -> str | None:
    """The gda error envelope's ``error.code`` from a CLI result, if any."""
    try:
        return json.loads(stdout).get("error", {}).get("code")
    except (ValueError, AttributeError):
        return None


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
def test_windowed_daemon_captures_the_running_viewport(tmp_path, daemon_runtime_dir):
    # Skip (visibly, via -rs) where no DisplayServer is usable — a windowed session
    # can't launch there. Uses gda's shared display helper (the same one gda's
    # `daemon start --windowed` precondition keys on, #345), so the pre-check and the
    # tool agree. Runs for real on a genuine desktop (macOS Aqua / Linux+DISPLAY).
    reason = windowed_unavailable_reason()
    if reason is not None:
        pytest.skip(reason)
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
        if started.returncode != 0:
            # gda refuses `daemon start --windowed` pre-launch with the typed
            # live_windowed_unavailable where no DisplayServer is usable (#345); the
            # pre-check above should have caught it, but honor it as a skip if it slips
            # through (env race), not a failure.
            code = _error_code(started.stdout)
            if code in _NO_DISPLAY_CODES:
                pytest.skip(
                    f"windowed session unavailable in this environment ({code})"
                )
            raise AssertionError(started.stdout + started.stderr)
        assert json.loads(started.stdout)["windowed"] is True

        # `screen capture` writes a real PNG of the running game's viewport. The
        # windowed session launches lazily here; if this environment can't bring up
        # a window server after all (despite the pre-check), the daemon reports a
        # display/session code — skip rather than fail (env limitation, not a bug).
        cap = run("screen", "capture", "--output", str(out))
        if cap.returncode != 0:
            code = _error_code(cap.stdout)
            if code in _NO_DISPLAY_CODES:
                pytest.skip(
                    f"windowed session unavailable in this environment ({code})"
                )
            raise AssertionError(cap.stdout + cap.stderr)  # a real capture failure
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
