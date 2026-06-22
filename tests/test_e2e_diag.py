"""S1 (e2e): `gda diag` reads a running game's real runtime diagnostics (#224).

The #224 DoD: a real `gda daemon start` -> a real engine session the daemon
launches with `--log-file` (its own Session log) -> a scene that `push_error`s and
`print`s a KNOWN marker at `_ready` -> `gda diag errors` reads the error back
STRUCTURED (with a normalized `level`) and `gda diag log` reads the printed line
back. Daemon-served: the diag read works against the daemon-owned log even though
`project_godot` disables the project's own file logging — the daemon's
`--log-file` forces logging on regardless (ADR-0022).

Run e2e serially; not a fresh empty HOME (Godot first-run). The
`daemon_runtime_dir` fixture keeps the daemon's UDS path within the OS `sun_path`
limit. NOTE: this module is the DoD and is NOT run by the implementing slice — a
sibling worktree runs a real Godot concurrently, so the main agent runs all e2e
serially in review.
"""

import json
import os
import shutil
import subprocess

import pytest

from gda.binary import resolve_godot_binary

from .conftest import project_godot

GODOT = resolve_godot_binary()

# A main scene whose root script emits a KNOWN runtime error and a KNOWN print
# line at `_ready`, so the daemon's Session log captures both for `diag` to read
# back. push_error -> the engine logs `ERROR: known error` + an `at:` line; print
# -> a plain `known line` in the same captured stream.
MAIN_GD = """\
extends Node2D

func _ready() -> void:
	print("known line")
	push_error("known error")
"""

MAIN_TSCN = (
    "[gd_scene load_steps=2 format=3]\n\n"
    '[ext_resource type="Script" path="res://main.gd" id="1"]\n\n'
    '[node name="Main" type="Node2D"]\n'
    'script = ExtResource("1")\n'
)
PROJECT_GODOT = project_godot(extra='run/main_scene="res://main.tscn"')

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")


@pytest.mark.e2e
def test_diag_reads_back_a_known_runtime_error_and_log_line(tmp_path, daemon_runtime_dir):
    gda = shutil.which("gda")
    assert gda, "the `gda` console script is not on PATH"
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")
    (tmp_path / "main.gd").write_text(MAIN_GD, encoding="utf-8")

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
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        # diag errors: the daemon launches the session (with --log-file), the game
        # push_errors at _ready, and the daemon reads the structured error back from
        # the Session log it owns — even though the project disables file logging.
        errors = run("diag", "errors")
        assert errors.returncode == 0, errors.stdout + errors.stderr
        error_docs = json.loads(errors.stdout)["errors"]
        known = [e for e in error_docs if "known error" in e["message"]]
        assert known, error_docs
        assert known[0]["level"] == "error"

        # diag log: the SAME session's captured output stream carries the print line.
        log = run("diag", "log")
        assert log.returncode == 0, log.stdout + log.stderr
        lines = json.loads(log.stdout)["lines"]
        assert any("known line" in line for line in lines), lines
    finally:
        run("daemon", "stop")
