"""Project expectations evaluated against real Godot-imported model facts."""

import json
import struct
from pathlib import Path

import pytest

from tests.support import Gda

pytestmark = pytest.mark.e2e
LIMB = "Character/RootBone/Skeleton3D/Arm_L"
SKELETON = "Character/RootBone/Skeleton3D"


def _mutate_glb(path: Path, mutation) -> None:
    data = path.read_bytes()
    json_length = struct.unpack_from("<I", data, 12)[0]
    document = json.loads(data[20 : 20 + json_length])
    mutation(document)
    payload = json.dumps(document, separators=(",", ":")).encode()
    payload += b" " * (-len(payload) % 4)
    chunks = (
        struct.pack("<I4s", len(payload), b"JSON") + payload + data[20 + json_length :]
    )
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks)


@pytest.fixture
def checked_model(godot_project):
    generator = Path(__file__).parent / "fixtures" / "model_check_fixture.gd"
    (godot_project / "create_model.gd").write_bytes(generator.read_bytes())
    run = Gda(godot_project, json_output=True)
    assert (
        run.json("script", "run", "res://create_model.gd", "--strict")["exit_status"]
        == 0
    )

    # GLTFDocument emits one mesh per instance. Sharing mesh 0 gives the
    # imported fixture an independently known unique-mesh count.
    model = godot_project / "model.glb"

    def share_mesh(document):
        for node in document["nodes"]:
            if "mesh" in node:
                node["mesh"] = 0

    _mutate_glb(model, share_mesh)
    run.json("resource", "import", "res://model.glb")
    (godot_project / "baseline.json").write_text(
        json.dumps(run.json("resource", "inspect-model", "res://model.glb"))
    )
    return godot_project


def _expectations(project: Path, name: str, checks: list[dict]) -> Path:
    path = project / name
    path.write_text(json.dumps({"checks": checks}))
    return path


def _check(run: Gda, expectations: Path, *source: str) -> dict:
    return run.json(
        "asset-pipeline", "check", "--expectations", str(expectations), *source
    )


def _baseline_checks() -> list[dict]:
    return [
        {"id": "limb", "kind": "node", "node": LIMB, "type": "MeshInstance3D"},
        {"id": "nodes", "kind": "count", "metric": "node_count", "min": 8, "max": 8},
        {
            "id": "meshes",
            "kind": "count",
            "metric": "mesh_instance_count",
            "min": 2,
            "max": 2,
        },
        {
            "id": "shared",
            "kind": "count",
            "metric": "unique_mesh_count",
            "min": 1,
            "max": 1,
        },
        {"id": "size", "kind": "dimensions", "min": [6, 4, 1], "max": [6, 4, 1]},
        {
            "id": "material",
            "kind": "material",
            "node": LIMB,
            "surface": 0,
            "name": "LimbMaterial",
        },
        {"id": "bone", "kind": "bone", "node": SKELETON, "name": "HandBone"},
        {
            "id": "skin",
            "kind": "skin_bind",
            "node": LIMB,
            "bind": 0,
            "skeleton": SKELETON,
            "bone": "HandBone",
        },
        {
            "id": "animation",
            "kind": "animation_target",
            "node": "AnimationPlayer",
            "animation": "Wave",
            "track": 0,
            "target": SKELETON,
            "bone": "HandBone",
        },
    ]


def test_imported_glb_satisfies_all_supported_expectation_kinds(checked_model):
    project = checked_model
    checks = _baseline_checks()
    result = _check(
        Gda(project, json_output=True),
        _expectations(project, "baseline-expectations.json", checks),
        "--path",
        "res://model.glb",
    )

    assert result["completed"] == ["validate", "inspect", "evaluate"]
    assert result["resource"] == "res://model.glb"
    assert result["observation_source"] == "godot"
    assert result["verdict"] == "pass"
    assert {item["id"]: item["verdict"] for item in result["checks"]} == {
        item["id"]: "pass" for item in checks
    }


def test_renamed_imported_limb_fails_fixed_path_but_preserves_mesh_count(checked_model):
    project = checked_model
    run = Gda(project, json_output=True)
    expectations = _expectations(project, "rename.json", _baseline_checks()[:3])
    _mutate_glb(
        project / "model.glb",
        lambda document: next(
            node for node in document["nodes"] if node.get("name") == "Arm_L"
        ).update(name="Arm_R"),
    )
    assert (
        run.json("resource", "import", "res://model.glb")["assets"][0]["status"]
        == "imported"
    )

    result = _check(
        run,
        expectations,
        "--path",
        "res://model.glb",
        "--baseline",
        str(project / "baseline.json"),
    )
    assert {item["id"]: item["verdict"] for item in result["checks"]} == {
        "limb": "fail",
        "nodes": "pass",
        "meshes": "pass",
    }
    node_changes = [
        (change["kind"], change["location"]["node"])
        for change in result["comparison"]["changes"]
        if change["section"] == "nodes"
    ]
    assert node_changes == [
        ("removed", LIMB),
        ("added", "Character/RootBone/Skeleton3D/Arm_R"),
    ]


def test_real_geometry_material_and_animation_mutations_fail_fixed_expectations(
    checked_model,
):
    project = checked_model
    run = Gda(project, json_output=True)
    expectations = _expectations(project, "mutations.json", _baseline_checks())

    def mutate(document):
        other = next(
            i
            for i, node in enumerate(document["nodes"])
            if node.get("name") == "Arm_L2"
        )
        # Godot normalizes transforms on a skinned mesh node. Scale the other
        # imported mesh so the static resource-space bounds must change.
        document["nodes"][other]["scale"] = [2, 1, 1]
        document["meshes"][0]["primitives"][0].pop("material")
        document["animations"][0]["channels"][0]["target"]["node"] = other

    _mutate_glb(project / "model.glb", mutate)
    assert (
        run.json("resource", "import", "res://model.glb")["assets"][0]["status"]
        == "imported"
    )
    result = _check(
        run,
        expectations,
        "--path",
        "res://model.glb",
        "--baseline",
        str(project / "baseline.json"),
    )

    assert result["verdict"] == "fail"
    assert {item["id"]: item["verdict"] for item in result["checks"]} == {
        "limb": "pass",
        "nodes": "pass",
        "meshes": "pass",
        "shared": "pass",
        "size": "fail",
        "material": "fail",
        "bone": "pass",
        "skin": "pass",
        "animation": "fail",
    }
    changes = result["comparison"]["changes"]
    assert [change["section"] for change in changes] == [
        "tracks",
        "materials",
        "nodes",
        "materials",
        "bounds",
    ]
    assert changes[0]["location"] == {
        "node": "AnimationPlayer",
        "animation": "Wave",
        "track": 0,
    }
    assert changes[0]["kind"] == "changed"
    assert changes[1]["location"] == {"node": LIMB, "surface": 0}
    assert changes[1]["kind"] in {"changed", "removed"}
    assert changes[-1]["after"]["size"] == [7, 4, 1]


def test_node_truncation_makes_unobserved_requirements_insufficient(checked_model):
    project = checked_model
    expectations = _expectations(
        project,
        "partial-nodes.json",
        [
            {"id": "limb", "kind": "node", "node": LIMB},
            {"id": "nodes", "kind": "count", "metric": "node_count", "min": 8},
            {"id": "size", "kind": "dimensions", "min": [6, 4, 1]},
        ],
    )
    result = _check(
        Gda(project, json_output=True),
        expectations,
        "--path",
        "res://model.glb",
        "--max-nodes",
        "1",
    )
    assert result["verdict"] == "insufficient"
    assert {item["verdict"] for item in result["checks"]} == {"insufficient"}


def test_duplicate_short_names_require_exact_full_paths(checked_model):
    project = checked_model
    expectations = _expectations(
        project,
        "duplicate-paths.json",
        [
            {"id": "character", "kind": "node", "node": "Character/Arm_L"},
            {"id": "prop", "kind": "node", "node": "Props/Arm_L"},
            {"id": "short", "kind": "node", "node": "Arm_L"},
        ],
    )
    result = _check(
        Gda(project, json_output=True),
        expectations,
        "--path",
        "res://duplicate_names.tscn",
    )

    assert {item["id"]: item["verdict"] for item in result["checks"]} == {
        "character": "pass",
        "prop": "pass",
        "short": "fail",
    }


def test_detail_truncation_is_insufficient_without_false_diff_removals(checked_model):
    project = checked_model
    expectations = _expectations(
        project,
        "partial-details.json",
        [
            {
                "id": "material",
                "kind": "material",
                "node": LIMB,
                "surface": 0,
                "name": "LimbMaterial",
            },
            {
                "id": "animation",
                "kind": "animation_target",
                "node": "AnimationPlayer",
                "animation": "Wave",
                "track": 0,
                "target": SKELETON,
                "bone": "HandBone",
            },
        ],
    )
    result = _check(
        Gda(project, json_output=True),
        expectations,
        "--path",
        "res://model.glb",
        "--max-items",
        "1",
        "--baseline",
        str(project / "baseline.json"),
    )

    assert result["verdict"] == "insufficient"
    assert {item["verdict"] for item in result["checks"]} == {"insufficient"}
    comparison = result["comparison"]
    assert comparison["status"] == "partial"
    assert comparison["incomplete_sections"]
    assert not any(
        change["section"] in {"tracks", "surfaces"} and change["kind"] == "removed"
        for change in comparison["changes"]
    )


def test_raw_inspection_report_is_accepted_without_engine_reinspection(checked_model):
    project = checked_model
    expectations = _expectations(
        project,
        "report-expectations.json",
        [{"id": "limb", "kind": "node", "node": LIMB}],
    )
    result = _check(
        Gda(project, json_output=True),
        expectations,
        "--report",
        str(project / "baseline.json"),
    )
    assert result["completed"] == ["validate", "evaluate"]
    assert result["observation_source"] == "supplied_report"
    assert result["verdict"] == "pass"
