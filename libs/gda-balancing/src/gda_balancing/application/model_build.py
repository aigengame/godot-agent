"""Build and publish a Standard Schema Model."""

from dataclasses import dataclass
from typing import Any

from gda_balancing.domain.artifact_set import ArtifactSetMemberSpec
from gda_balancing.domain.model import (
    authority_context_for_checked,
    check_model_source,
    compile_checked_model,
    model_build_command_input_identity,
    validate_compiled_artifacts,
)
from gda_balancing.domain.publication import (
    publication_authentication_key,
    publish_lazy_artifact_set,
)
from gda_balancing.domain.diagnostics import Schema2RefusalReport


MODEL_BUILD_ARTIFACT_SET = (
    ArtifactSetMemberSpec("build-receipt", "build-receipt"),
    ArtifactSetMemberSpec("capability-manifest", "capability-manifest"),
    ArtifactSetMemberSpec("debug-map", "debug-map"),
    ArtifactSetMemberSpec("model-explanation", "model-explanation"),
    ArtifactSetMemberSpec("package-lock", "package-lock"),
    ArtifactSetMemberSpec("resolution-receipt", "resolution-receipt"),
    ArtifactSetMemberSpec("resolved-model", "resolved-model", role="primary"),
    ArtifactSetMemberSpec("rir-semantic-payload", "rir-semantic-payload"),
)


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
        authority_context_for_checked(checked),
        checked.source_identity,
        out,
        invocation_key,
        descriptor_identity,
        model_build_command_input_identity(checked),
        artifact_set,
        lambda: compile_checked_model(checked),
        validate_compiled_artifacts,
        publication_fault,
        authentication_key=authentication_key,
    )
    return ModelBuildReceipt(root=receipt)
