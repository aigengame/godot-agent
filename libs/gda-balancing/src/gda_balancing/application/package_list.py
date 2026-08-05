"""List the Package Releases in one admitted authority context."""

from typing import Any

from gda_balancing.domain.authority.package_catalog import list_package_releases
from gda_balancing.schema2.authority import (
    AuthorityContextProvider,
    AuthorityLoadError,
    resolve_authority_context,
)
from gda_balancing.schema2.bootstrap import BootstrapAdmission
from gda_balancing.schema2.diagnostics import (
    Schema2RefusalReport,
    bootstrap_refusal,
    ingress_refusal,
)


def list_packages(
    provider: AuthorityContextProvider,
) -> dict[str, Any] | Schema2RefusalReport:
    """Resolve one authority context and return its package inventory."""
    try:
        context = resolve_authority_context(provider)
    except AuthorityLoadError as err:
        return ingress_refusal(err.code, err.subject, err.message)
    if isinstance(context, BootstrapAdmission):
        return bootstrap_refusal(context)
    return list_package_releases(context)
