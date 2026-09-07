"""The ``gda asset-pipeline`` supporting-context integration (#908)."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal, Optional

import typer
from pydantic import BaseModel, ConfigDict, Field, model_validator

from gda_assets.api import AssetFile, AssetRecipe, PipelineResult, Resize, run_pipeline

from gda.dispatch import dispatch_recipe, params_or_bad_parameter
from gda.errors import Failure, invalid_project_failure, make_failure
from gda.execution import ExecutionKind
from gda.headless import (
    HeadlessCommand,
    godot_option,
    json_option,
    params_json_option,
    project_option,
)
from gda.integrations.asset_pipeline import GdaGodotAssetPort, validate_asset_targets


class AssetResizeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: int = Field(
        strict=True, ge=1, le=16384, description="Requested output width in pixels."
    )
    height: int = Field(
        strict=True, ge=1, le=16384, description="Requested output height in pixels."
    )
    resampling: Literal["nearest", "bilinear", "lanczos"] = Field(
        default="nearest", description="Resize resampling method."
    )

    @model_validator(mode="after")
    def _bounded_pixels(self) -> "AssetResizeInput":
        if self.width * self.height > 64 * 1024 * 1024:
            raise ValueError("resize output must not exceed 64 megapixels")
        return self


class AssetFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(
        description="Source file relative to source_root, or an absolute path."
    )
    target: str = Field(
        description="Explicit res:// destination in the selected project."
    )
    resize: AssetResizeInput | None = Field(
        default=None, description="Optional PNG target-dimension resize."
    )
    references: list[str] = Field(
        default_factory=list,
        description="Explicitly selected res:// target members referenced by this file.",
    )


class AssetPipelineRunParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files: list[AssetFileInput] = Field(
        min_length=1,
        max_length=32,
        description="One to 32 explicit source-to-target file mappings.",
    )
    source_root: Path | None = Field(
        default=None,
        description=(
            "Required base directory when any source is relative; may be omitted "
            "when every source is absolute."
        ),
    )
    overwrite: bool = Field(
        default=False, description="Whether existing target files may be replaced."
    )
    source_mode: Literal["existing", "imagegen"] = Field(
        default="existing",
        description="Whether files already existed or came from a completed image-generation call.",
    )
    provenance: dict[str, Any] | None = Field(
        default=None,
        description="Optional caller-declared producer metadata; never an engine observation.",
    )

    @model_validator(mode="after")
    def _relative_sources_require_a_base(self) -> "AssetPipelineRunParams":
        if self.source_root is None and any(
            not Path(item.source).is_absolute() for item in self.files
        ):
            raise ValueError("source_root is required when any source path is relative")
        return self


class InstalledAssetResult(BaseModel):
    source: str
    target: str
    state: str
    resize: AssetResizeInput | None = None


class ImportResult(BaseModel):
    facts: dict[str, Any]


class LoadResult(BaseModel):
    path: str
    resource_type: str
    texture_size: tuple[int, int] | None = None
    scene_node_count: int | None = None
    engine: dict[str, Any] | None = None


class PipelineFailureResult(BaseModel):
    stage: str
    code: str
    message: str
    cause: dict[str, Any] | None = None


class PipelineRunResult(BaseModel):
    completed: list[str]
    outputs: list[InstalledAssetResult]
    import_result: ImportResult | None = None
    observations: list[LoadResult]
    failure: PipelineFailureResult | None = None
    source_mode: Literal["existing", "imagegen"] = "existing"
    caller_declared_provenance: dict[str, Any] | None = None


class AssetPipelineRunResult(BaseModel):
    project_root: str = Field(description="Resolved Godot project root.")
    pipeline: PipelineRunResult = Field(
        description="Bounded result of this pipeline invocation."
    )


def _pipeline_result(result: PipelineResult) -> PipelineRunResult:
    return PipelineRunResult.model_validate(asdict(result))


def _failure_message(stage: str, message: str, result: PipelineRunResult) -> str:
    affected = (
        ", ".join(f"{item.target} ({item.state})" for item in result.outputs)
        or "no installed files"
    )
    return f"asset pipeline failed during {stage}: {message}; affected: {affected}"


def run_asset_pipeline(
    params: AssetPipelineRunParams,
    *,
    project: Path | None,
    godot: str | None,
) -> AssetPipelineRunResult | Failure:
    if project is None:
        empty = PipelineRunResult(
            completed=[],
            outputs=[],
            observations=[],
            failure=PipelineFailureResult(
                stage="validate",
                code="project_not_found",
                message="asset-pipeline run requires a Godot project",
            ),
            source_mode=params.source_mode,
            caller_declared_provenance=params.provenance,
        )
        failure = invalid_project_failure(
            "asset-pipeline run requires a Godot project; pass --project or run it inside one"
        )
        failure.error = failure.error.model_copy(
            update={
                "message": _failure_message("validate", failure.error.message, empty),
                "partial_result": empty.model_dump(mode="json"),
            }
        )
        return failure
    ownership_failure = validate_asset_targets(
        project, [item.target for item in params.files]
    )
    if ownership_failure is not None:
        empty = PipelineRunResult(
            completed=[],
            outputs=[],
            observations=[],
            failure=PipelineFailureResult(
                stage="validate",
                code=ownership_failure.error.code,
                message=ownership_failure.error.message,
            ),
            source_mode=params.source_mode,
            caller_declared_provenance=params.provenance,
        )
        ownership_failure.error = ownership_failure.error.model_copy(
            update={
                "message": _failure_message(
                    "validate", ownership_failure.error.message, empty
                ),
                "partial_result": empty.model_dump(mode="json"),
            }
        )
        return ownership_failure
    port = GdaGodotAssetPort(project, godot)
    files = tuple(
        AssetFile(
            source=item.source,
            target=item.target,
            resize=(Resize(**item.resize.model_dump()) if item.resize else None),
            references=tuple(item.references),
        )
        for item in params.files
    )
    recipe = AssetRecipe(
        files=files,
        overwrite=params.overwrite,
        source_mode=params.source_mode,
        provenance=params.provenance,
    )
    pipeline = run_pipeline(
        recipe,
        source_root=(params.source_root or project).resolve(),
        project_root=project,
        godot=port,
    )
    typed_result = _pipeline_result(pipeline)
    serialized = typed_result.model_dump(mode="json")
    if pipeline.failure is not None:
        if port.last_failure is not None:
            failure = port.last_failure
            failure.error = failure.error.model_copy(
                update={
                    "message": _failure_message(
                        pipeline.failure.stage, failure.error.message, typed_result
                    ),
                    "partial_result": serialized,
                }
            )
            return failure
        code = (
            "invalid_params"
            if pipeline.failure.stage in {"validate", "stage"}
            else "operation_failed"
        )
        failure = make_failure(
            code,
            _failure_message(
                pipeline.failure.stage, pipeline.failure.message, typed_result
            ),
            "",
        )
        failure.error = failure.error.model_copy(update={"partial_result": serialized})
        return failure
    return AssetPipelineRunResult(project_root=str(project), pipeline=typed_result)


def render_asset_pipeline(result: AssetPipelineRunResult) -> str:
    pipeline = result.pipeline.model_dump(mode="json")
    lines = [
        f"asset pipeline: {len(pipeline['outputs'])} file(s)",
        f"  stages: {', '.join(pipeline['completed'])}",
    ]
    for output in pipeline["outputs"]:
        lines.append(f"  {output['state']:>10}  {output['target']}")
    for observed in pipeline["observations"]:
        detail = observed.get("texture_size") or observed.get("scene_node_count")
        suffix = f" ({detail})" if detail is not None else ""
        lines.append(
            f"  loaded {observed['path']} as {observed['resource_type']}{suffix}"
        )
    return "\n".join(lines)


def _recipe(params, *, project, godot):
    return run_asset_pipeline(params, project=project, godot=godot)


ASSET_PIPELINE_RUN_COMMAND = HeadlessCommand(
    operation="asset-pipeline-run",
    input_model=AssetPipelineRunParams,
    output_model=AssetPipelineRunResult,
    render=render_asset_pipeline,
    kind=ExecutionKind.COMPOSITE,
    recipe=_recipe,
)

_app = typer.Typer(
    help="Install selected files and verify them through Godot.", no_args_is_help=True
)


@_app.command(name="run", cls=ASSET_PIPELINE_RUN_COMMAND.command_class())
def asset_pipeline_run(
    files: str = typer.Option(
        ..., "--files", help="JSON array of source-to-target file mappings."
    ),
    source_root: Optional[Path] = typer.Option(
        None,
        "--source-root",
        help=(
            "Base directory for relative source paths; required when any source "
            "is relative."
        ),
    ),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Allow replacement of existing target files."
    ),
    source_mode: str = typer.Option(
        "existing", "--source-mode", help="Source declaration: existing or imagegen."
    ),
    provenance: Optional[str] = typer.Option(
        None,
        "--provenance",
        help="JSON object containing optional caller-declared provenance.",
    ),
    json_output: bool = json_option(),
    schema: bool = ASSET_PIPELINE_RUN_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Install selected files, import them, and verify what Godot loads."""
    try:
        decoded_files = json.loads(files)
        decoded_provenance = json.loads(provenance) if provenance is not None else None
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"invalid JSON: {exc.msg}") from exc
    params = params_or_bad_parameter(
        AssetPipelineRunParams,
        files=decoded_files,
        source_root=source_root,
        overwrite=overwrite,
        source_mode=source_mode,
        provenance=decoded_provenance,
    )
    dispatch_recipe(
        ASSET_PIPELINE_RUN_COMMAND,
        params,
        json_output=json_output,
        godot=godot,
        project=project,
    )


def register(root: typer.Typer) -> None:
    root.add_typer(_app, name="asset-pipeline")
