"""Project expectations through the installed supporting-context API."""

from gda_assets.api import check_model
from gda_assets.application.ports import ModelInspectionPort
from gda_assets.domain.model import ModelFacts, NodeFacts


class ObservedModel:
    def inspect_model(self, path, *, subtree, max_nodes, max_items):
        return ModelFacts(
            resource=path,
            subtree=subtree,
            engine=(4, 6),
            measurement=("resource", "static_mesh_aabb"),
            nodes=(NodeFacts(".", "Node3D"), NodeFacts("Arm_L", "MeshInstance3D")),
            counts={"node_count": 2, "mesh_instance_count": 1, "unique_mesh_count": 1},
            bounds=None,
        )


def test_required_full_path_fails_after_limb_rename_with_same_mesh_count(tmp_path):
    expectations = tmp_path / "model.expectations.json"
    expectations.write_text(
        '{"checks":[{"id":"limb","kind":"node","node":"Arm_R","type":"MeshInstance3D"}]}'
    )
    port: ModelInspectionPort = ObservedModel()
    result = check_model(expectations, path="res://model.glb", godot=port)
    assert result.failure is None
    assert result.verdict == "fail"
    assert result.checks[0].id == "limb"
    assert result.checks[0].location == {"resource": "res://model.glb", "node": "Arm_R"}
    assert result.checks[0].actual is None
    assert result.checks[0].expected == {"type": "MeshInstance3D"}


def test_missing_node_in_partial_report_is_insufficient_but_present_node_passes(
    tmp_path,
):
    from dataclasses import replace

    class Partial(ObservedModel):
        def inspect_model(self, path, **kwargs):
            return replace(
                super().inspect_model(path, **kwargs), omissions=((".", "nodes"),)
            )

    expectations = tmp_path / "expectations.json"
    expectations.write_text(
        '{"checks":[{"id":"known","kind":"node","node":"Arm_L"},{"id":"missing","kind":"node","node":"Arm_R"}]}'
    )
    result = check_model(expectations, path="res://model.glb", godot=Partial())
    assert result.verdict == "insufficient"
    assert [c.verdict for c in result.checks] == ["pass", "insufficient"]


def test_invalid_expectations_are_input_failure_before_inspection(tmp_path):
    expectations = tmp_path / "expectations.json"
    expectations.write_text(
        '{"checks":[{"id":"limb","kind":"node","node":"../Arm_L"}]}'
    )
    result = check_model(expectations, path="res://model.glb", godot=ObservedModel())
    assert result.verdict is None
    assert result.failure is not None
    assert result.failure.code == "invalid_expectations"
    assert result.failure.stage == "validate"
    assert result.completed == []


def test_count_and_dimensions_use_node_coverage_not_texture_coverage(tmp_path):
    import json
    from dataclasses import replace

    facts = ObservedModel().inspect_model(
        "res://model.glb", subtree=".", max_nodes=256, max_items=1024
    )
    facts = replace(
        facts,
        bounds={"position": [0, 0, 0], "size": [2, 4, 2]},
        omissions=(("Arm_L", "textures"),),
    )
    expectations = tmp_path / "expectations.json"
    expectations.write_text(
        json.dumps(
            {
                "checks": [
                    {
                        "id": "meshes",
                        "kind": "count",
                        "metric": "mesh_instance_count",
                        "min": 1,
                        "max": 1,
                    },
                    {
                        "id": "size",
                        "kind": "dimensions",
                        "min": [1, 1, 1],
                        "max": [3, 3, 3],
                    },
                ]
            }
        )
    )
    result = check_model(expectations, report=facts)
    assert result.verdict == "fail"
    assert [c.verdict for c in result.checks] == ["pass", "fail"]
    result = check_model(
        expectations, report=replace(facts, omissions=((".", "nodes"),))
    )
    assert result.verdict == "insufficient"
    assert [c.verdict for c in result.checks] == ["insufficient", "insufficient"]


def test_material_bone_skin_and_animation_bindings_keep_exact_locations(tmp_path):
    import json
    from dataclasses import replace
    from gda_assets.domain.model import (
        AnimationFacts,
        BindFacts,
        BoneFacts,
        MaterialFacts,
        SurfaceFacts,
        TrackFacts,
    )

    facts = ObservedModel().inspect_model(
        "res://model.glb", subtree=".", max_nodes=256, max_items=1024
    )
    facts = replace(
        facts,
        nodes=(
            NodeFacts(
                "Rig",
                "Skeleton3D",
                bone_count=1,
                bones=(BoneFacts(0, "Arm_L", -1, ()),),
            ),
            NodeFacts(
                "Body",
                "MeshInstance3D",
                surface_count=1,
                surfaces=(
                    SurfaceFacts(
                        0,
                        {},
                        MaterialFacts(
                            "StandardMaterial3D", "Fur", None, "mesh_surface"
                        ),
                    ),
                ),
                skin_present=True,
                skeleton="Rig",
                bind_count=1,
                binds=(BindFacts(0, 0, None),),
            ),
            NodeFacts(
                "AnimationPlayer",
                "AnimationPlayer",
                animation_count=1,
                animations=(
                    AnimationFacts(
                        "Walk",
                        1,
                        0,
                        1,
                        (
                            TrackFacts(
                                0,
                                "position_3d",
                                "Rig:Arm_L",
                                True,
                                "Rig",
                                "Arm_L",
                                "resolved",
                                "bone",
                                None,
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    expectations = tmp_path / "expectations.json"
    expectations.write_text(
        json.dumps(
            {
                "checks": [
                    {
                        "id": "fur",
                        "kind": "material",
                        "node": "Body",
                        "surface": 0,
                        "name": "Fur",
                    },
                    {"id": "bone", "kind": "bone", "node": "Rig", "name": "Arm_L"},
                    {
                        "id": "bind",
                        "kind": "skin_bind",
                        "node": "Body",
                        "bind": 0,
                        "skeleton": "Rig",
                        "bone": "Arm_L",
                    },
                    {
                        "id": "walk",
                        "kind": "animation_target",
                        "node": "AnimationPlayer",
                        "animation": "Walk",
                        "track": 0,
                        "target": "Rig",
                        "bone": "Arm_L",
                    },
                ]
            }
        )
    )
    result = check_model(expectations, report=facts)
    assert result.verdict == "pass", result
    assert result.checks[0].location["surface"] == 0
    assert result.checks[3].location == {
        "resource": "res://model.glb",
        "node": "AnimationPlayer",
        "animation": "Walk",
        "track": 0,
    }
    broken = replace(
        facts,
        nodes=(
            facts.nodes[0],
            replace(facts.nodes[1], surfaces=(SurfaceFacts(0, {}),)),
            replace(
                facts.nodes[2],
                animations=(
                    AnimationFacts(
                        "Walk",
                        1,
                        0,
                        1,
                        (
                            TrackFacts(
                                0,
                                "position_3d",
                                "Rig:Missing",
                                True,
                                "Rig",
                                "Missing",
                                "unresolved",
                                None,
                                "bone not found",
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    result = check_model(expectations, report=broken)
    assert [c.verdict for c in result.checks] == ["fail", "pass", "pass", "fail"]


def test_check_entry_schema_and_saved_report_fail_verdict_agree_on_both_input_paths(
    tmp_path,
    monkeypatch,
):
    import json
    from typer.testing import CliRunner
    from gda.cli import app
    from tests.asset_pipeline.test_model_report_validation import _report

    report = tmp_path / "report.json"
    report.write_text(json.dumps(_report()))
    expectations = tmp_path / "expectations.json"
    expectations.write_text('{"checks":[{"id":"limb","kind":"node","node":"Missing"}]}')
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GDA_PROJECT", raising=False)
    monkeypatch.setenv("GDA_GODOT", str(tmp_path / "absent-engine"))
    runner = CliRunner()
    schema_call = runner.invoke(app, ["asset-pipeline", "check", "--schema"])
    assert schema_call.exit_code == 0, schema_call.output
    schema = json.loads(schema_call.stdout)
    assert schema["kind"] == "composite"
    assert "verdict" in schema["output"]["properties"]
    argv = runner.invoke(
        app,
        [
            "asset-pipeline",
            "check",
            "--expectations",
            str(expectations),
            "--report",
            str(report),
            "--json",
        ],
    )
    structured = runner.invoke(
        app,
        [
            "asset-pipeline",
            "check",
            "--params-json",
            json.dumps({"expectations": str(expectations), "report": str(report)}),
            "--json",
        ],
    )
    assert argv.exit_code == structured.exit_code == 0, (argv.output, structured.output)
    assert json.loads(argv.stdout) == json.loads(structured.stdout)
    assert json.loads(argv.stdout)["verdict"] == "fail"


def test_invalid_document_is_nonzero_workflow_error_on_cli_and_structured_input(
    tmp_path,
):
    import json
    from typer.testing import CliRunner
    from gda.cli import app
    from tests.asset_pipeline.test_model_report_validation import _report

    report = tmp_path / "report.json"
    report.write_text(json.dumps(_report()))
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"checks":[{"id":"size","kind":"dimensions","min":[NaN,0,0]}]}')
    runner = CliRunner()
    options = {"expectations": str(invalid), "report": str(report)}
    argv = runner.invoke(
        app,
        [
            "asset-pipeline",
            "check",
            "--expectations",
            str(invalid),
            "--report",
            str(report),
            "--json",
        ],
    )
    structured = runner.invoke(
        app, ["asset-pipeline", "check", "--params-json", json.dumps(options), "--json"]
    )
    assert argv.exit_code == structured.exit_code == 4
    assert json.loads(argv.stdout) == json.loads(structured.stdout)
    error = json.loads(argv.stdout)["error"]
    assert error["code"] == "invalid_params"
    assert error["partial_result"]["failure"]["code"] == "invalid_expectations"
    assert error["partial_result"]["verdict"] is None


def test_inspection_failure_keeps_native_code_details_and_workflow_stage(
    monkeypatch, tmp_path
):
    from gda.commands.asset_pipeline import AssetPipelineCheckParams, run_asset_check
    from gda.errors import Failure, make_failure
    from tests.support import minimal_project

    expectation = tmp_path / "checks.json"
    expectation.write_text('{"checks":[{"id":"root","kind":"node","node":"."}]}')
    failure = make_failure(
        "not_a_scene",
        "could not be loaded as PackedScene",
        "Check the imported resource",
    )
    monkeypatch.setattr(
        "gda.integrations.asset_pipeline.run_resource_inspect_model_operation",
        lambda *a, **k: failure,
    )
    result = run_asset_check(
        AssetPipelineCheckParams(expectations=expectation, path="res://broken.glb"),
        project=minimal_project(tmp_path / "project"),
        godot=None,
    )
    assert isinstance(result, Failure)
    assert result.error.code == "not_a_scene"
    assert "could not be loaded as PackedScene" in result.error.message
    partial = result.error.partial_result
    assert partial is not None
    assert partial["completed"] == ["validate"]
    assert partial["failure"]["stage"] == "inspect"
    assert partial["failure"]["cause"]["code"] == "not_a_scene"
