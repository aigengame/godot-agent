"""Bounded results for one invocation, without a persistent workflow identity."""

from dataclasses import dataclass, field
from typing import Any

from gda_assets.domain.recipe import Resize
from gda_assets.domain.observations import ContentObservations


@dataclass(frozen=True)
class InstalledFile:
    source: str
    target: str
    state: str
    resize: Resize | None = None


@dataclass(frozen=True)
class ImportOutcome:
    facts: dict[str, Any]


@dataclass(frozen=True)
class LoadObservation:
    path: str
    resource_type: str
    texture_size: tuple[int, int] | None = None
    scene_node_count: int | None = None
    engine: dict[str, Any] | None = None


@dataclass(frozen=True)
class PipelineFailure:
    stage: str
    code: str
    message: str
    cause: dict[str, Any] | None = None


@dataclass
class PipelineResult:
    source_mode: str = "existing"
    caller_declared_provenance: dict[str, Any] | None = None
    completed: list[str] = field(default_factory=list)
    outputs: list[InstalledFile] = field(default_factory=list)
    import_result: ImportOutcome | None = None
    observations: list[LoadObservation] = field(default_factory=list)
    failure: PipelineFailure | None = None
    production: dict[str, Any] | None = None
    cleanup: dict[str, bool] | None = None
    content_observations: ContentObservations | None = None
