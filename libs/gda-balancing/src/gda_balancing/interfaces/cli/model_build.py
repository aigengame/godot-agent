"""CLI adapter for building and publishing a Standard Schema Model."""

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from gda_balancing.application.model_build import MODEL_BUILD_ARTIFACT_SET, build_model
from gda_balancing.interfaces.cli.descriptors import (
    CommandDescriptor,
    ConformanceFixtures,
)
from gda_balancing.interfaces.cli.artifact_set import ArtifactSetMemberLocator
from gda_balancing.interfaces.cli.model_fixtures import VALID_MODEL_SOURCE
from gda_balancing.interfaces.cli.path_contracts import reject_input_aliasing
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.model.resolution import MODEL_REFUSAL_CATALOG
from gda_balancing.interfaces.cli.surface import descriptor_identity


class ModelBuildInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    out: str
    invocation_key: str = Field(pattern=r"^[0-9a-f]{64}$")


class ModelBuildResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_kind: str
    artifact_version: str
    wire_schema_identity: str
    descriptor_identity: str
    invocation_key: str
    manifest_identity: str
    manifest_locator: str
    member_locators: list[ArtifactSetMemberLocator]
    content_identity: str


def model_build_handler(
    *, publication_fault: str | None = None
) -> Callable[[ModelBuildInput], ModelBuildResult | Schema2RefusalReport]:
    """Create the build handler; ``publication_fault`` is test-only injection."""
    if publication_fault not in {
        None,
        "after-member-write",
        "before-commit",
        "before-anchor-commit",
        "after-commit",
    }:
        raise ValueError("unknown publication fault")

    def _run(inp: ModelBuildInput) -> ModelBuildResult | Schema2RefusalReport:
        reject_input_aliasing(inp.out, inp.source, input_is_known_path=True)
        result = build_model(
            inp.source,
            inp.out,
            inp.invocation_key,
            descriptor_identity(MODEL_BUILD),
            MODEL_BUILD.artifact_set,
            publication_fault,
        )
        if isinstance(result, Schema2RefusalReport):
            return result
        return ModelBuildResult.model_validate(result.root)

    return _run


run_model_build = model_build_handler()


MODEL_BUILD = CommandDescriptor(
    group="model",
    command="build",
    description="Build and atomically publish a Standard Schema 2.0 Model.",
    input_model=ModelBuildInput,
    output_model=ModelBuildResult,
    handler=run_model_build,
    fixtures=ConformanceFixtures(valid_document=VALID_MODEL_SOURCE),
    positional_field="source",
    artifact_set=MODEL_BUILD_ARTIFACT_SET,
    schema_major=2,
    structured_params=True,
    refusal_catalog=MODEL_REFUSAL_CATALOG,
    usage_codes=(
        "argument_conflict",
        "invalid_argument",
        "invocation_key_conflict",
        "unknown_argument",
        "unreadable_input",
        "unwritable_output",
    ),
)
