"""Resolve command authority into an admitted context or public refusal."""

from gda_balancing.domain.authority.admission import BootstrapAdmission
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    AuthorityContextProvider,
    AuthorityLoadError,
    resolve_authority_context,
)
from gda_balancing.domain.diagnostics import (
    Schema2RefusalReport,
    bootstrap_refusal,
    ingress_refusal,
)


def admit_command_authority(
    provider: AuthorityContextProvider,
) -> AdmittedAuthorityContext | Schema2RefusalReport:
    """Resolve one command's authority and map admission failures."""
    try:
        context = resolve_authority_context(provider)
    except AuthorityLoadError as err:
        return ingress_refusal(err.code, err.subject, err.message)
    if isinstance(context, BootstrapAdmission):
        return bootstrap_refusal(context)
    return context
