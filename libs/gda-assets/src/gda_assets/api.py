"""Supported host-facing API for the internal asset workflow library."""

from pathlib import Path

from gda_assets.application.package_ports import GodotPackagePort
from gda_assets.domain.package import (
    PackageCheckRequest,
    PackageCheckResult,
    PackageEngine,
    PackageInspection,
    PackagePresence,
    PackageResource,
)
from gda_assets.application.preview_ports import GodotPreviewPort, PreviewHost
from gda_assets.domain.preview import PreviewBounds, PreviewCamera, PreviewSettings
from gda_assets.domain.preview_result import (
    PreviewRequest,
    PreviewResult,
    PreviewNode,
    PreviewInspection,
    PreviewState,
    PreviewCapture,
    PreviewStats,
    PreviewSample,
    PreviewBudget,
    PreviewPerformance,
    PreviewDiagnostic,
    PreviewDiagnostics,
)
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
from gda_assets.domain.prompt import (
    JsonScalar,
    PromptOptionKey,
    PromptDeclarationKey,
    PromptFile,
    PromptHandoff,
    PromptOutput,
    PromptOutputRequest,
    PromptPreparation,
    PromptPrepareRequest,
    PromptRecord,
    PromptRevision,
    PromptRevisionRequest,
)
from gda_assets.domain.concept import (
    AuthoringArtifact,
    ConceptAuthoringResult,
    ConceptAuthorRequest,
    ConceptBrief,
    ConceptBriefSnapshot,
    ConceptCandidate,
    ConceptConsumer,
    ConceptPreparation,
    ConceptPrepareRequest,
    ConceptSelection,
    ConceptSelectRequest,
    ConceptUse,
    ConsumedConcept,
    SelectedConcept,
    SpriteSheetLayout,
    SpriteSheetObservation,
)

__all__ = [
    "check_package",
    "GodotPackagePort",
    "PackageCheckRequest",
    "PackageCheckResult",
    "PackageEngine",
    "PackageInspection",
    "PackagePresence",
    "PackageResource",
    "preview_asset",
    "GodotPreviewPort",
    "PreviewHost",
    "PreviewBounds",
    "PreviewCamera",
    "PreviewSettings",
    "PreviewRequest",
    "PreviewResult",
    "PreviewNode",
    "PreviewInspection",
    "PreviewState",
    "PreviewCapture",
    "PreviewStats",
    "PreviewSample",
    "PreviewBudget",
    "PreviewPerformance",
    "PreviewDiagnostic",
    "PreviewDiagnostics",
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
    "JsonScalar",
    "PromptOptionKey",
    "PromptDeclarationKey",
    "PromptFile",
    "PromptHandoff",
    "PromptOutput",
    "PromptOutputRequest",
    "PromptPreparation",
    "PromptPrepareRequest",
    "PromptRecord",
    "PromptRevision",
    "PromptRevisionRequest",
    "prepare_prompt",
    "inspect_prompt",
    "revise_prompt",
    "register_prompt_output",
    "AuthoringArtifact",
    "ConceptAuthoringResult",
    "ConceptAuthorRequest",
    "ConceptBrief",
    "ConceptBriefSnapshot",
    "ConceptCandidate",
    "ConceptConsumer",
    "ConceptPreparation",
    "ConceptPrepareRequest",
    "ConceptSelection",
    "ConceptSelectRequest",
    "ConceptUse",
    "ConsumedConcept",
    "SelectedConcept",
    "SpriteSheetLayout",
    "SpriteSheetObservation",
    "prepare_concept",
    "select_concept",
    "author_concept",
]


def prepare_concept(request: ConceptPrepareRequest) -> ConceptPreparation:
    """Preserve a concept brief and its external generation handoff."""
    from gda_assets.adapters.concept_files import ConceptFiles
    from gda_assets.adapters.prompt_files import PromptFiles
    from gda_assets.application.concept import prepare_concept as _prepare_concept

    return _prepare_concept(request, files=ConceptFiles(), prompts=PromptFiles())


def select_concept(request: ConceptSelectRequest) -> ConceptSelection:
    """Pin explicitly completed, registered candidates into one handoff."""
    from gda_assets.adapters.concept_files import ConceptFiles
    from gda_assets.adapters.prompt_files import PromptFiles
    from gda_assets.application.concept import select_concept as _select_concept

    return _select_concept(request, files=ConceptFiles(), prompts=PromptFiles())


def author_concept(request: ConceptAuthorRequest) -> ConceptAuthoringResult:
    """Run one of the two bounded selected-reference authoring examples."""
    from gda_assets.adapters.concept_authoring import (
        BlenderReferenceBlockoutAuthor,
        SpriteSheetReferenceAuthor,
    )
    from gda_assets.adapters.concept_files import ConceptFiles
    from gda_assets.application.concept import author_concept as _author_concept

    if request.consumer == "blender-reference-blockout":
        author = BlenderReferenceBlockoutAuthor()
    elif request.consumer == "sprite-sheet-reference":
        author = SpriteSheetReferenceAuthor()
    else:
        raise PortFailure(
            "unsupported_concept_consumer",
            f"Unsupported concept consumer: {request.consumer}",
        )
    return _author_concept(request, files=ConceptFiles(), author=author)


def prepare_prompt(request: PromptPrepareRequest) -> PromptPreparation:
    """Save one prompt record before an external generation attempt."""
    from gda_assets.adapters.prompt_files import PromptFiles
    from gda_assets.application.prompt import prepare_prompt as _prepare_prompt

    return _prepare_prompt(request, files=PromptFiles())


def inspect_prompt(record: Path) -> PromptPreparation:
    """Inspect and reuse an existing prompt record from any working directory."""
    from gda_assets.adapters.prompt_files import PromptFiles
    from gda_assets.application.prompt import inspect_prompt as _inspect_prompt

    return _inspect_prompt(record, files=PromptFiles())


def revise_prompt(request: PromptRevisionRequest) -> PromptRevision:
    """Create a separate prompt record from saved inputs plus explicit changes."""
    from gda_assets.adapters.prompt_files import PromptFiles
    from gda_assets.application.prompt import revise_prompt as _revise_prompt

    return _revise_prompt(request, files=PromptFiles())


def register_prompt_output(request: PromptOutputRequest) -> PromptRecord:
    """Associate a validated local PNG without invoking a producer."""
    from gda_assets.adapters.prompt_files import PromptFiles
    from gda_assets.application.prompt import (
        register_prompt_output as _register_prompt_output,
    )

    return _register_prompt_output(request, files=PromptFiles())


def check_package(
    request: PackageCheckRequest, *, godot: GodotPackagePort
) -> PackageCheckResult:
    """Inspect a local PCK and apply the same project-owned model expectations."""
    from gda_assets.adapters.expectations import read_expectations
    from gda_assets.adapters.package_files import PackageFiles
    from gda_assets.application.package import check_package as _check_package

    try:
        conditions = read_expectations(request.expectations)
    except PortFailure as exc:
        return PackageCheckResult(
            request,
            failure=PipelineFailure("validate", exc.code, str(exc), exc.cause),
        )
    return _check_package(request, conditions, godot=godot, files=PackageFiles())


def preview_asset(request: PreviewRequest, *, host: PreviewHost) -> PreviewResult:
    """Run the isolated preview using the host's bound Godot capabilities."""
    from gda_assets.adapters.preview_files import PreviewFiles
    from gda_assets.application.preview import preview_asset as _preview_asset

    return _preview_asset(request, host=host, files=PreviewFiles())


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
