"""The workflow verifies observed instance content after explicit reset."""

from dataclasses import replace
import json
import struct

import pytest

from gda_assets.application.refresh import refresh_pipeline
from gda_assets.domain.artifacts import PipelineResult
from gda_assets.domain.refresh import (
    RefreshRequest,
    ModelContent,
    ImportedContent,
    InstanceContent,
    SessionState,
    CaptureObservation,
    ReadyObservation,
    StartObservation,
    StopObservation,
)
from gda_assets.application.ports import PortFailure


CONTENT = ModelContent("godot-static-model-content-v2", "4.6.3", True, "b" * 64)


class Runtime:
    def __init__(self):
        self.calls = []
        self.session = "A"

    def import_assets(self, paths):
        raise AssertionError("Invalid request must not import")

    def check_load(self, path):
        raise AssertionError("Invalid request must not load")

    def inspect_content(self, path, **limits):
        self.calls.append("imported")
        return ImportedContent(path, CONTENT)

    def status(self):
        self.calls.append("status")
        return SessionState(True, 42, True, self.session)

    def stop(self):
        self.calls.append("stop")
        return StopObservation(True, 41)

    def start(self, scene, *, windowed):
        self.calls.append(("start", scene, windowed))
        self.session = "B"
        return StartObservation(False, False, "1", (), (), 42, windowed, False)

    def wait_ready(self, timeout):
        self.calls.append(("ready", timeout))
        return ReadyObservation(43, True)

    def observe_content(self, node, **limits):
        self.calls.append("instance")
        return InstanceContent(node, 123, "res://model.glb", self.session, 7, CONTENT)

    def capture(self, output):
        raise AssertionError("No capture requested")


def test_refresh_verifies_new_session_and_actual_instance_without_disk_history():
    result = PipelineResult(completed=["import", "load"])
    port = Runtime()
    refresh_pipeline(
        result,
        RefreshRequest("res://model.glb", "res://test.tscn", "/root/Test/Model", True),
        port,
    )

    assert result.failure is None
    assert result.refresh is not None
    assert result.refresh.before is not None
    assert result.refresh.after is not None
    assert result.refresh.instance is not None
    assert result.refresh.comparison is not None
    assert result.refresh.status == "verified"
    assert result.refresh.before.session_id == "A"
    assert result.refresh.after.session_id == "B"
    assert result.refresh.instance.instance_id == 123
    assert result.refresh.runtime_state_preserved is False
    assert result.refresh.comparison.status == "match"
    assert port.calls == [
        "imported",
        "status",
        "stop",
        ("start", "res://test.tscn", True),
        ("ready", 25.0),
        "status",
        "instance",
        "status",
    ]
    assert result.content_observations is None


@pytest.mark.parametrize(
    "failure_stage", ["start", "spawn_io", "ready", "instance", "final_status"]
)
def test_runtime_failure_preserves_completed_import_and_reports_final_state(
    failure_stage,
):
    class Failing(Runtime):
        def start(self, scene, *, windowed):
            if failure_stage == "spawn_io":
                raise OSError("spawn failed")
            if failure_stage == "start":
                self.session = None
                raise PortFailure("binary_not_found", "missing engine")
            return super().start(scene, windowed=windowed)

        def wait_ready(self, timeout):
            if failure_stage == "ready":
                raise PortFailure("launch_timeout", "readiness expired")
            return super().wait_ready(timeout)

        def observe_content(self, node, **limits):
            self.calls.append("observed")
            if failure_stage == "instance":
                raise PortFailure("node_not_found", "selected instance missing")
            return super().observe_content(node, **limits)

        def status(self):
            if failure_stage == "final_status" and "observed" in self.calls:
                raise PortFailure("daemon_not_running", "final state unavailable")
            return super().status()

    result = PipelineResult(completed=["import", "load"])
    refresh_pipeline(
        result,
        RefreshRequest("res://model.glb", "res://test.tscn", "/root/Test/Model", True),
        Failing(),
    )
    assert result.failure is not None
    assert result.refresh is not None
    assert result.refresh.status == "incomplete"
    assert result.completed == ["import", "load"]
    if failure_stage == "final_status":
        assert result.refresh.after is None
        assert result.refresh.issues
    else:
        assert result.refresh.after is not None


@pytest.mark.parametrize(
    "capture_session,capture_frame", [("B", 8), ("A", 8), ("B", 6)]
)
def test_capture_is_correlated_to_observation_without_relabeling_launched_scene(
    tmp_path, capture_session, capture_frame
):
    class Capturing(Runtime):
        def capture(self, output):
            assert output == tmp_path / "view.png"
            return CaptureObservation(
                str(output), capture_session, "res://test.tscn", capture_frame, "c" * 64
            )

    result = PipelineResult()
    refresh_pipeline(
        result,
        RefreshRequest(
            "res://model.glb",
            "res://test.tscn",
            "/root/Test/Model",
            True,
            capture_output=tmp_path / "view.png",
        ),
        Capturing(),
    )
    assert result.refresh is not None
    assert result.refresh.instance is not None
    capture = result.refresh.capture
    assert capture is not None
    assert capture.launched_scene == "res://test.tscn"
    assert result.refresh.instance.scene_file_path == "res://model.glb"
    assert (result.refresh.status == "verified") == (
        capture_session == "B" and capture_frame >= 7
    )


def test_daemon_session_change_after_observation_prevents_overall_verification():
    class Replaced(Runtime):
        def observe_content(self, node, **limits):
            observed = super().observe_content(node, **limits)
            self.session = "C"
            return observed

    result = PipelineResult()
    refresh_pipeline(
        result,
        RefreshRequest("res://model.glb", "res://test.tscn", "/root/Test/Model", True),
        Replaced(),
    )
    assert result.refresh is not None
    assert result.refresh.after is not None
    assert result.refresh.comparison is not None
    assert result.failure is not None
    assert result.refresh.status == "incomplete"
    assert result.refresh.after.session_id == "C"
    assert result.refresh.comparison.status == "match"
    assert result.failure.code == "refresh_session_changed"


@pytest.mark.parametrize(
    ("change", "status"),
    [
        ({"session_id": "A"}, "incomplete"),
        ({"node": "/root/Test/Wrong"}, "mismatch"),
        ({"scene_file_path": "res://wrong.glb"}, "mismatch"),
        ({"content": replace(CONTENT, digest="a" * 64)}, "mismatch"),
        ({"content": replace(CONTENT, complete=False, digest=None)}, "incomplete"),
        ({"content": replace(CONTENT, unsupported=("skin",))}, "incomplete"),
        ({"content": replace(CONTENT, omitted=("vertex limit",))}, "incomplete"),
        ({"content": replace(CONTENT, engine="4.6.4")}, "incomplete"),
        ({"content": replace(CONTENT, measurement="other")}, "incomplete"),
    ],
)
def test_stale_wrong_changed_and_unmeasured_instances_cannot_verify(change, status):
    class Changed(Runtime):
        def observe_content(self, node, **limits):
            return replace(super().observe_content(node, **limits), **change)

    result = PipelineResult(completed=["import", "load"])
    refresh_pipeline(
        result,
        RefreshRequest("res://model.glb", "res://test.tscn", "/root/Test/Model", True),
        Changed(),
    )

    assert result.failure is not None
    assert result.refresh is not None
    assert result.refresh.comparison is not None
    assert result.refresh.after is not None
    assert result.refresh.status == status
    assert result.refresh.comparison.status == status
    assert result.refresh.comparison.reasons
    assert "refresh" not in result.completed
    assert result.refresh.after.session_id == "B"


def _handoff(tmp_path):
    from gda_assets.api import AssetFile, AssetRecipe

    source = tmp_path / "model.glb"
    doc = json.dumps({"asset": {"version": "2.0"}}).encode()
    doc += b" " * (-len(doc) % 4)
    source.write_bytes(
        struct.pack("<4sIII4s", b"glTF", 2, 20 + len(doc), len(doc), b"JSON") + doc
    )
    project = tmp_path / "project"
    project.mkdir()
    return project, AssetRecipe((AssetFile(str(source), "res://model.glb"),))


@pytest.mark.parametrize("fail_load", [False, True])
def test_public_pipeline_refresh_begins_only_after_successful_import_and_load(
    tmp_path, fail_load
):
    from gda_assets.api import run_pipeline, ImportOutcome, LoadObservation

    class Godot(Runtime):
        def import_assets(self, paths):
            self.calls.append("import")
            return ImportOutcome({"engine_pass": True})

        def check_load(self, path):
            self.calls.append("load")
            if fail_load:
                raise PortFailure("operation_failed", "load rejected")
            return LoadObservation(path, "PackedScene")

    project, recipe = _handoff(tmp_path)
    godot = Godot()
    result = run_pipeline(
        recipe,
        source_root=None,
        project_root=project,
        godot=godot,
        refresh=RefreshRequest(
            "res://model.glb", "res://test.tscn", "/root/Test/Model", True
        ),
        runtime=godot,
    )
    assert (project / "model.glb").exists()
    if fail_load:
        assert result.failure is not None
        assert result.failure.stage == "load"
        assert result.refresh is None
        assert godot.calls == ["import", "load"]
    else:
        assert result.failure is None
        assert result.refresh is not None
        assert result.refresh.status == "verified"
        assert godot.calls[:3] == ["import", "load", "imported"]


@pytest.mark.parametrize(
    "changes",
    [
        {"path": "res://other.glb"},
        {"scene": ""},
        {"scene": "res://../test.tscn"},
        {"node": "Model"},
        {"node": "/root/Test/../Model"},
        {"timeout": float("nan")},
        {"max_vertices": 0},
        {"windowed": False, "capture_output": "view.png"},
        {"runtime_missing": True},
    ],
)
def test_invalid_refresh_is_refused_before_file_install_or_session_reset(
    tmp_path, changes
):
    from gda_assets.api import run_pipeline

    project, recipe = _handoff(tmp_path)
    changes = dict(changes)
    missing = changes.pop("runtime_missing", False)
    request = replace(
        RefreshRequest("res://model.glb", "res://test.tscn", "/root/Test/Model", True),
        **changes,
    )
    port = Runtime()
    result = run_pipeline(
        recipe,
        source_root=None,
        project_root=project,
        godot=port,
        refresh=request,
        runtime=None if missing else port,
    )
    assert result.failure is not None
    assert result.failure.code == "invalid_refresh"
    assert result.failure.stage == "validate"
    assert result.outputs == []
    assert list(project.iterdir()) == []
    assert port.calls == []
