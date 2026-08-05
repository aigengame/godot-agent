"""The Schema 2.0 `version` meta command."""

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

from gda_balancing.application.version import report_version
from gda_balancing.interfaces.cli.descriptors import (
    CommandDescriptor,
    ConformanceFixtures,
)
from gda_balancing.domain.authority.context import (
    AuthorityContextProvider,
    packaged_authority_context,
)
from gda_balancing.domain.authority.admission import BOOTSTRAP_REFUSAL_CATALOG
from gda_balancing.domain.diagnostics import Schema2RefusalReport


class VersionInput(BaseModel):
    """`version` takes no arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class VersionResult(BaseModel):
    """The independently versioned toolkit and current forward Schema line."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    toolkit_version: str
    supported_schema_line: str


def version_handler(
    provider: AuthorityContextProvider,
) -> Callable[[VersionInput], VersionResult | Schema2RefusalReport]:
    """Build the version tracer around one admitted authority provider."""

    def _run(_: VersionInput) -> VersionResult | Schema2RefusalReport:
        result = report_version(provider)
        if isinstance(result, Schema2RefusalReport):
            return result
        return VersionResult(
            toolkit_version=result.toolkit_version,
            supported_schema_line=result.supported_schema_line,
        )

    return _run


run_version = version_handler(packaged_authority_context)


VERSION = CommandDescriptor(
    group=None,
    command="version",
    description=(
        "Report the toolkit package version and the supported Standard "
        "Schema line as distinct fields."
    ),
    input_model=VersionInput,
    output_model=VersionResult,
    handler=run_version,
    fixtures=ConformanceFixtures(valid_args=()),
    schema_major=2,
    structured_params=True,
    refusal_catalog=BOOTSTRAP_REFUSAL_CATALOG,
    usage_codes=(
        "argument_conflict",
        "invalid_argument",
        "unknown_argument",
    ),
)
