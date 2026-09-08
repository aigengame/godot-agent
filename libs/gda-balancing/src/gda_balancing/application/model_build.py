"""Build and publish a Standard Schema Model."""

from dataclasses import dataclass
from typing import Any

from gda_balancing.domain.artifact_set import (
    ArtifactSetPlan,
    ProtocolArtifactSetMemberSpec,
    resolve_artifact_set,
    label_artifacts,
)
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
    ProtocolArtifactSetMemberSpec(
        "build-receipt",
    ),
    ProtocolArtifactSetMemberSpec(
        "capability-manifest",
    ),
    ProtocolArtifactSetMemberSpec(
        "debug-map",
    ),
    ProtocolArtifactSetMemberSpec(
        "model-explanation",
    ),
    ProtocolArtifactSetMemberSpec(
        "package-lock",
    ),
    ProtocolArtifactSetMemberSpec(
        "resolution-receipt",
    ),
    ProtocolArtifactSetMemberSpec("resolved-model", role="primary"),
    ProtocolArtifactSetMemberSpec(
        "rir-semantic-payload",
    ),
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
    artifact_set: ArtifactSetPlan,
    publication_fault: str | None = None,
) -> ModelBuildReceipt | Schema2RefusalReport:
    """Check, lazily compile, and publish one Model Source Package."""
    authentication_key = publication_authentication_key()
    checked = check_model_source(source)
    if isinstance(checked, Schema2RefusalReport):
        return checked
    artifact_set = resolve_artifact_set(
        authority_context_for_checked(checked).language_bundle, artifact_set
    )
    receipt = publish_lazy_artifact_set(
        authority_context_for_checked(checked),
        checked.source_identity,
        out,
        invocation_key,
        descriptor_identity,
        model_build_command_input_identity(checked),
        artifact_set,
        lambda: label_artifacts(
            compile_checked_model(checked),
            artifact_set,
            lambda value: str(value["artifact_kind"]),
        ),
        validate_compiled_artifacts,
        publication_fault,
        authentication_key=authentication_key,
    )
    return ModelBuildReceipt(root=receipt)
