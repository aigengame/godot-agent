"""Unified package acceptance command across CLI and MCP transports."""

import hashlib
import json
from pathlib import Path
import struct
import sys

from typer.testing import CliRunner

from gda.cli import app
from gda.commands.asset_pipeline import (
    AssetPipelinePackageCheckParams,
    run_asset_package_check,
)
from gda.commands.resource import PackageResourcePresenceResult
from gda.errors import Failure, make_failure
from gda.mcp.server import build_server
from gda.models import EngineVersion
from gda_assets.api import PackageCheckResult, PipelineFailure
from gda_assets.domain.model import CheckResult, ModelCheckResult
from gda_assets.domain.package import (
    PackageCleanup,
    PackageEngine,
    PackageExclusion,
    PackagePresence,
    PackageSnapshot,
)
from tests.mcp_support import FakeGdaRunner, gda_result, list_tools, schema_then
from tests.support import minimal_project, panel_text


def test_check_package_help_schema_and_mcp_share_the_public_contract():
    runner = CliRunner()
    schema_call = runner.invoke(app, ["asset-pipeline", "check-package", "--schema"])
    assert schema_call.exit_code == 0, schema_call.output
    schema = json.loads(schema_call.stdout)
    assert schema["kind"] == "composite"
    assert schema["input"]["properties"]["exclude"]["maxItems"] == 64
    assert schema["input"]["properties"]["max_nodes"]["maximum"] == 4096
    assert "PackageCheckResult" in schema["output"]["$defs"]
    bindings = {item["input_property"]: item for item in schema["argv"]}
    assert bindings["exclude"]["option"] == "--exclude"
    assert bindings["exclude"]["multiple"] is True
    tools = list_tools(
        build_server(FakeGdaRunner(schema_then(lambda *_: gda_result())))
    ).tools
    tool = next(item for item in tools if item.name == "asset_pipeline_check_package")
    assert tool.input_schema == schema["input"]
    assert tool.output_schema == schema["output"]
    help_text = panel_text(
        runner.invoke(app, ["asset-pipeline", "check-package", "--help"]).stdout
    )
    assert all(
        option in help_text
        for option in ("--package", "--path", "--expectations", "--exclude")
    )
    assert "--project" not in help_text


def test_check_package_argv_and_params_json_pass_the_same_request(
    monkeypatch, tmp_path
):
    package = tmp_path / "game.pck"
    expectations = tmp_path / "expectations.json"
    monkeypatch.setenv("GDA_PROJECT", str(tmp_path / "absent-project"))
    calls = []

    def check(request, *, godot):
        calls.append((request, godot))
        return PackageCheckResult(
            request=request, completed=["validate", "evaluate"], verdict="pass"
        )

    monkeypatch.setattr("gda.commands.asset_pipeline.check_package", check)
    common = {
        "package": str(package),
        "path": "res://model.glb",
        "expectations": str(expectations),
        "exclude": ["res://debug.gd", "res://secret.tres"],
        "subtree": "Body",
        "max_nodes": 10,
        "max_items": 20,
    }
    runner = CliRunner()
    outputs = []
    for args in (
        [
            "--package",
            str(package),
            "--path",
            common["path"],
            "--expectations",
            str(expectations),
            "--exclude",
            common["exclude"][0],
            "--exclude",
            common["exclude"][1],
            "--subtree",
            "Body",
            "--max-nodes",
            "10",
            "--max-items",
            "20",
        ],
        ["--params-json", json.dumps(common)],
    ):
        result = runner.invoke(
            app,
            [
                "asset-pipeline",
                "check-package",
                *args,
                "--godot",
                "godot-custom",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        outputs.append(json.loads(result.stdout))

    assert outputs[0] == outputs[1]
    assert calls[0][0] == calls[1][0]
    assert calls[0][0].package == package.resolve()
    assert calls[0][0].exclude == ("res://debug.gd", "res://secret.tres")
    assert calls[0][1]._godot == calls[1][1]._godot == "godot-custom"


def test_package_workflow_failure_is_nonzero_with_full_partial_result(
    monkeypatch, tmp_path
):
    native = make_failure("path_not_found", "missing package", "native stderr")
    native.child_stderr = "native stderr"

    class Port:
        last_failure = native

        def __init__(self, godot):
            pass

    monkeypatch.setattr("gda.commands.asset_pipeline.GdaGodotPackagePort", Port)

    def check(request, *, godot):
        return PackageCheckResult(
            request=request,
            completed=["validate"],
            failure=PipelineFailure(
                "stage",
                "path_not_found",
                "missing package",
                {"code": "path_not_found"},
            ),
        )

    monkeypatch.setattr("gda.commands.asset_pipeline.check_package", check)
    result = run_asset_package_check(
        AssetPipelinePackageCheckParams(
            package=tmp_path / "missing.pck",
            path="res://model.glb",
            expectations=tmp_path / "expectations.json",
        ),
        project=minimal_project(tmp_path / "unrelated"),
        godot=None,
    )

    assert isinstance(result, Failure)
    assert result.error.code == "path_not_found"
    assert result.error.message == "package check failed during stage: missing package"
    assert result.error.partial_result is not None
    assert result.error.partial_result["package_check"]["completed"] == ["validate"]
    assert result.child_stderr == "native stderr"


def test_incomplete_pck_failure_retains_snapshot_and_cleanup(monkeypatch, tmp_path):
    marker = tmp_path / "main-pack-launched"
    binary = tmp_path / "godot-editor-probe"
    binary.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys\n"
        f"marker = pathlib.Path({str(marker)!r})\n"
        "if '--main-pack' in sys.argv:\n"
        "    marker.write_text('launched')\n"
        "print('Options: \\n-e, --editor  Start the editor.')\n"
    )
    binary.chmod(0o755)
    package = tmp_path / "failed-export.pck"
    package.write_bytes(
        struct.pack(
            "<6I2Q16I",
            0x43504447,
            3,
            4,
            6,
            3,
            2,
            112,
            0,
            *([0] * 16),
        )
        + b"\0" * 8
    )
    expectations = tmp_path / "expectations.json"
    expectations.write_text(
        '{"checks":[{"id":"nodes","kind":"count","metric":"node_count","min":1}]}'
    )
    monkeypatch.setenv("GDA_USER_DATA_ROOT", str(tmp_path / "user-data"))

    result = run_asset_package_check(
        AssetPipelinePackageCheckParams(
            package=package,
            path="res://main.tscn",
            expectations=expectations,
        ),
        project=None,
        godot=str(binary),
    )

    assert isinstance(result, Failure)
    assert result.error.code == "operation_failed"
    assert result.error.partial_result is not None
    partial = result.error.partial_result["package_check"]
    assert partial["failure"]["stage"] == "presence"
    assert partial["package"]["source"] == str(package)
    assert (
        partial["package"]["sha256"] == hashlib.sha256(package.read_bytes()).hexdigest()
    )
    assert partial["package"]["size_bytes"] == 112
    assert partial["completed"] == ["validate", "stage", "cleanup"]
    assert partial["cleanup"] == {"staging_removed": True, "issues": []}
    assert not Path(partial["package"]["root"]).exists()
    assert not marker.exists()


def test_package_load_recovery_is_consistent_in_json_and_human_output(
    monkeypatch, tmp_path
):
    package = tmp_path / "game.pck"
    package.write_bytes(b"fixture")
    expectations = tmp_path / "expectations.json"
    expectations.write_text('{"checks":[{"id":"root","kind":"node","node":"."}]}')
    engine = EngineVersion(
        major=4,
        minor=6,
        patch=3,
        hex=0x40603,
        status="stable",
        build="official",
        hash="abc",
        string="4.6.3.stable.official",
        timestamp=0,
    )
    monkeypatch.setattr(
        "gda.integrations.package.run_package_resource_presence_operation",
        lambda *args, **kwargs: PackageResourcePresenceResult.model_validate(
            {
                "engine_version": engine.model_dump(),
                "resources": [{"path": "res://wrapper.tscn", "present": True}],
            }
        ),
    )
    monkeypatch.setattr(
        "gda.integrations.package.run_package_inspect_model_operation",
        lambda *args, **kwargs: make_failure(
            "not_a_scene",
            "imported sources may need resource import",
            "ERROR: Cannot open file 'res://accent.tres'.",
        ),
    )
    args = [
        "asset-pipeline",
        "check-package",
        "--package",
        str(package),
        "--path",
        "res://wrapper.tscn",
        "--expectations",
        str(expectations),
    ]
    runner = CliRunner()

    structured = runner.invoke(app, [*args, "--json"])
    human = runner.invoke(app, args)

    assert structured.exit_code == human.exit_code == 4
    error = json.loads(structured.stdout)["error"]
    assert error["message"] in human.stdout
    assert error["diagnostics"] in human.stdout
    assert "check export inclusion and dependencies" in error["message"]
    assert "does not establish that a dependency is missing" in error["message"]
    assert "resource import" not in error["message"]
    partial = error["partial_result"]["package_check"]
    assert partial["failure"]["cause"]["message"] == error["message"].removeprefix(
        "package check failed during inspect: "
    )
    assert partial["cleanup"] == {"staging_removed": True, "issues": []}
    assert not Path(partial["package"]["root"]).exists()


def test_human_result_names_editor_evidence_verdict_and_cleanup(monkeypatch, tmp_path):
    package = tmp_path / "game.pck"
    expectations = tmp_path / "expectations.json"

    def check(request, *, godot):
        return PackageCheckResult(
            request=request,
            package=PackageSnapshot("source", package, tmp_path, "a" * 64, 42),
            presence=PackagePresence(PackageEngine("4.5.stable", "abc"), ()),
            exclusions=(PackageExclusion("res://debug.gd", False, "pass"),),
            check=ModelCheckResult(
                resource="res://model.glb",
                verdict="fail",
                checks=[
                    CheckResult(
                        "left-arm",
                        "fail",
                        {"node": "Arm_L"},
                        {},
                        None,
                        "Required node and type",
                    )
                ],
            ),
            verdict="fail",
            cleanup=PackageCleanup(staging_removed=True),
        )

    monkeypatch.setattr("gda.commands.asset_pipeline.check_package", check)
    result = CliRunner().invoke(
        app,
        [
            "asset-pipeline",
            "check-package",
            "--package",
            str(package),
            "--path",
            "res://model.glb",
            "--expectations",
            str(expectations),
            "--exclude",
            "res://debug.gd",
        ],
    )

    assert result.exit_code == 0, result.output
    assert all(
        fact in result.stdout
        for fact in (
            "editor inspection",
            "res://model.glb",
            "sha256=" + "a" * 64,
            "4.5.stable (abc)",
            "exclusion pass: res://debug.gd present=False",
            "staging_removed=True",
            "left-arm: Required node and type",
        )
    )
