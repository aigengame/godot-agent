"""CLI adapter for building and publishing a Standard Schema Model."""

from collections.abc import Callable
from dataclasses import replace

from pydantic import BaseModel, ConfigDict, Field

from gda_balancing.application.authority import admit_command_authority
from gda_balancing.application.model_build import MODEL_BUILD_ARTIFACT_SET, build_model
from gda_balancing.interfaces.cli.descriptors import (
    CommandDescriptor,
    ConformanceFixtures,
    authority_context_handler,
)
from gda_balancing.interfaces.cli.artifact_set import ArtifactSetMemberLocator
from gda_balancing.interfaces.cli.model_fixtures import VALID_MODEL_SOURCE
from gda_balancing.interfaces.cli.path_contracts import reject_input_aliasing
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.model import model_refusal_catalog
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    AuthorityContextProvider,
    packaged_authority_context,
)
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
    authority_context_provider: AuthorityContextProvider = packaged_authority_context,
    *,
    publication_fault: str | None = None,
    _descriptor: CommandDescriptor | None = None,
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

    def _run(
        inp: ModelBuildInput,
        authority_context: AdmittedAuthorityContext | None = None,
    ) -> ModelBuildResult | Schema2RefusalReport:
        reject_input_aliasing(inp.out, inp.source, input_is_known_path=True)
        context = authority_context or admit_command_authority(
            authority_context_provider
        )
        if isinstance(context, Schema2RefusalReport):
            return context
        result = build_model(
            inp.source,
            inp.out,
            inp.invocation_key,
            descriptor_identity(
                _descriptor or MODEL_BUILD,
                authority_context=context,
            ),
            (_descriptor or MODEL_BUILD).artifact_set,
            publication_fault,
            authority_context=context,
        )
        if isinstance(result, Schema2RefusalReport):
            return result
        return ModelBuildResult.model_validate(result.root)

    return authority_context_handler(_run)


def _model_refusal_catalog(
    context: AdmittedAuthorityContext | None,
) -> tuple[tuple[str, str], ...]:
    return model_refusal_catalog(None if context is None else context.language_bundle)


def model_build_descriptor(
    authority_context_provider: AuthorityContextProvider = packaged_authority_context,
    *,
    publication_fault: str | None = None,
) -> CommandDescriptor:
    """Compose Model build behavior and projections over one authority source."""

    def _unbound(_inp: ModelBuildInput) -> ModelBuildResult:
        raise RuntimeError("Model build descriptor handler is not bound")

    descriptor = CommandDescriptor(
        group="model",
        command="build",
        description="Build and atomically publish a Standard Schema 2.0 Model.",
        input_model=ModelBuildInput,
        output_model=ModelBuildResult,
        handler=_unbound,
        fixtures=ConformanceFixtures(valid_document=VALID_MODEL_SOURCE),
        positional_field="source",
        artifact_set=MODEL_BUILD_ARTIFACT_SET,
        schema_major=2,
        structured_params=True,
        authority_context_provider=authority_context_provider,
        refusal_catalog_provider=_model_refusal_catalog,
        usage_codes=(
            "argument_conflict",
            "invalid_argument",
            "invocation_key_conflict",
            "unknown_argument",
            "unreadable_input",
            "unwritable_output",
        ),
    )
    return replace(
        descriptor,
        handler=model_build_handler(
            authority_context_provider,
            publication_fault=publication_fault,
            _descriptor=descriptor,
        ),
    )


MODEL_BUILD = model_build_descriptor()
run_model_build = model_build_handler()
