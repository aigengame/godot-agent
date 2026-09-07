"""Supported host-facing API for the internal asset workflow library."""

from pathlib import Path

from gda_assets.application.integrate import run_pipeline as _run_pipeline
from gda_assets.application.ports import GodotAssetPort, PortFailure
from gda_assets.domain.artifacts import (
    ImportOutcome,
    InstalledFile,
    LoadObservation,
    PipelineResult,
    PipelineFailure,
)
from gda_assets.domain.recipe import AssetFile, AssetRecipe, Resize

__all__ = [
    "AssetFile",
    "AssetRecipe",
    "GodotAssetPort",
    "ImportOutcome",
    "InstalledFile",
    "LoadObservation",
    "PipelineResult",
    "PipelineFailure",
    "PortFailure",
    "Resize",
    "run_pipeline",
]


def run_pipeline(
    recipe: AssetRecipe,
    *,
    source_root: Path,
    project_root: Path,
    godot: GodotAssetPort,
) -> PipelineResult:
    """Compose local file handling with the host's injected Godot capabilities."""
    from gda_assets.adapters.files import LocalFiles

    return _run_pipeline(
        recipe,
        source_root=source_root,
        project_root=project_root,
        godot=godot,
        files=LocalFiles(),
    )
