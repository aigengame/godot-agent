"""Supported host-facing API for the internal asset workflow library."""

from pathlib import Path

from gda_assets.application.check import check_model as _check_model
from gda_assets.application.ports import ModelInspectionPort
from gda_assets.domain.model import (
    ModelFacts,
    ModelCheckResult,
    NodeFacts,
    MaterialFacts,
    SurfaceFacts,
    BoneFacts,
    BindFacts,
    TrackFacts,
    AnimationFacts,
)

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
    "check_model",
    "ModelFacts",
    "NodeFacts",
    "MaterialFacts",
    "SurfaceFacts",
    "BoneFacts",
    "BindFacts",
    "TrackFacts",
    "AnimationFacts",
    "ModelCheckResult",
    "ModelInspectionPort",
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


def check_model(
    expectations: Path,
    *,
    path: str | None = None,
    godot: ModelInspectionPort | None = None,
    report: ModelFacts | None = None,
    subtree: str = ".",
    max_nodes: int = 256,
    max_items: int = 1024,
    baseline: ModelFacts | None = None,
) -> ModelCheckResult:
    """Read project expectations and evaluate injected or previously observed facts."""
    from gda_assets.adapters.expectations import read_expectations

    try:
        conditions = read_expectations(expectations)
    except PortFailure as exc:
        return ModelCheckResult(
            failure=PipelineFailure("validate", exc.code, str(exc), exc.cause)
        )
    return _check_model(
        conditions,
        path=path,
        godot=godot,
        report=report,
        subtree=subtree,
        max_nodes=max_nodes,
        max_items=max_items,
        baseline=baseline,
    )
