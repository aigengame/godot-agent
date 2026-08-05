"""Build and publish a Standard Schema Model."""

from dataclasses import dataclass
from typing import Any

from gda_balancing.domain.artifact_set import ArtifactSetMemberSpec
from gda_balancing.domain.model import compilation
from gda_balancing.domain.model.checking import check_source
from gda_balancing.schema2.diagnostics import Schema2RefusalReport
from gda_balancing.schema2.model import (
    publication_authentication_key,
    publish_model_artifacts,
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
    checked = check_source(source)
    if isinstance(checked, Schema2RefusalReport):
        return checked
    receipt = publish_model_artifacts(
        checked,
        source,
        out,
        invocation_key,
        descriptor_identity,
        artifact_set,
        publication_fault,
        authentication_key=authentication_key,
        compiler=compilation.compile_checked_model,
    )
    return ModelBuildReceipt(root=receipt)
