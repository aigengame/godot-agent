"""S1 (e2e): gda --params-json against the real Godot engine (issue #199, ADR-0015).

Drives the structured params-input ABI through the real installed console script
and a real Godot process: a JSON params object (on the command line, and via
stdin) produces the same on-disk effect as the argv form — the ``.tscn`` is
created and reads back. Per RULES.md DoD the fake-runner fast tests do not count
toward this gate.
"""

import json
import subprocess

import pytest

from gda.binary import resolve_godot_binary

from tests.support import GDA_CMD

GODOT = resolve_godot_binary()


@pytest.mark.e2e
def test_scene_create_via_params_json_creates_the_scene(godot_project):
    scene_path = godot_project / "main.tscn"
    params = json.dumps({"path": str(scene_path), "root_type": "Node2D"})

    created = subprocess.run(
        [
            *GDA_CMD,
            "scene",
            "create",
            "--params-json",
            params,
            "--json",
            "--godot",
            str(GODOT),
        ],
        capture_output=True,
        text=True,
    )

    assert created.returncode == 0, created.stdout + created.stderr
    data = json.loads(created.stdout)
    assert data["root_type"] == "Node2D"
    # root_name derived model-side from the filename — same as the argv path.
    assert data["root_name"] == "main"
    # The .tscn really landed on disk.
    assert scene_path.exists()

    # And reads back through the engine — the file is loadable, not just present.
    got = subprocess.run(
        [*GDA_CMD, "scene", "get", str(scene_path), "--json", "--godot", str(GODOT)],
        capture_output=True,
        text=True,
    )
    assert got.returncode == 0, got.stdout + got.stderr
    assert json.loads(got.stdout)["root"]["type"] == "Node2D"


@pytest.mark.e2e
def test_scene_create_via_params_json_stdin_creates_the_scene(godot_project):
    # `--params-json -` reads the object from stdin through the real chain.
    scene_path = godot_project / "fromstdin.tscn"
    params = json.dumps({"path": str(scene_path), "root_type": "Node2D"})

    created = subprocess.run(
        [*GDA_CMD, "scene", "create", "--params-json", "-", "--json", "--godot", str(GODOT)],
        input=params,
        capture_output=True,
        text=True,
    )

    assert created.returncode == 0, created.stdout + created.stderr
    assert json.loads(created.stdout)["root_name"] == "fromstdin"
    assert scene_path.exists()
