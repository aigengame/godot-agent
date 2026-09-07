"""Vector3 values and Node3D local transforms through the public CLI (#885)."""

import json

import pytest

from tests.conftest import LIVE_PROJECT_GODOT
from tests.support import Gda

pytestmark = pytest.mark.e2e

TRANSFORM_SCENE = """[gd_scene format=3]

[node name="Main" type="Node3D"]
transform = Transform3D(0, -1, 0, 1, 0, 0, 0, 0, 1, 10, 20, 30)

[node name="Child" type="Node3D" parent="."]
transform = Transform3D(0, -3, 0, 2, 0, 0, 0, 0, 4, 1, 2, 3)
"""
LOCAL_FIELDS = ("position", "rotation", "scale")


def _local_values(run):
    data = run.json("node", "get", "res://main.tscn", "--node", "Child")
    properties = {p["name"]: p["value"] for p in data["properties"]}
    return {name: properties[name] for name in LOCAL_FIELDS}


def test_vector3_projects_recursively_from_a_project_setting(godot_project):
    config = godot_project / "project.godot"
    config.write_text(
        config.read_text()
        + "\n[vectors]\nvalue=Vector3(1.25, -2.5, 3.75)\n"
        + 'nested={"array": [Vector3(4, 5, 6)], '
        + '"packed": PackedVector3Array(7, 8, 9)}\n',
        encoding="utf-8",
    )
    run = Gda(godot_project, json_output=True)
    assert run.json("project", "get", "vectors/value")["value"] == [1.25, -2.5, 3.75]
    assert run.json("project", "get", "vectors/nested")["value"] == {
        "array": [[4, 5, 6]],
        "packed": [[7, 8, 9]],
    }


def test_vector3_assignment_uses_three_components_and_preserves_small_values(
    godot_project,
):
    config = godot_project / "project.godot"
    config.write_text(
        config.read_text() + "\n[vectors]\nvalue=Vector3(1, 2, 3)\n",
        encoding="utf-8",
    )
    run = Gda(godot_project, json_output=True)
    assigned = run.json("project", "set", "vectors/value", "--value", "1e-18,-2.5,3.75")
    assert assigned["value"] == pytest.approx([1e-18, -2.5, 3.75], abs=1e-25)
    assert run.json("project", "get", "vectors/value")["value"] == assigned["value"]
    before = config.read_bytes()
    for invalid in ("1,2", "1,2,3,4", "1,two,3", "1,2,", "[1,2,3]", "1e-320,2,3"):
        error = run.error(
            "project",
            "set",
            "vectors/value",
            "--value",
            invalid,
            code="uncoercible_value",
        )
        if invalid.startswith("1e-320"):
            assert "Godot's own float parser" in error["message"]
        assert config.read_bytes() == before


def test_node3d_local_writes_survive_reopen_and_preserve_other_components(
    godot_project,
):
    scene = godot_project / "main.tscn"
    scene.write_text(TRANSFORM_SCENE, encoding="utf-8")
    run = Gda(godot_project, json_output=True)
    before = _local_values(run)
    assert before["position"] == [1, 2, 3]
    assert before["scale"] == [2, 3, 4]
    # The initial child and parent both rotate 90 degrees around Z; the local
    # rotation is a quarter turn in radians, not the world-space half turn.
    assert before["rotation"] == pytest.approx([0, 0, 1.5707963267948966])
    for field, value in (
        ("position", [9, 8, 7]),
        ("rotation", [0.2, 0.3, 0.4]),
        ("scale", [1.5, 2.5, 3.5]),
    ):
        written = run.json(
            "node",
            "set",
            "res://main.tscn",
            "--node",
            "Child",
            "--property",
            field,
            "--value",
            ",".join(map(str, value)),
        )
        assert written["type"] == "Vector3"
        assert written["value"] == pytest.approx(value, abs=1e-6)
        reopened = _local_values(run)  # each command starts a fresh engine
        assert reopened[field] == pytest.approx(value, abs=1e-6)
        for other in LOCAL_FIELDS:
            if other != field:
                assert reopened[other] == pytest.approx(before[other], abs=1e-6)
        before = reopened
    saved = scene.read_bytes()
    run.error(
        "node",
        "set",
        "res://main.tscn",
        "--node",
        "Child",
        "--property",
        "rotation",
        "--value",
        "1,2",
        code="uncoercible_value",
    )
    assert scene.read_bytes() == saved

    # Global properties are outside the writable surface of this slice.
    run.error(
        "node",
        "set",
        "res://main.tscn",
        "--node",
        "Child",
        "--property",
        "global_position",
        "--value",
        "1,2,3",
        code="unknown_property",
    )
    assert scene.read_bytes() == saved


@pytest.mark.skipif("os.name != 'posix'")
def test_live_local_transform_reads_after_writes_without_saving(
    tmp_path, daemon_runtime_dir
):
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    scene = tmp_path / "main.tscn"
    scene.write_text(TRANSFORM_SCENE, encoding="utf-8")
    run = Gda(tmp_path, json_output=True)

    def read_local():
        return {
            field: run.json("game", "get", "/root/Main/Child", "--property", field)[
                "properties"
            ][0]["value"]
            for field in LOCAL_FIELDS
        }

    try:
        run.json("daemon", "start")
        before = read_local()
        assert before["position"] == [1, 2, 3]
        unfiltered = run.json("game", "get", "/root/Main/Child")
        assert not set(LOCAL_FIELDS) & {p["name"] for p in unfiltered["properties"]}
        saved = scene.read_bytes()
        for field, value in (
            ("position", [9, 8, 7]),
            ("rotation", [0.2, 0.3, 0.4]),
            ("scale", [1.5, 2.5, 3.5]),
        ):
            written = run.json(
                "game",
                "set",
                "--params-json",
                json.dumps(
                    {
                        "node": "/root/Main/Child",
                        "property": field,
                        "value": ",".join(map(str, value)),
                    }
                ),
            )
            assert written["type"] == "Vector3"
            assert written["verified"] is True
            observed = read_local()
            assert observed[field] == written["value"]
            assert observed[field] == pytest.approx(value, abs=1e-6)
            for other in LOCAL_FIELDS:
                if other != field:
                    assert observed[other] == pytest.approx(before[other], abs=1e-6)
            before = observed
        for invalid in ("1,2", "1,two,3", "1e-320,2,3"):
            refused = run(
                "game",
                "set",
                "/root/Main/Child",
                "--property",
                "position",
                "--value",
                invalid,
            )
            assert refused.returncode != 0
            error = json.loads(refused.stdout)["error"]
            assert error["category"] == "live"
            assert error["code"] == "live_uncoercible_value"
            assert read_local() == before
        refused = run(
            "game",
            "set",
            "/root/Main/Child",
            "--property",
            "global_position",
            "--value",
            "1,2,3",
        )
        assert refused.returncode != 0
        assert json.loads(refused.stdout)["error"]["code"] == "live_unknown_property"
        assert scene.read_bytes() == saved
    finally:
        run("daemon", "stop")


def test_vector3_resource_assignment_with_structured_params_and_human_read(
    godot_project,
):
    run = Gda(godot_project, json_output=True)
    run.json("resource", "create", "res://box.tres", "--type", "BoxMesh")
    params = {"path": "res://box.tres", "property": "size", "value": "2,3,4"}
    assigned = run.json("resource", "set", "--params-json", json.dumps(params))
    assert assigned["value"] == [2, 3, 4]
    read = run.json("resource", "get", "res://box.tres")
    size = next(p for p in read["properties"] if p["name"] == "size")
    assert size["value"] == [2, 3, 4]
    assert size["type"] == "Vector3"
    human = Gda(godot_project)("resource", "get", "res://box.tres")
    assert human.returncode == 0
    assert "Vector3" in human.stdout and "size" in human.stdout
