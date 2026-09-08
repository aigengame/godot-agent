"""The ``gda asset-pipeline`` supporting-context integration (#908)."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any, Literal, Optional, get_args

import typer
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from gda_assets.api import (
    AssetFile,
    AssetRecipe,
    PipelineResult,
    ModelComparison,
    Resize,
    run_pipeline,
    ProductionRequest,
    ProductionOutput,
    CollectionRequest,
    ContentObservations,
    RefreshRequest,
    RefreshResult,
    PreviewCamera,
    PreviewRequest,
    PreviewResult,
    PreviewSettings,
    preview_asset,
    PackageCheckRequest,
    PackageCheckResult,
    check_package,
    JsonScalar,
    PromptOutputRequest,
    PromptPreparation,
    PromptPrepareRequest,
    PromptRecord,
    PromptRevision,
    PromptRevisionRequest,
    prepare_prompt,
    inspect_prompt,
    register_prompt_output,
    revise_prompt,
    PortFailure,
    PromptDeclarationKey,
    PromptOptionKey,
    ConceptAuthoringResult,
    ConceptAuthorRequest,
    ConceptCandidate,
    ConceptConsumer,
    ConceptPreparation,
    ConceptPrepareRequest,
    ConceptSelection,
    ConceptSelectRequest,
    SpriteSheetLayout,
    author_concept,
    prepare_concept,
    select_concept,
)

from gda.dispatch import dispatch_recipe, params_or_bad_parameter
from gda.errors import (
    Failure,
    invalid_project_failure,
    make_failure,
    validation_error_message,
)
from gda.execution import ExecutionKind
from gda.headless import (
    HeadlessCommand,
    godot_option,
    json_option,
    params_json_option,
    project_option,
)
from gda.integrations.asset_pipeline import GdaGodotAssetPort, validate_asset_targets
from gda.integrations.preview import GdaPreviewHost
from gda.integrations.package import GdaGodotPackagePort


class _AssetCommandModel(BaseModel):
    # Core commands mount this group too. Build its validators and serializers
    # only when an asset command or schema request first uses the model.
    model_config = ConfigDict(defer_build=True)


StrictCoordinate = Annotated[float, Field(strict=True)]


class AssetResizeInput(_AssetCommandModel):
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


class AssetFileInput(_AssetCommandModel):
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


class ProductionOutputInput(_AssetCommandModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(description="Producer output role, currently model.")
    target: str = Field(description="Explicit res:// destination for this output.")


class ProductionInput(_AssetCommandModel):
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


class AssetRefreshInput(_AssetCommandModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(
        description="Selected GLB output whose imported root is compared with the runtime instance."
    )
    scene: str = Field(
        description="Explicit res:// test scene to relaunch; runtime state is lost."
    )
    node: str = Field(
        description="Absolute /root/... path of that model instance in the new session."
    )
    windowed: bool = Field(
        default=False,
        strict=True,
        description="Launch a rendered window; required for capture_output.",
    )
    timeout: float = Field(
        default=25.0,
        gt=0,
        le=50,
        allow_inf_nan=False,
        description="Existing daemon readiness timeout in seconds.",
    )
    max_nodes: int = Field(
        default=256,
        strict=True,
        ge=1,
        le=1024,
        description="Maximum nodes in the content sample.",
    )
    max_vertices: int = Field(
        default=200000,
        strict=True,
        ge=1,
        le=1000000,
        description="Maximum vertices in the content sample.",
    )
    capture_output: Path | None = Field(
        default=None,
        description="Optional PNG filesystem output for a subsequent capture in the same session.",
    )


class AssetPipelineRunParams(_AssetCommandModel):
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
    collect_observations: bool = Field(
        default=False,
        description="Collect bounded selected disk/import observations; no runtime or full reproducibility claim.",
    )
    observations_output: Path | None = Field(
        default=None,
        description="Optional new JSON output file for collected observations; never overwritten. Requires collect_observations.",
    )
    declared_output_sha256: dict[str, str] = Field(
        default_factory=dict,
        description="Optional caller-declared SHA-256 per installed res:// output; checked only with collect_observations.",
    )
    refresh: AssetRefreshInput | None = Field(
        default=None,
        description="After successful import/load, reset an explicit scene and compare its selected model instance. Independent of collect_observations.",
    )

    @model_validator(mode="after")
    def _relative_sources_require_a_base(self) -> "AssetPipelineRunParams":
        if not self.collect_observations and (
            self.observations_output is not None or self.declared_output_sha256
        ):
            raise ValueError(
                "observations_output and declared_output_sha256 require collect_observations"
            )
        if bool(self.files) == (self.production is not None):
            raise ValueError("Select exactly one of files or production")
        if self.production is not None and self.source_mode != "existing":
            raise ValueError("Production determines its observed source mode")
        if self.source_root is None and any(
            not Path(item.source).is_absolute() for item in self.files
        ):
            raise ValueError("source_root is required when any source path is relative")
        return self


class InstalledAssetResult(_AssetCommandModel):
    source: str
    target: str
    state: str
    resize: AssetResizeInput | None = None


class ImportResult(_AssetCommandModel):
    facts: dict[str, Any]


class LoadResult(_AssetCommandModel):
    path: str
    resource_type: str
    texture_size: tuple[int, int] | None = None
    scene_node_count: int | None = None
    engine: dict[str, Any] | None = None


class PipelineFailureResult(_AssetCommandModel):
    stage: str
    code: str
    message: str
    cause: dict[str, Any] | None = None


class PipelineRunResult(_AssetCommandModel):
    completed: list[str]
    outputs: list[InstalledAssetResult]
    import_result: ImportResult | None = None
    observations: list[LoadResult]
    failure: PipelineFailureResult | None = None
    source_mode: str = "existing"
    production: dict[str, Any] | None = None
    cleanup: dict[str, bool] | None = None
    caller_declared_provenance: dict[str, Any] | None = None
    content_observations: ContentObservations | None = None
    refresh: RefreshResult | None = None


class AssetPipelineRunResult(_AssetCommandModel):
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
        collection=CollectionRequest(
            params.observations_output, params.declared_output_sha256
        )
        if params.collect_observations
        else None,
        import_observer=port if params.collect_observations else None,
        refresh=RefreshRequest(**params.refresh.model_dump())
        if params.refresh
        else None,
        runtime=port if params.refresh else None,
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
    if pipeline["content_observations"] is not None:
        content = pipeline["content_observations"]
        lines.append(
            f"  disk/import observations: {content['status']} (selected file bytes only)"
        )
        if content["saved_to"]:
            lines.append(f"  saved observations: {content['saved_to']}")
    if pipeline["refresh"] is not None:
        refresh = pipeline["refresh"]
        lines.append(
            f"  runtime content: {refresh['status']}; runtime state is not preserved"
        )
        if refresh["instance"] is not None:
            observed = refresh["instance"]
            lines.append(
                f"  observed {observed['node']} in session {observed['session_id']} at frame {observed['engine_frame']}"
            )
        if refresh["capture"] is not None:
            lines.append(f"  subsequent capture: {refresh['capture']['path']}")
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
    collect_observations: bool = typer.Option(
        False,
        "--collect-observations",
        help="Collect selected disk/import hashes and coverage; no runtime proof.",
    ),
    observations_output: Optional[Path] = typer.Option(
        None,
        "--observations-output",
        help="Save collected observations to a new JSON file; never overwrite.",
    ),
    declared_output_sha256: str = typer.Option(
        "{}",
        "--declared-output-sha256",
        help="JSON res:// output-to-SHA-256 declarations; requires collection.",
    ),
    refresh: Optional[str] = typer.Option(
        None,
        "--refresh",
        help="JSON request to reset an explicit scene and compare a selected model instance after import. Runtime state is lost.",
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
        decoded_hashes = json.loads(declared_output_sha256)
        decoded_refresh = json.loads(refresh) if refresh is not None else None
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
        collect_observations=collect_observations,
        observations_output=observations_output,
        declared_output_sha256=decoded_hashes,
        refresh=decoded_refresh,
    )
    dispatch_recipe(
        ASSET_PIPELINE_RUN_COMMAND,
        params,
        json_output=json_output,
        godot=godot,
        project=project,
    )


class PreviewCameraInput(_AssetCommandModel):
    model_config = ConfigDict(extra="forbid")
    name: Literal["front", "side", "three_quarter"]
    position: tuple[StrictCoordinate, StrictCoordinate, StrictCoordinate]
    target: tuple[StrictCoordinate, StrictCoordinate, StrictCoordinate]
    size: StrictCoordinate
    near: StrictCoordinate
    far: StrictCoordinate
    up: tuple[StrictCoordinate, StrictCoordinate, StrictCoordinate] = (0.0, 1.0, 0.0)


class PreviewSettingsInput(_AssetCommandModel):
    model_config = ConfigDict(extra="forbid")
    width: int = Field(default=640, strict=True, ge=64, le=2048)
    height: int = Field(default=360, strict=True, ge=64, le=2048)
    padding: float = Field(default=1.15, strict=True, gt=1, le=3, allow_inf_nan=False)
    cameras: tuple[PreviewCameraInput, ...] = ()


class AssetPipelinePreviewParams(_AssetCommandModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(
        min_length=1, description="Local GLB path or project-owned res:// GLB resource."
    )
    output_dir: Path = Field(
        description="Exclusive filesystem directory for retained preview captures."
    )
    settings: Path | None = Field(
        default=None, description="Optional preview settings JSON file (at most 1 MiB)."
    )
    frames: int = Field(
        default=60,
        strict=True,
        ge=1,
        le=120,
        description="Performance sample frames at the final view, without stabilization.",
    )
    timeout: float = Field(
        default=25.0,
        strict=True,
        gt=0,
        le=50,
        allow_inf_nan=False,
        description="Maximum seconds to wait for the owned runtime session to become ready.",
    )
    max_nodes: int = Field(
        default=256,
        strict=True,
        ge=1,
        le=4096,
        description="Maximum imported nodes to inspect; incomplete bounds need camera overrides.",
    )
    budget: Path | None = Field(
        default=None,
        description="Optional local JSON budget for the sampled scene-level performance monitors.",
    )
    baseline: Path | None = Field(
        default=None,
        description="Optional local preview JSON result (at most 4 MiB) for setup-compatible comparison.",
    )


class AssetPipelinePreviewResult(_AssetCommandModel):
    preview: PreviewResult = Field(description="Bounded isolated preview result.")


def _preview_result(result: PreviewResult) -> AssetPipelinePreviewResult:
    return AssetPipelinePreviewResult.model_validate({"preview": asdict(result)})


def run_asset_preview(
    params: AssetPipelinePreviewParams,
    *,
    project: Path | None,
    godot: str | None,
) -> AssetPipelinePreviewResult | Failure:
    settings = PreviewSettingsInput()
    if params.settings is not None:
        try:
            if not params.settings.is_file():
                return make_failure(
                    "invalid_params", "settings must be a regular JSON file", ""
                )
            with params.settings.open("rb") as stream:
                raw_settings = stream.read(1024 * 1024 + 1)
            if len(raw_settings) > 1024 * 1024:
                return make_failure(
                    "invalid_params", "settings JSON must not exceed 1 MiB", ""
                )
            settings = PreviewSettingsInput.model_validate_json(
                raw_settings.decode("utf-8")
            )
        except ValidationError as exc:
            return make_failure(
                "invalid_params",
                f"invalid preview settings: {validation_error_message(exc)}",
                "",
            )
        except (OSError, UnicodeError, ValueError) as exc:
            return make_failure("invalid_params", f"invalid settings JSON: {exc}", "")
    source = Path(params.path)
    if params.path.startswith("res://"):
        if project is None:
            return invalid_project_failure(
                "asset-pipeline preview with a res:// path requires a Godot project; pass --project"
            )
        refusal = validate_asset_targets(project, [params.path])
        if refusal is not None:
            return refusal
        source = (project / params.path.removeprefix("res://")).resolve()
    else:
        source = source.resolve()
    host = GdaPreviewHost(godot)
    request = PreviewRequest(
        source=source,
        output_dir=params.output_dir.resolve(),
        settings=PreviewSettings(
            width=settings.width,
            height=settings.height,
            padding=settings.padding,
            cameras=tuple(
                PreviewCamera(
                    camera.name,
                    camera.position,
                    camera.target,
                    camera.size,
                    camera.near,
                    camera.far,
                    camera.up,
                )
                for camera in settings.cameras
            ),
        ),
        frames=params.frames,
        timeout=params.timeout,
        max_nodes=params.max_nodes,
        budget=params.budget.resolve() if params.budget is not None else None,
        baseline=params.baseline.resolve() if params.baseline is not None else None,
    )
    result = preview_asset(request, host=host)
    typed = _preview_result(result)
    if result.failure is None:
        return typed
    native = host.last_failure
    cause = result.failure.cause or {}
    native_matches = native is not None and (
        cause.get("code") == native.error.code
        or (
            result.failure.code == native.error.code
            and result.failure.message == native.error.message
        )
    )
    failure = (
        native
        if native_matches
        else make_failure(
            "invalid_params"
            if result.failure.stage == "validate"
            else "operation_failed",
            result.failure.message,
            "",
        )
    )
    assert failure is not None
    failure.error = failure.error.model_copy(
        update={
            "message": f"asset preview failed during {result.failure.stage}: {result.failure.message}",
            "partial_result": typed.model_dump(mode="json"),
        }
    )
    return failure


def render_asset_preview(result: AssetPipelinePreviewResult) -> str:
    preview = result.preview
    lines = [f"asset preview: {len(preview.views)} view(s)"]
    if preview.inspection is not None:
        lines.append(
            f"  inspected {preview.inspection.resource}: {len(preview.inspection.nodes)} node(s)"
        )
    for view in preview.views:
        name = (
            view.state.camera.name
            if view.state is not None
            else f"view_{view.capture.applied_view}"
        )
        lines.append(
            f"  {name}: {view.capture.receipt.path} "
            f"({view.capture.width}x{view.capture.height})"
        )
    if preview.performance is not None:
        lines.append(f"  performance: passed={preview.performance.passed}")
    if preview.comparison is not None:
        lines.append(f"  comparison: {preview.comparison.status}")
        lines.extend(f"    {reason}" for reason in preview.comparison.reasons)
        lines.extend(
            f"    {name}: mean delta={change.mean_delta:g}, p95 delta={change.p95_delta:g}"
            for name, change in preview.comparison.changes.items()
        )
    if preview.diagnostics is not None:
        lines.append(
            f"  diagnostics: {len(preview.diagnostics.errors)} entry(s), "
            f"truncated={preview.diagnostics.truncated}"
        )
    return "\n".join(lines)


ASSET_PIPELINE_PREVIEW_COMMAND = HeadlessCommand(
    operation="asset-pipeline-preview",
    input_model=AssetPipelinePreviewParams,
    output_model=AssetPipelinePreviewResult,
    render=render_asset_preview,
    kind=ExecutionKind.COMPOSITE,
    recipe=run_asset_preview,
)


@_app.command(name="preview", cls=ASSET_PIPELINE_PREVIEW_COMMAND.command_class())
def asset_pipeline_preview(
    path: str = typer.Option(
        ..., "--path", help="Local GLB path or project-owned res:// resource."
    ),
    output_dir: Path = typer.Option(
        ..., "--output-dir", help="Exclusive directory for retained captures."
    ),
    settings: Optional[Path] = typer.Option(
        None, "--settings", help="Optional preview settings JSON file (at most 1 MiB)."
    ),
    frames: int = typer.Option(60, "--frames", min=1, max=120),
    timeout: float = typer.Option(
        25.0, "--timeout", help="Positive readiness timeout in seconds, at most 50."
    ),
    max_nodes: int = typer.Option(256, "--max-nodes", min=1, max=4096),
    budget: Optional[Path] = typer.Option(
        None, "--budget", help="Optional performance budget JSON."
    ),
    baseline: Optional[Path] = typer.Option(
        None, "--baseline", help="Optional saved preview result JSON."
    ),
    json_output: bool = json_option(),
    schema: bool = ASSET_PIPELINE_PREVIEW_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Render and measure an isolated three-view GLB preview."""
    dispatch_recipe(
        ASSET_PIPELINE_PREVIEW_COMMAND,
        params_or_bad_parameter(
            AssetPipelinePreviewParams,
            path=path,
            output_dir=output_dir,
            settings=settings,
            frames=frames,
            timeout=timeout,
            max_nodes=max_nodes,
            budget=budget,
            baseline=baseline,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
    )


def register(root: typer.Typer) -> None:
    root.add_typer(_app, name="asset-pipeline")


class AssetPipelineCheckParams(_AssetCommandModel):
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


class AssetConditionResult(_AssetCommandModel):
    id: str
    verdict: Literal["pass", "fail", "insufficient"]
    location: dict[str, Any]
    expected: Any
    actual: Any
    reason: str


class AssetPipelineCheckResult(_AssetCommandModel):
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


class AssetPipelinePackageCheckParams(_AssetCommandModel):
    model_config = ConfigDict(extra="forbid")
    package: Path = Field(description="Local .pck file to inspect in isolation.")
    path: str = Field(description="Exact res:// model resource inside the package.")
    expectations: Path = Field(description="Local model expectation JSON file.")
    exclude: list[str] = Field(
        default_factory=list,
        max_length=64,
        description="Up to 64 exact res:// paths required to be absent.",
    )
    subtree: str = Field(default=".", description="Resource-relative model subtree.")
    max_nodes: int = Field(
        default=256,
        strict=True,
        ge=1,
        le=4096,
        description="Maximum nodes in the selected package model subtree.",
    )
    max_items: int = Field(
        default=1024,
        strict=True,
        ge=1,
        le=16384,
        description="Maximum detail records across the package model report.",
    )


class AssetPipelinePackageCheckResult(_AssetCommandModel):
    package_check: PackageCheckResult = Field(
        description="Editor-based inspection and project-intent verdict for one PCK."
    )


def run_asset_package_check(
    params: AssetPipelinePackageCheckParams,
    *,
    project: Path | None,
    godot: str | None,
) -> AssetPipelinePackageCheckResult | Failure:
    del project
    port = GdaGodotPackagePort(godot)
    result = check_package(
        PackageCheckRequest(
            package=params.package.resolve(),
            path=params.path,
            expectations=params.expectations.resolve(),
            exclude=tuple(params.exclude),
            subtree=params.subtree,
            max_nodes=params.max_nodes,
            max_items=params.max_items,
        ),
        godot=port,
    )
    typed = AssetPipelinePackageCheckResult.model_validate(
        {"package_check": asdict(result)}
    )
    if result.failure is None:
        return typed
    native = port.last_failure
    cause = result.failure.cause or {}
    native_matches = native is not None and (
        cause.get("code") == native.error.code
        or (
            result.failure.code == native.error.code
            and result.failure.message == native.error.message
        )
    )
    failure = (
        native
        if native_matches
        else make_failure(
            "invalid_params"
            if result.failure.stage == "validate"
            else "operation_failed",
            result.failure.message,
            "",
        )
    )
    assert failure is not None
    failure.error = failure.error.model_copy(
        update={
            "message": f"package check failed during {result.failure.stage}: {result.failure.message}",
            "partial_result": typed.model_dump(mode="json"),
        }
    )
    return failure


def render_asset_package_check(result: AssetPipelinePackageCheckResult) -> str:
    checked = result.package_check
    lines = [
        f"package check: {checked.verdict} (editor inspection)",
        f"  origin: {checked.origin}",
    ]
    if checked.package is not None:
        lines.append(
            f"  package: sha256={checked.package.sha256} size={checked.package.size_bytes}"
        )
    if checked.presence is not None:
        lines.append(
            f"  engine: {checked.presence.engine.version} ({checked.presence.engine.build_hash})"
        )
    if checked.inspection is not None:
        lines.append(f"  inspected: {checked.inspection.model.resource}")
    else:
        lines.append(f"  selected: {checked.request.path}")
    if checked.check is not None:
        model_check = AssetPipelineCheckResult.model_validate(asdict(checked.check))
        lines.extend(
            "  " + line for line in render_asset_check(model_check).splitlines()
        )
    lines.extend(
        f"  exclusion {item.verdict}: {item.path} present={item.present}"
        for item in checked.exclusions
    )
    lines.append(f"  cleanup: staging_removed={checked.cleanup.staging_removed}")
    return "\n".join(lines)


ASSET_PIPELINE_PACKAGE_CHECK_COMMAND = HeadlessCommand(
    operation="asset-pipeline-check-package",
    input_model=AssetPipelinePackageCheckParams,
    output_model=AssetPipelinePackageCheckResult,
    render=render_asset_package_check,
    kind=ExecutionKind.COMPOSITE,
    inherits_project=False,
    recipe=run_asset_package_check,
)


@_app.command(
    name="check-package", cls=ASSET_PIPELINE_PACKAGE_CHECK_COMMAND.command_class()
)
def asset_pipeline_check_package(
    package: Path = typer.Option(..., "--package", help="Local .pck file."),
    path: str = typer.Option(..., "--path", help="Exact res:// model resource."),
    expectations: Path = typer.Option(
        ..., "--expectations", help="Local model expectation JSON."
    ),
    exclude: Optional[list[str]] = typer.Option(
        None,
        "--exclude",
        help="Exact res:// path required absent; repeat up to 64 times.",
    ),
    subtree: str = typer.Option(".", "--subtree"),
    max_nodes: int = typer.Option(256, "--max-nodes", min=1, max=4096),
    max_items: int = typer.Option(1024, "--max-items", min=1, max=16384),
    json_output: bool = json_option(),
    schema: bool = ASSET_PIPELINE_PACKAGE_CHECK_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
) -> None:
    """Inspect a PCK with a Godot editor binary. Read verdict; completed checks exit 0."""
    dispatch_recipe(
        ASSET_PIPELINE_PACKAGE_CHECK_COMMAND,
        params_or_bad_parameter(
            AssetPipelinePackageCheckParams,
            package=package,
            path=path,
            expectations=expectations,
            exclude=exclude or [],
            subtree=subtree,
            max_nodes=max_nodes,
            max_items=max_items,
        ),
        json_output=json_output,
        godot=godot,
        project=None,
    )


REQUESTED_OPTION_HELP = f"Supported keys: {', '.join(get_args(PromptOptionKey))}."
DECLARATION_HELP = f"Supported keys: {', '.join(get_args(PromptDeclarationKey))}."
PromptVariableKey = Annotated[str, Field(max_length=128)]
PromptVariableValue = Annotated[str, Field(max_length=4096)]


class PromptPrepareParams(_AssetCommandModel):
    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        json_schema_extra={
            "oneOf": [
                {
                    "required": ["text"],
                    "properties": {
                        "text": {"type": "string"},
                        "template": {"type": "null"},
                    },
                },
                {
                    "required": ["template"],
                    "properties": {
                        "template": {"type": "string"},
                        "text": {"type": "null"},
                    },
                },
            ]
        },
    )
    record: Path = Field(description="New caller-visible prompt record directory.")
    text: str | None = Field(
        default=None,
        description="Literal prompt text; select exactly one source. Resolved UTF-8 text is limited to 1 MiB.",
    )
    template: Path | None = Field(
        default=None,
        description="Template text file using $name or ${name}; select exactly one source.",
    )
    style: Path | None = Field(
        default=None, description="Optional style text prepended before one blank line."
    )
    variables: dict[PromptVariableKey, PromptVariableValue] = Field(
        default_factory=dict,
        max_length=64,
        description="At most 64 exact placeholders; keys at most 128 and values at most 4096 characters.",
    )
    references: tuple[Path, ...] = Field(
        default=(),
        max_length=16,
        description="Up to 16 local reference files copied into the record.",
    )
    producer: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        description="Optional caller-selected external producer name.",
    )
    requested_options: dict[PromptOptionKey, JsonScalar] = Field(
        default_factory=dict, description=REQUESTED_OPTION_HELP
    )

    @model_validator(mode="after")
    def _one_prompt_source(self) -> "PromptPrepareParams":
        if (self.text is None) == (self.template is None):
            raise ValueError("Select exactly one of text or template")
        return self


class PromptInspectParams(_AssetCommandModel):
    model_config = ConfigDict(extra="forbid")
    record: Path = Field(description="Existing prompt record directory.")


class PromptReviseParams(_AssetCommandModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    source_record: Path = Field(
        description="Existing record whose saved snapshots are reused."
    )
    record: Path = Field(description="New caller-visible revision record directory.")
    text: str | None = Field(
        default=None, description="Optional replacement literal prompt text."
    )
    template: Path | None = Field(
        default=None, description="Optional replacement template file."
    )
    style: Path | None = Field(
        default=None, description="Optional replacement style file."
    )
    remove_style: bool = Field(
        default=False,
        strict=True,
        description="Explicitly remove the saved style snapshot.",
    )
    variables: dict[PromptVariableKey, PromptVariableValue] | None = Field(
        default=None,
        max_length=64,
        description="Optional replacement of at most 64 bounded template variables.",
    )
    references: tuple[Path, ...] | None = Field(
        default=None,
        max_length=16,
        description="Optional replacement set of up to 16 references.",
    )
    producer: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        description="Optional replacement producer declaration.",
    )
    requested_options: dict[PromptOptionKey, JsonScalar] | None = Field(
        default=None, description=REQUESTED_OPTION_HELP
    )


class PromptRegisterOutputParams(_AssetCommandModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    record: Path = Field(description="Existing prompt record directory.")
    output: Path = Field(description="Existing completed local PNG file.")
    name: str = Field(
        min_length=1,
        max_length=255,
        description="Caller-chosen safe PNG filename for this record.",
    )
    submitted_prompt: str | None = Field(
        default=None, description="Actual submitted prompt when explicitly known."
    )
    caller_declarations: dict[PromptDeclarationKey, JsonScalar] = Field(
        default_factory=dict,
        description=DECLARATION_HELP,
        json_schema_extra={
            "properties": {
                "generation_completed": {
                    "anyOf": [{"type": "boolean"}, {"type": "null"}]
                }
            }
        },
    )
    reported_provider: str | None = Field(
        default=None,
        description="Provider identity reported after generation, if available.",
    )
    reported_model: str | None = Field(
        default=None,
        description="Model identity reported after generation, if available.",
    )
    reported_options: dict[PromptOptionKey, JsonScalar] = Field(
        default_factory=dict, description=REQUESTED_OPTION_HELP
    )


class PromptPreparationResult(_AssetCommandModel):
    preparation: PromptPreparation


class PromptRevisionResult(_AssetCommandModel):
    revision: PromptRevision


class PromptRecordResult(_AssetCommandModel):
    prompt_record: PromptRecord


def _prompt_failure(exc: PortFailure) -> Failure:
    code = {
        "destination_conflict": "already_exists",
        "prompt_stage_failed": "operation_failed",
    }.get(exc.code, "invalid_params")
    return make_failure(code, str(exc), "")


def run_prompt_prepare(
    params: PromptPrepareParams, *, project: Path | None, godot: str | None
) -> PromptPreparationResult | Failure:
    del project, godot
    try:
        prepared = prepare_prompt(
            PromptPrepareRequest(
                params.record.resolve(),
                params.text,
                params.template.resolve() if params.template else None,
                params.style.resolve() if params.style else None,
                params.variables,
                tuple(path.resolve() for path in params.references),
                params.producer,
                params.requested_options,
            )
        )
        return PromptPreparationResult(preparation=prepared)
    except PortFailure as exc:
        return _prompt_failure(exc)


def run_prompt_inspect(
    params: PromptInspectParams, *, project: Path | None, godot: str | None
) -> PromptPreparationResult | Failure:
    del project, godot
    try:
        return PromptPreparationResult(
            preparation=inspect_prompt(params.record.resolve())
        )
    except PortFailure as exc:
        return _prompt_failure(exc)


def run_prompt_revise(
    params: PromptReviseParams, *, project: Path | None, godot: str | None
) -> PromptRevisionResult | Failure:
    del project, godot
    try:
        revised = revise_prompt(
            PromptRevisionRequest(
                source_record=params.source_record.resolve(),
                record=params.record.resolve(),
                text=params.text,
                template=params.template.resolve() if params.template else None,
                style=params.style.resolve() if params.style else None,
                remove_style=params.remove_style,
                variables=params.variables,
                references=tuple(path.resolve() for path in params.references)
                if params.references is not None
                else None,
                producer=params.producer,
                requested_options=(
                    params.requested_options
                    if params.requested_options is not None
                    else None
                ),
            )
        )
        return PromptRevisionResult(revision=revised)
    except PortFailure as exc:
        return _prompt_failure(exc)


def run_prompt_register_output(
    params: PromptRegisterOutputParams, *, project: Path | None, godot: str | None
) -> PromptRecordResult | Failure:
    del project, godot
    try:
        record = register_prompt_output(
            PromptOutputRequest(
                params.record.resolve(),
                params.output.resolve(),
                params.name,
                params.submitted_prompt,
                params.caller_declarations,
                params.reported_provider,
                params.reported_model,
                params.reported_options,
            )
        )
        return PromptRecordResult(prompt_record=record)
    except PortFailure as exc:
        return _prompt_failure(exc)


def render_prompt_preparation(result: PromptPreparationResult) -> str:
    record, handoff = result.preparation.record, result.preparation.handoff
    return (
        f"prompt saved: {record.record}\n  mode: {record.mode}; generation: {record.generation_status}"
        f"\n  inputs: {record.resolved_path}; {len(record.references)} reference(s)"
        f"\n  handoff: {handoff.action}; register with {handoff.registration_operation}"
        f"\n  outputs: {', '.join(item.name for item in record.outputs) or 'none'}"
    )


def render_prompt_revision(result: PromptRevisionResult) -> str:
    prepared = PromptPreparationResult(preparation=result.revision.preparation)
    return (
        render_prompt_preparation(prepared)
        + f"\n  changed: {', '.join(result.revision.changed_fields) or 'none'}"
    )


def render_prompt_record(result: PromptRecordResult) -> str:
    record = result.prompt_record
    return (
        f"prompt record: {record.record}\n  generation: {record.generation_status}"
        f"; registered outputs: {', '.join(item.name for item in record.outputs) or 'none'}"
    )


def _projectless_asset_command(
    operation, input_model, output_model, render, recipe
) -> HeadlessCommand:
    return HeadlessCommand(
        operation=operation,
        input_model=input_model,
        output_model=output_model,
        render=render,
        kind=ExecutionKind.COMPOSITE,
        recipe=recipe,
        inherits_project=False,
    )


PROMPT_PREPARE_COMMAND = _projectless_asset_command(
    "asset-pipeline-prompt-prepare",
    PromptPrepareParams,
    PromptPreparationResult,
    render_prompt_preparation,
    run_prompt_prepare,
)
PROMPT_INSPECT_COMMAND = _projectless_asset_command(
    "asset-pipeline-prompt-inspect",
    PromptInspectParams,
    PromptPreparationResult,
    render_prompt_preparation,
    run_prompt_inspect,
)
PROMPT_REVISE_COMMAND = _projectless_asset_command(
    "asset-pipeline-prompt-revise",
    PromptReviseParams,
    PromptRevisionResult,
    render_prompt_revision,
    run_prompt_revise,
)
PROMPT_REGISTER_OUTPUT_COMMAND = _projectless_asset_command(
    "asset-pipeline-prompt-register-output",
    PromptRegisterOutputParams,
    PromptRecordResult,
    render_prompt_record,
    run_prompt_register_output,
)


def _json_map(value: str | None, label: str) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"invalid {label} JSON: {exc.msg}") from exc
    if not isinstance(decoded, dict):
        raise typer.BadParameter(f"{label} must be a JSON object")
    return decoded


def _json_document(value: str, label: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"invalid {label} JSON: {exc.msg}") from exc


@_app.command(name="prompt-prepare", cls=PROMPT_PREPARE_COMMAND.command_class())
def prompt_prepare(
    record: Path = typer.Option(..., "--record", help="New prompt record directory."),
    text: Optional[str] = typer.Option(None, "--text", help="Literal prompt text."),
    template: Optional[Path] = typer.Option(
        None, "--template", help="Template file using $name placeholders."
    ),
    style: Optional[Path] = typer.Option(
        None, "--style", help="Optional prepended style text file."
    ),
    variables: str = typer.Option(
        "{}", "--variables", help="JSON object of exact string template variables."
    ),
    references: Optional[list[Path]] = typer.Option(
        None, "--reference", help="Local reference file; repeat up to 16."
    ),
    producer: Optional[str] = typer.Option(
        None, "--producer", help="Caller-selected external producer."
    ),
    requested_options: str = typer.Option(
        "{}", "--requested-options", help=REQUESTED_OPTION_HELP
    ),
    json_output: bool = json_option(),
    schema: bool = PROMPT_PREPARE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
) -> None:
    """Save prepared prompt inputs and return an external handoff."""
    dispatch_recipe(
        PROMPT_PREPARE_COMMAND,
        params_or_bad_parameter(
            PromptPrepareParams,
            record=record,
            text=text,
            template=template,
            style=style,
            variables=_json_map(variables, "variables"),
            references=references or (),
            producer=producer,
            requested_options=_json_map(requested_options, "requested-options"),
        ),
        json_output=json_output,
        godot=None,
        project=None,
    )


@_app.command(name="prompt-inspect", cls=PROMPT_INSPECT_COMMAND.command_class())
def prompt_inspect(
    record: Path = typer.Option(
        ..., "--record", help="Existing prompt record directory."
    ),
    json_output: bool = json_option(),
    schema: bool = PROMPT_INSPECT_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
) -> None:
    """Inspect saved prompt inputs, outputs, and external handoff."""
    dispatch_recipe(
        PROMPT_INSPECT_COMMAND,
        PromptInspectParams(record=record),
        json_output=json_output,
        godot=None,
        project=None,
    )


@_app.command(name="prompt-revise", cls=PROMPT_REVISE_COMMAND.command_class())
def prompt_revise(
    source_record: Path = typer.Option(..., "--source-record"),
    record: Path = typer.Option(..., "--record"),
    text: Optional[str] = typer.Option(None, "--text"),
    template: Optional[Path] = typer.Option(None, "--template"),
    style: Optional[Path] = typer.Option(None, "--style"),
    remove_style: bool = typer.Option(False, "--remove-style"),
    variables: Optional[str] = typer.Option(
        None, "--variables", help="Replacement JSON string map."
    ),
    references: Optional[list[Path]] = typer.Option(
        None, "--reference", help="Replacement reference set; repeat."
    ),
    producer: Optional[str] = typer.Option(None, "--producer"),
    requested_options: Optional[str] = typer.Option(
        None, "--requested-options", help=REQUESTED_OPTION_HELP
    ),
    json_output: bool = json_option(),
    schema: bool = PROMPT_REVISE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
) -> None:
    """Create a separate prompt record with explicit changes."""
    dispatch_recipe(
        PROMPT_REVISE_COMMAND,
        params_or_bad_parameter(
            PromptReviseParams,
            source_record=source_record,
            record=record,
            text=text,
            template=template,
            style=style,
            remove_style=remove_style,
            variables=_json_map(variables, "variables"),
            references=references,
            producer=producer,
            requested_options=_json_map(requested_options, "requested-options"),
        ),
        json_output=json_output,
        godot=None,
        project=None,
    )


@_app.command(
    name="prompt-register-output", cls=PROMPT_REGISTER_OUTPUT_COMMAND.command_class()
)
def prompt_register_output(
    record: Path = typer.Option(..., "--record"),
    output: Path = typer.Option(..., "--output"),
    name: str = typer.Option(..., "--name", help="Caller-chosen safe PNG filename."),
    submitted_prompt: Optional[str] = typer.Option(None, "--submitted-prompt"),
    caller_declarations: str = typer.Option(
        "{}", "--caller-declarations", help=DECLARATION_HELP
    ),
    reported_provider: Optional[str] = typer.Option(None, "--reported-provider"),
    reported_model: Optional[str] = typer.Option(None, "--reported-model"),
    reported_options: str = typer.Option(
        "{}", "--reported-options", help=REQUESTED_OPTION_HELP
    ),
    json_output: bool = json_option(),
    schema: bool = PROMPT_REGISTER_OUTPUT_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
) -> None:
    """Register an existing completed PNG without invoking a producer."""
    dispatch_recipe(
        PROMPT_REGISTER_OUTPUT_COMMAND,
        params_or_bad_parameter(
            PromptRegisterOutputParams,
            record=record,
            output=output,
            name=name,
            submitted_prompt=submitted_prompt,
            caller_declarations=_json_map(caller_declarations, "caller-declarations"),
            reported_provider=reported_provider,
            reported_model=reported_model,
            reported_options=_json_map(reported_options, "reported-options"),
        ),
        json_output=json_output,
        godot=None,
        project=None,
    )


class ConceptPrepareParams(_AssetCommandModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    brief: Path = Field(
        description="Caller-authored concept brief JSON file (at most 1 MiB)."
    )
    record: Path = Field(
        description="New exclusive concept and prompt record directory."
    )
    producer: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        description="Optional caller-selected external producer name.",
    )
    requested_options: dict[PromptOptionKey, JsonScalar] = Field(
        default_factory=dict, description=REQUESTED_OPTION_HELP
    )


class ConceptCandidateInput(_AssetCommandModel):
    model_config = ConfigDict(extra="forbid")
    record: Path = Field(description="Existing registered prompt record directory.")
    output: str = Field(
        min_length=1,
        max_length=255,
        description="Exact registered PNG output slot filename.",
    )


class ConceptSelectParams(_AssetCommandModel):
    model_config = ConfigDict(extra="forbid")
    brief_record: Path = Field(description="Record created by concept-prepare.")
    handoff: Path = Field(
        description="New exclusive selected-reference handoff directory."
    )
    candidates: tuple[ConceptCandidateInput, ...] = Field(
        min_length=1,
        max_length=8,
        description="Ordered list of 1 to 8 registered prompt output candidates.",
    )


class SpriteSheetLayoutInput(_AssetCommandModel):
    model_config = ConfigDict(extra="forbid")
    width: int = Field(strict=True, ge=1, le=2048)
    height: int = Field(strict=True, ge=1, le=2048)
    cell_width: int = Field(strict=True, ge=1, le=2048)
    cell_height: int = Field(strict=True, ge=1, le=2048)
    frames: int = Field(strict=True, ge=1, le=64)


class ConceptAuthorParams(_AssetCommandModel):
    model_config = ConfigDict(extra="forbid")
    handoff: Path = Field(description="Existing selected-reference handoff directory.")
    consumer: ConceptConsumer = Field(description="Bounded example authoring consumer.")
    output: Path = Field(description="New exclusive authoring output directory.")
    reference_index: int = Field(
        default=0,
        strict=True,
        ge=0,
        le=7,
        description="Zero-based selected reference to consume.",
    )
    blender_executable: Path | None = Field(
        default=None,
        description="Optional Blender executable for the blockout consumer.",
    )
    sprite_layout: SpriteSheetLayoutInput | None = Field(
        default=None, description="Required layout for the sprite-sheet consumer."
    )


class ConceptPreparationResult(_AssetCommandModel):
    preparation: ConceptPreparation


class ConceptSelectionResult(_AssetCommandModel):
    selection: ConceptSelection


class ConceptAuthorResult(_AssetCommandModel):
    authoring: ConceptAuthoringResult


def _concept_failure(exc: PortFailure) -> Failure:
    if exc.code == "destination_conflict":
        code = "already_exists"
    elif exc.code in {
        "concept_prepare_failed",
        "concept_select_failed",
        "concept_author_failed",
    }:
        code = "operation_failed"
    else:
        code = "invalid_params"
    return make_failure(code, str(exc), "")


def run_concept_prepare(
    params: ConceptPrepareParams, *, project: Path | None, godot: str | None
) -> ConceptPreparationResult | Failure:
    del project, godot
    try:
        return ConceptPreparationResult(
            preparation=prepare_concept(
                ConceptPrepareRequest(
                    brief=params.brief.resolve(),
                    record=params.record.resolve(),
                    producer=params.producer,
                    requested_options=params.requested_options,
                )
            )
        )
    except PortFailure as exc:
        return _concept_failure(exc)


def run_concept_select(
    params: ConceptSelectParams, *, project: Path | None, godot: str | None
) -> ConceptSelectionResult | Failure:
    del project, godot
    try:
        return ConceptSelectionResult(
            selection=select_concept(
                ConceptSelectRequest(
                    brief_record=params.brief_record.resolve(),
                    handoff=params.handoff.resolve(),
                    candidates=tuple(
                        ConceptCandidate(item.record.resolve(), item.output)
                        for item in params.candidates
                    ),
                )
            )
        )
    except PortFailure as exc:
        return _concept_failure(exc)


def run_concept_author(
    params: ConceptAuthorParams, *, project: Path | None, godot: str | None
) -> ConceptAuthorResult | Failure:
    del project, godot
    layout = params.sprite_layout
    try:
        return ConceptAuthorResult(
            authoring=author_concept(
                ConceptAuthorRequest(
                    handoff=params.handoff.resolve(),
                    consumer=params.consumer,
                    output=params.output.resolve(),
                    reference_index=params.reference_index,
                    blender_executable=params.blender_executable.resolve()
                    if params.blender_executable
                    else None,
                    sprite_layout=SpriteSheetLayout(**layout.model_dump())
                    if layout
                    else None,
                )
            )
        )
    except PortFailure as exc:
        return _concept_failure(exc)


def render_concept_preparation(result: ConceptPreparationResult) -> str:
    value = result.preparation
    return (
        f"concept prepared: {value.brief_snapshot.path}\n"
        f"  use: {value.brief.use}; prompt record: {value.prompt.record.record}\n"
        f"  handoff: {value.prompt.handoff.action}"
    )


def render_concept_selection(result: ConceptSelectionResult) -> str:
    value = result.selection
    return (
        f"concept references selected: {value.handoff}\n"
        f"  use: {value.brief.use}; selected: {len(value.selected)}\n"
        f"  authoring: {value.authoring_status}"
    )


def render_concept_authoring(result: ConceptAuthorResult) -> str:
    value = result.authoring
    return (
        f"concept authored: {value.consumer}\n"
        f"  consumed: {value.consumed.path}; reference loaded: {value.reference_loaded}\n"
        f"  influence: {value.influence}; artifacts: "
        + (", ".join(str(item.path) for item in value.artifacts) or "none")
    )


CONCEPT_PREPARE_COMMAND = _projectless_asset_command(
    "asset-pipeline-concept-prepare",
    ConceptPrepareParams,
    ConceptPreparationResult,
    render_concept_preparation,
    run_concept_prepare,
)
CONCEPT_SELECT_COMMAND = _projectless_asset_command(
    "asset-pipeline-concept-select",
    ConceptSelectParams,
    ConceptSelectionResult,
    render_concept_selection,
    run_concept_select,
)
CONCEPT_AUTHOR_COMMAND = _projectless_asset_command(
    "asset-pipeline-concept-author",
    ConceptAuthorParams,
    ConceptAuthorResult,
    render_concept_authoring,
    run_concept_author,
)


@_app.command(name="concept-prepare", cls=CONCEPT_PREPARE_COMMAND.command_class())
def concept_prepare(
    brief: Path = typer.Option(..., "--brief"),
    record: Path = typer.Option(..., "--record"),
    producer: Optional[str] = typer.Option(None, "--producer"),
    requested_options: str = typer.Option(
        "{}", "--requested-options", help=REQUESTED_OPTION_HELP
    ),
    json_output: bool = json_option(),
    schema: bool = CONCEPT_PREPARE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
) -> None:
    """Preserve a concept brief and return an external prompt handoff."""
    dispatch_recipe(
        CONCEPT_PREPARE_COMMAND,
        params_or_bad_parameter(
            ConceptPrepareParams,
            brief=brief,
            record=record,
            producer=producer,
            requested_options=_json_map(requested_options, "requested-options"),
        ),
        json_output=json_output,
        godot=None,
        project=None,
    )


@_app.command(name="concept-select", cls=CONCEPT_SELECT_COMMAND.command_class())
def concept_select(
    brief_record: Path = typer.Option(..., "--brief-record"),
    handoff: Path = typer.Option(..., "--handoff"),
    candidates: str = typer.Option(
        ..., "--candidates", help="JSON array of 1 to 8 record/output objects."
    ),
    json_output: bool = json_option(),
    schema: bool = CONCEPT_SELECT_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
) -> None:
    """Pin completed registered PNG candidates into a reusable handoff."""
    dispatch_recipe(
        CONCEPT_SELECT_COMMAND,
        params_or_bad_parameter(
            ConceptSelectParams,
            brief_record=brief_record,
            handoff=handoff,
            candidates=_json_document(candidates, "candidates"),
        ),
        json_output=json_output,
        godot=None,
        project=None,
    )


@_app.command(name="concept-author", cls=CONCEPT_AUTHOR_COMMAND.command_class())
def concept_author(
    handoff: Path = typer.Option(..., "--handoff"),
    consumer: ConceptConsumer = typer.Option(..., "--consumer"),
    output: Path = typer.Option(..., "--output"),
    reference_index: int = typer.Option(0, "--reference-index", min=0, max=7),
    blender_executable: Optional[Path] = typer.Option(None, "--blender-executable"),
    sprite_layout: Optional[str] = typer.Option(
        None, "--sprite-layout", help="JSON sprite sheet layout object."
    ),
    json_output: bool = json_option(),
    schema: bool = CONCEPT_AUTHOR_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
) -> None:
    """Author one bounded example from a selected concept reference."""
    dispatch_recipe(
        CONCEPT_AUTHOR_COMMAND,
        params_or_bad_parameter(
            ConceptAuthorParams,
            handoff=handoff,
            consumer=consumer,
            output=output,
            reference_index=reference_index,
            blender_executable=blender_executable,
            sprite_layout=_json_document(sprite_layout, "sprite-layout")
            if sprite_layout is not None
            else None,
        ),
        json_output=json_output,
        godot=None,
        project=None,
    )
