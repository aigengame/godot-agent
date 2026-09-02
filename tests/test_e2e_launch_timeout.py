"""S (e2e): a hung REAL engine leaves evidence on every launch channel (#714).

The defect this closes is one a fake cannot show. The buffered capture discarded
whatever the child had written when the timeout expired, so a sentinel op, an
export or an import pass that wedged came back with nothing but ``gda: <label>
timed out after <n>s`` — no engine output, no wall clock. Whether the engine
really does write before it wedges, whether that output survives gda's own
terminate-then-kill teardown, and whether the run is bounded at all are facts
about a real Godot process; a canned ``RunResult`` would assert only the can.

So each arm here wedges a REAL engine and asserts the same three things per
channel: the run is ended at its own ceiling, the envelope names that ceiling and
the wall clock, and the engine's own output is in the diagnostics.

Two levers wedge it, one per engine path:

- a blocking **autoload** ``_init`` wedges the GAME path (the sentinel channel),
  after the engine has printed its banner and the entry script has run;
- a blocking **editor plugin** ``_enter_tree`` wedges the EDITOR path, which both
  ``--import`` and ``--export-<mode>`` boot. An autoload cannot do it there: the
  editor does not instantiate autoloads.

Neither can be interrupted politely — a GDScript loop never returns to the main
loop, so the engine cannot honour the SIGTERM gda sends first — which makes these
arms cover the kill path too, and is why each spends its ceiling plus gda's
terminate grace.

The sentinel and export channels are driven through their runner objects rather
than through the CLI: neither exposes a timeout flag (60s and 600s, fixed), so a
CLI arm would have to spend a real minute or ten. ``resource import`` does expose
``--timeout``, so its arm is the full CLI round trip.
"""

import json
import subprocess
import time
from pathlib import Path

import pytest

from gda.binary import resolve_godot_binary
from gda.commands.export import ExportRunMode, classify_export_run
from gda.errors import Failure, classify_run
from gda.export_runner import SubprocessExportRunner
from gda.models import EngineVersion
from gda.runner import SubprocessGodotRunner
from tests.support import GDA_CMD

GODOT = resolve_godot_binary()

# The ceiling every arm gives its wedged engine. Long enough for a real Godot to
# boot and print, short enough that three arms plus gda's terminate grace stay
# well inside a test run.
CEILING_SECONDS = 4.0

# A blocking autoload: it announces itself on BOTH streams and then never returns.
# `printerr` matters — gda's stdout carries the ADR-0002 result object, so the
# stderr line is the one a channel forwards, while the stdout line proves the
# capture is not stderr-only.
BLOCKING_AUTOLOAD_GD = """\
extends Node


func _init() -> void:
	print("AUTOLOAD REACHED")
	printerr("AUTOLOAD WEDGED")
	while true:
		OS.delay_msec(50)
"""

# A blocking editor plugin: the same wedge for the editor paths (`--import`,
# `--export-<mode>`), which is where an autoload never runs.
BLOCKING_PLUGIN_GD = """\
@tool
extends EditorPlugin


func _enter_tree() -> void:
	print("PLUGIN REACHED")
	printerr("PLUGIN WEDGED")
	while true:
		OS.delay_msec(50)
"""

PLUGIN_CFG = """\
[plugin]

name="wedge"
description="blocks editor startup so a launch has to be ended by gda"
author="gda tests"
version="1.0"
script="plugin.gd"
"""


def _wedged_project(tmp_path: Path, *, autoload: bool, plugin: bool) -> Path:
    """A project whose engine startup never finishes on the requested path(s)."""
    sections = [
        "config_version=5\n\n[application]\n\n",
        'config/name="t714"\n\n',
        # The e2e file-logging policy (#180): no launch here writes a shared
        # user://logs/godot.log, so concurrent runs cannot contend over it.
        "[debug]\n\nfile_logging/enable_file_logging=false\n"
        "file_logging/enable_file_logging.pc=false\n\n",
    ]
    if autoload:
        (tmp_path / "wedge.gd").write_text(BLOCKING_AUTOLOAD_GD, encoding="utf-8")
        sections.append('[autoload]\n\nWedge="*res://wedge.gd"\n\n')
    if plugin:
        addon = tmp_path / "addons" / "wedge"
        addon.mkdir(parents=True)
        (addon / "plugin.gd").write_text(BLOCKING_PLUGIN_GD, encoding="utf-8")
        (addon / "plugin.cfg").write_text(PLUGIN_CFG, encoding="utf-8")
        sections.append(
            "[editor_plugins]\n\n"
            'enabled=PackedStringArray("res://addons/wedge/plugin.cfg")\n'
        )
    (tmp_path / "project.godot").write_text("".join(sections), encoding="utf-8")
    return tmp_path


def _assert_bounded(elapsed: float) -> None:
    """The run was ended by gda's ceiling, not by the engine and not by luck."""
    assert elapsed >= CEILING_SECONDS, f"the run ended early, at {elapsed:.1f}s"
    # The ceiling plus gda's terminate-then-kill grace, generously. A wedged
    # GDScript loop ignores the SIGTERM, so the grace is always spent in full.
    assert elapsed < CEILING_SECONDS + 20, f"the run overran its bound: {elapsed:.1f}s"


def _assert_caller_first_remediation(message: str) -> None:
    """The remediation a real timeout publishes reads caller-first (#716, #717).

    Asserted on the REAL envelope rather than only at the builder, because this is
    the sentence an agent acts on and its ORDER is the contract: the caller's remedy
    precedes the host suspicion, and the host suspicion carries the condition that
    earns it. The advisory clause is #716's decision made legible at the point of
    consumption — the capture beside it is partial by construction, so a recognized
    line in it must not be read as a different verdict.
    """
    caller_remedy = message.index("read the captured output")
    host_suspicion = message.index("suspect the binary or the machine")
    assert caller_remedy < host_suspicion, message
    assert "the capture shows the engine never started" in message
    # The flag is named with its qualifier: only `resource import` of these three
    # channels has a `--timeout` (the sentinel's 60s and the export's 600s are
    # gda's own, fixed).
    assert "--timeout, where the command exposes one" in message
    # The channels that qualifier excludes still get a next step (PR #793 review).
    assert "Where the command exposes no --timeout" in message
    assert "reduce the work or give the machine more headroom" in message
    assert "any engine error in it is advisory" in message


def _assert_timeout_envelope(
    failure: Failure, label: str, *, expect: list[str]
) -> None:
    error = failure.error
    assert error.code == "launch_timeout", error
    assert error.category.value == "environment"
    assert error.message.startswith(f"{label} launched but did not return")
    assert f"timeout of {CEILING_SECONDS}s" in error.message
    assert "elapsed 4." in error.message, error.message
    assert "16384 UTF-8 bytes (16 KiB)" in error.message
    _assert_caller_first_remediation(error.message)
    for expected in expect:
        assert expected in error.diagnostics, error.diagnostics


@pytest.mark.e2e
def test_a_wedged_sentinel_op_reports_what_the_engine_printed(tmp_path):
    project = _wedged_project(tmp_path, autoload=True, plugin=False)
    runner = SubprocessGodotRunner(GODOT, project=project, timeout=CEILING_SECONDS)

    started = time.monotonic()
    raw = runner.run("info", {})
    elapsed = time.monotonic() - started

    _assert_bounded(elapsed)
    outcome = classify_run(raw, GODOT, EngineVersion)
    assert isinstance(outcome, Failure)
    _assert_timeout_envelope(
        outcome,
        "Godot",
        # Both streams, and both from the engine itself: the banner it printed on
        # its own, and the autoload's two lines from before it stopped returning.
        expect=["Godot Engine v", "AUTOLOAD REACHED", "AUTOLOAD WEDGED"],
    )


@pytest.mark.e2e
def test_a_wedged_export_reports_what_the_engine_printed(tmp_path):
    project = _wedged_project(tmp_path, autoload=False, plugin=True)
    runner = SubprocessExportRunner(GODOT, project=project, timeout=CEILING_SECONDS)

    started = time.monotonic()
    raw = runner.run("Linux/X11", "release", "build/game.x86_64")
    elapsed = time.monotonic() - started

    _assert_bounded(elapsed)
    outcome = classify_export_run(
        raw,
        GODOT,
        preset="Linux/X11",
        platform="Linux/X11",
        mode=ExportRunMode.RELEASE,
        output_path="build/game.x86_64",
        created_dirs=[],
    )
    assert isinstance(outcome, Failure)
    _assert_timeout_envelope(
        outcome, "Godot export", expect=["PLUGIN REACHED", "PLUGIN WEDGED"]
    )


@pytest.mark.e2e
def test_a_wedged_import_pass_reports_what_the_engine_printed(tmp_path):
    # The full CLI round trip, which this channel can afford: `resource import`
    # exposes --timeout, so the ceiling is the test's to choose.
    project = _wedged_project(tmp_path, autoload=False, plugin=True)
    # An asset with no sidecar, so the pass is needed and really runs.
    (project / "icon.png").write_bytes(b"\x89PNG not really an image")

    started = time.monotonic()
    run = subprocess.run(
        [
            *GDA_CMD,
            "resource",
            "import",
            "res://icon.png",
            "--timeout",
            str(CEILING_SECONDS),
            "--project",
            str(project),
            "--godot",
            str(GODOT),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    elapsed = time.monotonic() - started

    _assert_bounded(elapsed)
    assert run.returncode == 124, run.stdout + run.stderr
    error = json.loads(run.stdout)["error"]
    assert error["code"] == "launch_timeout"
    assert error["message"].startswith("Godot import launched but did not return")
    assert f"timeout of {CEILING_SECONDS}s" in error["message"]
    assert "elapsed 4." in error["message"]
    _assert_caller_first_remediation(error["message"])
    assert "PLUGIN WEDGED" in error["diagnostics"]
