"""Report toolkit and supported Standard Schema versions."""

from dataclasses import dataclass

from gda_balancing.application.authority import admit_command_authority
from gda_balancing.domain.authority.versioning import supported_schema_line
from gda_balancing.infrastructure.distribution import distribution_version
from gda_balancing.domain.authority.context import AuthorityContextProvider
from gda_balancing.domain.diagnostics import Schema2RefusalReport


@dataclass(frozen=True)
class VersionReport:
    """The toolkit version and supported Standard Schema line."""

    toolkit_version: str
    supported_schema_line: str


def report_version(
    provider: AuthorityContextProvider,
) -> VersionReport | Schema2RefusalReport:
    """Resolve admitted authority and report its public version axes."""
    context = admit_command_authority(provider)
    if isinstance(context, Schema2RefusalReport):
        return context
    return VersionReport(
        toolkit_version=distribution_version("gda-balancing"),
        supported_schema_line=supported_schema_line(context),
    )
