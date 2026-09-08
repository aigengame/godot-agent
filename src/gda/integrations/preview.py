"""gda host projections for the isolated model-preview workflow."""

import json
from pathlib import Path
from typing import NoReturn

from gda.commands.diag import DiagErrorsParams, run_diag_errors_operation
from gda.commands.game import (
    GameGetParams,
    GameSetParams,
    run_game_get_operation,
    run_game_set_operation,
)
from gda.commands.perf import (
    PerfMonitorName,
    PerfMonitorsParams,
    run_perf_monitors_operation,
)
from gda.commands.resource import (
    ResourceInspectModelParams,
    run_resource_inspect_model_operation,
)
from gda.commands.screen import ScreenCaptureParams, run_screen_capture_operation
from gda.errors import Failure, make_failure
from gda.integrations.asset_pipeline import GdaGodotAssetPort
from pydantic import TypeAdapter, ValidationError

from gda_assets.api import (
    CaptureObservation,
    PreviewBounds,
    PreviewBudget,
    PreviewCapture,
    PreviewDiagnostic,
    PreviewDiagnostics,
    PreviewInspection,
    PreviewNode,
    PreviewPerformance,
    PreviewSample,
    PreviewState,
    PreviewStats,
)


_PREVIEW_STATE_ADAPTER = TypeAdapter(PreviewState)


class GdaGodotPreviewPort(GdaGodotAssetPort):
    """Project native gda results into the preview library's bounded DTOs."""

    def inspect_preview(self, max_nodes: int) -> PreviewInspection:
        outcome = run_resource_inspect_model_operation(
            self._project,
            ResourceInspectModelParams(
                path="res://model.glb", max_nodes=max_nodes, max_items=1024
            ),
            godot=self._godot,
        )
        if isinstance(outcome, Failure):
            self._raise(outcome)
        return PreviewInspection(
            resource=outcome.path,
            engine=outcome.engine_version.string,
            coordinate_space=outcome.measurement.coordinate_space,
            geometry=outcome.measurement.geometry,
            bounds=(
                PreviewBounds(outcome.bounds.position, outcome.bounds.size)
                if outcome.bounds is not None
                else None
            ),
            nodes=tuple(PreviewNode(node.path, node.type) for node in outcome.nodes),
            omissions=tuple(
                (omission.node_path, omission.section) for omission in outcome.omissions
            ),
            limitations=tuple(outcome.measurement.limitations),
        )

    def select_view(self, index: int) -> None:
        outcome = run_game_set_operation(
            self._project,
            GameSetParams(
                node="/root/Preview", property="view_index", value=str(index)
            ),
        )
        if isinstance(outcome, Failure):
            self._raise(outcome)
        if (
            not outcome.verified
            or type(outcome.value) is not int
            or outcome.value != index
        ):
            self._contract_failure(
                "preview view_index was not verified after selection"
            )

    def capture_view(self, index: int, output: Path) -> PreviewCapture:
        outcome = run_screen_capture_operation(
            self._project,
            ScreenCaptureParams(
                output=str(output),
                await_node="/root/Preview",
                await_property="applied_view",
                await_value=index,
                await_frames=120,
            ),
        )
        if isinstance(outcome, Failure):
            self._raise(outcome)
        if outcome.predicate is None:
            self._contract_failure("preview capture omitted its predicate evidence")
        if type(outcome.predicate.observed) is not int:
            self._contract_failure("preview capture applied_view was not an integer")
        receipt = outcome.receipt
        return PreviewCapture(
            receipt=CaptureObservation(
                path=outcome.path,
                session_id=receipt.session_id,
                launched_scene=receipt.scene_path,
                engine_frame=receipt.engine_frame,
                sha256=receipt.sha256,
            ),
            width=outcome.width,
            height=outcome.height,
            frames_waited=outcome.predicate.frames_waited,
            applied_view=outcome.predicate.observed,
        )

    def observe_view(self) -> PreviewState:
        outcome = run_game_get_operation(
            self._project,
            GameGetParams(node="/root/Preview", property="view_state"),
        )
        if isinstance(outcome, Failure):
            self._raise(outcome)
        try:
            if (
                len(outcome.properties) != 1
                or outcome.properties[0].name != "view_state"
            ):
                raise ValueError("game get did not return exactly view_state")
            value = outcome.properties[0].value
            if not isinstance(value, dict):
                raise TypeError("view_state is not a Dictionary")
            return _PREVIEW_STATE_ADAPTER.validate_json(json.dumps(value), strict=True)
        except (IndexError, TypeError, ValueError, ValidationError) as exc:
            self._contract_failure(f"invalid preview view_state: {exc}")

    def performance(self, frames: int, *, budget: bool) -> PreviewPerformance:
        outcome = run_perf_monitors_operation(
            self._project,
            PerfMonitorsParams(
                frames=frames,
                monitors=[
                    PerfMonitorName.fps,
                    PerfMonitorName.draw_calls,
                    PerfMonitorName.primitives_in_frame,
                ],
                budget=str(self._project / "budget.json") if budget else None,
            ),
        )
        if isinstance(outcome, Failure):
            self._raise(outcome)
        if outcome.kind != "window" or any(
            item is None for item in (outcome.frames, outcome.stats, outcome.samples)
        ):
            self._contract_failure("preview performance did not return a window")
        assert outcome.frames is not None and outcome.stats is not None
        assert outcome.samples is not None
        return PreviewPerformance(
            frames=outcome.frames,
            stats={
                name: PreviewStats(**stats.model_dump())
                for name, stats in outcome.stats.items()
            },
            samples=tuple(
                PreviewSample(sample.frame, sample.timestamp, dict(sample.values))
                for sample in outcome.samples
            ),
            budget=(
                {
                    name: PreviewBudget(**verdict.model_dump())
                    for name, verdict in outcome.budget.items()
                }
                if outcome.budget is not None
                else None
            ),
            passed=outcome.passed,
        )

    def diagnostics(self) -> PreviewDiagnostics:
        outcome = run_diag_errors_operation(self._project, DiagErrorsParams(limit=65))
        if isinstance(outcome, Failure):
            self._raise(outcome)
        return PreviewDiagnostics(
            errors=tuple(
                PreviewDiagnostic(error.level, error.message, error.file, error.line)
                for error in outcome.errors[:64]
            ),
            truncated=len(outcome.errors) > 64,
        )

    def _contract_failure(self, message: str) -> NoReturn:
        self._raise(make_failure("contract_violation", message, ""))


class GdaPreviewHost:
    """Bind one preview invocation's temporary project to a fresh adapter."""

    def __init__(self, godot: str | None = None) -> None:
        self._godot = godot
        self._port: GdaGodotPreviewPort | None = None

    def __call__(self, project: Path) -> GdaGodotPreviewPort:
        self._port = GdaGodotPreviewPort(project, self._godot)
        return self._port

    @property
    def last_failure(self) -> Failure | None:
        return self._port.last_failure if self._port is not None else None
