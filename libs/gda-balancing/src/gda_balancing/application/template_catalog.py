"""Retrieve admitted packaged Template releases."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

from gda_balancing.domain.template import (
    TemplateProvider,
    load_admitted_template,
    minimal_release,
    template_refusal,
)
from gda_balancing.schema2.authority import (
    AuthorityContextProvider,
    packaged_authority_context,
)
from gda_balancing.schema2.diagnostics import Schema2RefusalReport


@dataclass(frozen=True)
class TemplateReleaseSummary:
    """Identity of one admitted packaged Template release."""

    id: str
    version: str
    content_identity: str


def list_templates(
    provider: TemplateProvider = minimal_release,
    *,
    authority_context_provider: AuthorityContextProvider = packaged_authority_context,
) -> tuple[TemplateReleaseSummary, ...] | Schema2RefusalReport:
    """List packaged releases admitted under the active authority context."""
    admitted = load_admitted_template(provider, authority_context_provider)
    if isinstance(admitted, Schema2RefusalReport):
        return admitted
    release = admitted.release
    return (
        TemplateReleaseSummary(
            id=cast(str, release["id"]),
            version=cast(str, release["version"]),
            content_identity=cast(str, release["content_identity"]),
        ),
    )


def get_template(
    template_id: str,
    version: str,
    provider: TemplateProvider = minimal_release,
    *,
    authority_context_provider: AuthorityContextProvider = packaged_authority_context,
) -> dict[str, Any] | Schema2RefusalReport:
    """Get one exact admitted packaged Template release."""
    admitted = load_admitted_template(provider, authority_context_provider)
    if isinstance(admitted, Schema2RefusalReport):
        return admitted
    release = admitted.release
    if (template_id, version) != (release["id"], release["version"]):
        return template_refusal(
            "language.package_version_unavailable",
            "resolution",
            cast(str, release["content_identity"]),
            "/id",
            f"Template release {template_id}@{version} is unavailable",
        )
    return deepcopy(cast(dict[str, Any], release))
