"""Returning package-only resource operations and isolated runner."""

from pathlib import Path

from gda.commands.resource import (
    PackageResourcePresenceParams,
    PackageResourcePresenceResult,
    ResourceInspectModelParams,
    ResourceInspectModelResult,
    run_package_inspect_model_operation,
    run_package_resource_presence_operation,
)
from gda.errors import Failure
from gda.package_runner import PackageGodotRunner
from gda.parser import build_result
from gda.runner import RunResult


ENGINE = {
    "major": 4,
    "minor": 6,
    "patch": 3,
    "hex": 263683,
    "status": "stable",
    "build": "official",
    "hash": "abc",
    "timestamp": 0,
    "string": "4.6.3-stable (official)",
}


class _Runner:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def run(self, operation, params):
        self.calls.append((operation, params))
        return RunResult(build_result(self.payload), "", 0)


def _package(tmp_path: Path, suffix: str = ".pck") -> Path:
    package = tmp_path / f"game{suffix}"
    package.write_bytes(b"package")
    return package


def test_package_runner_requires_editor_help_and_uses_isolated_main_pack(tmp_path):
    calls = []
    working_directories = []

    def launch(
        binary, args, *, cwd, timeout, timeout_label="Godot operation", **_kwargs
    ):
        calls.append(args)
        working_directories.append(cwd)
        assert cwd.is_dir()
        if args == ["--help"]:
            return RunResult("Option legend (this build = editor)\n-e, --editor", "", 0)
        return RunResult(build_result({"ok": True}), "", 0)

    package = _package(tmp_path)
    outcome = PackageGodotRunner(Path("/godot"), package, make_launch=launch).run(
        "test-op", {"path": "res://model.glb"}
    )

    assert outcome.exit_code == 0
    assert calls[1][:2] == ["--main-pack", str(package)]
    assert "--path" not in calls[1]
    assert calls[1][-3:] == [
        "--",
        "test-op",
        '{"path": "res://model.glb"}',
    ]
    assert working_directories[0] == working_directories[1]
    assert not working_directories[0].exists()


def test_package_runner_refuses_path_enabled_template_without_running_payload(tmp_path):
    calls = []

    def launch(
        binary, args, *, cwd, timeout, timeout_label="Godot operation", **_kwargs
    ):
        calls.append(args)
        return RunResult(
            "Option legend (this build = release export template)\n"
            "X --main-pack <file>\nX --script <script>",
            "",
            0,
        )

    result = PackageGodotRunner(
        Path("/template"), _package(tmp_path), make_launch=launch
    ).run("test-op", {})

    assert calls == [["--help"]]
    assert "operation_failed" in result.stdout
    assert "requires a Godot editor binary" in result.stdout


def test_package_inspection_returns_the_existing_typed_model(tmp_path):
    package = _package(tmp_path)
    runner = _Runner(
        {
            "path": "res://model.glb",
            "subtree": ".",
            "engine_version": ENGINE,
            "measurement": {
                "coordinate_space": "resource",
                "geometry": "static_mesh_aabb",
                "limitations": [],
            },
            "nodes": [],
            "summary": {
                "node_count": 0,
                "mesh_instance_count": 0,
                "unique_mesh_count": 0,
            },
            "bounds": None,
            "truncated": False,
            "omissions": [],
        }
    )
    seen = []

    def factory(_binary, selected):
        seen.append(selected)
        return runner

    result = run_package_inspect_model_operation(
        package,
        ResourceInspectModelParams(path="res://model.glb"),
        godot="/godot",
        make_runner=factory,
    )

    assert isinstance(result, ResourceInspectModelResult)
    assert result.engine_version.string == "4.6.3-stable (official)"
    assert seen == [package.absolute()]
    assert runner.calls[0][0] == "resource-inspect-model"


def test_package_presence_preserves_requested_order_and_native_engine(tmp_path):
    runner = _Runner(
        {
            "engine_version": ENGINE,
            "resources": [
                {"path": "res://included.glb", "present": True},
                {"path": "res://omitted.glb", "present": False},
            ],
        }
    )
    result = run_package_resource_presence_operation(
        _package(tmp_path),
        PackageResourcePresenceParams(
            paths=["res://included.glb", "res://omitted.glb"]
        ),
        godot="/godot",
        make_runner=lambda _binary, _package: runner,
    )

    assert isinstance(result, PackageResourcePresenceResult)
    assert [(item.path, item.present) for item in result.resources] == [
        ("res://included.glb", True),
        ("res://omitted.glb", False),
    ]
    assert result.engine_version.hash == "abc"


def test_package_presence_rejects_a_reply_for_different_paths(tmp_path):
    runner = _Runner(
        {
            "engine_version": ENGINE,
            "resources": [{"path": "res://other.glb", "present": True}],
        }
    )
    result = run_package_resource_presence_operation(
        _package(tmp_path),
        PackageResourcePresenceParams(paths=["res://model.glb"]),
        godot="/godot",
        make_runner=lambda _binary, _package: runner,
    )

    assert isinstance(result, Failure)
    assert result.error.code == "contract_violation"


def test_package_inputs_reject_zip_missing_package_and_non_resource_path(tmp_path):
    zip_result = run_package_inspect_model_operation(
        _package(tmp_path, ".zip"), ResourceInspectModelParams(path="res://model.glb")
    )
    missing_result = run_package_inspect_model_operation(
        tmp_path / "missing.pck", ResourceInspectModelParams(path="res://model.glb")
    )
    path_result = run_package_resource_presence_operation(
        _package(tmp_path), PackageResourcePresenceParams(paths=["model.glb"])
    )

    assert isinstance(zip_result, Failure) and zip_result.error.code == "invalid_params"
    assert (
        isinstance(missing_result, Failure)
        and missing_result.error.code == "path_not_found"
    )
    assert isinstance(path_result, Failure) and path_result.error.code == "invalid_path"
