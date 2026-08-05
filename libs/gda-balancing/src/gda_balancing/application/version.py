"""Report toolkit and supported Standard Schema versions."""

from dataclasses import dataclass

from gda_balancing.domain.authority.versioning import supported_schema_line
from gda_balancing.infrastructure.distribution import distribution_version
from gda_balancing.domain.authority.context import (
    AuthorityContextProvider,
    AuthorityLoadError,
    resolve_authority_context,
)
from gda_balancing.domain.authority.admission import BootstrapAdmission
from gda_balancing.domain.diagnostics import (
    Schema2RefusalReport,
    bootstrap_refusal,
    ingress_refusal,
)


@dataclass(frozen=True)
class VersionReport:
    """The toolkit version and supported Standard Schema line."""

    toolkit_version: str
    supported_schema_line: str


def report_version(
    provider: AuthorityContextProvider,
) -> VersionReport | Schema2RefusalReport:
    """Resolve admitted authority and report its public version axes."""
    try:
        context = resolve_authority_context(provider)
    except AuthorityLoadError as err:
        return ingress_refusal(err.code, err.subject, err.message)
    if isinstance(context, BootstrapAdmission):
        return bootstrap_refusal(context)
    return VersionReport(
        toolkit_version=distribution_version("gda-balancing"),
        supported_schema_line=supported_schema_line(context),
    )
