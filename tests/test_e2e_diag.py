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
import time

import pytest

from tests.support import Gda

from .conftest import LIVE_PROJECT_GODOT, SCRIPTED_MAIN_TSCN

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

# A main scene whose `_ready` calls a chain a() -> b() that triggers a runtime
# GDScript error (calling a method on a null), so the engine emits a `GDScript
# backtrace` with three frames (b, a, _ready) — most-recent-first — that `gda
# diag errors` reads back as a multi-frame `callstack` (#283).
CALLSTACK_MAIN_GD = """\
extends Node2D

func _ready() -> void:
	a()

func a() -> void:
	b()

func b() -> void:
	var n = null
	n.do_thing()
"""

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")


@pytest.mark.e2e
def test_diag_reads_back_a_known_runtime_error_and_log_line(
    tmp_path, daemon_runtime_dir
):
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(SCRIPTED_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "main.gd").write_text(MAIN_GD, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

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


@pytest.mark.e2e
def test_diag_reads_back_a_multi_frame_callstack(tmp_path, daemon_runtime_dir):
    # #283: a deliberately-thrown runtime error whose `_ready` calls a chain
    # a() -> b() that errors (a null method call). The engine emits a GDScript
    # backtrace, so `gda diag errors` reports an ordered, multi-frame `callstack`
    # — not just the top `file:line`. Same lifecycle as the sibling test: a
    # NON-diag live op (`game tree`) launches + warms the session, THEN diag
    # observes the daemon-owned Session log.
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(SCRIPTED_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "main.gd").write_text(CALLSTACK_MAIN_GD, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

    def poll_errors(needle, timeout=15.0):
        deadline = time.monotonic() + timeout
        last = []
        while time.monotonic() < deadline:
            proc = run("diag", "errors")
            assert proc.returncode == 0, proc.stdout + proc.stderr
            last = json.loads(proc.stdout)["errors"]
            if any(needle in e["message"] for e in last):
                return last
            time.sleep(1.0)
        return last

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        # Launch + warm the session; by the time `game tree` returns, the chained
        # error has been logged with its GDScript backtrace.
        tree = run("game", "tree")
        assert tree.returncode == 0, tree.stdout + tree.stderr

        # The null method call surfaces as a script error naming `do_thing`.
        errors = poll_errors("do_thing")
        offending = [e for e in errors if "do_thing" in e["message"]]
        assert offending, errors
        error = offending[0]

        # The callstack is the ORDERED chain, most-recent-first: b -> a -> _ready.
        functions = [frame["function"] for frame in error["callstack"]]
        assert functions == ["b", "a", "_ready"], error
        # Frame [0] equals the top single-frame location (unchanged behaviour).
        assert error["callstack"][0]["function"] == error["function"]
        assert error["callstack"][0]["file"] == error["file"]
        assert error["callstack"][0]["line"] == error["line"]
        # Every frame points back into the one script.
        assert all(frame["file"] == "res://main.gd" for frame in error["callstack"]), (
            error
        )
    finally:
        run("daemon", "stop")
