"""Returning resource-load operation used by composite workflows (#908)."""

from gda.commands.resource import (
    ResourceLoadResult,
    run_resource_load_operation,
)
from gda.errors import Failure, make_failure
from gda.models import EngineVersion


VERSION = EngineVersion(
    major=4,
    minor=6,
    patch=3,
    hex=0x040603,
    status="stable",
    build="official",
    hash="test",
    string="4.6.3-stable (official)",
    timestamp=0,
)


def test_resource_load_operation_returns_typed_engine_observation(
    monkeypatch, tmp_path
):
    project = tmp_path / "project"
    project.mkdir()
    (project / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    texture = project / "art" / "icon.png"
    texture.parent.mkdir()
    texture.write_bytes(b"png")
    expected = ResourceLoadResult(
        path="res://art/icon.png",
        resource_type="CompressedTexture2D",
        engine_version=VERSION,
        texture_size=[16, 8],
    )
    seen = {}

    def execute(params, *, godot, project):
        seen.update(params=params, godot=godot, project=project)
        return expected

    monkeypatch.setattr("gda.commands.resource._execute_resource_load", execute)

    outcome = run_resource_load_operation(project, texture, godot="/tmp/Godot")

    assert outcome is expected
    assert seen["params"].model_dump() == {"path": "res://art/icon.png"}
    assert seen["godot"] == "/tmp/Godot"
    assert seen["project"] == project


def test_resource_load_operation_rejects_escape_before_engine(monkeypatch, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"png")

    monkeypatch.setattr(
        "gda.commands.resource._execute_resource_load",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Godot must not run for an escaped target")
        ),
    )

    outcome = run_resource_load_operation(project, outside)

    assert isinstance(outcome, Failure)
    assert outcome.error.code == "target_outside_project"


def test_resource_load_operation_preserves_engine_failure(monkeypatch, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    missing = project / "missing.glb"

    expected = make_failure("path_not_found", "resource not found", "")
    monkeypatch.setattr(
        "gda.commands.resource._execute_resource_load",
        lambda params, *, godot, project: expected,
    )

    outcome = run_resource_load_operation(project, missing)

    assert outcome is expected
