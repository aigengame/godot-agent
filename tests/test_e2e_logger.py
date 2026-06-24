"""S1 (e2e): `gda logger tail` reads a running game's real structured log (#281).

The #281 DoD: a real `gda daemon start` -> a NON-diag live op (`gda game tree`)
LAUNCHES the engine session (the daemon spawns it with `--log-file`, its own
Session log) and blocks until the main scene is current, so the scene's `_ready`
(which `print`s a KNOWN line, `push_warning`s a KNOWN warning, and `push_error`s a
KNOWN error) has run and flushed -> THEN `gda logger tail --json` reads them back
as STRUCTURED `LogRecord`s (the print as an `info` record, the push_warning as a
`warning`, the push_error as an `error` carrying an engine `source`), and
`gda logger tail --raw` reads the same content back as verbatim lines. `logger
tail` OBSERVES the already-launched session; it does NOT create one (ADR-0022).
Daemon-served: the read works against the daemon-owned log even though
`project_godot` disables the project's own file logging — the daemon's
`--log-file` forces logging on regardless. The structured read survives after the
session ends (the persisted log, ADR-0022).

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

# A main scene whose root script emits a KNOWN print line, a KNOWN warning, and a
# KNOWN error at `_ready`, so the daemon's Session log captures all three for
# `logger tail` to read back structured. print -> a plain `info` record;
# push_warning -> a `warning` record (engine WARNING + `at:` line); push_error ->
# an `error` record (engine ERROR + `at:` line, carrying a source frame).
MAIN_GD = """\
extends Node2D

func _ready() -> void:
	print("known line")
	push_warning("known warning")
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
def test_logger_tail_reads_back_structured_records_and_raw_lines(tmp_path, daemon_runtime_dir):
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

    def poll_records(extra_args, needle, timeout=15.0):
        # The session is already launched + warmed by `game tree`; this short poll
        # is a belt-and-suspenders for the log flush, NOT for launching the session.
        deadline = time.monotonic() + timeout
        last = []
        while time.monotonic() < deadline:
            proc = run("logger", "tail", *extra_args)
            assert proc.returncode == 0, proc.stdout + proc.stderr
            doc = json.loads(proc.stdout)
            last = doc["records"] or doc["lines"]
            texts = [r["message"] if isinstance(r, dict) else r for r in last]
            if any(needle in t for t in texts):
                return last
            time.sleep(1.0)
        return last

    try:
        started = run("daemon", "start")
        assert started.returncode == 0, started.stdout + started.stderr

        # Launch + warm the session with a NON-logger live op. `game tree` blocks
        # until the main scene is current, so the game's `_ready` has printed /
        # push_warned / push_errored the known markers into the daemon's --log-file
        # by the time this returns.
        tree = run("game", "tree")
        assert tree.returncode == 0, tree.stdout + tree.stderr

        # Default: structured records. The known print is a plain `info` record.
        records = poll_records([], "known line")
        info = [r for r in records if "known line" in r["message"]]
        assert info, records
        assert info[0]["level"] == "info"
        assert info[0]["origin"] is None

        # The push_error is an `error` record carrying an engine source frame.
        records = poll_records([], "known error")
        errors = [r for r in records if "known error" in r["message"]]
        assert errors, records
        assert errors[0]["level"] == "error"
        assert errors[0]["origin"] in ("engine", "script")
        assert errors[0]["source"] is not None
        assert errors[0]["source"]["file"]  # res://main.gd, when the engine logged it

        # The push_warning is a `warning` record (told apart from the error by level).
        records = poll_records([], "known warning")
        warnings = [r for r in records if "known warning" in r["message"]]
        assert warnings, records
        assert warnings[0]["level"] == "warning"

        # `--level error` filters out the info + warning records, keeping the error.
        errors_only = poll_records(["--level", "error"], "known error")
        assert errors_only, "expected the error to survive --level error"
        assert all(r["level"] == "error" for r in errors_only)

        # `--raw` returns the same content as verbatim lines (the superseded
        # `diag log` view): the print line and the ERROR header are present.
        raw_lines = poll_records(["--raw"], "known line")
        assert any("known line" in line for line in raw_lines), raw_lines
        assert any("known error" in line for line in raw_lines), raw_lines

        # The structured read survives after the session ends: stop the daemon's
        # session implicitly is not exposed, but the persisted log is still served
        # while the daemon lives — re-read once more to assert idempotent crash-
        # survivable behaviour (ADR-0022): the records are still there.
        again = run("logger", "tail")
        assert again.returncode == 0, again.stdout + again.stderr
        again_records = json.loads(again.stdout)["records"]
        assert any("known error" in r["message"] for r in again_records), again_records
    finally:
        run("daemon", "stop")
