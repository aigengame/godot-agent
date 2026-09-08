"""Run one isolated fixed-view preview through injected Godot capabilities."""

import math

from gda_assets.application.ports import PortFailure
from gda_assets.application.preview_ports import PreviewFilesPort, PreviewHost
from gda_assets.domain.artifacts import PipelineFailure
from gda_assets.domain.preview import cameras_match, frame_views, validate_settings
from gda_assets.domain.preview_comparison import compare_previews
from gda_assets.domain.preview_result import PreviewRequest, PreviewResult, PreviewView


def _failure(stage: str, exc: PortFailure | OSError | ValueError) -> PipelineFailure:
    if isinstance(exc, PortFailure):
        return PipelineFailure(stage, exc.code, str(exc), exc.cause)
    return PipelineFailure(
        stage,
        "invalid_preview" if isinstance(exc, ValueError) else "preview_io_failed",
        str(exc),
    )


def preview_asset(
    request: PreviewRequest, *, host: PreviewHost, files: PreviewFilesPort
) -> PreviewResult:
    result = PreviewResult(request)
    project = None
    runtime = None
    start_attempted = False
    baseline = None
    stage = "validate"
    try:
        validate_settings(request.settings)
        if type(request.frames) is not int or not 1 <= request.frames <= 120:
            raise ValueError("Preview performance frames must be between 1 and 120")
        if not math.isfinite(request.timeout) or not 0 < request.timeout <= 50:
            raise ValueError("Preview readiness timeout must be finite and in (0, 50]")
        if type(request.max_nodes) is not int or not 1 <= request.max_nodes <= 4096:
            raise ValueError("Preview max_nodes must be between 1 and 4096")
        if request.baseline is not None:
            baseline = files.read_baseline(request.baseline)
        stage = "prepare"
        project, result.source_sha256 = files.prepare(
            request.source, request.output_dir, request.budget
        )
        result.project = str(project)
        result.completed.append(stage)
        runtime = host(project)
        stage = "import"
        runtime.import_assets(["res://model.glb"])
        result.completed.append(stage)
        stage = "inspect"
        result.inspection = runtime.inspect_preview(request.max_nodes)
        result.completed.append(stage)
        stage = "framing"
        complete = (
            result.inspection.coordinate_space == "resource"
            and result.inspection.geometry == "static_mesh_aabb"
            and not any(
                section == "nodes" for _, section in result.inspection.omissions
            )
        )
        cameras = frame_views(
            result.inspection.bounds, request.settings, bounds_complete=complete
        )
        files.configure(project, request.settings, cameras)
        result.completed.append(stage)
        stage = "start"
        start_attempted = True
        runtime.start("res://preview.tscn", windowed=True)
        result.completed.append(stage)
        stage = "ready"
        runtime.wait_ready(request.timeout)
        result.session = runtime.status()
        if (
            not result.session.running
            or not result.session.windowed
            or not result.session.session_id
        ):
            raise PortFailure(
                "preview_session_unavailable",
                "The isolated windowed session is not ready",
            )
        result.completed.append(stage)
        previous_frame = -1
        for index, camera in enumerate(cameras):
            stage = f"view.{camera.name}"
            runtime.select_view(index)
            capture = runtime.capture_view(
                index, request.output_dir.resolve() / f"{camera.name}.png"
            )
            result.views.append(PreviewView(None, capture))
            state = runtime.observe_view()
            result.views[-1] = PreviewView(state, capture)
            if (
                capture.applied_view != index
                or state.index != index
                or not cameras_match(camera, state.camera)
                or capture.receipt.session_id != result.session.session_id
                or capture.receipt.launched_scene != "res://preview.tscn"
                or (capture.width, capture.height) != state.viewport
                or state.viewport != (request.settings.width, request.settings.height)
                or state.engine != result.inspection.engine
                or capture.receipt.engine_frame <= previous_frame
            ):
                raise PortFailure(
                    "preview_view_unassociated",
                    "Capture and fixture view observations do not match the requested setup",
                )
            previous_frame = capture.receipt.engine_frame
            result.completed.append(stage)
        stage = "performance"
        before = runtime.status()
        result.performance = runtime.performance(
            request.frames, budget=request.budget is not None
        )
        after = runtime.status()
        if (
            not before.running
            or not after.running
            or before.session_id != result.session.session_id
            or after.session_id != result.session.session_id
        ):
            raise PortFailure(
                "preview_session_changed",
                "The performance window is not associated with the preview session",
            )
        result.performance_session = result.session.session_id
        result.completed.append(stage)
    except (PortFailure, OSError, ValueError) as exc:
        result.failure = _failure(stage, exc)
    finally:
        if runtime is not None:
            if start_attempted:
                try:
                    result.diagnostics = runtime.diagnostics()
                except (PortFailure, OSError, ValueError) as exc:
                    result.cleanup.issues.append(f"Diagnostics unavailable: {exc}")
                    result.failure = result.failure or _failure("diagnostics", exc)
            try:
                runtime.stop()
                result.cleanup.session_stopped = not runtime.status().running
                if not result.cleanup.session_stopped:
                    raise PortFailure(
                        "preview_cleanup_failed",
                        "The owned preview session is still running; temporary project retained",
                    )
            except (PortFailure, OSError, ValueError) as exc:
                result.cleanup.issues.append(str(exc))
                result.failure = result.failure or _failure("cleanup", exc)
        if project is not None and (runtime is None or result.cleanup.session_stopped):
            try:
                files.remove_project(project)
                result.cleanup.project_removed = True
            except (PortFailure, OSError, ValueError) as exc:
                result.cleanup.issues.append(str(exc))
                result.failure = result.failure or _failure("cleanup", exc)
    if baseline is not None:
        result.comparison = compare_previews(baseline, result)
    return result
