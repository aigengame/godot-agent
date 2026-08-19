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
def test_a_scene_with_missing_dependencies_still_starts_which_is_why_both_exist(
    godot_project,
):
    # Complementarity, pinned rather than asserted in prose: the engine builds the
    # tree without the reference it could not resolve, so the scene DOES come up. A
    # preflight alone would call this fine; only static validation names the missing
    # file. Neither command replaces the other.
    (godot_project / "main.tscn").write_text(
        "[gd_scene load_steps=2 format=3]\n\n"
        '[ext_resource type="Script" path="res://gone.gd" id="1_gone"]\n\n'
        '[node name="Hero" type="Node2D"]\n'
        'script = ExtResource("1_gone")\n',
        encoding="utf-8",
    )
    gda = _gda_project(godot_project)

    preflighted = gda("scene", "preflight", "res://main.tscn", "--json")
    assert preflighted.returncode == 0, preflighted.stdout + preflighted.stderr
    assert json.loads(preflighted.stdout)["status"] == "ready"

    validated = gda("scene", "validate", "res://main.tscn", "--json")
    assert validated.returncode == 0, validated.stdout + validated.stderr
    assert json.loads(validated.stdout)["problems"][0]["path"] == "res://gone.gd"


@pytest.mark.e2e
def test_a_missing_scene_is_refused_not_reported_as_a_verdict(godot_project):
    gda = _gda_project(godot_project)

    preflighted = gda("scene", "preflight", "res://nosuch.tscn", "--json")

    assert preflighted.returncode == 4, preflighted.stdout + preflighted.stderr
    assert json.loads(preflighted.stdout)["error"]["code"] == "path_not_found"
