"""Fixed model-preview setup and compatible scene-level comparisons."""

from dataclasses import dataclass
import math
from typing import Literal


Vector3 = tuple[float, float, float]
ViewName = Literal["front", "side", "three_quarter"]
VIEW_NAMES: tuple[ViewName, ...] = ("front", "side", "three_quarter")


@dataclass(frozen=True)
class PreviewBounds:
    position: Vector3
    size: Vector3


@dataclass(frozen=True)
class PreviewCamera:
    name: ViewName
    position: Vector3
    target: Vector3
    size: float
    near: float
    far: float
    up: Vector3 = (0.0, 1.0, 0.0)


@dataclass(frozen=True)
class PreviewSettings:
    width: int = 640
    height: int = 360
    padding: float = 1.15
    cameras: tuple[PreviewCamera, ...] = ()


def _finite_vector(vector: Vector3) -> bool:
    return len(vector) == 3 and all(math.isfinite(value) for value in vector)


def _validate_camera(camera: PreviewCamera) -> None:
    if not all(
        _finite_vector(vector) for vector in (camera.position, camera.target, camera.up)
    ):
        raise ValueError(f"camera {camera.name} vectors must be finite Vector3 values")
    direction = (
        camera.target[0] - camera.position[0],
        camera.target[1] - camera.position[1],
        camera.target[2] - camera.position[2],
    )
    if math.hypot(*direction) == 0:
        raise ValueError(f"camera {camera.name} direction must be nonzero")
    if math.hypot(*camera.up) == 0:
        raise ValueError(f"camera {camera.name} up vector must be nonzero")
    if math.hypot(*_cross(direction, camera.up)) <= 1e-12:
        raise ValueError(f"camera {camera.name} direction and up cannot be parallel")
    if not math.isfinite(camera.size) or camera.size <= 0:
        raise ValueError(f"camera {camera.name} size must be finite and positive")
    if not math.isfinite(camera.near) or camera.near <= 0:
        raise ValueError(f"camera {camera.name} near must be finite and positive")
    if not math.isfinite(camera.far) or camera.far <= camera.near:
        raise ValueError(
            f"camera {camera.name} far must be finite and greater than near"
        )


def validate_settings(settings: PreviewSettings) -> None:
    """Reject preview settings that cannot produce the bounded three-view setup."""
    if (
        not isinstance(settings.width, int)
        or isinstance(settings.width, bool)
        or not isinstance(settings.height, int)
        or isinstance(settings.height, bool)
        or not 64 <= settings.width <= 2048
        or not 64 <= settings.height <= 2048
    ):
        raise ValueError("preview viewport width and height must be in 64..2048")
    if not math.isfinite(settings.padding) or not 1 < settings.padding <= 3:
        raise ValueError("preview padding must be finite and in (1, 3]")
    if settings.cameras:
        names = tuple(camera.name for camera in settings.cameras)
        if names != VIEW_NAMES:
            raise ValueError(
                "camera overrides must be exactly front, side, three_quarter in order"
            )
        for camera in settings.cameras:
            _validate_camera(camera)


def _validate_bounds(bounds: PreviewBounds | None, *, complete: bool) -> PreviewBounds:
    if bounds is None:
        raise ValueError("automatic framing requires bounds")
    if not complete:
        raise ValueError("automatic framing cannot use incomplete bounds")
    if not _finite_vector(bounds.position) or not _finite_vector(bounds.size):
        raise ValueError("automatic framing bounds must be finite Vector3 values")
    if any(value < 0 for value in bounds.size):
        raise ValueError("automatic framing bounds size must be nonnegative")
    if not any(value > 0 for value in bounds.size):
        raise ValueError("automatic framing bounds contain no geometry")
    return bounds


def _dot(left: Vector3, right: Vector3) -> float:
    return sum(a * b for a, b in zip(left, right))


def _cross(left: Vector3, right: Vector3) -> Vector3:
    a, b, c = left
    x, y, z = right
    return b * z - c * y, c * x - a * z, a * y - b * x


def _unit(vector: Vector3) -> Vector3:
    length = math.hypot(*vector)
    return vector[0] / length, vector[1] / length, vector[2] / length


def cameras_match(expected: PreviewCamera, actual: PreviewCamera) -> bool:
    """Compare applied camera frames, allowing native numeric projection precision."""
    try:
        _validate_camera(expected)
        _validate_camera(actual)
    except ValueError:
        return False
    frames = []
    for camera in (expected, actual):
        back = _unit(
            (
                camera.position[0] - camera.target[0],
                camera.position[1] - camera.target[1],
                camera.position[2] - camera.target[2],
            )
        )
        up = _unit(_cross(back, _unit(_cross(camera.up, back))))
        frames.append(
            camera.position + back + up + (camera.size, camera.near, camera.far)
        )
    return expected.name == actual.name and all(
        math.isclose(left, right, rel_tol=1e-5, abs_tol=1e-5)
        for left, right in zip(*frames)
    )


def frame_views(
    bounds: PreviewBounds | None,
    settings: PreviewSettings,
    *,
    bounds_complete: bool = True,
) -> tuple[PreviewCamera, ...]:
    """Fit projected AABB corners with an orthographic, height-preserving camera."""
    validate_settings(settings)
    if settings.cameras:
        return settings.cameras
    bounds = _validate_bounds(bounds, complete=bounds_complete)
    p, s = bounds.position, bounds.size
    center = p[0] + s[0] / 2, p[1] + s[1] / 2, p[2] + s[2] / 2
    offsets = [
        (x * s[0] / 2, y * s[1] / 2, z * s[2] / 2)
        for x in (-1, 1)
        for y in (-1, 1)
        for z in (-1, 1)
    ]
    views = []
    axes: tuple[Vector3, ...] = ((0, 0, 1), (1, 0, 0), (1, 0.55, 1))
    for name, axis in zip(VIEW_NAMES, axes):
        back = _unit(axis)
        right = _unit(_cross((0.0, 1.0, 0.0), back))
        up = _unit(_cross(back, right))
        hx = max(abs(_dot(point, right)) for point in offsets)
        hy = max(abs(_dot(point, up)) for point in offsets)
        hd = max(abs(_dot(point, back)) for point in offsets)
        size = settings.padding * max(
            2 * hy, 2 * hx * settings.height / settings.width, 0.01
        )
        distance = hd + 2 * size
        views.append(
            PreviewCamera(
                name=name,
                position=(
                    center[0] + back[0] * distance,
                    center[1] + back[1] * distance,
                    center[2] + back[2] * distance,
                ),
                target=center,
                size=size,
                near=max(0.01, distance - hd - size),
                far=distance + hd + size,
                up=up,
            )
        )
    return tuple(views)
