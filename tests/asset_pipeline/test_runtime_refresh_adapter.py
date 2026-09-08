"""gda's returning operations projected through the asset refresh port."""

import pytest

from gda.commands.daemon import (
    DaemonStartResult,
    DaemonStatusResult,
    DaemonStopResult,
    DaemonWaitReadyResult,
)
from gda.commands.game import GameInspectModelContentResult
from gda.commands.resource import ResourceInspectModelContentResult
from gda.commands.screen import CaptureReceipt, ScreenCaptureResult
from gda.errors import make_failure
from gda.integrations.asset_pipeline import GdaGodotAssetPort
from gda.model_content import ModelContent as NativeModelContent
from gda.models import EngineVersion
from gda_assets.api import PortFailure


ENGINE = EngineVersion(
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


def _content(digest: str = "a" * 64) -> NativeModelContent:
    return NativeModelContent(
        measurement="godot-static-model-content-v1",
        engine_version=ENGINE,
        complete=True,
        digest=digest,
        nodes=2,
        surfaces=1,
        vertices=3,
        unsupported=[],
        omitted=[],
    )


def test_adapter_projects_native_content_lifecycle_and_capture(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "gda.integrations.asset_pipeline.run_resource_inspect_model_content_operation",
        lambda *args, **kwargs: ResourceInspectModelContentResult(
            path="res://model.glb", content=_content()
        ),
    )
    statuses = iter(
        [
            DaemonStatusResult(
                running=True,
                pid=10,
                socket_path="/tmp/gda.sock",
                windowed=False,
                session_id="old-session",
            ),
            DaemonStatusResult(
                running=True,
                pid=11,
                socket_path="/tmp/gda.sock",
                windowed=True,
                session_id="new-session",
            ),
        ]
    )
    monkeypatch.setattr(
        "gda.integrations.asset_pipeline.run_daemon_status_operation",
        lambda *args, **kwargs: next(statuses),
    )
    monkeypatch.setattr(
        "gda.integrations.asset_pipeline.run_daemon_stop_operation",
        lambda *args, **kwargs: DaemonStopResult(stopped=True, pid=10),
    )
    monkeypatch.setattr(
        "gda.integrations.asset_pipeline.run_daemon_start_operation",
        lambda *args, **kwargs: DaemonStartResult(
            pid=11,
            socket_path="/tmp/gda.sock",
            installed_harness=False,
            harness_synced=False,
            harness_version="1",
            created_paths=[],
            created_sections=[],
            windowed=True,
            already_running=False,
        ),
    )
    monkeypatch.setattr(
        "gda.integrations.asset_pipeline.run_daemon_wait_ready_operation",
        lambda *args, **kwargs: DaemonWaitReadyResult(pid=11, launched=True),
    )
    monkeypatch.setattr(
        "gda.integrations.asset_pipeline.run_game_inspect_model_content_operation",
        lambda *args, **kwargs: GameInspectModelContentResult(
            node="/root/Main/Model",
            instance_id=42,
            scene_file_path="res://model.glb",
            session_id="new-session",
            engine_frame=17,
            content=_content(),
        ),
    )
    capture_path = tmp_path / "capture.png"
    monkeypatch.setattr(
        "gda.integrations.asset_pipeline.run_screen_capture_operation",
        lambda *args, **kwargs: ScreenCaptureResult(
            path=str(capture_path),
            width=8,
            height=8,
            bytes=12,
            receipt=CaptureReceipt(
                session_id="new-session",
                scene_path="res://launch.tscn",
                scene_uid=None,
                engine_frame=18,
                observed=None,
                sha256="b" * 64,
            ),
        ),
    )

    port = GdaGodotAssetPort(tmp_path, godot="godot")
    imported = port.inspect_content("res://model.glb", max_nodes=8, max_vertices=20)
    before = port.status()
    stopped = port.stop()
    started = port.start("res://launch.tscn", windowed=True)
    ready = port.wait_ready(7.5)
    after = port.status()
    instance = port.observe_content("/root/Main/Model", max_nodes=8, max_vertices=20)
    capture = port.capture(capture_path)

    assert imported.path == "res://model.glb"
    assert imported.content.engine == "4.6.3.stable.official"
    assert imported.content.digest == "a" * 64
    assert before.session_id == "old-session"
    assert after.session_id == "new-session"
    assert stopped == {"stopped": True, "pid": 10}
    assert started["pid"] == 11
    assert ready == {"pid": 11, "launched": True}
    assert instance.node == "/root/Main/Model"
    assert instance.instance_id == 42
    assert instance.scene_file_path == "res://model.glb"
    assert instance.session_id == "new-session"
    assert instance.engine_frame == 17
    assert instance.content.engine == "4.6.3.stable.official"
    assert capture.path == str(capture_path)
    assert capture.session_id == "new-session"
    assert capture.launched_scene == "res://launch.tscn"
    assert capture.engine_frame == 18
    assert capture.sha256 == "b" * 64


def test_final_status_failure_does_not_replace_primary_native_failure(
    monkeypatch, tmp_path
):
    primary = make_failure("operation_failed", "content sampling failed", "sample")
    secondary = make_failure("daemon_not_running", "daemon stopped", "status")
    monkeypatch.setattr(
        "gda.integrations.asset_pipeline.run_resource_inspect_model_content_operation",
        lambda *args, **kwargs: primary,
    )
    monkeypatch.setattr(
        "gda.integrations.asset_pipeline.run_daemon_status_operation",
        lambda *args, **kwargs: secondary,
    )
    port = GdaGodotAssetPort(tmp_path)

    with pytest.raises(PortFailure, match="content sampling failed"):
        port.inspect_content("res://model.glb", max_nodes=8, max_vertices=20)
    with pytest.raises(PortFailure, match="daemon stopped"):
        port.status()

    assert port.last_failure is primary


def test_adapter_forwards_a_native_contract_refusal(monkeypatch, tmp_path):
    failure = make_failure("contract_violation", "corrupt content reply", "payload")
    monkeypatch.setattr(
        "gda.integrations.asset_pipeline.run_game_inspect_model_content_operation",
        lambda *args, **kwargs: failure,
    )
    port = GdaGodotAssetPort(tmp_path)

    with pytest.raises(PortFailure) as caught:
        port.observe_content("/root/Main/Model", max_nodes=8, max_vertices=20)

    assert caught.value.code == "contract_violation"
    assert caught.value.cause is not None
    assert caught.value.cause["diagnostics"] == "payload"
    assert port.last_failure is failure
