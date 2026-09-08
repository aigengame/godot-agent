"""Project-facing model facts, independent of the engine's report representation."""

from dataclasses import dataclass, field
from typing import Any, Literal

from gda_assets.domain.artifacts import PipelineFailure

Verdict = Literal["pass", "fail", "insufficient"]


@dataclass(frozen=True)
class MaterialFacts:
    type: str
    name: str
    path: str | None
    source: str
    textures: tuple[tuple[str, str, str | None], ...] = ()
    textures_available: bool = True


@dataclass(frozen=True)
class SurfaceFacts:
    index: int
    geometry: dict[str, Any]
    material: MaterialFacts | None = None


@dataclass(frozen=True)
class BoneFacts:
    index: int
    name: str
    parent: int
    rest: tuple[float, ...]


@dataclass(frozen=True)
class BindFacts:
    index: int
    bone_index: int | None
    reason: str | None


@dataclass(frozen=True)
class TrackFacts:
    index: int
    type: str
    path: str
    enabled: bool
    target: str | None
    bone: str | None
    status: str
    scope: str | None
    reason: str | None


@dataclass(frozen=True)
class AnimationFacts:
    name: str
    length: float
    loop_mode: int
    track_count: int
    tracks: tuple[TrackFacts, ...] = ()


@dataclass(frozen=True)
class NodeFacts:
    path: str
    type: str
    transform: tuple[float, ...] | None = None
    surface_count: int | None = None
    surfaces: tuple[SurfaceFacts, ...] = ()
    bone_count: int | None = None
    bones: tuple[BoneFacts, ...] = ()
    skin_present: bool = False
    skin_unavailable: str | None = None
    skeleton: str | None = None
    bind_count: int | None = None
    binds: tuple[BindFacts, ...] = ()
    animation_count: int | None = None
    animations: tuple[AnimationFacts, ...] = ()


@dataclass(frozen=True)
class ModelFacts:
    resource: str
    subtree: str
    engine: tuple[int, int]
    measurement: tuple[str, str]
    nodes: tuple[NodeFacts, ...]
    counts: dict[str, int]
    bounds: dict[str, Any] | None
    omissions: tuple[tuple[str, str], ...] = ()

    def incomplete(self, section: str, node: str | None = None) -> bool:
        return any(
            s == section and (node is None or p == node) for p, s in self.omissions
        )

    def includes(self, node: str) -> bool:
        return (
            self.subtree == "."
            or node == self.subtree
            or node.startswith(self.subtree + "/")
        )


@dataclass(frozen=True)
class CheckResult:
    id: str
    verdict: Verdict
    location: dict[str, Any]
    expected: Any
    actual: Any
    reason: str


@dataclass(frozen=True)
class ModelChange:
    section: str
    location: dict[str, Any]
    kind: Literal["added", "removed", "changed"]
    before: Any
    after: Any


@dataclass(frozen=True)
class IncompleteSection:
    section: str
    reason: str
    node: str


@dataclass(frozen=True)
class ComparedResources:
    before: str
    after: str


@dataclass(frozen=True)
class ModelComparison:
    status: Literal["comparable", "partial", "non_comparable"]
    reasons: list[str]
    resources: ComparedResources
    changes: list[ModelChange]
    incomplete_sections: list[IncompleteSection]


@dataclass
class ModelCheckResult:
    completed: list[str] = field(default_factory=list)
    resource: str | None = None
    observation_source: str | None = None
    verdict: Verdict | None = None
    checks: list[CheckResult] = field(default_factory=list)
    comparison: ModelComparison | None = None
    failure: PipelineFailure | None = None
