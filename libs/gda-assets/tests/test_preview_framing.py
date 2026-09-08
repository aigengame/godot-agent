"""Camera policies verified against the native off-origin preview probe."""

import pytest

from gda_assets.domain.preview import (
    PreviewBounds,
    PreviewCamera,
    PreviewSettings,
    frame_views,
    validate_settings,
)


def test_three_fixed_views_frame_off_origin_model_in_wide_viewport():
    views = frame_views(
        PreviewBounds(position=(2.0, -1.0, 1.0), size=(4.0, 3.0, 3.0)),
        PreviewSettings(),
    )

    assert [view.name for view in views] == ["front", "side", "three_quarter"]
    assert views[0].target == (4.0, 0.5, 2.5)
    assert views[0].size == pytest.approx(3.45)
    assert views[0].position == pytest.approx((4.0, 0.5, 10.9))
    assert views[2].size == pytest.approx(5.2786060792)


@pytest.mark.parametrize(
    "width,height", [(63, 360), (2049, 360), (640, 0), (640.5, 360)]
)
def test_viewport_dimensions_are_bounded(width, height):
    with pytest.raises(ValueError, match="viewport"):
        validate_settings(PreviewSettings(width=width, height=height))


@pytest.mark.parametrize("padding", [1.0, 3.01, float("inf"), float("nan")])
def test_padding_is_finite_and_adds_space(padding):
    with pytest.raises(ValueError, match="padding"):
        validate_settings(PreviewSettings(padding=padding))


@pytest.mark.parametrize(
    "bounds",
    [
        None,
        PreviewBounds((0, 0, 0), (0, 0, 0)),
        PreviewBounds((float("nan"), 0, 0), (1, 1, 1)),
        PreviewBounds((0, 0, 0), (-1, 1, 1)),
    ],
)
def test_automatic_framing_rejects_missing_or_unusable_bounds(bounds):
    with pytest.raises(ValueError, match="bounds"):
        frame_views(bounds, PreviewSettings())


def test_automatic_framing_requires_complete_bounds_but_allows_a_plane():
    bounds = PreviewBounds((3, -2, 4), (5, 0, 2))

    with pytest.raises(ValueError, match="incomplete"):
        frame_views(bounds, PreviewSettings(), bounds_complete=False)

    views = frame_views(bounds, PreviewSettings())
    assert len(views) == 3
    assert all(view.size > 0 and 0 < view.near < view.far for view in views)


def _camera(name, *, position=(0.0, 0.0, 4.0), target=(0.0, 0.0, 0.0), **kw):
    return PreviewCamera(
        name=name,
        position=position,
        target=target,
        size=kw.get("size", 4.0),
        near=kw.get("near", 0.1),
        far=kw.get("far", 20.0),
        up=kw.get("up", (0.0, 1.0, 0.0)),
    )


def _override(**replacement):
    cameras = [
        _camera("front"),
        _camera("side", position=(4.0, 0.0, 0.0)),
        _camera("three_quarter", position=(4.0, 2.0, 4.0)),
    ]
    if replacement:
        index = replacement.pop("index")
        cameras[index] = _camera(cameras[index].name, **replacement)
    return tuple(cameras)


def test_complete_explicit_override_bypasses_automatic_bounds():
    cameras = _override()

    assert (
        frame_views(
            None,
            PreviewSettings(cameras=cameras),
            bounds_complete=False,
        )
        == cameras
    )


def test_override_requires_exact_canonical_order():
    wrong_order = (_camera("side"), _camera("front"), _camera("three_quarter"))
    with pytest.raises(ValueError, match="front, side, three_quarter"):
        validate_settings(PreviewSettings(cameras=wrong_order))


@pytest.mark.parametrize(
    "replacement,match",
    [
        ({"index": 0, "position": (float("inf"), 0, 4)}, "finite"),
        ({"index": 0, "target": (0, 0, 4)}, "direction"),
        ({"index": 0, "up": (0, 0, 0)}, "up"),
        ({"index": 0, "up": (0, 0, 1)}, "parallel"),
        ({"index": 0, "size": 0}, "size"),
        ({"index": 0, "near": 0}, "near"),
        ({"index": 0, "near": 2, "far": 1}, "far"),
    ],
)
def test_override_rejects_invalid_camera_geometry(replacement, match):
    with pytest.raises(ValueError, match=match):
        validate_settings(PreviewSettings(cameras=_override(**replacement)))
