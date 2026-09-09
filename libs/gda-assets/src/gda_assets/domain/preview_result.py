"""Compact observations from one isolated preview invocation."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from gda_assets.domain.artifacts import PipelineFailure
from gda_assets.domain.preview import (
    PreviewBounds,
    PreviewCamera,
    PreviewSettings,
    Vector3,
)
from gda_assets.domain.refresh import CaptureObservation, SessionState


@dataclass(frozen=True)
class PreviewRequest:
    source: Path
    output_dir: Path
    settings: PreviewSettings = field(default_factory=PreviewSettings)
    frames: int = 60
    timeout: float = 25.0
    max_nodes: int = 256
    budget: Path | None = None
    baseline: Path | None = None
    warmup_seconds: float = 0.0


@dataclass(frozen=True)
class PreviewNode:
    path: str
    type: str


@dataclass(frozen=True)
class PreviewInspection:
    resource: str
    engine: str
    coordinate_space: str
    geometry: str
    bounds: PreviewBounds | None
    nodes: tuple[PreviewNode, ...]
    omissions: tuple[tuple[str, str], ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class PreviewState:
    index: int
    camera: PreviewCamera
    viewport: tuple[int, int]
    renderer: str
    engine: str
    platform: str
    pose: Literal["static_imported"]
    background: tuple[float, float, float, float]
    ambient_energy: float
    light_energy: float
    light_rotation: Vector3
    overlays: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreviewCapture:
    receipt: CaptureObservation
    width: int
    height: int
    frames_waited: int
    applied_view: int


@dataclass(frozen=True)
class PreviewView:
    state: PreviewState | None
    capture: PreviewCapture


@dataclass(frozen=True)
class PreviewStats:
    count: int
    min: float
    max: float
    mean: float
    p50: float
    p95: float


@dataclass(frozen=True)
class PreviewSample:
    frame: int
    timestamp: int
    values: dict[str, float]


@dataclass(frozen=True)
class PreviewBudget:
    stat: str
    value: float
    min: float | None
    max: float | None
    passed: bool


@dataclass(frozen=True)
class PreviewPerformance:
    frames: int
    stats: dict[str, PreviewStats]
    samples: tuple[PreviewSample, ...]
    budget: dict[str, PreviewBudget] | None
    passed: bool | None


@dataclass(frozen=True)
class PreviewDiagnostic:
    level: str
    message: str
    file: str | None
    line: int | None


@dataclass(frozen=True)
class PreviewDiagnostics:
    errors: tuple[PreviewDiagnostic, ...]
    truncated: bool


@dataclass(frozen=True)
class PreviewMetricChange:
    before: PreviewStats
    after: PreviewStats
    mean_delta: float
    p95_delta: float
    before_budget: PreviewBudget | None = None
    after_budget: PreviewBudget | None = None


_PERFORMANCE_LIMITATIONS = (
    "FPS is a sampled scene-level counter affected by startup and measurement conditions; repeated per-frame samples can read the same counter update.",
    "Comparable setup, including the optional wait, does not establish stabilized performance or per-mesh cost; low FPS values are retained.",
)


@dataclass(frozen=True)
class PreviewComparison:
    status: Literal["comparable", "non_comparable"]
    reasons: tuple[str, ...]
    changes: dict[str, PreviewMetricChange] = field(default_factory=dict)
    baseline_origin: Literal["supplied_preview_result"] = "supplied_preview_result"
    limitations: tuple[str, ...] = _PERFORMANCE_LIMITATIONS


@dataclass
class PreviewCleanup:
    session_stopped: bool = False
    project_removed: bool = False
    issues: list[str] = field(default_factory=list)


@dataclass
class PreviewResult:
    request: PreviewRequest
    completed: list[str] = field(default_factory=list)
    project: str | None = None
    source_sha256: str | None = None
    inspection: PreviewInspection | None = None
    views: list[PreviewView] = field(default_factory=list)
    session: SessionState | None = None
    performance: PreviewPerformance | None = None
    performance_session: str | None = None
    diagnostics: PreviewDiagnostics | None = None
    comparison: PreviewComparison | None = None
    cleanup: PreviewCleanup = field(default_factory=PreviewCleanup)
    failure: PipelineFailure | None = None
    limitations: tuple[str, ...] = (
        "Static imported pose and mesh bounds do not establish animated-pose or collision bounds.",
        "View names use Godot axes; resource-relative node names do not guarantee a Blender source-object mapping.",
        "Performance samples are scene-level observations at the final view, not per-mesh GPU cost.",
        "The performance window starts after the final view and optional bounded wait.",
        *_PERFORMANCE_LIMITATIONS,
        "A repeated setup does not promise identical pixels or performance across runs.",
    )
