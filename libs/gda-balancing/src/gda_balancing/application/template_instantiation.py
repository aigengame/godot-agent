"""Instantiate and publish one admitted Template release."""

from typing import Any

from gda_balancing.domain.artifact_set import ArtifactSetMemberSpec
from gda_balancing.domain.publication import (
    publication_authentication_key,
    publish_artifact_set,
)
from gda_balancing.domain.template import (
    TemplateProvider,
    prepare_template_instantiation,
)
from gda_balancing.domain.authority.context import AuthorityContextProvider
from gda_balancing.domain.diagnostics import Schema2RefusalReport


def instantiate_template(
    template_id: str,
    version: str,
    package_id: str,
    out: str,
    invocation_key: str,
    descriptor_identity: str,
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
    provider: TemplateProvider,
    authority_context_provider: AuthorityContextProvider,
    *,
    publication_fault: str | None = None,
) -> dict[str, Any] | Schema2RefusalReport:
    """Prepare one Template instance and atomically publish its artifact set."""
    plan = prepare_template_instantiation(
        template_id,
        version,
        package_id,
        provider,
        authority_context_provider,
    )
    if isinstance(plan, Schema2RefusalReport):
        return plan
    return publish_artifact_set(
        plan.artifacts,
        out,
        invocation_key,
        descriptor_identity,
        plan.command_input_identity,
        plan.language_bundle,
        artifact_set,
        plan.member_is_admitted,
        publication_fault,
        authentication_key=publication_authentication_key(),
    )
