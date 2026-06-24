"""S1 (e2e): `gda diag` reads a running game's real runtime diagnostics (#224).

The #224 DoD: a real `gda daemon start` -> a NON-diag live op (`gda game tree`)
LAUNCHES the engine session (the daemon spawns it with `--log-file`, its own
Session log) and blocks until the main scene is current, so the scene's `_ready`
(which `push_error`s a KNOWN marker) has run and flushed -> THEN `gda diag errors`
reads the error back STRUCTURED (with a normalized `level`). diag OBSERVES the
already-launched session; it does NOT create one (ADR-0022). Daemon-served: the
diag read works against the daemon-owned log even though `project_godot` disables
the project's own file logging — the daemon's `--log-file` forces logging on
regardless. (The raw output-log read-back moved to `gda logger tail` — see
`test_e2e_logger.py`, #281.)

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
import time

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

    # Correct lifecycle (ADR-0022): `gda diag` OBSERVES an already-launched session
    # — it does NOT create one. So the session must be launched by a NON-diagnostic
    # live op first, then diag reads it back. `gda game tree` is that op: the harness
    # gates its reply on `current_scene != null` (ADR-0020 frame-coherence), so when
    # it returns, the main scene's `_ready` — which push_errors / prints the known
    # markers — has run and flushed into the daemon-owned Session log. (`daemon start`
    # alone does NOT auto-spawn a session; a live op does.)
    def poll_diag(sub, key, needle, timeout=15.0):
        # The session is already launched + warmed by `game tree`; this short poll is
        # a belt-and-suspenders for the log flush, NOT for launching the session.
        deadline = time.monotonic() + timeout
        last = []
        while time.monotonic() < deadline:
            proc = run("diag", sub)
            assert proc.returncode == 0, proc.stdout + proc.stderr
            last = json.loads(proc.stdout)[key]
            texts = [it["message"] if isinstance(it, dict) else it for it in last]
            if any(needle in t for t in texts):
                return last
            time.sleep(1.0)
        return last

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        # Launch + warm the session with a NON-diag live op. `game tree` blocks until
        # the main scene is current, so the game's `_ready` has push_errored / printed
        # the known markers into the daemon's --log-file by the time this returns.
        tree = run("game", "tree")
        assert tree.returncode == 0, tree.stdout + tree.stderr

        # diag errors: the daemon reads the structured error back from the Session log
        # it owns — even though the project disables file logging (the --log-file forces
        # it on). diag did NOT launch the session; `game tree` did.
        error_docs = poll_diag("errors", "errors", "known error")
        known = [e for e in error_docs if "known error" in e["message"]]
        assert known, error_docs
        # push_error surfaces as an error-class diagnostic (ERROR / SCRIPT ERROR).
        assert known[0]["level"] in ("error", "script_error"), known[0]
    finally:
        run("daemon", "stop")
