"""Place selected files, import them, and ask the host what Godot loaded."""

from pathlib import Path
from tempfile import TemporaryDirectory
from dataclasses import replace

from gda_assets.application.ports import (
    AssetFilesPort,
    GodotAssetPort,
    PortFailure,
    AssetProducer,
    ProductionRequest,
    GodotImportObservationPort,
    ObservationFilesPort,
)
from gda_assets.application.observe import observe_before, finish_collection
from gda_assets.domain.observations import (
    CollectionRequest,
    ContentObservations,
    validate_collection,
)
from gda_assets.domain.artifacts import PipelineFailure, PipelineResult
from gda_assets.domain.recipe import AssetRecipe, validate_recipe


def run_pipeline(
    recipe: AssetRecipe,
    *,
    source_root: Path | None,
    project_root: Path,
    godot: GodotAssetPort,
    files: AssetFilesPort,
    production: ProductionRequest | None = None,
    producer: AssetProducer | None = None,
    collection: CollectionRequest | None = None,
    import_observer: GodotImportObservationPort | None = None,
    observation_files: ObservationFilesPort | None = None,
) -> PipelineResult:
    result = PipelineResult(
        source_mode=recipe.source_mode, caller_declared_provenance=recipe.provenance
    )
    stage = "validate"
    workspace = None
    import_attempted = False
    try:
        if collection is not None:
            if import_observer is None or observation_files is None:
                raise PortFailure(
                    "invalid_collection", "Collection requires observation ports"
                )
            try:
                validate_collection(
                    collection,
                    [
                        item.target
                        for item in (production.outputs if production else recipe.files)
                    ],
                )
            except ValueError as exc:
                raise PortFailure("invalid_collection", str(exc)) from exc
            if collection.save_to is not None:
                observation_files.validate_output(collection.save_to)
        with TemporaryDirectory(prefix="gda-assets-") as workspace:
            if production is not None:
                if recipe.files:
                    raise PortFailure(
                        "invalid_recipe",
                        "Select existing files or production, not both",
                    )
                stage = "produce"
                if producer is None:
                    raise PortFailure(
                        "unsupported_producer",
                        f"Unsupported producer: {production.kind}",
                    )
                produced = producer.produce(production, source_root, Path(workspace))
                result.production = produced.observations
                result.source_mode = produced.source_mode
                recipe = replace(recipe, files=produced.files)
                result.completed.append(stage)
            stage = "validate"
            try:
                validate_recipe(recipe)
            except ValueError as exc:
                raise PortFailure("invalid_recipe", str(exc)) from exc
            plans = files.validate(recipe, source_root or project_root, project_root)
            result.completed.append(stage)
            stage = "stage"
            staged = [
                files.stage(plan, Path(workspace), index)
                for index, plan in enumerate(plans)
            ]
            files.validate_installation(staged, overwrite=recipe.overwrite)
            result.completed.append(stage)
            stage = "install"
            for item in staged:
                result.outputs.append(files.install(item, overwrite=recipe.overwrite))
            result.completed.append(stage)
            stage = "import"
            if collection is not None:
                assert import_observer is not None and observation_files is not None
                stage = "observe"
                result.content_observations = ContentObservations(
                    declared_output_sha256=dict(collection.declared_output_sha256)
                )
                observe_before(
                    result.content_observations,
                    recipe,
                    import_observer,
                    observation_files,
                )
                stage = "import"
            import_attempted = True
            result.import_result = godot.import_assets(
                [item.target for item in recipe.files]
            )
            result.completed.append(stage)
            stage = "load"
            for item in recipe.files:
                result.observations.append(godot.check_load(item.target))
            result.completed.append(stage)
    except PortFailure as exc:
        result.failure = PipelineFailure(stage, exc.code, str(exc), exc.cause)
    except OSError as exc:
        result.failure = PipelineFailure(stage, "file_io_failed", str(exc))
    finally:
        if (
            result.content_observations is not None
            and collection is not None
            and import_observer is not None
            and observation_files is not None
        ):
            finish_collection(
                result,
                collection,
                import_observer,
                observation_files,
                import_attempted=import_attempted,
            )
        if production is not None and workspace is not None:
            result.cleanup = {"workspace_removed": not Path(workspace).exists()}
    return result
