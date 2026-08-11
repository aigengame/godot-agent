"""Get one exact Package Release member."""

from typing import Literal

from gda_balancing.application.authority import admit_command_authority
from gda_balancing.domain.authority.package_catalog import (
    PackageArtifactContent,
    get_package_release,
)
from gda_balancing.domain.authority.context import AuthorityContextProvider
from gda_balancing.domain.diagnostics import Schema2RefusalReport


def get_package(
    provider: AuthorityContextProvider,
    package_id: str,
    version: str,
    member: Literal["release", "conformance-vectors"],
) -> PackageArtifactContent | Schema2RefusalReport:
    """Resolve one authority context and select an exact Package Release member."""
    context = admit_command_authority(provider)
    if isinstance(context, Schema2RefusalReport):
        return context
    return get_package_release(context, package_id, version, member)
