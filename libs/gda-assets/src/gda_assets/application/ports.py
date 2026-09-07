"""Godot capabilities implemented by the host, with no import of gda."""

from typing import Protocol
from dataclasses import dataclass
from pathlib import Path

from gda_assets.domain.artifacts import ImportOutcome, InstalledFile, LoadObservation
from gda_assets.domain.recipe import AssetFile, AssetRecipe


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
