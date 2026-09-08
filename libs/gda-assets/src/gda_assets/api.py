"""Supported host-facing API for the internal asset workflow library."""

from pathlib import Path

from gda_assets.application.check import check_model as _check_model
from gda_assets.application.ports import ModelInspectionPort
from gda_assets.application.ports import GodotImportObservationPort
from gda_assets.application.ports import GodotRefreshPort
from gda_assets.domain.refresh import (
    RefreshRequest,
    RefreshResult,
    ModelContent,
    ImportedContent,
    InstanceContent,
    SessionState,
    CaptureObservation,
    StopObservation,
    StartObservation,
    ReadyObservation,
)
from gda_assets.domain.observations import (
    CollectionRequest,
    ContentObservations,
    ImportAssetFacts,
)
from gda_assets.domain.model import (
    ModelFacts,
    ModelCheckResult,
    ModelComparison,
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
    "RefreshRequest",
    "RefreshResult",
    "ModelContent",
    "ImportedContent",
    "InstanceContent",
    "SessionState",
    "CaptureObservation",
    "StopObservation",
    "StartObservation",
    "ReadyObservation",
    "GodotRefreshPort",
    "CollectionRequest",
    "ContentObservations",
    "ImportAssetFacts",
    "GodotImportObservationPort",
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
    "ModelComparison",
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
    collection: CollectionRequest | None = None,
    import_observer: GodotImportObservationPort | None = None,
    refresh: RefreshRequest | None = None,
    runtime: GodotRefreshPort | None = None,
) -> PipelineResult:
    """Compose local file handling with the host's injected Godot capabilities."""
    from gda_assets.adapters.files import LocalFiles
    from gda_assets.adapters.observations import LocalObservationFiles

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
        collection=collection,
        import_observer=import_observer,
        observation_files=LocalObservationFiles(project_root) if collection else None,
        refresh=refresh,
        runtime=runtime,
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
