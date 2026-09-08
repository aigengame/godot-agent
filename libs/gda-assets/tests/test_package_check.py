"""Package acceptance composes isolation with the existing expectation evaluator."""

from dataclasses import replace
from pathlib import Path

import pytest

from gda_assets.application.check import check_model
from gda_assets.application.package import check_package
from gda_assets.application.ports import PortFailure
from gda_assets.domain.expectations import Expectation
from gda_assets.domain.model import ModelFacts, NodeFacts
from gda_assets.domain.package import (
    PackageCheckRequest,
    PackageEngine,
    PackageInspection,
    PackagePresence,
    PackageResource,
    PackageSnapshot,
)


ENGINE = PackageEngine("4.6.3-stable (official)", "abc123")
MODEL = ModelFacts(
    "res://model.glb",
    ".",
    (4, 6),
    ("resource", "imported_mesh"),
    (NodeFacts(".", "Node3D"), NodeFacts("Arm_L", "MeshInstance3D")),
    {"nodes": 2},
    None,
)
CONDITIONS = (Expectation("left-arm", "node", "Arm_L", {"type": "MeshInstance3D"}),)


class Files:
    def __init__(self, root: Path):
        self.snapshot_value = PackageSnapshot(
            str(root / "source.pck"),
            root / "stage" / "model.pck",
            root / "stage",
            "a" * 64,
            12,
        )
        self.removed = []

    def snapshot(self, source):
        return self.snapshot_value

    def remove(self, snapshot):
        self.removed.append(snapshot)


class Godot:
    def __init__(self):
        self.calls = []

    def resource_presence(self, package, paths):
        self.calls.append(("presence", package))
        return PackagePresence(
            ENGINE, tuple(PackageResource(path, False) for path in paths)
        )

    def inspect_model(self, package, path, **scope):
        self.calls.append(("inspect", package))
        return PackageInspection(ENGINE, MODEL)


def request(root: Path, **kwargs):
    return PackageCheckRequest(
        root / "source.pck", "res://model.glb", root / "rules.json", **kwargs
    )


def test_package_uses_staged_bytes_and_same_evaluator(tmp_path):
    files, godot = Files(tmp_path), Godot()
    result = check_package(
        request(tmp_path, exclude=("res://dev/test.gd",)),
        CONDITIONS,
        godot=godot,
        files=files,
    )

    assert result.failure is None
    assert result.origin == "package_editor_inspection"
    assert result.verdict == "pass"
    assert result.check is not None
    assert result.check.checks[0].id == "left-arm"
    assert result.check.checks[0].actual == {"type": "MeshInstance3D"}
    assert result.exclusions[0].verdict == "pass"
    assert result.inspection is not None
    assert result.inspection.model is MODEL
    assert result.presence is not None and result.presence.engine == ENGINE
    assert godot.calls == [
        ("presence", files.snapshot_value.path),
        ("inspect", files.snapshot_value.path),
    ]
    assert files.removed == [files.snapshot_value]
    assert result.cleanup.staging_removed is True
    source_result = check_model(CONDITIONS, report=MODEL)
    assert result.check.checks == source_result.checks
    assert result.check.verdict == source_result.verdict


def test_excluded_resource_presence_is_a_content_failure(tmp_path):
    class IncludedDevelopmentFile(Godot):
        def resource_presence(self, package, paths):
            return PackagePresence(
                ENGINE, tuple(PackageResource(path, True) for path in paths)
            )

    files = Files(tmp_path)
    result = check_package(
        request(tmp_path, exclude=("res://dev.gd",)),
        CONDITIONS,
        godot=IncludedDevelopmentFile(),
        files=files,
    )
    assert result.failure is None
    assert result.check is not None and result.check.verdict == "pass"
    assert result.exclusions[0].verdict == "fail"
    assert result.verdict == "fail"
    assert result.cleanup.staging_removed


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        (replace(MODEL, nodes=()), "fail"),
        (replace(MODEL, nodes=(), omissions=((".", "nodes"),)), "insufficient"),
    ],
)
def test_model_failure_and_coverage_are_preserved(tmp_path, facts, expected):
    class ModelVariant(Godot):
        def inspect_model(self, package, path, **scope):
            return PackageInspection(ENGINE, facts)

    result = check_package(
        request(tmp_path), CONDITIONS, godot=ModelVariant(), files=Files(tmp_path)
    )
    assert result.verdict == expected
    assert result.failure is None
    assert result.inspection is not None
    assert result.inspection.model.omissions == facts.omissions


def test_load_failure_retains_engine_and_package_and_cleans_staging(tmp_path):
    class MissingModel(Godot):
        def inspect_model(self, package, path, **scope):
            raise PortFailure(
                "godot_failed", "No packaged model", cause={"code": "path_not_found"}
            )

    result = check_package(
        request(tmp_path), CONDITIONS, godot=MissingModel(), files=Files(tmp_path)
    )
    assert result.failure is not None and result.failure.stage == "inspect"
    assert result.failure.cause == {"code": "path_not_found"}
    assert result.package is not None
    assert result.presence is not None and result.presence.engine == ENGINE
    assert result.check is None and result.verdict is None
    assert result.cleanup.staging_removed


@pytest.mark.parametrize("load_fails", [False, True])
def test_cleanup_failure_does_not_replace_primary_failure(tmp_path, load_fails):
    class BrokenCleanup(Files):
        def remove(self, snapshot):
            raise PortFailure(
                "package_cleanup_failed", "Owned staging could not be removed"
            )

    class MaybeMissing(Godot):
        def inspect_model(self, package, path, **scope):
            if load_fails:
                raise PortFailure("godot_failed", "Package model missing")
            return super().inspect_model(package, path, **scope)

    result = check_package(
        request(tmp_path),
        CONDITIONS,
        godot=MaybeMissing(),
        files=BrokenCleanup(tmp_path),
    )
    assert result.failure is not None
    assert result.failure.stage == ("inspect" if load_fails else "cleanup")
    assert not result.cleanup.staging_removed
    assert result.cleanup.issues == ["Owned staging could not be removed"]
    assert result.verdict == (None if load_fails else "pass")


def test_failed_snapshot_never_asks_to_remove_unowned_source(tmp_path):
    class FailedStage(Files):
        def snapshot(self, source):
            raise PortFailure("package_stage_failed", "Copy failed")

    files, godot = FailedStage(tmp_path), Godot()
    result = check_package(request(tmp_path), CONDITIONS, godot=godot, files=files)
    assert result.failure is not None and result.failure.stage == "stage"
    assert not files.removed
    assert not godot.calls
    assert result.package is None


@pytest.mark.parametrize(
    "changed",
    [
        {"path": "../model.glb"},
        {"path": "res://../model.glb"},
        {"path": "res://model.glb\x00"},
        {"exclude": ("res://model.glb",)},
        {"exclude": ("res://dev.gd", "res://dev.gd")},
        {"exclude": tuple(f"res://dev/{i}.gd" for i in range(65))},
        {"subtree": "../Model"},
        {"max_nodes": True},
        {"max_items": 16385},
    ],
)
def test_invalid_request_has_no_external_effects(tmp_path, changed):
    files, godot = Files(tmp_path), Godot()
    result = check_package(
        replace(request(tmp_path), **changed), CONDITIONS, godot=godot, files=files
    )
    assert result.failure is not None and result.failure.stage == "validate"
    assert result.package is None
    assert not godot.calls and not files.removed


@pytest.mark.parametrize(
    "kind",
    [
        "missing_presence",
        "duplicate_presence",
        "wrong_engine",
        "wrong_resource",
        "wrong_subtree",
    ],
)
def test_mismatched_observation_cannot_pass(tmp_path, kind):
    class Mismatched(Godot):
        def resource_presence(self, package, paths):
            if kind == "missing_presence":
                return PackagePresence(ENGINE, ())
            if kind == "duplicate_presence":
                return PackagePresence(ENGINE, (PackageResource(paths[0], False),) * 2)
            return super().resource_presence(package, paths)

        def inspect_model(self, package, path, **scope):
            if kind == "wrong_engine":
                return PackageInspection(PackageEngine("4.7", "different"), MODEL)
            if kind == "wrong_resource":
                return PackageInspection(
                    ENGINE, replace(MODEL, resource="res://other.glb")
                )
            return PackageInspection(ENGINE, replace(MODEL, subtree="Arm_L"))

    result = check_package(
        request(tmp_path), CONDITIONS, godot=Mismatched(), files=Files(tmp_path)
    )
    assert result.failure is not None
    assert result.failure.code == "invalid_package_observation"
    assert result.verdict is None and result.check is None
    assert result.cleanup.staging_removed


def test_sixty_four_exclusions_fit_the_bounded_engine_call(tmp_path):
    class Bounded(Godot):
        def resource_presence(self, package, paths):
            assert len(paths) == 64
            return super().resource_presence(package, paths)

    excluded = tuple(f"res://dev/{i}.gd" for i in range(64))
    result = check_package(
        request(tmp_path, exclude=excluded),
        CONDITIONS,
        godot=Bounded(),
        files=Files(tmp_path),
    )
    assert result.verdict == "pass"
    assert len(result.exclusions) == 64
