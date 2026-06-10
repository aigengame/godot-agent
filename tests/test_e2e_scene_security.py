"""S1 (e2e): reading a scene must not execute the scene's code (issue #30).

``gda scene get`` reports a scene's structured tree by inspecting the packed
scene's stored state, NOT by instantiating it. Instantiating would run the
``_init`` of any attached script, so merely *reading* a scene would execute
arbitrary project code — and a script that prints a sentinel-shaped line could
forge or corrupt the command's result. The guarantee is that the scene is never
instantiated (issue #30), so that line is never emitted in the first place.

This test plants a root script whose ``_init`` both writes a marker file (an
observable side effect) and prints a forged result block, then asserts neither
happened: the real tree is reported and the side-effect file does not exist.
"""

import json
import shutil
import subprocess

import pytest

from gda.binary import resolve_godot_binary

GODOT = resolve_godot_binary()

requires_godot = pytest.mark.skipif(
    not GODOT.exists(), reason=f"real Godot binary not found at {GODOT}"
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
@requires_godot
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
