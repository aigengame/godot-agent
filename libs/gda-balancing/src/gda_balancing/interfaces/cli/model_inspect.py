"""CLI adapter for retrieving a published Model explanation."""

from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, RootModel

from gda_balancing.application.model_inspect import inspect_model
from gda_balancing.interfaces.cli.descriptors import (
    CommandDescriptor,
    ConformanceFixtures,
)
from gda_balancing.domain.artifacts import artifact_wire_schema
from gda_balancing.interfaces.cli.model_build import (
    MODEL_BUILD,
    ModelBuildInput,
    ModelBuildResult,
    run_model_build,
)
from gda_balancing.interfaces.cli.model_fixtures import VALID_MODEL_SOURCE
from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.model.semantics import MODEL_INSPECT_REFUSAL_CATALOG
from gda_balancing.interfaces.cli.surface import descriptor_identity


class ModelInspectInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt: str
    format: Literal["canonical", "indented"] = "canonical"


class ModelInspectResult(RootModel[dict[str, Any]]):
    model_config = ConfigDict(frozen=True)


def run_model_inspect(
    inp: ModelInspectInput,
) -> ModelInspectResult | Schema2RefusalReport:
    result = inspect_model(
        inp.receipt,
        descriptor_identity(MODEL_BUILD),
        MODEL_BUILD.artifact_set,
    )
    if isinstance(result, Schema2RefusalReport):
        return result
    return ModelInspectResult.model_validate(result.root)


def _model_explanation_schema() -> dict[str, object]:
    return artifact_wire_schema(
        packaged_authority_context().language_bundle,
        "model-explanation",
    )


def _prepare_model_inspect(root: Path, token: int) -> str:
    source = root / f"inspect-model-{token}.json"
    source.write_text(VALID_MODEL_SOURCE, encoding="utf-8")
    result = run_model_build(
        ModelBuildInput(
            source=str(source),
            out=str(root / f"inspect-model-{token}-out.json"),
            invocation_key=f"{token:064x}",
        )
    )
    if not isinstance(result, ModelBuildResult):
        raise RuntimeError("Model inspect prerequisite build was refused")
    receipt = result.model_dump(mode="json")
    receipt_path = Path(cast(str, receipt["manifest_locator"])).with_name(
        "artifact-set-receipt.json"
    )
    return receipt_path.read_text(encoding="utf-8")


MODEL_INSPECT = CommandDescriptor(
    group="model",
    command="inspect",
    description="Retrieve and render one stored immutable Model explanation.",
    input_model=ModelInspectInput,
    output_model=ModelInspectResult,
    handler=run_model_inspect,
    fixtures=ConformanceFixtures(
        prepare_valid_document=_prepare_model_inspect,
        refusing_document="{}",
    ),
    positional_field="receipt",
    json_presentation_field="format",
    schema_major=2,
    structured_params=True,
    success_schema=_model_explanation_schema,
    refusal_catalog=MODEL_INSPECT_REFUSAL_CATALOG,
    usage_codes=(
        "invalid_argument",
        "unknown_argument",
        "unreadable_input",
    ),
)
