"""PCK returning operations projected into assets-owned package facts."""

import pytest

from gda.commands.resource import (
    PackageResourcePresenceResult,
    ResourceInspectModelResult,
)
from gda.errors import make_failure
from gda.integrations.package import GdaGodotPackagePort
from gda.models import EngineVersion
from gda_assets.api import PortFailure
from tests.asset_pipeline.test_model_report_validation import _report


ENGINE = EngineVersion(
    major=4,
    minor=5,
    patch=0,
    hex=0x40500,
    status="stable",
    build="official",
    hash="abc",
    string="4.5.stable.official",
    timestamp=0,
)


def test_package_adapter_preserves_engine_presence_and_model_scope(
    monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setattr(
        "gda.integrations.package.run_package_resource_presence_operation",
        lambda package, params, **kwargs: (
            calls.append((package, params, kwargs))
            or PackageResourcePresenceResult.model_validate(
                {
                    "engine_version": ENGINE.model_dump(),
                    "resources": [
                        {"path": "res://debug.gd", "present": False},
                        {"path": "res://secret.tres", "present": True},
                    ],
                }
            )
        ),
    )
    raw = _report()
    raw["engine_version"] = ENGINE.model_dump()
    monkeypatch.setattr(
        "gda.integrations.package.run_package_inspect_model_operation",
        lambda package, params, **kwargs: (
            calls.append((package, params, kwargs))
            or ResourceInspectModelResult.model_validate(raw)
        ),
    )
    package = tmp_path / "game.pck"
    port = GdaGodotPackagePort("godot")

    presence = port.resource_presence(package, ("res://debug.gd", "res://secret.tres"))
    inspection = port.inspect_model(
        package, "res://model.glb", subtree=".", max_nodes=12, max_items=34
    )

    assert presence.engine.version == "4.5.stable.official"
    assert presence.engine.build_hash == "abc"
    assert [(item.path, item.present) for item in presence.resources] == [
        ("res://debug.gd", False),
        ("res://secret.tres", True),
    ]
    assert inspection.engine == presence.engine
    assert inspection.model.resource == "res://model.glb"
    assert calls[0][1].paths == ["res://debug.gd", "res://secret.tres"]
    assert calls[1][1].max_nodes == 12 and calls[1][1].max_items == 34
    assert calls[0][2]["godot"] == calls[1][2]["godot"] == "godot"


def test_package_adapter_retains_native_failure(monkeypatch, tmp_path):
    failure = make_failure("path_not_found", "package missing", "native stderr")
    monkeypatch.setattr(
        "gda.integrations.package.run_package_resource_presence_operation",
        lambda *args, **kwargs: failure,
    )
    port = GdaGodotPackagePort()

    with pytest.raises(PortFailure, match="package missing") as raised:
        port.resource_presence(tmp_path / "missing.pck", ("res://model.glb",))

    assert raised.value.code == "path_not_found"
    assert port.last_failure is failure
    assert failure.child_stderr == "native stderr"
