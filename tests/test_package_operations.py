"""Returning package-only resource operations and isolated runner."""

from pathlib import Path
import struct

import pytest

from gda.commands.resource import (
    PackageResourcePresenceParams,
    PackageResourcePresenceResult,
    ResourceInspectModelParams,
    ResourceInspectModelResult,
    run_package_inspect_model_operation,
    run_package_resource_presence_operation,
)
from gda.errors import Failure
from gda.package_runner import PackageGodotRunner, make_package_runner
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


def _godot_v3_pck_header(
    *, directory_offset: int, file_base: int = 112, format_version: int = 3
) -> bytes:
    """The fixed Godot 4.6.3 V3 header, plus its 16-byte export alignment."""
    header = struct.pack(
        "<6I2Q16I",
        0x43504447,
        format_version,
        4,
        6,
        3,
        2,
        file_base,
        directory_offset,
        *([0] * 16),
    )
    return header + b"\0" * 8


def test_package_runner_uses_isolated_main_pack(tmp_path):
    calls = []
    working_directories = []

    def launch(
        binary, args, *, cwd, timeout, timeout_label="Godot operation", **_kwargs
    ):
        calls.append(args)
        working_directories.append(cwd)
        assert cwd.is_dir()
        return RunResult(build_result({"ok": True}), "", 0)

    package = _package(tmp_path)
    outcome = PackageGodotRunner(Path("/godot"), package, make_launch=launch).run(
        "test-op", {"path": "res://model.glb"}
    )

    assert outcome.exit_code == 0
    assert calls[0][:2] == ["--main-pack", str(package)]
    assert "--path" not in calls[0]
    assert calls[0][-3:] == [
        "--",
        "test-op",
        '{"path": "res://model.glb"}',
    ]
    assert not working_directories[0].exists()


def test_returning_operation_refuses_template_before_running_payload(tmp_path):
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

    package = _package(tmp_path)
    result = run_package_resource_presence_operation(
        package,
        PackageResourcePresenceParams(paths=["res://model.glb"]),
        godot="/template",
        make_runner=lambda binary, selected: make_package_runner(
            binary, selected, make_launch=launch
        ),
    )

    assert calls == [["--help"]]
    assert isinstance(result, Failure)
    assert result.error.code == "operation_failed"
    assert "requires a Godot desktop editor binary" in result.error.message
    assert "release export template" in result.error.diagnostics


def test_returning_operation_refuses_an_incomplete_v3_pck_before_main_pack(
    tmp_path,
):
    calls = []

    def launch(
        binary, args, *, cwd, timeout, timeout_label="Godot operation", **_kwargs
    ):
        calls.append(args)
        if args == ["--help"]:
            return RunResult("Options:\n-e, --editor  Start the editor.\n", "", 0)
        return RunResult(
            build_result(
                {
                    "engine_version": ENGINE,
                    "resources": [{"path": "res://model.glb", "present": False}],
                }
            ),
            "",
            0,
        )

    package = tmp_path / "failed-export.pck"
    package.write_bytes(_godot_v3_pck_header(directory_offset=0))
    result = run_package_resource_presence_operation(
        package,
        PackageResourcePresenceParams(paths=["res://model.glb"]),
        godot="/godot",
        make_runner=lambda binary, selected: make_package_runner(
            binary, selected, make_launch=launch
        ),
    )

    assert calls == [["--help"]]
    assert isinstance(result, Failure)
    assert result.error.code == "operation_failed"
    assert "incomplete Godot PCK" in result.error.message
    assert str(package) in result.error.diagnostics
    assert "format version: 3" in result.error.diagnostics
    assert "directory offset: 0" in result.error.diagnostics


@pytest.mark.parametrize(
    "contents",
    [
        b"package",
        b"NOPE" + _godot_v3_pck_header(directory_offset=0)[4:],
        _godot_v3_pck_header(directory_offset=0, format_version=99),
        _godot_v3_pck_header(directory_offset=128, file_base=128)
        + b"\0" * 16
        + struct.pack("<I", 0),
    ],
    ids=("short", "opaque", "unknown-format", "legal-empty-v3"),
)
def test_package_admission_leaves_other_artifacts_to_godot(tmp_path, contents):
    calls = []

    def launch(
        binary, args, *, cwd, timeout, timeout_label="Godot operation", **_kwargs
    ):
        calls.append(args)
        return RunResult("Options:\n-e, --editor  Start the editor.\n", "", 0)

    package = tmp_path / "package.pck"
    package.write_bytes(contents)
    result = make_package_runner(Path("/godot"), package, make_launch=launch)

    assert isinstance(result, PackageGodotRunner)
    assert calls == [["--help"]]


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
