"""Place selected files, import them, and ask the host what Godot loaded."""

from pathlib import Path
from tempfile import TemporaryDirectory

from gda_assets.application.ports import AssetFilesPort, GodotAssetPort, PortFailure
from gda_assets.domain.artifacts import PipelineFailure, PipelineResult
from gda_assets.domain.recipe import AssetRecipe, validate_recipe


def run_pipeline(
    recipe: AssetRecipe,
    *,
    source_root: Path,
    project_root: Path,
    godot: GodotAssetPort,
    files: AssetFilesPort,
) -> PipelineResult:
    result = PipelineResult(
        source_mode=recipe.source_mode, caller_declared_provenance=recipe.provenance
    )
    stage = "validate"
    try:
        try:
            validate_recipe(recipe)
        except ValueError as exc:
            raise PortFailure("invalid_recipe", str(exc)) from exc
        plans = files.validate(recipe, source_root, project_root)
        result.completed.append(stage)
        stage = "stage"
        with TemporaryDirectory(prefix="gda-assets-") as workspace:
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
    return result
