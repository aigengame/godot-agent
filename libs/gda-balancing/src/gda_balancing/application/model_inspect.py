"""Retrieve one authenticated published Model explanation."""

from dataclasses import dataclass
from typing import Any

from gda_balancing.domain.artifact_set import ArtifactSetMemberSpec
from gda_balancing.domain.model.inspection import read_model_explanation
from gda_balancing.domain.model.inspection_types import ModelInspectAdmissionError
from gda_balancing.domain.diagnostics import Schema2RefusalReport, ingress_refusal


@dataclass(frozen=True)
class ModelExplanation:
    """One admitted explanation projected from a committed Model build."""

    root: dict[str, Any]


def inspect_model(
    receipt: str,
    descriptor_identity: str,
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
) -> ModelExplanation | Schema2RefusalReport:
    """Authenticate a build receipt and return its Model explanation."""
    try:
        explanation = read_model_explanation(
            receipt,
            descriptor_identity,
            artifact_set,
        )
    except ModelInspectAdmissionError as err:
        return ingress_refusal(err.code, err.subject, err.message)
    return ModelExplanation(root=explanation)
