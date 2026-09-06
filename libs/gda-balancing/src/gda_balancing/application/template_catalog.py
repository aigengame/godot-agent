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
from gda_balancing.domain.authority.context import (
    AuthorityContextProvider,
    packaged_authority_context,
)
from gda_balancing.domain.diagnostics import Schema2RefusalReport


@dataclass(frozen=True)
class TemplateReleaseSummary:
    """Identity of one admitted packaged Template release."""

    id: str
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
            content_identity=cast(str, release["content_identity"]),
        ),
    )


def get_template(
    template_id: str,
    provider: TemplateProvider = minimal_release,
    *,
    authority_context_provider: AuthorityContextProvider = packaged_authority_context,
) -> dict[str, Any] | Schema2RefusalReport:
    """Get the current admitted packaged Template by id."""
    admitted = load_admitted_template(provider, authority_context_provider)
    if isinstance(admitted, Schema2RefusalReport):
        return admitted
    release = admitted.release
    if template_id != release["id"]:
        return template_refusal(
            "language.package_unavailable",
            "resolution",
            cast(str, release["content_identity"]),
            "/id",
            f"Template {template_id} is unavailable",
        )
    return deepcopy(cast(dict[str, Any], release))
