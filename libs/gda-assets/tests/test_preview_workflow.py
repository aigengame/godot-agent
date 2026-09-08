"""Preview composition through owned file and Godot capabilities."""

from pathlib import Path
from dataclasses import replace

import pytest

from gda_assets.application.ports import PortFailure
from gda_assets.application.preview import preview_asset
from gda_assets.domain.artifacts import ImportOutcome
from gda_assets.domain.preview import PreviewBounds, PreviewSettings, frame_views
from gda_assets.domain.preview_result import (
    PreviewCapture,
    PreviewBudget,
    PreviewDiagnostics,
    PreviewInspection,
    PreviewNode,
    PreviewPerformance,
    PreviewRequest,
    PreviewResult,
    PreviewSample,
    PreviewState,
    PreviewStats,
)
from gda_assets.domain.refresh import (
    CaptureObservation,
    ReadyObservation,
    SessionState,
    StartObservation,
    StopObservation,
)


class Files:
    def __init__(self, project: Path):
        self.project = project
        self.removed = False
        self.prepared = False
        self.baseline: PreviewResult | None = None

    def read_baseline(self, path):
        if self.baseline is None:
            raise PortFailure("invalid_preview_baseline", "Baseline unavailable")
        return self.baseline

    def prepare(self, source, output_dir, budget):
        self.prepared = True
        return self.project, "a" * 64

    def configure(self, project, settings, cameras):
        self.settings, self.cameras = settings, cameras

    def remove_project(self, project):
        assert project == self.project
        self.removed = True


class Runtime:
    def __init__(self, files: Files):
        self.files = files
        self.running = False
        self.index = -1
        self.selections = []

    def import_assets(self, paths):
        assert paths == ["res://model.glb"]
        return ImportOutcome({"imported": True})

    def inspect_preview(self, max_nodes):
        return PreviewInspection(
            "res://model.glb",
            "4.6.3",
            "resource",
            "static_mesh_aabb",
            PreviewBounds((2, -1, 1), (4, 3, 3)),
            (PreviewNode(".", "Node3D"), PreviewNode("Mesh", "MeshInstance3D")),
            (),
            ("Static mesh bounds.",),
        )

    def start(self, scene, *, windowed):
        assert scene == "res://preview.tscn" and windowed is True
        self.running = True
        return StartObservation(
            True, True, "22", ("res://.gda/harness.gd",), ("autoload",), 42, True, False
        )

    def wait_ready(self, timeout):
        return ReadyObservation(42, True)

    def status(self):
        return SessionState(
            self.running, 42 if self.running else None, True, "preview-session"
        )

    def select_view(self, index):
        self.index = index
        self.selections.append(index)

    def capture_view(self, index, output):
        assert index == self.index
        return PreviewCapture(
            CaptureObservation(
                str(output),
                "preview-session",
                "res://preview.tscn",
                10 + index,
                "b" * 64,
            ),
            640,
            360,
            1,
            index,
        )

    def observe_view(self):
        return PreviewState(
            self.index,
            self.files.cameras[self.index],
            (640, 360),
            "gl_compatibility",
            "4.6.3",
            "Linux",
            "static_imported",
            (0.08, 0.1, 0.14, 1),
            0.65,
            1.4,
            (-45, -35, 0),
        )

    def performance(self, frames, *, budget):
        assert self.index == 2 and frames == 2 and budget is False
        return PreviewPerformance(
            2,
            {"fps": PreviewStats(2, 60, 60, 60, 60, 60)},
            (PreviewSample(0, 100, {"fps": 60}), PreviewSample(1, 116, {"fps": 60})),
            None,
            None,
        )

    def diagnostics(self):
        return PreviewDiagnostics((), False)

    def stop(self):
        self.running = False
        return StopObservation(True, 42)


def test_preview_captures_three_views_and_cleans_its_project(tmp_path):
    files = Files(tmp_path / "isolated")
    runtime = Runtime(files)
    request = PreviewRequest(tmp_path / "model.glb", tmp_path / "views", frames=2)

    result = preview_asset(request, host=lambda project: runtime, files=files)

    assert result.failure is None
    assert runtime.selections == [0, 1, 2]
    assert [view.state.camera.name for view in result.views if view.state] == [
        "front",
        "side",
        "three_quarter",
    ]
    assert result.views[0].capture.receipt.path == str(tmp_path / "views/front.png")
    assert result.performance_session == "preview-session"
    assert result.cleanup.session_stopped and result.cleanup.project_removed
    assert files.removed and not runtime.running


def test_baseline_is_compared_after_complete_cleanup(tmp_path):
    files = Files(tmp_path / "isolated")
    runtime = Runtime(files)
    request = PreviewRequest(tmp_path / "model.glb", tmp_path / "views", frames=2)
    files.baseline = preview_asset(request, host=lambda _: runtime, files=files)

    result = preview_asset(
        replace(
            request, output_dir=tmp_path / "new-views", baseline=tmp_path / "prior.json"
        ),
        host=lambda _: runtime,
        files=files,
    )

    assert result.failure is None
    assert result.comparison is not None and result.comparison.status == "comparable"
    assert result.comparison.changes["fps"].mean_delta == 0
    assert result.cleanup.session_stopped and result.cleanup.project_removed


def test_invalid_baseline_fails_before_preparing_project(tmp_path):
    files = Files(tmp_path / "isolated")
    result = preview_asset(
        PreviewRequest(
            tmp_path / "model.glb",
            tmp_path / "views",
            baseline=tmp_path / "missing.json",
        ),
        host=lambda _: Runtime(files),
        files=files,
    )
    assert (
        result.failure is not None and result.failure.code == "invalid_preview_baseline"
    )
    assert result.failure.stage == "validate" and not files.prepared


def test_wrong_camera_cannot_be_labelled_as_the_requested_view(tmp_path, monkeypatch):
    files = Files(tmp_path / "isolated")
    runtime = Runtime(files)
    original = runtime.observe_view

    def wrong_camera():
        state = original()
        return replace(state, camera=replace(state.camera, position=(99, 99, 99)))

    monkeypatch.setattr(runtime, "observe_view", wrong_camera)
    result = preview_asset(
        PreviewRequest(tmp_path / "model.glb", tmp_path / "views", frames=2),
        host=lambda _: runtime,
        files=files,
    )

    assert result.failure is not None
    assert result.failure.code == "preview_view_unassociated"
    assert len(result.views) == 1
    assert result.views[0].capture.receipt.path.endswith("front.png")
    assert result.cleanup.session_stopped and files.removed


@pytest.mark.parametrize("mismatch", ["frame", "session", "engine"])
def test_unassociated_observations_fail_and_retain_capture(
    tmp_path, monkeypatch, mismatch
):
    files = Files(tmp_path / "isolated")
    runtime = Runtime(files)
    capture_view = runtime.capture_view
    observe_view = runtime.observe_view

    def capture(index, output):
        captured = capture_view(index, output)
        if mismatch == "frame":
            return replace(captured, receipt=replace(captured.receipt, engine_frame=10))
        if mismatch == "session":
            return replace(
                captured, receipt=replace(captured.receipt, session_id="wrong")
            )
        return captured

    def observe():
        state = observe_view()
        return (
            replace(state, engine="different-engine") if mismatch == "engine" else state
        )

    monkeypatch.setattr(runtime, "capture_view", capture)
    monkeypatch.setattr(runtime, "observe_view", observe)
    result = preview_asset(
        PreviewRequest(tmp_path / "model.glb", tmp_path / "views", frames=2),
        host=lambda _: runtime,
        files=files,
    )

    assert result.failure is not None
    assert result.failure.code == "preview_view_unassociated"
    assert len(result.views) == (2 if mismatch == "frame" else 1)
    assert result.cleanup.session_stopped and files.removed


def test_capture_failure_keeps_completed_views_and_stops_owned_session(
    tmp_path, monkeypatch
):
    files = Files(tmp_path / "isolated")
    runtime = Runtime(files)
    original = runtime.capture_view

    def capture(index, output):
        if index == 1:
            raise PortFailure("capture_failed", "render output unavailable")
        return original(index, output)

    monkeypatch.setattr(runtime, "capture_view", capture)
    result = preview_asset(
        PreviewRequest(tmp_path / "model.glb", tmp_path / "views", frames=2),
        host=lambda _: runtime,
        files=files,
    )

    assert result.failure is not None
    assert result.failure.stage == "view.side"
    assert len(result.views) == 1
    assert result.performance is None
    assert result.cleanup.session_stopped and files.removed


def test_stop_failure_retains_temporary_project_for_recovery(tmp_path, monkeypatch):
    files = Files(tmp_path / "isolated")
    runtime = Runtime(files)

    def stop():
        raise PortFailure("stop_failed", "daemon did not acknowledge stop")

    monkeypatch.setattr(runtime, "stop", stop)
    result = preview_asset(
        PreviewRequest(tmp_path / "model.glb", tmp_path / "views", frames=2),
        host=lambda _: runtime,
        files=files,
    )

    assert result.failure is not None
    assert result.failure.stage == "cleanup"
    assert not result.cleanup.session_stopped and not files.removed
    assert result.project == str(files.project)
    assert len(result.views) == 3


@pytest.mark.parametrize("override", [False, True])
def test_incomplete_bounds_require_explicit_camera_override(
    tmp_path, monkeypatch, override
):
    files = Files(tmp_path / "isolated")
    runtime = Runtime(files)
    inspection = runtime.inspect_preview(256)
    monkeypatch.setattr(
        runtime,
        "inspect_preview",
        lambda _: replace(inspection, omissions=((".", "nodes"),)),
    )
    settings = (
        PreviewSettings(cameras=frame_views(inspection.bounds, PreviewSettings()))
        if override
        else PreviewSettings()
    )
    result = preview_asset(
        PreviewRequest(
            tmp_path / "model.glb", tmp_path / "views", frames=2, settings=settings
        ),
        host=lambda _: runtime,
        files=files,
    )
    if override:
        assert result.failure is None and len(result.views) == 3
    else:
        assert result.failure is not None and result.failure.stage == "framing"
        assert "start" not in result.completed and not runtime.selections
    assert files.removed


def test_budget_failure_is_retained_as_measurement_data(tmp_path, monkeypatch):
    files = Files(tmp_path / "isolated")
    runtime = Runtime(files)
    measured = runtime.performance

    def performance(frames, *, budget):
        assert budget is True
        return replace(
            measured(frames, budget=False),
            passed=False,
            budget={"fps": PreviewBudget("mean", 60, 120, None, False)},
        )

    monkeypatch.setattr(runtime, "performance", performance)
    result = preview_asset(
        PreviewRequest(
            tmp_path / "model.glb",
            tmp_path / "views",
            frames=2,
            budget=tmp_path / "budget.json",
        ),
        host=lambda _: runtime,
        files=files,
    )
    assert result.failure is None
    assert result.performance is not None and result.performance.passed is False
    assert (
        result.performance.budget is not None
        and not result.performance.budget["fps"].passed
    )
    assert files.removed


def test_cleanup_failure_does_not_replace_original_capture_failure(
    tmp_path, monkeypatch
):
    files = Files(tmp_path / "isolated")
    runtime = Runtime(files)

    def fail_capture(*_):
        raise PortFailure("capture_failed", "capture interrupted")

    def fail_stop():
        raise PortFailure("stop_failed", "daemon unavailable")

    monkeypatch.setattr(runtime, "capture_view", fail_capture)
    monkeypatch.setattr(runtime, "stop", fail_stop)
    result = preview_asset(
        PreviewRequest(tmp_path / "model.glb", tmp_path / "views", frames=2),
        host=lambda _: runtime,
        files=files,
    )
    assert result.failure is not None and result.failure.code == "capture_failed"
    assert result.failure.stage == "view.front"
    assert result.cleanup.issues == ["daemon unavailable"]
    assert not files.removed


@pytest.mark.parametrize("frames", [0, 121, True])
def test_invalid_window_is_refused_before_files_or_host(tmp_path, frames):
    files = Files(tmp_path / "isolated")

    def unused_host(project):
        pytest.fail("Invalid request must not bind a runtime")

    result = preview_asset(
        PreviewRequest(tmp_path / "model.glb", tmp_path / "views", frames=frames),
        host=unused_host,
        files=files,
    )
    assert result.failure is not None and result.failure.stage == "validate"
    assert not files.prepared
