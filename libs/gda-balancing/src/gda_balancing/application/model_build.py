"""Build and publish a Standard Schema Model."""

from dataclasses import dataclass
from typing import Any

from gda_balancing.domain.artifact_set import ArtifactSetMemberSpec
from gda_balancing.domain.model import compilation
from gda_balancing.domain.model.checking import check_model_source
from gda_balancing.domain.publication import (
    publication_authentication_key,
    publish_lazy_artifact_set,
)
from gda_balancing.domain.diagnostics import Schema2RefusalReport


@dataclass(frozen=True)
class ModelBuildReceipt:
    """The published artifact-set receipt for one Model build."""

    root: dict[str, Any]


def build_model(
    source: str,
    out: str,
    invocation_key: str,
    descriptor_identity: str,
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
    publication_fault: str | None = None,
) -> ModelBuildReceipt | Schema2RefusalReport:
    """Check, lazily compile, and publish one Model Source Package."""
    authentication_key = publication_authentication_key()
    checked = check_model_source(source)
    if isinstance(checked, Schema2RefusalReport):
        return checked
    receipt = publish_lazy_artifact_set(
        compilation.authority_context_for_checked(checked),
        checked.source_identity,
        out,
        invocation_key,
        descriptor_identity,
        compilation.model_build_command_input_identity(checked),
        artifact_set,
        lambda: compilation.compile_checked_model(checked),
        compilation.validate_compiled_artifacts,
        publication_fault,
        authentication_key=authentication_key,
    )
    return ModelBuildReceipt(root=receipt)
