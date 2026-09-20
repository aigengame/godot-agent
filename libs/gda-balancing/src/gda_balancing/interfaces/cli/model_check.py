"""CLI adapter for checking a Standard Schema Model Source Package."""

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

from gda_balancing.application.authority import admit_command_authority
from gda_balancing.application.model_check import check_model
from gda_balancing.interfaces.cli.descriptors import (
    CommandDescriptor,
    ConformanceFixtures,
    authority_context_handler,
)
from gda_balancing.interfaces.cli.model_fixtures import VALID_MODEL_SOURCE
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    AuthorityContextProvider,
    packaged_authority_context,
)
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.model import model_refusal_catalog


class ModelCheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str


class ModelCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    checked: bool
    kernel_identity: str
    language_bundle_identity: str


def _model_refusal_catalog(
    context: AdmittedAuthorityContext | None,
) -> tuple[tuple[str, str], ...]:
    return model_refusal_catalog(None if context is None else context.language_bundle)


def model_check_handler(
    authority_context_provider: AuthorityContextProvider = packaged_authority_context,
) -> Callable[..., ModelCheckResult | Schema2RefusalReport]:
    """Bind Model checking to one explicit authority source."""

    def _run(
        inp: ModelCheckInput,
        authority_context: AdmittedAuthorityContext | None = None,
    ) -> ModelCheckResult | Schema2RefusalReport:
        context = authority_context or admit_command_authority(
            authority_context_provider
        )
        if isinstance(context, Schema2RefusalReport):
            return context
        result = check_model(inp.source, authority_context=context)
        if isinstance(result, Schema2RefusalReport):
            return result
        return ModelCheckResult(
            checked=True,
            kernel_identity=result.kernel_identity,
            language_bundle_identity=result.language_bundle_identity,
        )

    return authority_context_handler(_run)


def model_check_descriptor(
    authority_context_provider: AuthorityContextProvider = packaged_authority_context,
) -> CommandDescriptor:
    """Compose Model checking and all descriptor projections over one authority."""
    return CommandDescriptor(
        group="model",
        command="check",
        description="Check a Standard Schema 2.0 Model Source Package.",
        input_model=ModelCheckInput,
        output_model=ModelCheckResult,
        handler=model_check_handler(authority_context_provider),
        fixtures=ConformanceFixtures(valid_document=VALID_MODEL_SOURCE),
        positional_field="source",
        schema_major=2,
        structured_params=True,
        authority_context_provider=authority_context_provider,
        refusal_catalog_provider=_model_refusal_catalog,
        usage_codes=(
            "argument_conflict",
            "invalid_argument",
            "unknown_argument",
            "unreadable_input",
        ),
    )


run_model_check = model_check_handler()
MODEL_CHECK = model_check_descriptor()
