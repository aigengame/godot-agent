"""Get one admitted Standard Schema authority artifact."""

from typing import Literal

from gda_balancing.domain.authority.schema_catalog import (
    SchemaArtifactContent,
    get_schema_artifact,
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


def get_schema(
    provider: AuthorityContextProvider,
    artifact: Literal["language-bundle", "wire-schema", "diagnostic-catalog"],
) -> SchemaArtifactContent | Schema2RefusalReport:
    """Resolve one authority context and return the requested public artifact."""
    try:
        context = resolve_authority_context(provider)
    except AuthorityLoadError as err:
        return ingress_refusal(err.code, err.subject, err.message)
    if isinstance(context, BootstrapAdmission):
        return bootstrap_refusal(context)
    return get_schema_artifact(context, artifact)
