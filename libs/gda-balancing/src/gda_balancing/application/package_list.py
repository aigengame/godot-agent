"""List the Package Releases in one admitted authority context."""

from gda_balancing.application.authority import admit_command_authority
from gda_balancing.domain.authority.package_catalog import (
    PackageInventory,
    list_package_releases,
)
from gda_balancing.domain.authority.context import AuthorityContextProvider
from gda_balancing.domain.diagnostics import Schema2RefusalReport


def list_packages(
    provider: AuthorityContextProvider,
) -> PackageInventory | Schema2RefusalReport:
    """Resolve one authority context and return its package inventory."""
    context = admit_command_authority(provider)
    if isinstance(context, Schema2RefusalReport):
        return context
    return list_package_releases(context)
