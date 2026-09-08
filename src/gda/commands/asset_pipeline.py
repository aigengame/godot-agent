"""The ``gda asset-pipeline`` supporting-context integration (#908)."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal, Optional

import typer
from pydantic import BaseModel, ConfigDict, Field, model_validator

from gda_assets.api import (
    AssetFile,
    AssetRecipe,
    PipelineResult,
    ModelComparison,
    Resize,
    run_pipeline,
    ProductionRequest,
    ProductionOutput,
)

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


class ProductionOutputInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(description="Producer output role, currently model.")
    target: str = Field(description="Explicit res:// destination for this output.")


class ProductionInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "kind": "blender_saved",
                    "outputs": [{"role": "model", "target": "res://art/model.glb"}],
                    "options": {
                        "source": "/production/model.blend",
                        "scene": "AssetScene",
                        "root": "AssetRoot",
                        "uniform_scale": 2,
                    },
                }
            ],
        },
    )
    kind: str = Field(description="Producer kind; currently blender_saved.")
    outputs: list[ProductionOutputInput] = Field(
        min_length=1,
        max_length=32,
        description="Explicit output roles and destinations.",
    )
    options: dict[str, Any] = Field(
        description="Producer-owned configuration, validated by the selected adapter."
    )


class AssetPipelineRunParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files: list[AssetFileInput] = Field(
        default_factory=list,
        max_length=32,
        description="One to 32 explicit file mappings, or omit when using production.",
    )
    production: ProductionInput | None = Field(
        default=None,
        description="Produce files before the shared handoff; mutually exclusive with files.",
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
        if bool(self.files) == (self.production is not None):
            raise ValueError("Select exactly one of files or production")
        if self.production is not None and self.source_mode != "existing":
            raise ValueError("Production determines its observed source mode")
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
    source_mode: str = "existing"
    production: dict[str, Any] | None = None
    cleanup: dict[str, bool] | None = None
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
        project,
        [
            item.target
            for item in (
                params.production.outputs if params.production else params.files
            )
        ],
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
        source_root=(
            params.source_root.resolve()
            if params.source_root is not None
            else None
            if params.production
            else project.resolve()
        ),
        project_root=project,
        godot=port,
        production=(
            ProductionRequest(
                params.production.kind,
                tuple(
                    ProductionOutput(item.role, item.target)
                    for item in params.production.outputs
                ),
                params.production.options,
            )
            if params.production
            else None
        ),
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
        code = {
            "invalid_production": "invalid_params",
            "unsupported_producer": "invalid_params",
            "producer_unavailable": "binary_not_found",
            "producer_timeout": "launch_timeout",
        }.get(
            pipeline.failure.code,
            "invalid_params"
            if pipeline.failure.stage in {"validate", "stage"}
            else "operation_failed",
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
    help="Produce or install selected assets and verify them through Godot.",
    no_args_is_help=True,
)


@_app.command(name="run", cls=ASSET_PIPELINE_RUN_COMMAND.command_class())
def asset_pipeline_run(
    files: str = typer.Option(
        "[]",
        "--files",
        help="JSON array of source-to-target file mappings; omit for production.",
    ),
    production: Optional[str] = typer.Option(
        None,
        "--production",
        help="JSON producer request with kind, outputs and producer-owned options.",
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
    """Export saved Blender sources or install files, then verify what Godot loads."""
    try:
        decoded_files = json.loads(files)
        decoded_production = json.loads(production) if production is not None else None
        decoded_provenance = json.loads(provenance) if provenance is not None else None
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"invalid JSON: {exc.msg}") from exc
    params = params_or_bad_parameter(
        AssetPipelineRunParams,
        files=decoded_files,
        production=decoded_production,
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


class AssetPipelineCheckParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expectations: Path = Field(
        description="Project-owned expectation JSON file; relative paths use the caller's working directory."
    )
    path: str | None = Field(
        default=None,
        min_length=1,
        description="Model resource to inspect now; select exactly one of path or report.",
    )
    report: Path | None = Field(
        default=None,
        description="Saved resource inspect-model JSON; evaluated without an engine call.",
    )
    baseline: Path | None = Field(
        default=None,
        description="Optional saved inspection report to compare with current facts.",
    )
    subtree: str = Field(
        default=".",
        description="Resource-relative inspection subtree; saved reports carry their own scope.",
    )
    max_nodes: int = Field(
        default=256, ge=1, le=4096, description="Live inspection node limit."
    )
    max_items: int = Field(
        default=1024, ge=1, le=16384, description="Live inspection detail limit."
    )

    @model_validator(mode="after")
    def _one_source(self) -> "AssetPipelineCheckParams":
        if (self.path is not None) == (self.report is not None):
            raise ValueError("Select exactly one of path or report")
        if self.report is not None and (
            self.subtree != "." or self.max_nodes != 256 or self.max_items != 1024
        ):
            raise ValueError(
                "subtree and inspection limits apply only to live path inspection"
            )
        return self


class AssetConditionResult(BaseModel):
    id: str
    verdict: Literal["pass", "fail", "insufficient"]
    location: dict[str, Any]
    expected: Any
    actual: Any
    reason: str


class AssetPipelineCheckResult(BaseModel):
    completed: list[str]
    resource: str | None
    observation_source: Literal["godot", "supplied_report"] | None
    verdict: Literal["pass", "fail", "insufficient"] | None = Field(
        description="Content verdict. Every completed evaluation exits 0; invalid input or workflow failure exits nonzero."
    )
    checks: list[AssetConditionResult]
    comparison: ModelComparison | None
    failure: PipelineFailureResult | None


def run_asset_check(
    params: AssetPipelineCheckParams, *, project: Path | None, godot: str | None
) -> AssetPipelineCheckResult | Failure:
    from gda_assets.api import (
        check_model,
        ModelCheckResult,
        PipelineFailure,
        PortFailure,
    )
    from gda.integrations.model_reports import read_model_report

    port = GdaGodotAssetPort(project, godot) if project is not None else None
    native_failure = None
    try:
        if params.path is not None and port is None:
            native_failure = invalid_project_failure(
                "asset-pipeline check --path requires a Godot project; pass --project"
            )
            raise PortFailure(native_failure.error.code, native_failure.error.message)
        report = read_model_report(params.report) if params.report else None
        baseline = read_model_report(params.baseline) if params.baseline else None
        result = check_model(
            params.expectations,
            path=params.path,
            godot=port,
            report=report,
            subtree=params.subtree,
            max_nodes=params.max_nodes,
            max_items=params.max_items,
            baseline=baseline,
        )
    except PortFailure as exc:
        result = ModelCheckResult(
            failure=PipelineFailure("validate", exc.code, str(exc), exc.cause)
        )
    typed = AssetPipelineCheckResult.model_validate(asdict(result))
    if result.failure is None:
        return typed
    failure = native_failure or (port.last_failure if port else None)
    message = (
        f"asset pipeline failed during {result.failure.stage}: {result.failure.message}"
    )
    if failure is None:
        failure = make_failure(
            "invalid_params"
            if result.failure.code
            in {"invalid_expectations", "invalid_report", "invalid_check"}
            else "operation_failed",
            message,
            "",
        )
    failure.error = failure.error.model_copy(
        update={"message": message, "partial_result": typed.model_dump(mode="json")}
    )
    return failure


def render_asset_check(result: AssetPipelineCheckResult) -> str:
    lines = [f"asset check: {result.verdict} ({result.resource})"]
    lines.extend(
        f"  {item.verdict:>12}  {item.id}: {item.reason}" for item in result.checks
    )
    if result.comparison:
        lines.append(f"  comparison: {result.comparison.status}")
    return "\n".join(lines)


ASSET_PIPELINE_CHECK_COMMAND = HeadlessCommand(
    operation="asset-pipeline-check",
    input_model=AssetPipelineCheckParams,
    output_model=AssetPipelineCheckResult,
    render=render_asset_check,
    kind=ExecutionKind.COMPOSITE,
    recipe=run_asset_check,
)


@_app.command(name="check", cls=ASSET_PIPELINE_CHECK_COMMAND.command_class())
def asset_pipeline_check(
    expectations: Path = typer.Option(
        ..., "--expectations", help="Project-owned expectation JSON file."
    ),
    path: Optional[str] = typer.Option(
        None, "--path", help="Model resource to inspect through Godot."
    ),
    report: Optional[Path] = typer.Option(
        None, "--report", help="Saved resource inspect-model JSON; no engine call."
    ),
    baseline: Optional[Path] = typer.Option(
        None, "--baseline", help="Saved inspection report for compatible comparison."
    ),
    subtree: str = typer.Option(
        ".", "--subtree", help="Full resource-relative subtree for live inspection."
    ),
    max_nodes: int = typer.Option(
        256, "--max-nodes", min=1, max=4096, help="Live inspection node limit."
    ),
    max_items: int = typer.Option(
        1024, "--max-items", min=1, max=16384, help="Live inspection detail limit."
    ),
    json_output: bool = json_option(),
    schema: bool = ASSET_PIPELINE_CHECK_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Evaluate project intent and compare model facts. Read verdict; pass/fail/insufficient exit 0."""
    params = params_or_bad_parameter(
        AssetPipelineCheckParams,
        expectations=expectations,
        path=path,
        report=report,
        baseline=baseline,
        subtree=subtree,
        max_nodes=max_nodes,
        max_items=max_items,
    )
    dispatch_recipe(
        ASSET_PIPELINE_CHECK_COMMAND,
        params,
        json_output=json_output,
        godot=godot,
        project=project,
    )
