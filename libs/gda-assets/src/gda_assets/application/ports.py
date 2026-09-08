"""Godot capabilities implemented by the host, with no import of gda."""

from typing import Protocol
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gda_assets.domain.artifacts import ImportOutcome, InstalledFile, LoadObservation
from gda_assets.domain.recipe import AssetFile, AssetRecipe
from gda_assets.domain.model import ModelFacts
from gda_assets.domain.refresh import (
    ImportedContent,
    InstanceContent,
    SessionState,
    CaptureObservation,
)
from gda_assets.domain.observations import (
    FileDigest,
    ImportAssetFacts,
    ContentObservations,
)


@dataclass(frozen=True)
class ProductionOutput:
    role: str
    target: str


@dataclass(frozen=True)
class ProductionRequest:
    kind: str
    outputs: tuple[ProductionOutput, ...]
    options: dict[str, Any]


@dataclass(frozen=True)
class ProducedFiles:
    files: tuple[AssetFile, ...]
    source_mode: str
    observations: dict[str, Any]


class AssetProducer(Protocol):
    def produce(
        self, request: ProductionRequest, source_root: Path | None, workspace: Path
    ) -> ProducedFiles: ...


class PortFailure(Exception):
    def __init__(self, code: str, message: str, *, cause: dict | None = None):
        super().__init__(message)
        self.code = code
        self.cause = cause


@dataclass(frozen=True)
class FilePlan:
    item: AssetFile
    source: Path
    target: Path


@dataclass(frozen=True)
class StagedFile:
    plan: FilePlan
    path: Path


class AssetFilesPort(Protocol):
    def validate(
        self, recipe: AssetRecipe, source_root: Path, project_root: Path
    ) -> list[FilePlan]: ...

    def stage(self, plan: FilePlan, workspace: Path, index: int) -> StagedFile: ...

    def validate_installation(
        self, staged: list[StagedFile], *, overwrite: bool
    ) -> None: ...

    def install(self, staged: StagedFile, *, overwrite: bool) -> InstalledFile: ...


class GodotAssetPort(Protocol):
    def import_assets(self, paths: list[str]) -> ImportOutcome: ...

    def check_load(self, path: str) -> LoadObservation: ...


class GodotImportObservationPort(Protocol):
    def observe_import(self, paths: list[str]) -> list[ImportAssetFacts]: ...


class ObservationFilesPort(Protocol):
    def digest(self, resource: str) -> FileDigest: ...

    def validate_output(self, path: Path) -> None: ...

    def save(self, observations: ContentObservations, path: Path) -> None: ...


class ModelInspectionPort(Protocol):
    def inspect_model(
        self, path: str, *, subtree: str, max_nodes: int, max_items: int
    ) -> "ModelFacts": ...


class GodotRefreshPort(Protocol):
    def inspect_content(
        self, path: str, *, max_nodes: int, max_vertices: int
    ) -> ImportedContent: ...

    def status(self) -> SessionState: ...

    def stop(self) -> dict[str, Any]: ...

    def start(self, scene: str, *, windowed: bool) -> dict[str, Any]: ...

    def wait_ready(self, timeout: float) -> dict[str, Any]: ...

    def observe_content(
        self, node: str, *, max_nodes: int, max_vertices: int
    ) -> InstanceContent: ...

    def capture(self, output: Path) -> CaptureObservation: ...
