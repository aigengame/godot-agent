"""Get one admitted Standard Schema authority artifact."""

from typing import Literal

from gda_balancing.application.authority import admit_command_authority
from gda_balancing.domain.authority.schema_catalog import (
    SchemaArtifactContent,
    get_schema_artifact,
)
from gda_balancing.domain.authority.context import AuthorityContextProvider
from gda_balancing.domain.diagnostics import Schema2RefusalReport


def get_schema(
    provider: AuthorityContextProvider,
    artifact: Literal["language-bundle", "wire-schema", "diagnostic-catalog"],
) -> SchemaArtifactContent | Schema2RefusalReport:
    """Resolve one authority context and return the requested public artifact."""
    context = admit_command_authority(provider)
    if isinstance(context, Schema2RefusalReport):
        return context
    return get_schema_artifact(context, artifact)
