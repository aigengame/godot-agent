"""Supported host-facing API for the internal asset workflow library."""

from pathlib import Path

from gda_assets.application.integrate import run_pipeline as _run_pipeline
from gda_assets.application.ports import (
    GodotAssetPort,
    PortFailure,
    ProductionRequest,
    ProductionOutput,
)
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
    "ProductionRequest",
    "ProductionOutput",
    "Resize",
    "run_pipeline",
]


def run_pipeline(
    recipe: AssetRecipe,
    *,
    source_root: Path | None,
    project_root: Path,
    godot: GodotAssetPort,
    production: ProductionRequest | None = None,
) -> PipelineResult:
    """Compose local file handling with the host's injected Godot capabilities."""
    from gda_assets.adapters.files import LocalFiles

    producer = None
    if production is not None and production.kind == "blender_saved":
        from gda_assets.adapters.blender import BlenderSavedProducer

        producer = BlenderSavedProducer()

    return _run_pipeline(
        recipe,
        source_root=source_root,
        project_root=project_root,
        godot=godot,
        files=LocalFiles(),
        production=production,
        producer=producer,
    )
