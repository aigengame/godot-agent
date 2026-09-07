import pytest

from gda.commands.resource import (
    ResourceImportAsset,
    ResourceImportResult,
    ResourceImportSummary,
    ResourceLoadResult,
)
from gda.errors import make_failure
from gda.integrations.asset_pipeline import GdaGodotAssetPort
from gda.models import EngineVersion
from gda_assets.api import PortFailure


def _version() -> EngineVersion:
    return EngineVersion(
        major=4,
        minor=6,
        patch=3,
        hex=0,
        status="stable",
        build="official",
        hash="",
        string="4.6.3",
        timestamp=0,
    )


def test_host_adapter_projects_returning_gda_operations(monkeypatch, tmp_path):
    imported = ResourceImportResult(
        dry_run=False,
        cache_root="res://.godot",
        engine_pass=True,
        assets=[ResourceImportAsset(path="res://art/icon.png", status="imported")],
        created=[],
        summary=ResourceImportSummary(
            requested=1,
            cached=0,
            missing=0,
            stale=0,
            invalid=0,
            imported=1,
            not_importable=0,
            failed=0,
            created_cache_owned=0,
            created_source_adjacent=0,
        ),
    )
    loaded = ResourceLoadResult(
        path="res://art/icon.png",
        resource_type="CompressedTexture2D",
        engine_version=_version(),
        texture_size=[32, 16],
    )
    monkeypatch.setattr(
        "gda.integrations.asset_pipeline.run_resource_import_operation",
        lambda *args, **kwargs: imported,
    )
    monkeypatch.setattr(
        "gda.integrations.asset_pipeline.run_resource_load_operation",
        lambda *args, **kwargs: loaded,
    )

    port = GdaGodotAssetPort(tmp_path, "/Godot")

    assert port.import_assets(["res://art/icon.png"]).facts["engine_pass"] is True
    observation = port.check_load("res://art/icon.png")
    assert observation.texture_size == (32, 16)
    assert observation.engine is not None
    assert observation.engine["string"] == "4.6.3"


def test_host_adapter_retains_the_underlying_gda_failure(monkeypatch, tmp_path):
    failure = make_failure("operation_failed", "import failed", "engine stderr\n")
    monkeypatch.setattr(
        "gda.integrations.asset_pipeline.run_resource_import_operation",
        lambda *args, **kwargs: failure,
    )
    port = GdaGodotAssetPort(tmp_path)

    try:
        port.import_assets(["res://bad.glb"])
    except Exception as exc:
        assert getattr(exc, "code") == "operation_failed"
    else:
        raise AssertionError("expected the port to reject the import")
    assert port.last_failure is failure


def test_host_adapter_rejects_an_import_result_with_failed_assets(
    monkeypatch, tmp_path
):
    imported = ResourceImportResult(
        dry_run=False,
        cache_root="res://.godot",
        engine_pass=True,
        assets=[ResourceImportAsset(path="res://bad.glb", status="failed")],
        created=[],
        summary=ResourceImportSummary(
            requested=1,
            cached=0,
            missing=0,
            stale=0,
            invalid=0,
            imported=0,
            not_importable=0,
            failed=1,
            created_cache_owned=0,
            created_source_adjacent=0,
        ),
    )
    monkeypatch.setattr(
        "gda.integrations.asset_pipeline.run_resource_import_operation",
        lambda *args, **kwargs: imported,
    )

    with pytest.raises(PortFailure) as caught:
        GdaGodotAssetPort(tmp_path).import_assets(["res://bad.glb"])

    assert caught.value.code == "operation_failed"
    assert caught.value.cause is not None
    assert caught.value.cause["summary"]["failed"] == 1
