from dataclasses import replace
from pathlib import Path

import pytest

from gda_assets.domain.preview import PreviewBounds, PreviewSettings, frame_views
from gda_assets.domain.preview_comparison import compare_previews
from gda_assets.domain.preview_result import (
    PreviewCapture,
    PreviewBudget,
    PreviewDiagnostics,
    PreviewInspection,
    PreviewPerformance,
    PreviewRequest,
    PreviewResult,
    PreviewSample,
    PreviewState,
    PreviewStats,
    PreviewView,
)
from gda_assets.domain.refresh import CaptureObservation, SessionState


def _result(*, digest: str = "a" * 64) -> PreviewResult:
    settings = PreviewSettings(width=800, height=400)
    cameras = frame_views(PreviewBounds((2, 1, -3), (4, 2, 6)), settings)
    session = "preview-session"
    views = []
    for index, camera in enumerate(cameras):
        state = PreviewState(
            index,
            camera,
            (800, 400),
            "gl_compatibility",
            "4.6.3.stable",
            "macOS",
            "static_imported",
            (0.05, 0.05, 0.05, 1.0),
            0.7,
            1.2,
            (-0.7, -0.5, 0.0),
        )
        capture = PreviewCapture(
            CaptureObservation(
                f"/tmp/{camera.name}.png",
                session,
                "res://preview.tscn",
                10 + index,
                chr(98 + index) * 64,
            ),
            800,
            400,
            2,
            index,
        )
        views.append(PreviewView(state, capture))
    stats = {
        "fps": PreviewStats(3, 58.0, 62.0, 60.0, 60.0, 62.0),
        "frame_ms": PreviewStats(3, 15.0, 18.0, 16.0, 16.0, 18.0),
    }
    samples = (
        PreviewSample(0, 100, {"fps": 58.0, "frame_ms": 18.0}),
        PreviewSample(1, 116, {"fps": 60.0, "frame_ms": 16.0}),
        PreviewSample(2, 132, {"fps": 62.0, "frame_ms": 15.0}),
    )
    return PreviewResult(
        request=PreviewRequest(Path("a.glb"), Path("out"), settings, frames=3),
        completed=[
            "prepare",
            "import",
            "inspect",
            "framing",
            "start",
            "ready",
            "view.front",
            "view.side",
            "view.three_quarter",
            "performance",
        ],
        project="/tmp/project",
        source_sha256=digest,
        inspection=PreviewInspection(
            "res://model.glb",
            "4.6.3.stable",
            "resource",
            "static_mesh_aabb",
            PreviewBounds((2, 1, -3), (4, 2, 6)),
            (),
            (),
            (),
        ),
        views=views,
        session=SessionState(True, 123, True, session),
        performance=PreviewPerformance(3, stats, samples, None, None),
        performance_session=session,
        diagnostics=PreviewDiagnostics((), False),
    )


def _with_viewport(result: PreviewResult, viewport: tuple[int, int]) -> PreviewResult:
    result.request = replace(
        result.request,
        settings=replace(
            result.request.settings, width=viewport[0], height=viewport[1]
        ),
    )
    views = []
    for view in result.views:
        assert view.state is not None
        views.append(
            replace(
                view,
                state=replace(view.state, viewport=viewport),
                capture=replace(view.capture, width=viewport[0], height=viewport[1]),
            )
        )
    result.views = views
    return result


def _with_engine(result: PreviewResult, engine: str) -> PreviewResult:
    assert result.inspection is not None
    result.inspection = replace(result.inspection, engine=engine)
    views = []
    for view in result.views:
        assert view.state is not None
        views.append(replace(view, state=replace(view.state, engine=engine)))
    result.views = views
    return result


def _with_shorter_window(result: PreviewResult) -> PreviewResult:
    performance = result.performance
    assert performance is not None
    result.performance = replace(
        performance,
        frames=2,
        stats={
            name: replace(stats, count=2) for name, stats in performance.stats.items()
        },
        samples=performance.samples[:2],
    )
    return result


def _with_declared_frames(result: PreviewResult, frames: int) -> PreviewResult:
    assert result.performance is not None
    result.performance = replace(result.performance, frames=frames)
    return result


def test_compatible_results_report_full_metric_changes_despite_content_change():
    baseline = _result(digest="a" * 64)
    current = _result(digest="b" * 64)
    assert current.performance is not None
    current.performance.stats["fps"] = PreviewStats(3, 59, 64, 62, 62, 64)
    current.performance = replace(current.performance, passed=False)

    comparison = compare_previews(baseline, current)

    assert comparison.status == "comparable"
    assert comparison.reasons == ()
    assert comparison.changes["fps"].before.mean == 60
    assert comparison.changes["fps"].after.mean == 62
    assert comparison.changes["fps"].mean_delta == 2
    assert comparison.changes["fps"].p95_delta == 2


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            lambda result: _with_viewport(result, (801, 400)),
            "preview_setup_mismatch",
        ),
        (
            lambda result: _with_engine(result, "4.7.0"),
            "engine_mismatch",
        ),
        (
            lambda result: replace(
                result,
                views=[
                    replace(
                        result.views[0],
                        state=replace(
                            result.views[0].state,
                            camera=replace(result.views[0].state.camera, size=99),
                        ),
                    ),
                    *result.views[1:],
                ],
            ),
            "camera_mismatch",
        ),
        (
            _with_shorter_window,
            "performance_window_mismatch",
        ),
        (
            lambda result: replace(result, performance=None),
            "current:performance_missing",
        ),
        (
            lambda result: _with_declared_frames(result, 10**12),
            "current:performance_window_invalid",
        ),
    ],
)
def test_incompatible_or_incomplete_observation_has_no_deltas(mutation, reason):
    comparison = compare_previews(_result(), mutation(_result()))

    assert comparison.status == "non_comparable"
    assert reason in comparison.reasons
    assert comparison.changes == {}


def test_nonfinite_stats_and_mismatched_monitor_sets_are_not_comparable():
    current = _result()
    assert current.performance is not None
    current.performance.stats["fps"] = PreviewStats(3, 58, 62, float("nan"), 60, 62)
    del current.performance.stats["frame_ms"]
    current.performance = replace(
        current.performance,
        samples=tuple(
            replace(sample, values={"fps": sample.values["fps"]})
            for sample in current.performance.samples
        ),
    )

    comparison = compare_previews(_result(), current)

    assert "current:performance_stats_invalid" in comparison.reasons
    assert comparison.changes == {}


def test_inspection_omissions_do_not_block_explicitly_observed_views():
    current = _result()
    assert current.inspection is not None
    current.inspection = replace(
        current.inspection, omissions=(("Root/Mesh", "materials"),)
    )

    assert compare_previews(_result(), current).status == "comparable"


def test_different_budget_verdicts_are_retained_without_gating_comparison():
    baseline = _result()
    current = _result()
    assert baseline.performance is not None
    assert current.performance is not None
    baseline.performance = replace(
        baseline.performance,
        budget={"fps": PreviewBudget("mean", 60, 55, None, True)},
        passed=True,
    )
    current.performance = replace(
        current.performance,
        budget={"fps": PreviewBudget("mean", 60, 65, None, False)},
        passed=False,
    )

    comparison = compare_previews(baseline, current)

    assert comparison.status == "comparable"
    assert comparison.changes["fps"].before_budget is not None
    assert comparison.changes["fps"].after_budget is not None
    assert comparison.changes["fps"].before_budget.passed is True
    assert comparison.changes["fps"].after_budget.passed is False
