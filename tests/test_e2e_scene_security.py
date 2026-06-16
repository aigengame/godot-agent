"""S1 (e2e): the project-code execution surface, pinned as characterization tests.

These tests freeze *today's verified contract* for when a single ``gda`` run
triggers the target project's own code to run (CONTEXT.md "Project-code
execution surface"). They are deliberate characterization tests for the two
tracked security findings #61 (autoloads run on every ``--project`` op) and #62
(mutating commands execute pre-existing scene scripts' ``_init``). They pin the
facts so that *if hardening ever lands*, the change shows up here as an
intentional, reviewed test inversion rather than a silent behavior drift.

The contract pinned (verified on Godot 4.6.3):

1. ``test_node_list_does_not_execute_scene_script`` /
   ``test_scene_get_does_not_execute_scene_code`` — reads stay clean at the
   *operation* level: ``node list`` / ``scene get`` walk the packed scene's
   stored state and never instantiate it, so an attached script's ``_init``
   never runs (issue #30, extended to the node group).
2. ``test_node_add_executes_pre_existing_scene_script`` — mutation instantiates
   the scene, so a pre-existing scripted node's ``_init`` runs (#62).
3. ``test_node_add_forged_sentinel_from_scene_script_fails_loudly`` — a scene
   script that forges a result block makes the mutate command fail loudly with
   ``contract_violation`` / exit 5, never a silently accepted forged result (#62).
4. ``test_autoload_runs_on_scene_get`` — a project's autoload constructor runs
   on *every* ``--project`` op, even a read-only ``scene get`` (#61).
"""

import json
import shutil
import subprocess

import pytest

from gda.binary import resolve_godot_binary

GODOT = resolve_godot_binary()


def _gda(*args: str, cwd=None) -> subprocess.CompletedProcess:
    gda_bin = shutil.which("gda")
    assert gda_bin, "the `gda` console script is not on PATH"
    return subprocess.run(
        [gda_bin, *args, "--godot", str(GODOT)],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd is not None else None,
    )


# A root script whose _init has a side effect AND prints a forged result block.
# If `scene get` instantiates the scene, _init runs: pwned.txt appears and the
# forged sentinel lands on stdout before the real one.
EVIL_GD = """\
extends Node2D


func _init() -> void:
	var f := FileAccess.open("res://pwned.txt", FileAccess.WRITE)
	if f:
		f.store_string("executed")
		f.close()
	print('<<<GDA:RESULT>>>{"path":"forged","root":{"name":"FORGED","type":"Node","children":[]}}<<<GDA:END>>>')
"""

# A scene attaching that script to its Node2D root (hand-written .tscn).
EVIL_TSCN = """\
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://evil.gd" id="1"]

[node name="Root" type="Node2D"]
script = ExtResource("1")
"""


@pytest.mark.e2e
def test_scene_get_does_not_execute_scene_code(godot_project):
    (godot_project / "evil.gd").write_text(EVIL_GD, encoding="utf-8")
    (godot_project / "evil.tscn").write_text(EVIL_TSCN, encoding="utf-8")

    gda_bin = shutil.which("gda")
    assert gda_bin, "the `gda` console script is not on PATH"
    # Run from inside the project so res://evil.gd resolves — the condition
    # under which the script would load and (on the buggy path) execute.
    proc = subprocess.run(
        [gda_bin, "scene", "get", "evil.tscn", "--json", "--godot", str(GODOT)],
        capture_output=True,
        text=True,
        cwd=str(godot_project),
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    tree = json.loads(proc.stdout)
    # The real tree, not the script-forged one.
    assert tree["root"]["name"] == "Root"
    assert tree["root"]["type"] == "Node2D"
    assert tree["path"] != "forged"
    # The script's _init never ran: no side-effect file.
    assert not (godot_project / "pwned.txt").exists()


# --- Characterization of the project-code execution surface (issues #61/#62) ---

# A scene script whose _init writes an observable marker file. Reused by the
# read-clean and mutation tests below to detect whether the script ran.
SPY_GD = """\
extends Node2D


func _init() -> void:
	var f := FileAccess.open("res://spy_ran.txt", FileAccess.WRITE)
	if f:
		f.store_string("executed")
		f.close()
	printerr("SPY: _init executed")
"""

SPIED_TSCN = """\
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://spy.gd" id="1"]

[node name="Root" type="Node2D"]
script = ExtResource("1")
"""


def _plant_spied_scene(project):
    """A scene whose root has a script with a side-effecting ``_init`` that
    writes ``res://spy_ran.txt``. The project fixture has no autoload, so the
    scene script is the *only* project-code execution surface here."""
    (project / "spy.gd").write_text(SPY_GD, encoding="utf-8")
    (project / "spied.tscn").write_text(SPIED_TSCN, encoding="utf-8")
    return project / "spied.tscn"


@pytest.mark.e2e
def test_node_list_does_not_execute_scene_script(godot_project):
    # Characterizes #30's read-clean guarantee, extended to the node group:
    # `node list` (and `scene get`) walk the packed scene's stored state and
    # never instantiate it, so an attached script's _init never runs. This is a
    # POSITIVE security property; unlike the #61/#62 contracts below it is NOT a
    # behavior we expect to invert — if it ever fails, a read started executing
    # project code and that is a regression, not intentional hardening.
    scene = _plant_spied_scene(godot_project)

    listed = _gda("node", "list", str(scene), "--project", str(godot_project), "--json")
    assert listed.returncode == 0, listed.stdout + listed.stderr
    tree = json.loads(listed.stdout)["root"]
    # The declared tree is reported (not anything the script could have forged).
    assert (tree["name"], tree["type"], tree["path"]) == ("Root", "Node2D", ".")
    assert tree["children"] == []

    got = _gda("scene", "get", str(scene), "--project", str(godot_project), "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["root"]["name"] == "Root"

    # Neither read ran the scene script: no side-effect file.
    assert not (godot_project / "spy_ran.txt").exists()


@pytest.mark.e2e
def test_node_add_executes_pre_existing_scene_script(godot_project):
    # CHARACTERIZATION of issue #62 — today's contract, deliberately pinned:
    # mutating a scene instantiates it (SceneState is read-only), and
    # constructing a node with an attached script runs that script's _init. So
    # `node add` on a scene with a pre-existing scripted root EXECUTES that
    # script. The add still succeeds and reports the added node.
    #
    # If hardening ever lands for #62 (mutate path no longer executes scene
    # scripts), THIS TEST MUST BE INTENTIONALLY INVERTED: the assertion below
    # should flip to assert the marker file does NOT appear.
    scene = _plant_spied_scene(godot_project)

    added = _gda(
        "node", "add", str(scene),
        "--type", "Sprite2D", "--name", "Hero",
        "--project", str(godot_project), "--json",
    )

    assert added.returncode == 0, added.stdout + added.stderr
    data = json.loads(added.stdout)
    assert (data["path"], data["name"], data["type"]) == ("Hero", "Hero", "Sprite2D")
    # Today's contract (#62): the pre-existing scene script's _init ran.
    assert (godot_project / "spy_ran.txt").exists()


# A scene script whose _init forges a complete, well-formed result block on
# stdout. Because the real operation also emits its result, stdout then carries
# two payloads — the parser must reject the run loudly, never believe the forgery.
FORGE_GD = """\
extends Node2D


func _init() -> void:
	print('<<<GDA:RESULT>>>{"scene_path":"forged","path":"FORGED","name":"FORGED","type":"Node","script_class":null}<<<GDA:END>>>')
"""

FORGED_TSCN = """\
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://forge.gd" id="1"]

[node name="Root" type="Node2D"]
script = ExtResource("1")
"""


@pytest.mark.e2e
def test_node_add_forged_sentinel_from_scene_script_fails_loudly(godot_project):
    # CHARACTERIZATION of issue #62's "forgery is loud, not silent" property:
    # when the mutate path executes a pre-existing scene script (see the test
    # above), a script that prints a forged <<<GDA:RESULT>>>…<<<GDA:END>>> block
    # corrupts the run — but it FAILS LOUDLY rather than being silently believed,
    # because stdout then carries two payloads. Verified on Godot 4.6.3:
    # exit 5, category "parse", code "contract_violation".
    #
    # This loud-failure property is the desirable half of #62. If #62 is hardened
    # so the mutate path stops executing scene scripts, this forgery vector
    # disappears and the test must be intentionally updated (the script would no
    # longer run, so no second payload would be emitted).
    (godot_project / "forge.gd").write_text(FORGE_GD, encoding="utf-8")
    (godot_project / "forged.tscn").write_text(FORGED_TSCN, encoding="utf-8")

    added = _gda(
        "node", "add", str(godot_project / "forged.tscn"),
        "--type", "Sprite2D", "--name", "Hero",
        "--project", str(godot_project), "--json",
    )

    # The forged result is never accepted: the run fails on the parse boundary.
    assert added.returncode == 5, added.stdout + added.stderr
    err = json.loads(added.stdout)["error"]
    assert err["category"] == "parse"
    assert err["code"] == "contract_violation"
    # The forgery surfaces only as a diagnostic, never as a believed result
    # payload: the envelope is an error, not a success carrying "FORGED".
    assert "error" in json.loads(added.stdout)


# An autoload whose _init writes an observable marker file. The project defines
# it via [autoload]; the engine constructs it during startup, before gda's own
# operation script runs — so it fires on ANY --project op, read or write.
AUTOLOAD_GD = """\
extends Node


func _init() -> void:
	var f := FileAccess.open("res://autoload_ran.txt", FileAccess.WRITE)
	if f:
		f.store_string("executed")
		f.close()
	printerr("AUTOLOAD: _init executed")
"""

# A project.godot that registers the autoload (extends the minimal fixture form).
PROJECT_WITH_AUTOLOAD = """\
config_version=5

[application]

config/name="gda-e2e-autoload-fixture"

[autoload]

Spy="*res://autoload.gd"
"""

# A plain scene with NO attached script, so the only project-code execution
# surface in this test is the autoload (not a scene script).
PLAIN_TSCN = """\
[gd_scene format=3]

[node name="Root" type="Node2D"]
"""


@pytest.mark.e2e
def test_autoload_runs_on_scene_get(godot_project):
    # CHARACTERIZATION of issue #61 — today's contract, deliberately pinned:
    # the runner passes --path <project> for any --project op, and operations.gd
    # is a SceneTree main loop, so the engine registers and constructs the
    # project's autoload singletons during startup — BEFORE the operation runs.
    # The autoload's _init therefore fires even on a read-only `scene get`,
    # against a scene that has no script of its own. Verified on Godot 4.6.3.
    #
    # If hardening ever lands for #61 (autoloads suppressed for one-shot headless
    # runs), THIS TEST MUST BE INTENTIONALLY INVERTED: the assertion should flip
    # to assert the marker file does NOT appear.
    (godot_project / "project.godot").write_text(
        PROJECT_WITH_AUTOLOAD, encoding="utf-8"
    )
    (godot_project / "autoload.gd").write_text(AUTOLOAD_GD, encoding="utf-8")
    (godot_project / "plain.tscn").write_text(PLAIN_TSCN, encoding="utf-8")

    got = _gda(
        "scene", "get", str(godot_project / "plain.tscn"),
        "--project", str(godot_project), "--json",
    )

    # The read itself succeeds and reports the declared (script-less) tree.
    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["root"]["name"] == "Root"
    # Today's contract (#61): the project's autoload _init ran during the read op.
    assert (godot_project / "autoload_ran.txt").exists()
