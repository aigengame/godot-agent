"""S1 (e2e): ``gda scene preflight`` against the real Godot engine (#664).

The dynamic half of #664 (dogfooding GDA-DF-030: static validation passed while the
first live launch rejected every assembly). Everything this command reports comes
from behaviour only a real engine has — when readiness is propagated, what an error
inside ``_ready`` prints, and what a ``_ready`` that never returns does to the
process — so it is pinned here rather than against a canned payload.

The last test is the one that cannot be faked at all: a scene whose ``_ready`` blocks
takes the whole engine with it, so gda's own bound is the only thing that ends the
run, and the verdict has to come back within it.
"""

import json
import subprocess
import time

import pytest

from gda.binary import resolve_godot_binary
from tests.support import GDA_CMD

GODOT = resolve_godot_binary()

# printerr, not print: gda's stdout carries only the result object (ADR-0002), so
# the engine's stdout is consumed by the sentinel parse and never forwarded. Its
# stderr IS forwarded, exactly as on the sentinel channel, which is what lets this
# test prove the scene's own code ran.
READY_SCRIPT = """\
extends Node2D


func _ready() -> void:
	printerr("hero ready")
"""

# The GDA-DF-030 shape: the scene comes up and then rejects its own assembly.
FAILING_READY_SCRIPT = """\
extends Node2D


func _ready() -> void:
	assert(false, "no spawn point in the encounter")
"""

# A _ready that never returns. The engine never reaches another frame, so nothing
# more is printed and nothing in-engine can report a verdict.
BLOCKING_READY_SCRIPT = """\
extends Node2D


func _ready() -> void:
	while true:
		pass
"""


def _scene_tscn(script: str) -> str:
    return (
        "[gd_scene load_steps=2 format=3]\n\n"
        f'[ext_resource type="Script" path="res://{script}" id="1_s"]\n\n'
        '[node name="Hero" type="Node2D"]\n'
        'script = ExtResource("1_s")\n'
    )


def _gda_project(project):
    def gda(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [*GDA_CMD, *args, "--godot", str(GODOT), "--project", str(project)],
            capture_output=True,
            text=True,
        )

    return gda


def _scene(project, name: str, script_name: str, source: str):
    (project / script_name).write_text(source, encoding="utf-8")
    (project / name).write_text(_scene_tscn(script_name), encoding="utf-8")


@pytest.mark.e2e
def test_a_scene_that_comes_up_cleanly_is_started(godot_project):
    _scene(godot_project, "hero.tscn", "hero.gd", READY_SCRIPT)
    gda = _gda_project(godot_project)

    preflighted = gda("scene", "preflight", "res://hero.tscn", "--json")

    assert preflighted.returncode == 0, preflighted.stdout + preflighted.stderr
    data = json.loads(preflighted.stdout)
    assert data["status"] == "ready"
    assert data["started"] is True
    assert data["diagnostics"] == []
    assert data["project_root"] == str(godot_project.resolve())
    # The scene really ran, and the engine's stream reached the caller: its own
    # printerr line is forwarded to gda's stderr, like every other headless command's
    # engine diagnostics. Unrecognized prose there is not a diagnostic, so the clean
    # verdict above stands.
    assert "hero ready" in preflighted.stderr


@pytest.mark.e2e
def test_an_error_raised_in_ready_is_reported_though_the_scene_reached_ready(
    godot_project,
):
    # The distinction the issue asks for, end to end: the scene loads, compiles, and
    # reaches _ready — and is still broken. `status` reports how far it got, the
    # diagnostics say what went wrong, and `started` requires both.
    _scene(godot_project, "encounter.tscn", "encounter.gd", FAILING_READY_SCRIPT)
    gda = _gda_project(godot_project)

    # Static validation passes: every dependency resolves and the script compiles.
    validated = gda("scene", "validate", "res://encounter.tscn", "--json")
    assert validated.returncode == 0, validated.stdout + validated.stderr
    assert json.loads(validated.stdout)["valid"] is True

    preflighted = gda("scene", "preflight", "res://encounter.tscn", "--json")

    assert preflighted.returncode == 0, preflighted.stdout + preflighted.stderr
    data = json.loads(preflighted.stdout)
    assert data["status"] == "ready"
    assert data["started"] is False
    assert data["diagnostics"], preflighted.stderr
    diagnostic = data["diagnostics"][0]
    assert diagnostic["kind"] == "runtime_error"
    assert diagnostic["path"] == "res://encounter.gd"
    assert "no spawn point in the encounter" in diagnostic["message"]


@pytest.mark.e2e
def test_a_scene_whose_ready_never_returns_is_a_timeout_verdict_within_the_bound(
    godot_project,
):
    # A blocked _ready blocks the engine itself: no further frame runs, so no
    # in-engine budget can fire and only gda's launch bound ends the run. The verdict
    # still comes back — as a SUCCESS carrying status=timeout, because "it did not
    # come up" is the answer this command was asked for.
    _scene(godot_project, "hang.tscn", "hang.gd", BLOCKING_READY_SCRIPT)
    gda = _gda_project(godot_project)

    started_at = time.monotonic()
    preflighted = gda(
        "scene", "preflight", "res://hang.tscn", "--timeout", "3", "--json"
    )
    elapsed = time.monotonic() - started_at

    assert preflighted.returncode == 0, preflighted.stdout + preflighted.stderr
    data = json.loads(preflighted.stdout)
    assert data["status"] == "timeout"
    assert data["started"] is False
    # Bounded: the 3s ceiling plus gda's own terminate-then-kill teardown, nowhere
    # near the default 30s ceiling this run did not use.
    assert elapsed < 25, elapsed


@pytest.mark.e2e
def test_a_scene_missing_an_unimported_asset_starts_clean_which_is_why_both_exist(
    godot_project,
):
    # Complementarity, pinned rather than asserted in prose, on the case that shows it
    # sharpest: a texture that was never imported. The engine builds the tree without
    # it and says so in a sentence the recognized set does not cover, so the preflight
    # reports a CLEAN start — while static validation names the file and the node.
    # (The two do overlap elsewhere: a missing script produces sentences the parser
    # does know, and both commands then flag it.) Neither replaces the other.
    (godot_project / "dot.png").write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d494844520000000100000001080600000"
            "01f15c4890000000d4944415478da63fccf000000004010012a4f4b21"
            "0000000049454e44ae426082"
        )
    )
    (godot_project / "main.tscn").write_text(
        "[gd_scene load_steps=2 format=3]\n\n"
        '[ext_resource type="Texture2D" path="res://dot.png" id="1_dot"]\n\n'
        '[node name="Hero" type="Node2D"]\n\n'
        '[node name="Sprite" type="Sprite2D" parent="."]\n'
        'texture = ExtResource("1_dot")\n',
        encoding="utf-8",
    )
    gda = _gda_project(godot_project)

    preflighted = gda("scene", "preflight", "res://main.tscn", "--json")
    assert preflighted.returncode == 0, preflighted.stdout + preflighted.stderr
    started = json.loads(preflighted.stdout)
    assert started["status"] == "ready"
    assert started["started"] is True
    assert started["diagnostics"] == []

    validated = gda("scene", "validate", "res://main.tscn", "--json")
    assert validated.returncode == 0, validated.stdout + validated.stderr
    problem = json.loads(validated.stdout)["problems"][0]
    assert problem["kind"] == "unloadable_resource"
    assert problem["path"] == "res://dot.png"
    assert problem["nodes"] == ["Sprite"]


@pytest.mark.e2e
def test_a_missing_scene_is_refused_not_reported_as_a_verdict(godot_project):
    gda = _gda_project(godot_project)

    preflighted = gda("scene", "preflight", "res://nosuch.tscn", "--json")

    assert preflighted.returncode == 4, preflighted.stdout + preflighted.stderr
    assert json.loads(preflighted.stdout)["error"]["code"] == "path_not_found"


# Hands off in _ready — a splash/bootstrap shape. The node is gone before the first
# observed frame, so a verdict SAMPLED there would call it not_ready.
HANDOFF_READY_SCRIPT = """\
extends Node2D


func _ready() -> void:
	printerr("handing off")
	queue_free()
"""

# Fails on the fifth _process frame, not during _ready — the shape the observation
# window exists for.
LATE_FAILURE_SCRIPT = """\
extends Node2D

var _frames := 0


func _process(_delta: float) -> void:
	_frames += 1
	if _frames == 5:
		assert(false, "the encounter fell apart on frame five")
"""


@pytest.mark.e2e
def test_a_scene_that_hands_off_in_ready_still_counts_as_started(godot_project):
    # Readiness is LATCHED from the engine's signal, not sampled on a later frame:
    # the propagation happens before the first observed frame, and by then a scene
    # that freed itself in _ready is already gone. Sampling reported this shape as
    # not_ready — a scene that plainly started.
    _scene(godot_project, "splash.tscn", "splash.gd", HANDOFF_READY_SCRIPT)
    gda = _gda_project(godot_project)

    preflighted = gda("scene", "preflight", "res://splash.tscn", "--json")

    assert preflighted.returncode == 0, preflighted.stdout + preflighted.stderr
    data = json.loads(preflighted.stdout)
    assert data["status"] == "ready"
    assert data["started"] is True
    assert "handing off" in preflighted.stderr


@pytest.mark.e2e
def test_the_frame_window_is_what_catches_a_failure_after_ready(godot_project):
    # What --frames buys, measured rather than asserted: the same scene passes with a
    # one-frame window and fails with the default one, because its error lands on
    # frame five. This is why the window is not simply "wait for ready".
    _scene(godot_project, "late.tscn", "late.gd", LATE_FAILURE_SCRIPT)
    gda = _gda_project(godot_project)

    narrow = gda("scene", "preflight", "res://late.tscn", "--frames", "1", "--json")
    assert narrow.returncode == 0, narrow.stdout + narrow.stderr
    assert json.loads(narrow.stdout)["started"] is True

    default_window = gda("scene", "preflight", "res://late.tscn", "--json")

    assert default_window.returncode == 0, default_window.stdout + default_window.stderr
    data = json.loads(default_window.stdout)
    assert data["status"] == "ready"
    assert data["started"] is False
    assert "fell apart on frame five" in data["diagnostics"][0]["message"]


# Ends the run from inside _ready — a boot/splash shape, and what any autoload
# quitting under a condition looks like from outside.
QUITTING_READY_SCRIPT = """\
extends Node2D


func _ready() -> void:
	printerr("handing control back")
	get_tree().quit()
"""


@pytest.mark.e2e
def test_a_scene_that_quits_from_ready_still_gets_its_ready_verdict(godot_project):
    # The #709 review's lost readiness fact: the quit ends the run before the op
    # can emit the result sentinel, but the scene plainly came up — its _ready ran
    # to the quit call. The op prints readiness as its own evidence line the
    # moment the signal lands, so the verdict survives the project's exit instead
    # of being misreported as an operation failure (the pre-#709 behavior).
    _scene(godot_project, "splash.tscn", "splash.gd", QUITTING_READY_SCRIPT)
    gda = _gda_project(godot_project)

    preflighted = gda("scene", "preflight", "res://splash.tscn", "--json")

    assert preflighted.returncode == 0, preflighted.stdout + preflighted.stderr
    data = json.loads(preflighted.stdout)
    assert data["status"] == "ready"
    assert data["started"] is True
    assert data["diagnostics"] == []
    # The scene's own stderr line is still forwarded verbatim, so the handoff is
    # visible to a reader even though it is not a recognized diagnostic.
    assert "handing control back" in preflighted.stderr


# GDA-DF-030 in the spelling a Godot project actually writes it in: the scene
# comes up and reports its own invariant violation with `push_error`. The engine
# prints an ERROR whose message is entirely the project's prose, so its only
# script attribution is the GDScript backtrace under it — which is why #722 keys
# recognition on the `at:` frame the engine fixes as `push_error`.
#
# A helper frame between `_ready` and the call keeps the test honest about WHICH
# line is reported: the innermost project frame, not the outermost.
PUSH_ERROR_READY_SCRIPT = """\
extends Node2D


func _ready() -> void:
	_check_encounter()


func _check_encounter() -> void:
	push_error("no spawn point in the encounter")
	push_warning("and the arena is undersized")
"""


@pytest.mark.e2e
def test_a_push_error_raised_in_ready_is_reported_as_a_startup_diagnostic(
    godot_project,
):
    # #722, end to end on a real engine: before it, this scene reported
    # `started: true` with EMPTY diagnostics — the phantom-clean start the
    # dogfooding note is about, in the most common shape a project writes it.
    _scene(godot_project, "encounter.tscn", "encounter.gd", PUSH_ERROR_READY_SCRIPT)
    gda = _gda_project(godot_project)

    # Static validation passes: the scene's dependencies resolve and it compiles.
    # Only booting it reveals what the project itself thinks of what it found.
    validated = gda("scene", "validate", "res://encounter.tscn", "--json")
    assert validated.returncode == 0, validated.stdout + validated.stderr
    assert json.loads(validated.stdout)["valid"] is True

    preflighted = gda("scene", "preflight", "res://encounter.tscn", "--json")

    assert preflighted.returncode == 0, preflighted.stdout + preflighted.stderr
    data = json.loads(preflighted.stdout)
    # The scene DID reach _ready — status and started answer different questions,
    # and this is exactly the case where they diverge.
    assert data["status"] == "ready"
    assert data["started"] is False
    # Exactly one diagnostic: the push_warning beside it keeps the severity the
    # project chose for it, and gda does not promote a warning to an error.
    assert len(data["diagnostics"]) == 1, preflighted.stderr
    diagnostic = data["diagnostics"][0]
    assert diagnostic["kind"] == "push_error"
    assert diagnostic["message"] == "no spawn point in the encounter"
    # Backtrace-only attribution, resolved to the innermost project frame: the
    # line that CALLED push_error, which the engine reported and gda did not
    # invent. Line 9 is the push_error statement in the script above.
    assert diagnostic["path"] == "res://encounter.gd"
    assert diagnostic["line"] == 9
    # The engine's stream is still forwarded verbatim, warning included.
    assert "and the arena is undersized" in preflighted.stderr


# An engine-side error a script only TRIGGERED: raised from the engine's own C++
# (`get_node`), yet carrying a full GDScript backtrace.
INDIRECT_ERROR_SCRIPT = """\
extends Node2D


func _ready() -> void:
	print(get_node("/root/NoSuchThing"))
"""


@pytest.mark.e2e
def test_an_engine_error_a_script_triggered_is_not_reported_as_the_projects_own(
    godot_project,
):
    # The over-match this recognition could easily have had: the engine attaches a
    # GDScript backtrace to ANY error raised while a script is on the stack, so a
    # bad get_node() looks structurally identical to a push_error apart from its
    # `at:` frame. Keying on that frame is what keeps the engine's own failure out
    # of the project's diagnostics — the record stays unrecognized, and the
    # verbatim stream is where a reader still finds it.
    _scene(godot_project, "indirect.tscn", "indirect.gd", INDIRECT_ERROR_SCRIPT)
    gda = _gda_project(godot_project)

    preflighted = gda("scene", "preflight", "res://indirect.tscn", "--json")

    assert preflighted.returncode == 0, preflighted.stdout + preflighted.stderr
    data = json.loads(preflighted.stdout)
    assert data["status"] == "ready"
    assert data["diagnostics"] == []
    assert data["started"] is True
    assert "NoSuchThing" in preflighted.stderr


# The PR #720 review's preflight false positive: a compiled `extends Resource`
# script on a Node2D. The engine refuses the binding with a deterministic ERROR,
# the node boots silently script-less, and its `_ready` never runs — so a verdict
# that read only the ready latch called this a clean start.
RESOURCE_SCRIPT = """\
extends Resource


func describe() -> String:
	return "a resource script"
"""

INCOMPATIBLE_BINDING_TSCN = """\
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://res_script.gd" id="1"]

[node name="Root" type="Node2D"]
script = ExtResource("1")
"""


@pytest.mark.e2e
def test_a_refused_script_binding_is_not_a_clean_start(godot_project):
    (godot_project / "res_script.gd").write_text(RESOURCE_SCRIPT, encoding="utf-8")
    (godot_project / "badbind.tscn").write_text(
        INCOMPATIBLE_BINDING_TSCN, encoding="utf-8"
    )
    gda = _gda_project(godot_project)

    preflighted = gda("scene", "preflight", "res://badbind.tscn", "--json")

    assert preflighted.returncode == 0, preflighted.stdout + preflighted.stderr
    data = json.loads(preflighted.stdout)
    # The scene REACHES ready (the tree comes up), but the intended script never
    # bound: started must not call that clean.
    assert data["started"] is False
    kinds = [diag["kind"] for diag in data["diagnostics"]]
    assert "incompatible_script" in kinds


# A plain Resource declared `type="Script"` — the #709 review's counterexample.
# Every file loads; the engine refuses the value at bind time ("Cannot set object
# script") and the node boots script-less.
PLAIN_RESOURCE_TRES = """\
[gd_resource type="Resource" format=3]

[resource]
"""

NOT_A_SCRIPT_BINDING_TSCN = """\
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://data.tres" id="1"]

[node name="Root" type="Node2D"]
script = ExtResource("1")
"""


@pytest.mark.e2e
def test_a_non_script_binding_is_not_a_clean_start(godot_project):
    (godot_project / "data.tres").write_text(PLAIN_RESOURCE_TRES, encoding="utf-8")
    (godot_project / "notascript.tscn").write_text(
        NOT_A_SCRIPT_BINDING_TSCN, encoding="utf-8"
    )
    gda = _gda_project(godot_project)

    preflighted = gda("scene", "preflight", "res://notascript.tscn", "--json")

    assert preflighted.returncode == 0, preflighted.stdout + preflighted.stderr
    data = json.loads(preflighted.stdout)
    # The tree comes up, but the node the script was meant for runs script-less:
    # the engine's own refusal is the diagnostic that keeps started honest.
    assert data["started"] is False
    kinds = [diag["kind"] for diag in data["diagnostics"]]
    assert "incompatible_script" in kinds


@pytest.mark.e2e
def test_the_timeout_verdict_carries_the_elapsed_clock_and_the_configured_ceiling(
    godot_project,
):
    # #787, against the real engine: only a genuinely blocked scene produces the
    # numbers, because they are measured around a process that really did refuse to
    # come back. `elapsed_seconds` must be AT LEAST the ceiling — gda waited the
    # whole bound out and then tore the engine down — and `timeout_seconds` must be
    # exactly what this caller configured, not the 30s default the run did not use.
    # Together they are what tells this scene (stuck) from one that was merely slow.
    _scene(godot_project, "stuck.tscn", "stuck.gd", BLOCKING_READY_SCRIPT)
    gda = _gda_project(godot_project)

    preflighted = gda(
        "scene", "preflight", "res://stuck.tscn", "--timeout", "3", "--json"
    )

    assert preflighted.returncode == 0, preflighted.stdout + preflighted.stderr
    data = json.loads(preflighted.stdout)
    assert data["status"] == "timeout"
    assert data["timeout_seconds"] == 3.0
    assert data["elapsed_seconds"] >= 3.0, data
    # Measured, not a constant: the clock is the real wall time of a run gda ended,
    # so it sits just past the ceiling rather than on it.
    assert data["elapsed_seconds"] < 25, data


@pytest.mark.e2e
def test_a_scene_that_comes_up_carries_no_timeout_evidence(godot_project):
    # The invariance, on a real engine: nothing bounded this run, so the pair is
    # absent rather than null or zero. A `ready` verdict is byte-identical to what it
    # was before #787 added the keys.
    _scene(godot_project, "hero.tscn", "hero.gd", READY_SCRIPT)
    gda = _gda_project(godot_project)

    preflighted = gda("scene", "preflight", "res://hero.tscn", "--json")

    assert preflighted.returncode == 0, preflighted.stdout + preflighted.stderr
    data = json.loads(preflighted.stdout)
    assert data["status"] == "ready"
    assert "elapsed_seconds" not in data
    assert "timeout_seconds" not in data
