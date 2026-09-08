"""Native gda facts projected through the isolated preview host."""

import pytest

from gda.commands.diag import DiagErrorsResult
from gda.commands.game import GameGetResult, GameSetResult
from gda.commands.perf import PerfMonitorsResult
from gda.commands.resource import ResourceInspectModelResult
from gda.commands.screen import ScreenCaptureResult
from gda.errors import make_failure
from gda.integrations.preview import GdaGodotPreviewPort, GdaPreviewHost
from gda_assets.api import PortFailure


def test_preview_adapter_projects_inspection_and_view_state(monkeypatch, tmp_path):
    report = ResourceInspectModelResult.model_validate(
        {
            "path": "res://model.glb",
            "subtree": ".",
            "engine_version": {
                "major": 4,
                "minor": 6,
                "patch": 0,
                "hex": 0,
                "status": "stable",
                "build": "official",
                "hash": "abc",
                "string": "4.6.stable.official",
                "timestamp": 0,
            },
            "measurement": {
                "coordinate_space": "resource",
                "geometry": "static_mesh_aabb",
                "limitations": ["static only"],
            },
            "nodes": [
                {
                    "path": ".",
                    "type": "Node3D",
                    "local_transform": None,
                    "resource_transform": None,
                    "mesh": None,
                    "skeleton": None,
                    "animation_player": None,
                }
            ],
            "summary": {
                "node_count": 1,
                "mesh_instance_count": 0,
                "unique_mesh_count": 0,
            },
            "bounds": {"position": [1, 2, 3], "size": [4, 5, 6]},
            "truncated": True,
            "omissions": [
                {"node_path": ".", "section": "nodes", "reason": "node_limit"}
            ],
        }
    )
    state = {
        "index": 1,
        "camera": {
            "name": "side",
            "position": [2, 0, 0],
            "target": [0, 0, 0],
            "size": 3.0,
            "near": 0.1,
            "far": 20.0,
            "up": [0, 1, 0],
        },
        "viewport": [640, 360],
        "renderer": "gl_compatibility",
        "engine": "4.6.stable.official",
        "platform": "macOS",
        "pose": "static_imported",
        "background": [0.1, 0.2, 0.3, 1.0],
        "ambient_energy": 0.5,
        "light_energy": 1.0,
        "light_rotation": [-0.5, 0.4, 0.0],
        "overlays": ["axes"],
    }
    monkeypatch.setattr(
        "gda.integrations.preview.run_resource_inspect_model_operation",
        lambda *a, **k: report,
    )
    monkeypatch.setattr(
        "gda.integrations.preview.run_game_get_operation",
        lambda *a, **k: GameGetResult.model_validate(
            {
                "path": "/root/Preview",
                "name": "Preview",
                "type": "Node3D",
                "properties": [
                    {"name": "view_state", "type": "Dictionary", "value": state}
                ],
            }
        ),
    )
    port = GdaGodotPreviewPort(tmp_path)

    inspection = port.inspect_preview(10)
    observed = port.observe_view()

    assert inspection.engine == "4.6.stable.official"
    assert inspection.bounds is not None and inspection.bounds.size == (4.0, 5.0, 6.0)
    assert inspection.omissions == ((".", "nodes"),)
    assert observed.camera.name == "side"
    assert observed.viewport == (640, 360)
    assert observed.light_rotation == (-0.5, 0.4, 0.0)


def test_select_and_capture_use_fixture_contract_and_preserve_receipt(
    monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setattr(
        "gda.integrations.preview.run_game_set_operation",
        lambda project, params: (
            calls.append(params)
            or GameSetResult(
                path="/root/Preview",
                property="view_index",
                type="int",
                value=2,
                verified=True,
            )
        ),
    )
    capture = ScreenCaptureResult.model_validate(
        {
            "path": str(tmp_path / "side.png"),
            "width": 640,
            "height": 360,
            "bytes": 12,
            "receipt": {
                "session_id": "session-2",
                "scene_path": "res://preview.tscn",
                "scene_uid": None,
                "engine_frame": 90,
                "observed": 2,
                "sha256": "a" * 64,
            },
            "predicate": {
                "node": "/root/Preview",
                "property": "applied_view",
                "expected": 2,
                "observed": 2,
                "engine_frame": 90,
                "frames_waited": 4,
            },
        }
    )
    monkeypatch.setattr(
        "gda.integrations.preview.run_screen_capture_operation",
        lambda project, params: calls.append(params) or capture,
    )
    port = GdaGodotPreviewPort(tmp_path)

    port.select_view(2)
    result = port.capture_view(2, tmp_path / "side.png")

    assert calls[0].property == "view_index" and calls[0].value == "2"
    assert calls[1].await_property == "applied_view" and calls[1].await_frames == 120
    assert result.receipt.session_id == "session-2"
    assert result.receipt.launched_scene == "res://preview.tscn"
    assert (result.width, result.height, result.frames_waited, result.applied_view) == (
        640,
        360,
        4,
        2,
    )


def test_performance_and_diagnostics_preserve_native_verdicts_and_bound_output(
    monkeypatch, tmp_path
):
    perf = PerfMonitorsResult.model_validate(
        {
            "kind": "window",
            "frames": 2,
            "max_frames": 120,
            "stats": {
                "fps": {
                    "count": 2,
                    "min": 59.0,
                    "max": 60.0,
                    "mean": 59.5,
                    "p50": 59.0,
                    "p95": 60.0,
                }
            },
            "samples": [
                {"frame": 0, "timestamp": 10, "values": {"fps": 59.0}},
                {"frame": 1, "timestamp": 11, "values": {"fps": 60.0}},
            ],
            "budget": {
                "fps": {
                    "stat": "p50",
                    "value": 59.0,
                    "min": 60.0,
                    "max": None,
                    "passed": False,
                }
            },
            "passed": False,
        }
    )
    errors = [{"level": "error", "message": f"failure {i}"} for i in range(65)]
    seen = []
    monkeypatch.setattr(
        "gda.integrations.preview.run_perf_monitors_operation",
        lambda project, params: seen.append(params) or perf,
    )
    monkeypatch.setattr(
        "gda.integrations.preview.run_diag_errors_operation",
        lambda project, params: (
            seen.append(params) or DiagErrorsResult.model_validate({"errors": errors})
        ),
    )
    port = GdaGodotPreviewPort(tmp_path)

    performance = port.performance(2, budget=True)
    diagnostics = port.diagnostics()

    assert [item.value for item in seen[0].monitors] == [
        "fps",
        "draw_calls",
        "primitives_in_frame",
    ]
    assert seen[0].budget == str(tmp_path / "budget.json")
    assert performance.budget is not None
    assert performance.passed is False and performance.budget["fps"].passed is False
    assert len(diagnostics.errors) == 64 and diagnostics.truncated is True
    assert seen[1].limit == 65


def test_contract_failure_and_host_retain_primary_native_failure(monkeypatch, tmp_path):
    failure = make_failure("daemon_not_running", "start daemon", "native stderr")
    monkeypatch.setattr(
        "gda.integrations.preview.run_game_get_operation", lambda *a, **k: failure
    )
    host = GdaPreviewHost("godot")
    port = host(tmp_path)

    with pytest.raises(PortFailure, match="start daemon"):
        port.observe_view()

    assert host.last_failure is failure
    assert port._godot == "godot"


def test_malformed_view_state_becomes_contract_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "gda.integrations.preview.run_game_get_operation",
        lambda *a, **k: GameGetResult.model_validate(
            {
                "path": "/root/Preview",
                "name": "Preview",
                "type": "Node3D",
                "properties": [
                    {
                        "name": "view_state",
                        "type": "Dictionary",
                        "value": {
                            "index": True,
                            "camera": {"name": "front", "position": [0, 1]},
                        },
                    }
                ],
            }
        ),
    )
    port = GdaGodotPreviewPort(tmp_path)

    with pytest.raises(PortFailure) as raised:
        port.observe_view()

    assert raised.value.code == "contract_violation"
    assert port.last_failure is not None
    assert port.last_failure.error.code == "contract_violation"
