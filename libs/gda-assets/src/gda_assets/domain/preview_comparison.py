"""Compatibility checks for two complete model-preview observations."""

import math

from gda_assets.domain.preview import VIEW_NAMES, cameras_match, validate_warmup
from gda_assets.domain.preview_result import (
    PreviewComparison,
    PreviewMetricChange,
    PreviewPerformance,
    PreviewResult,
    PreviewStats,
)


def _add(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _valid_stats(stats: PreviewStats, frames: int) -> bool:
    values = (stats.min, stats.max, stats.mean, stats.p50, stats.p95)
    return (
        type(stats.count) is int
        and stats.count == frames
        and all(math.isfinite(value) for value in values)
        and stats.min >= 0
        and stats.min <= stats.mean <= stats.max
        and stats.min <= stats.p50 <= stats.p95 <= stats.max
    )


def _validate_performance(
    label: str, performance: PreviewPerformance | None, reasons: list[str]
) -> None:
    if performance is None:
        _add(reasons, f"{label}:performance_missing")
        return
    if type(performance.frames) is not int or not 1 <= performance.frames <= 120:
        _add(reasons, f"{label}:performance_window_invalid")
        return
    names = set(performance.stats)
    if not names:
        _add(reasons, f"{label}:performance_monitors_missing")
    if len(performance.samples) != performance.frames:
        _add(reasons, f"{label}:performance_window_invalid")
    if tuple(sample.frame for sample in performance.samples) != tuple(
        range(performance.frames)
    ):
        _add(reasons, f"{label}:performance_frame_order_invalid")
    timestamps = tuple(sample.timestamp for sample in performance.samples)
    if any(type(value) is not int for value in timestamps) or any(
        right < left for left, right in zip(timestamps, timestamps[1:])
    ):
        _add(reasons, f"{label}:performance_timestamp_order_invalid")
    for sample in performance.samples:
        if set(sample.values) != names or not all(
            math.isfinite(value) and value >= 0 for value in sample.values.values()
        ):
            _add(reasons, f"{label}:performance_samples_invalid")
            break
    if any(
        not _valid_stats(stats, performance.frames)
        for stats in performance.stats.values()
    ):
        _add(reasons, f"{label}:performance_stats_invalid")


def _validate_result(label: str, result: PreviewResult, reasons: list[str]) -> None:
    if result.failure is not None:
        _add(reasons, f"{label}:preview_failed")
    expected_stages = {
        "prepare",
        "import",
        "inspect",
        "framing",
        "start",
        "ready",
        "performance",
        *(f"view.{name}" for name in VIEW_NAMES),
    }
    try:
        validate_warmup(result.request.warmup_seconds)
    except ValueError:
        _add(reasons, f"{label}:warmup_invalid")
    else:
        if result.request.warmup_seconds > 0:
            expected_stages.add("warmup")
    if not expected_stages.issubset(result.completed):
        _add(reasons, f"{label}:preview_incomplete")
    if result.inspection is None or not result.inspection.engine:
        _add(reasons, f"{label}:engine_identity_missing")
    if result.diagnostics is None:
        _add(reasons, f"{label}:diagnostics_missing")
    elif result.diagnostics.truncated:
        _add(reasons, f"{label}:diagnostics_truncated")
    session_id = result.session.session_id if result.session is not None else None
    if (
        result.session is None
        or not result.session.running
        or not result.session.windowed
        or not session_id
    ):
        _add(reasons, f"{label}:session_unavailable")
    if len(result.views) != len(VIEW_NAMES):
        _add(reasons, f"{label}:views_incomplete")
    else:
        frames: list[int] = []
        for index, (name, view) in enumerate(zip(VIEW_NAMES, result.views)):
            state = view.state
            receipt = view.capture.receipt
            if state is None:
                _add(reasons, f"{label}:view_state_missing")
                continue
            if state.index != index or state.camera.name != name:
                _add(reasons, f"{label}:view_order_invalid")
            if (
                result.inspection is None
                or not state.engine
                or state.engine != result.inspection.engine
            ):
                _add(reasons, f"{label}:engine_identity_invalid")
            if (
                view.capture.applied_view != index
                or receipt.session_id != session_id
                or receipt.launched_scene != "res://preview.tscn"
                or (view.capture.width, view.capture.height) != state.viewport
                or min(state.viewport) <= 0
                or not receipt.path
                or not receipt.sha256
            ):
                _add(reasons, f"{label}:capture_unassociated")
            frames.append(receipt.engine_frame)
        if any(right <= left for left, right in zip(frames, frames[1:])):
            _add(reasons, f"{label}:capture_order_invalid")
    if result.performance_session != session_id:
        _add(reasons, f"{label}:performance_unassociated")
    _validate_performance(label, result.performance, reasons)


def _compatible_setup(
    baseline: PreviewResult, current: PreviewResult, reasons: list[str]
) -> None:
    assert baseline.inspection is not None and current.inspection is not None
    if baseline.inspection.engine != current.inspection.engine:
        _add(reasons, "engine_mismatch")
    for old, new in zip(baseline.views, current.views):
        assert old.state is not None and new.state is not None
        if not cameras_match(old.state.camera, new.state.camera):
            _add(reasons, "camera_mismatch")
        old_setup = (
            old.state.viewport,
            old.state.renderer,
            old.state.engine,
            old.state.platform,
            old.state.pose,
            old.state.overlays,
        )
        new_setup = (
            new.state.viewport,
            new.state.renderer,
            new.state.engine,
            new.state.platform,
            new.state.pose,
            new.state.overlays,
        )
        old_light = (
            *old.state.background,
            old.state.ambient_energy,
            old.state.light_energy,
            *old.state.light_rotation,
        )
        new_light = (
            *new.state.background,
            new.state.ambient_energy,
            new.state.light_energy,
            *new.state.light_rotation,
        )
        if old_setup != new_setup or not all(
            math.isclose(left, right, rel_tol=1e-5, abs_tol=1e-5)
            for left, right in zip(old_light, new_light)
        ):
            _add(reasons, "preview_setup_mismatch")
    if baseline.request.warmup_seconds != current.request.warmup_seconds:
        _add(reasons, "warmup_mismatch")
    assert baseline.performance is not None and current.performance is not None
    if set(baseline.performance.stats) != set(current.performance.stats):
        _add(reasons, "performance_monitors_mismatch")
    if baseline.performance.frames != current.performance.frames or tuple(
        sample.frame for sample in baseline.performance.samples
    ) != tuple(sample.frame for sample in current.performance.samples):
        _add(reasons, "performance_window_mismatch")


def compare_previews(
    baseline: PreviewResult, current: PreviewResult
) -> PreviewComparison:
    """Compare like-for-like preview setup and complete performance windows."""
    reasons: list[str] = []
    _validate_result("baseline", baseline, reasons)
    _validate_result("current", current, reasons)
    if not reasons:
        _compatible_setup(baseline, current, reasons)
    if reasons:
        return PreviewComparison("non_comparable", tuple(reasons))
    assert baseline.performance is not None and current.performance is not None
    changes = {
        name: PreviewMetricChange(
            before=baseline.performance.stats[name],
            after=current.performance.stats[name],
            mean_delta=current.performance.stats[name].mean
            - baseline.performance.stats[name].mean,
            p95_delta=current.performance.stats[name].p95
            - baseline.performance.stats[name].p95,
            before_budget=(baseline.performance.budget or {}).get(name),
            after_budget=(current.performance.budget or {}).get(name),
        )
        for name in sorted(baseline.performance.stats)
    }
    return PreviewComparison("comparable", (), changes)
