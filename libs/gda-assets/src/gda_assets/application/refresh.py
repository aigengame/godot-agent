"""Reset one explicit scene through injected lifecycle operations."""

from gda_assets.application.ports import GodotRefreshPort, PortFailure
from gda_assets.domain.artifacts import PipelineResult, PipelineFailure
from gda_assets.domain.refresh import RefreshRequest, RefreshResult, compare_instance


def refresh_pipeline(
    result: PipelineResult, request: RefreshRequest, godot: GodotRefreshPort
) -> None:
    refresh = RefreshResult(request)
    result.refresh = refresh
    stage = "inspect_imported"
    limits = {"max_nodes": request.max_nodes, "max_vertices": request.max_vertices}
    try:
        refresh.imported = godot.inspect_content(request.path, **limits)
        refresh.completed.append(stage)
        stage = "status"
        refresh.before = godot.status()
        stage = "stop"
        refresh.stop = godot.stop()
        refresh.completed.append(stage)
        stage = "start"
        refresh.start = godot.start(request.scene, windowed=request.windowed)
        refresh.completed.append(stage)
        stage = "ready"
        refresh.ready = godot.wait_ready(request.timeout)
        refresh.ready_session = godot.status()
        refresh.completed.append(stage)
        stage = "observe_instance"
        refresh.instance = godot.observe_content(request.node, **limits)
        refresh.completed.append(stage)
        stage = "compare"
        refresh.comparison = compare_instance(
            request,
            refresh.imported,
            refresh.instance,
            refresh.before,
            refresh.ready_session,
        )
        if refresh.comparison.status != "match":
            refresh.status = refresh.comparison.status
            raise PortFailure(
                f"refresh_{refresh.status}", "; ".join(refresh.comparison.reasons)
            )
        refresh.completed.append(stage)
        if request.capture_output is not None:
            stage = "capture"
            refresh.capture = godot.capture(request.capture_output)
            if (
                refresh.capture.session_id != refresh.instance.session_id
                or refresh.capture.engine_frame < refresh.instance.engine_frame
                or refresh.capture.launched_scene != request.scene
            ):
                raise PortFailure(
                    "refresh_capture_unassociated",
                    "The capture does not follow this observation in the requested scene's session.",
                )
            refresh.completed.append(stage)
        refresh.status = "verified"
    except PortFailure as exc:
        result.failure = PipelineFailure(
            f"refresh.{stage}", exc.code, str(exc), exc.cause
        )
    except OSError as exc:
        result.failure = PipelineFailure(
            f"refresh.{stage}", "runtime_io_failed", str(exc)
        )
    finally:
        try:
            refresh.after = godot.status()
            if result.failure is None and (
                not refresh.after.running
                or refresh.instance is None
                or refresh.after.session_id != refresh.instance.session_id
            ):
                result.failure = PipelineFailure(
                    "refresh.status",
                    "refresh_session_changed",
                    "The daemon session changed after the instance observation.",
                )
        except PortFailure as exc:
            refresh.issues.append(f"Final daemon state unavailable: {exc}")
            if result.failure is None:
                result.failure = PipelineFailure(
                    "refresh.status", exc.code, str(exc), exc.cause
                )
        except OSError as exc:
            refresh.issues.append(f"Final daemon state unavailable: {exc}")
            if result.failure is None:
                result.failure = PipelineFailure(
                    "refresh.status", "runtime_io_failed", str(exc)
                )
        if result.failure is not None:
            if refresh.status == "verified":
                refresh.status = "incomplete"
        else:
            result.completed.append("refresh")
