"""Get one exact Package Release member."""

from typing import Literal

from gda_balancing.domain.authority.package_catalog import (
    PackageArtifactContent,
    get_package_release,
)
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


def get_package(
    provider: AuthorityContextProvider,
    package_id: str,
    version: str,
    member: Literal["release", "conformance-vectors"],
) -> PackageArtifactContent | Schema2RefusalReport:
    """Resolve one authority context and select an exact Package Release member."""
    try:
        context = resolve_authority_context(provider)
    except AuthorityLoadError as err:
        return ingress_refusal(err.code, err.subject, err.message)
    if isinstance(context, BootstrapAdmission):
        return bootstrap_refusal(context)
    return get_package_release(context, package_id, version, member)
